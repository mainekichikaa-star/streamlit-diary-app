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

            # 3. プロフィール入力
            st.info("✍️ 基本情報を入力中...")
            await page.fill("#form_name", data['name'])
            
            # --- カップ数 (重要) ---
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            target_cup_val = cup_map.get(data['cup'].upper(), "3") # デフォルトC
            await page.select_option("#form_cup", value=target_cup_val)
            
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # キャッチコピー (15文字制限)
            catchphrase = data['ai_catchphrase'][:15]
            await page.fill("#form_catchcopy", catchphrase)
            await page.fill("#form_comments", data['ai_description'])

            # 4. 優先タグの選択
            st.info("🏷️ 優先タグを選択中...")
            priority_tag = page.locator('input[name="p_genre[1]"]')
            await priority_tag.scroll_into_view_if_needed()
            await priority_tag.check()

            # 5. 通常ジャンルの選択 (追加修正箇所)
            st.info("🏷️ 通常ジャンルを選択中...")
            # genre[1] (no1) を選択
            normal_genre = page.locator('input[name="genre[1]"]')
            await normal_genre.scroll_into_view_if_needed()
            await normal_genre.check()

            # 6. 登録実行
            st.info("💾 登録ボタンをクリックします...")
            submit_selector = "#form_update-btn"
            
            # ページ遷移を待機しながらクリック
            async with page.expect_navigation(timeout=60000):
                await page.click(submit_selector, force=True)

            # 7. 成功メッセージの確認
            st.info("🔍 結果を確認中...")
            success_locator = page.locator(".message")
            
            try:
                await success_locator.wait_for(state="visible", timeout=15000)
                msg_text = await success_locator.inner_text()
                
                if "データを登録しました" in msg_text:
                    st.success("🎉 登録に成功しました！")
                    await page.screenshot(path="registration_success.png")
                    return {"status": "success", "message": "登録完了"}
                else:
                    st.error(f"エラーメッセージ: {msg_text}")
                    await page.screenshot(path="error_message.png")
                    return {"status": "error", "message": msg_text}
            except:
                st.warning("遷移後の状態が不明です。スクリーンショットを確認してください。")
                await page.screenshot(path="debug_result.png")
                return {"status": "check", "message": "結果不明"}

        except Exception as e:
            await page.screenshot(path="critical_error.png")
            return {"status": "error", "message": f"停止エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("🤖 登録完了・完全修正版")

if st.button("全項目入力で登録を実行"):
    test_data = {
        "name": "るか",
        "cup": "C", # カップ数追加
        "age": 22,
        "height": 160,
        "ai_catchphrase": "新人入店！最高に可愛いです",
        "ai_description": "丁寧な接客でお迎えします。ぜひ会いに来てください！"
    }
    
    with st.status("実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="登録成功！", state="complete")
            st.image("registration_success.png")
        else:
            status.update(label="エラー", state="error")
            st.error(res["message"])
            if os.path.exists("error_message.png"):
                st.image("error_message.png")
