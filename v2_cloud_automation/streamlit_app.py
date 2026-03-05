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
            # 1. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await page.wait_for_load_state("networkidle")

            # 2. 新規登録画面へ
            st.info("📑 登録画面へ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")
            await page.wait_for_load_state("networkidle")

            # 3. 基本情報入力
            st.info("✍️ プロフィールを入力中...")
            await page.fill("#form_name", data['name'])
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            await page.select_option("#form_cup", value=cup_map.get(data['cup'].upper(), "3"))
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            await page.fill("#form_catchcopy", data['ai_catchphrase'][:15])
            await page.fill("#form_comments", data['ai_description'])

            # 4. タグ・ジャンル選択
            st.info("🏷️ 各種タグを選択中...")
            await page.locator('input[name="p_genre[1]"]').check() # 優先タグ
            await page.locator('input[name="genre[1]"]').check()   # 通常ジャンル

            # 5. 登録実行
            st.info("💾 登録ボタンをクリック...")
            submit_selector = "#form_update-btn"
            async with page.expect_navigation(timeout=60000):
                await page.click(submit_selector, force=True)

            # 6. 成功確認（修正ポイント：テキストで要素を特定）
            st.info("🔍 登録結果を検証中...")
            # 11個ある .message の中から「データを登録しました」という文字を持つものだけを待機
            success_locator = page.get_by_text("データを登録しました。")
            
            try:
                await success_locator.wait_for(state="visible", timeout=15000)
                st.success("✅ 基本情報の登録に成功しました！")
                
                # --- 画像アップロード処理 ---
                image_path = "girl_photo.jpg" 
                if os.path.exists(image_path):
                    st.info("📸 画像アップロードを開始します...")
                    
                    # ボタンが表示されるまで少し待機してからクリック
                    upload_btn = page.locator('a[data-target="con1"]')
                    await upload_btn.wait_for(state="visible", timeout=10000)
                    await upload_btn.click()
                    
                    # ファイル選択 (モーダル内のinputを狙う)
                    # 複数ある場合は .first や セレクタの絞り込みが必要な場合があります
                    file_input = page.locator('input[type="file"]')
                    await file_input.set_input_files(image_path)
                    
                    # 完了まで少し待機
                    await asyncio.sleep(5) 
                    st.success("📸 画像のアップロード操作が完了しました。")
                else:
                    st.warning(f"⚠️ 画像ファイル({image_path})がないためスキップしました。")
                
                await page.screenshot(path="final_result.png")
                return {"status": "success", "message": "一括処理完了"}

            except Exception as e:
                st.error(f"判定エラー: {str(e)}")
                await page.screenshot(path="check_error.png")
                return {"status": "error", "message": "完了メッセージの確認に失敗"}

        except Exception as e:
            await page.screenshot(path="critical_error.png")
            return {"status": "error", "message": f"停止エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("👸 女の子一括登録 & 画像UP")
st.markdown("---")

if st.button("🚀 実行する"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "新人入店！最高に可愛いです",
        "ai_description": "丁寧な接客でお迎えします。ぜひ会いに来てください！"
    }
    
    with st.status("自動処理中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="すべて成功！", state="complete")
            st.image("final_result.png")
        else:
            status.update(label="エラー", state="error")
            st.error(res["message"])
