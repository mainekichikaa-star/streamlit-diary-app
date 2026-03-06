async def run_automation(cast_data, sub_image_paths):
    main_img_tmp = "temp_main.jpg"
    if not download_by_filename(cast_data.get('メイン画像'), main_img_tmp):
        return {"status": "error", "message": "メイン画像取得失敗"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン & 新規作成画面へ
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data.get('ID')).strip())
            await page.fill("#form_password", str(cast_data.get('PASSWORD')).strip())
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 & タグ選択 (既存ロジック維持)
            await page.fill("#form_name", str(cast_data.get('名前')))
            await page.fill("#form_tall", str(cast_data.get('身長')))
            await page.fill("#form_bust", str(cast_data.get('バスト')))
            await page.fill("#form_waist", str(cast_data.get('ウエスト')))
            await page.fill("#form_hip", str(cast_data.get('ヒップ')))
            
            # --- タグ選択 ---
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 
                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 
                                "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).check(force=True)

            # 保存
            await page.click("#form_update-btn", force=True)
            
            # 3. リロード待機
            st.info("💾 保存完了を待機中...")
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=30000)

            # 4. メイン画像アップロード
            st.info("📸 メイン画像をアップロードします")
            await page.click('a[data-target="con1"]')
            
            # ファイル選択
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(main_img_tmp)
            
            # 【重要】ファイル選択後、ボタンが出るまで少し待つ
            await asyncio.sleep(2) 
            
            up_btn = page.locator('button.upbtn').first
            # 待機時間を20秒に延長
            await up_btn.wait_for(state="visible", timeout=20000)
            await up_btn.click(force=True)
            
            # Jcrop ドラッグ
            tracker = page.locator(".jcrop-tracker.target").first
            await tracker.wait_for(state="visible", timeout=15000)
            box = await tracker.bounding_box()
            if box:
                await page.mouse.move(box["x"], box["y"])
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
                await page.mouse.up()
            
            await page.get_by_role("button", name="修正する").click()
            await asyncio.sleep(1)

            # 5. サブ画像
            if sub_image_paths:
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        await page.click(f'a[data-target="con{i+2}"]')
                        await page.locator('input[type="file"]').first.set_input_files(sub_tmp)
                        
                        # サブ画像も同様に待機
                        await asyncio.sleep(1.5)
                        sub_up_btn = page.locator('button.upbtn').first
                        await sub_up_btn.wait_for(state="visible", timeout=15000)
                        await sub_up_btn.click(force=True)
                        
                        await asyncio.sleep(1)
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 6. 完了
            await page.locator("#signup3").click()
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)
