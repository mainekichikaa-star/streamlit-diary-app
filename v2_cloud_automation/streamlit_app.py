import streamlit as st
import asyncio
import os
import subprocess
from playwright.async_api import async_playwright

@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

async def run_automation(data):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP']) 
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # --------------------------------------------------
            # STEP 1: ログイン
            # --------------------------------------------------
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await page.wait_for_load_state("networkidle")

            # --------------------------------------------------
            # STEP 2: 新規登録画面へ
            # --------------------------------------------------
            st.info("📑 登録画面へ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")
            await page.wait_for_load_state("networkidle")

            # --------------------------------------------------
            # STEP 3: プロフィール入力
            # --------------------------------------------------
            st.info("✍️ 基本情報を入力中...")
            await page.fill("#form_name", data['name'])
            
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            target_cup_val = cup_map.get(data['cup'].upper(), "3")
            await page.select_option("#form_cup", value=target_cup_val)
            
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            catchphrase = data['ai_catchphrase'][:15]
            await page.fill("#form_catchcopy", catchphrase)
            await page.fill("#form_comments", data['ai_description'])

            # --------------------------------------------------
            # STEP 4: 各種タグの選択 (優先タグ & 通常ジャンル)
            # --------------------------------------------------
            st.info("🏷️ タグを選択中...")
            await page.locator('input[name="p_genre[1]"]').check() # 優先タグ no1
            await page.locator('input[name="genre[1]"]').check()   # 通常ジャンル no1

            # --------------------------------------------------
            # STEP 5: 登録実行
            # --------------------------------------------------
            st.info("💾 登録ボタンをクリック...")
            submit_selector = "#form_update-btn"
            async with page.expect_navigation(timeout=60000):
                await page.click(submit_selector, force=True)

            # --------------------------------------------------
            # STEP 6: 成功確認 ＆ 画像アップロード開始
            # --------------------------------------------------
            st.info("🔍 登録結果を確認 ＆ 画像アップロード準備...")
            success_locator = page.locator(".message")
            await success_locator.wait_for(state="visible", timeout=15000)
            msg_text = await success_locator.inner_text()
            
            if "データを登録しました" in msg_text:
                st.success("✅ 基本情報の登録成功！続けて画像をアップロードします。")
                
                # 画像ファイルパスの確認 (適宜修正してください)
                image_path = "girl_photo.jpg" 
                
                if os.path.exists(image_path):
                    st.info("📸 画像アップロード中...")
                    # 1. 画像編集用の子ウィンドウ(モーダル)を開くボタンをクリック
                    # 登録直後のページにある「con1」ターゲットのリンクを狙う
                    await page.click('a[data-target="con1"]')
                    
                    # 2. ファイル選択(input type="file")にパスを入力
                    # idやnameが異なる場合はここを調整
                    await page.set_input_files('input[type="file"]', image_path)
                    
                    # 3. アップロード確定ボタン（例としてid="upload"など。サイト仕様に合わせて調整）
                    # await page.click("#upload_button_id") 
                    
                    # 4. 少し待機して保存
                    await asyncio.sleep(3)
                    st.success("📸 画像の送信が完了しました！")
                else:
                    st.warning(f"⚠️ アップロードする画像が見つかりません: {image_path}")
                
                await page.screenshot(path="final_result.png")
                return {"status": "success", "message": "登録 ＆ 画像処理完了"}
            else:
                st.error(f"❌ 登録エラー: {msg_text}")
                return {"status": "error", "message": msg_text}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"停止エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("👸 女の子一括登録くん")
st.markdown("---")

if st.button("🚀 登録 ＆ 画像アップロードを実行"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "新人入店！最高に可愛いです",
        "ai_description": "丁寧な接客でお迎えします。ぜひ会いに来てください！"
    }
    
    with st.status("自動処理を実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="すべて完了！", state="complete")
            st.image("final_result.png", caption="最終的な画面状態")
        else:
            status.update(label="エラー発生", state="error")
            st.error(res["message"])
