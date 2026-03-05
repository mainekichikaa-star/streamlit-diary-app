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
        # 文字化け対策
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
            
            # カップ選択 (value値で指定)
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            target_cup = cup_map.get(data['cup'].upper().replace("カップ",""), "0")
            await page.select_option("#form_cup", value=target_cup)
            
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # 4. キャッチコピー・メッセージ (解析したIDを正確に使用)
            await page.fill("#form_catchcopy", data['ai_catchphrase'])
            await page.fill("#form_title", "新人スタッフの紹介")
            await page.fill("#form_comments", data['ai_description'])
            
            # 5. タグ選択
            st.info("🏷️ タグを選択中...")
            if 'tag_ids' in data:
                for tid in data['tag_ids']:
                    selector = f"#genre{tid}"
                    if await page.query_selector(selector):
                        await page.check(selector)

            # --- 画像アップロードは一旦スキップ（登録完了を優先するため） ---

            # 6. 登録実行
            st.info("💾 登録ボタンをクリックします...")
            
            # 確実にボタンが見える位置までスクロール
            submit_btn = page.locator("#form_update-btn")
            await submit_btn.scroll_into_view_if_needed()
            
            # クリックしてナビゲーションを待つ
            await asyncio.gather(
                page.wait_for_navigation(timeout=60000),
                submit_btn.click()
            )

            # 7. 成功メッセージの確認
            st.info("🔍 完了メッセージを確認中...")
            # 画面内に「データを登録しました」があるか確認
            success_msg = page.locator(".message", has_text="データを登録しました")
            
            # メッセージが表示されるまで最大20秒待機
            await success_msg.wait_for(state="visible", timeout=20000)
            
            st.success("🎉 『データを登録しました。』を確認！登録成功です！")
            await page.screenshot(path="registration_success.png")
            return {"status": "success", "message": "登録完了"}

        except Exception as e:
            # エラー時の画面を保存して原因を特定しやすくする
            await page.screenshot(path="debug_error.png")
            return {"status": "error", "message": f"停止エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("🤖 登録完了・最優先実行ロボ")

if st.button("今すぐ登録を実行"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "最高に可愛い新人が入店しました！",
        "ai_description": "丁寧な接客でお迎えします。ぜひ会いに来てください！",
        "tag_ids": ["10", "21"]
    }
    
    with st.status("登録処理中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="登録に成功しました！", state="complete")
            st.image("registration_success.png")
        else:
            status.update(label="登録失敗", state="error")
            st.error(res["message"])
            if os.path.exists("debug_error.png"):
                st.image("debug_error.png", caption="エラー発生時の画面")
