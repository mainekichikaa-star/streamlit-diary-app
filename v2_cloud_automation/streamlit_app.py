import streamlit as st
import asyncio
import os
import subprocess
import requests
import re
from playwright.async_api import async_playwright

@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

def download_google_drive_image(url, save_path):
    try:
        match = re.search(r'd/([a-zA-Z0-9_-]+)', url)
        if not match: return False
        file_id = match.group(1)
        direct_url = f'https://drive.google.com/uc?export=download&id={file_id}'
        response = requests.get(direct_url, timeout=15)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception:
        return False

async def run_automation(data):
    tmp_image = "temp_girl_photo.jpg"
    if not download_google_drive_image(data['image_url'], tmp_image):
        return {"status": "error", "message": "画像の取得に失敗しました。"}

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

            # 3. プロフィール入力
            st.info("✍️ プロフィール入力中...")
            await page.fill("#form_name", data['name'])
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            await page.select_option("#form_cup", value=cup_map.get(data['cup'].upper(), "3"))
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            await page.fill("#form_catchcopy", data['ai_catchphrase'][:15])
            await page.fill("#form_comments", data['ai_description'])
            await page.locator('input[name="p_genre[1]"]').check()
            await page.locator('input[name="genre[1]"]').check()

            # 4. 登録実行
            st.info("💾 登録ボタンをクリック...")
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # 5. 画像アップロード工程
            st.info("🔍 画像をアップロード中...")
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=15000)
            await page.click('a[data-target="con1"]')
            
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(tmp_image)
            
            # アップロードボタンをクリック
            await page.locator('button.upbtn').first.click()
            
            # --- ここから追加：モーダルを閉じる工程 ---
            st.info("⏳ 処理の完了を待機中...")
            await asyncio.sleep(3) # プレビュー生成待ち
            
            # 「閉じる」ボタンをクリック（画像内の×ボタンなど）
            st.info("✖️ モーダルを閉じます...")
            close_btn = page.locator('span.modal-close')
            if await close_btn.is_visible():
                await close_btn.click()
                await asyncio.sleep(1)

            # --- 連続登録のためのボタンクリック ---
            st.info("🔄 次の登録準備へ...")
            # 「女の子の新規登録」ボタンをクリック
            next_signup_btn = page.locator("#signup3")
            if await next_signup_btn.is_visible():
                await next_signup_btn.click()
                await page.wait_for_load_state("networkidle")
            
            st.success("✅ 全行程完了！次の登録画面へ遷移しました。")
            await page.screenshot(path="final_ready.png")
            return {"status": "success", "message": "一括登録 ＆ 次回準備完了"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"実行エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(tmp_image): os.remove(tmp_image)

# --- Streamlit UI ---
st.title("👸 女の子一括登録（ループ対応版）")
target_url = "https://drive.google.com/file/d/1uF4r8coNfFkhTiB4aH2ztUWjNw33HrtW/view?usp=drive_link"

if st.button("🚀 登録 ＆ 次回画面へ遷移"):
    test_data = {
        "name": "るか", "cup": "C", "age": 22, "height": 160,
        "ai_catchphrase": "ループ登録テスト",
        "ai_description": "登録完了後に自動で次の新規登録画面へ戻ります。",
        "image_url": target_url
    }
    with st.status("自動処理中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="完了！", state="complete")
            st.image("final_ready.png")
        else:
            status.update(label="エラー", state="error")
            st.error(res["message"])
