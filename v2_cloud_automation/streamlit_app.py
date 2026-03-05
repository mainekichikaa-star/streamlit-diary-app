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
            st.info("✍️ 基本情報を入力中...")
            await page.fill("#form_name", data['name'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # キャッチコピーは15文字以内制限
            catchphrase = data['ai_catchphrase'][:15]
            await page.fill("#form_catchcopy", catchphrase)
            
            await page.fill("#form_comments", data['ai_description'])

            # 4. 優先ジャンル（タグ）の選択（最低1つ必須）
            st.info("🏷️ 優先タグを選択中...")
            # no1 (value="1") を選択
            priority_tag = page.locator('input[name="p_genre[1]"]')
            await priority_tag.scroll_into_view_if_needed()
            await priority_tag.check()

            # 5. 登録実行
            st.info("💾 登録ボタンをクリックします...")
            submit_selector = "#form_update-btn"
            await page.locator(submit_selector).scroll_into_view_if_needed()
            
            # ページ遷移を待機しながらクリック
            async with page.expect_navigation(timeout=60000):
                await page.click(submit_selector, force=True)

            # 6. 成功メッセージの確認
            st.info("🔍 完了メッセージを確認中...")
            success_locator = page.locator(".message")
            
            # エラーメッセージが出ていないか、成功が出ているかチェック
            try:
                await success_locator.wait_for(state="visible", timeout=10000)
                msg_text = await success_locator.inner_text()
                
                if "データを登録しました" in msg_text:
                    st.success("🎉 登録完了しました！")
                    await page.screenshot(path="registration_success.png")
                    return {"status": "success", "message": "登録完了"}
                else:
                    # エラーメッセージが返ってきた場合
                    st.error(f"バリデーションエラー: {msg_text}")
                    await page.screenshot(path="validation_error.png")
                    return {"status": "error", "message": msg_text}
            except:
                st.warning("成功メッセージが見つかりません。画面を確認してください。")
                await page.screenshot(path="debug_after_click.png")
                return {"status": "check", "message": "遷移後の状態を確認してください"}

        except Exception as e:
            await page.screenshot(path="debug_error.png")
            return {"status": "error", "message": f"停止エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("🤖 登録完了・タグ＆文字数修正版")

if st.button("修正版で登録を実行"):
    test_data = {
        "name": "るか",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "新人入店！最高に可愛いです", # 15文字以内
        "ai_description": "丁寧な接客でお迎えします。ぜひ会いに来てください！"
    }
    
    with st.status("実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="登録成功！", state="complete")
            st.image("registration_success.png")
        else:
            status.update(label="エラーまたは要確認", state="error")
            st.error(res["message"])
            if os.path.exists("validation_error.png"):
                st.image("validation_error.png")
            elif os.path.exists("debug_error.png"):
                st.image("debug_error.png")
