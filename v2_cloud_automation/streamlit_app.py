async def run_automation(cast_data, sub_image_paths):
    main_img_tmp = "temp_main.jpg"
    if not download_by_filename(cast_data['メイン画像'], main_img_tmp):
        return {"status": "error", "message": f"メイン画像の取得失敗: {cast_data['メイン画像']}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info(f"🌐 ログイン中: {cast_data['名前']}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data['ID'])) 
            await page.fill("#form_password", str(cast_data['PASSWORD'])) 
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (不足分を追加)
            st.info("✍️ プロフィール詳細を入力中...")
            await page.fill("#form_name", str(cast_data['名前']))
            await page.fill("#form_age", str(cast_data['若・妻'])) # 年齢
            await page.fill("#form_tall", str(cast_data['身長'])) # 身長
            
            # 3サイズ入力
            await page.fill("#form_bust", str(cast_data['バスト']))
            await page.fill("#form_waist", str(cast_data['ウエスト']))
            await page.fill("#form_hip", str(cast_data['ヒップ']))

            # カップ数の選択 (例: "C" -> "Cカップ" を含む項目を選択)
            cup_text = f"{cast_data['カップ数']}カップ"
            await page.select_option("#form_cup", label=cup_text)

            # タグ選択
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 
                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 
                                "#genre73", "#genre74"]
            for selector in target_genre_ids:
                checkbox = page.locator(selector)
                if await checkbox.count() > 0:
                    await checkbox.check(force=True)

            # 基本情報登録
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # --- 画像アップロード共通処理ルーチン ---
            async def upload_and_crop(target_id, file_path, label):
                st.info(f"📸 {label} を処理中...")
                # モーダルを開く (con1, con2, con3...)
                await page.click(f'a[data-target="{target_id}"]')
                await page.wait_for_selector('input[type="file"]')
                
                # アップロード
                await page.locator('input[type="file"]').set_input_files(file_path)
                await page.click('button.upbtn')
                
                # ドラッグ操作 (Jcrop)
                tracker = page.locator(".jcrop-tracker.target").first
                await tracker.wait_for(state="visible", timeout=15000)
                box = await tracker.bounding_box()
                if box:
                    await page.mouse.move(box["x"], box["y"])
                    await page.mouse.down()
                    await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=20)
                    await page.mouse.up()
                
                # 確定ボタン
                fix_btn = page.get_by_role("button", name="修正する")
                await fix_btn.wait_for(state="visible")
                await fix_btn.click()
                await asyncio.sleep(3) # 反映待ち

            # 3. メイン画像のアップロード (画像:1)
            await upload_and_crop("con1", main_img_tmp, "画像1(メイン)")

            # 4. サブ画像のアップロード (画像:2 ～ 画像:8)
            for i, sub_url in enumerate(sub_image_paths):
                if i >= 7: break # 最大8枚まで
                target_num = i + 2 # con2, con3...
                sub_tmp = f"temp_sub_{target_num}.jpg"
                
                if download_by_filename(sub_url, sub_tmp):
                    await upload_and_crop(f"con{target_num}", sub_tmp, f"画像{target_num}")
                    if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 5. 登録完了ボタン
            next_signup_btn = page.locator("#signup3")
            await next_signup_btn.wait_for(state="visible")
            await next_signup_btn.click()
            
            return {"status": "success"}

        except Exception as e:
            await page.screenshot(path="error_detail.png") # デバッグ用
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)
