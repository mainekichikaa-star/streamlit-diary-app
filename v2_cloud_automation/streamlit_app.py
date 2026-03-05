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
    except Exception: return False

async def run_automation(data):
    tmp_image = "temp_girl_photo.jpg"
    if not download_google_drive_image(data['image_url'], tmp_image):
        return {"status": "error", "message": "画像の取得に失敗しました。"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP']) 
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン & 登録画面へ
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (テスト用)
            await page.fill("#form_name", data['name'])
            await page.locator('input[name="p_genre[1]"]').check()
            await page.locator('input[name="genre[1]"]').check()
            
            st.info("💾 基本情報を登録中...")
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # 3. 画像アップロード
            st.info("📸 画像をアップロード中...")
            await page.get_by_text("データを登録しました。").wait_for(state="visible")
            await page.click('a[data-target="con1"]')
            await page.locator('input[type="file"]').first.set_input_files(tmp_image)
            await page.locator('button.upbtn').first.click()
            
            # 4. ドラッグ操作 (Jcrop対応)
            st.info("↕️ 画像の範囲をドラッグで選択中...")
            # 修正：トラッカーが表示されるまで待機
            tracker = page.locator(".jcrop-tracker.target").first
            await tracker.wait_for(state="visible", timeout=10000)
            
            box = await tracker.bounding_box()
            if box:
                # 左上角にマウスを移動してダウン
                await page.mouse.move(box["x"], box["y"])
                await page.mouse.down()
                # 右下へ向かって大きくドラッグ（画像全体を覆うように）
                await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=20)
                await page.mouse.up()
            
            # 5. 「修正する」ボタンで確定
            st.info("✅ 修正ボタンをクリック...")
            fix_btn = page.locator('input[value="修正する"].btn')
            await fix_btn.wait_for(state="visible")
            await fix_btn.click()
            await asyncio.sleep(2)

            # 6. 連続登録へ移行
            st.info("🔄 次の登録へ...")
            next_signup_btn = page.locator("#signup3")
            await next_signup_btn.wait_for(state="visible")
            await next_signup_btn.click()
            
            st.success("🎉 完了しました！")
            return {"status": "success", "message": "正常終了"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(tmp_image): os.remove(tmp_image)

# --- Streamlit UI ---
st.title("👸 女の子一括登録（ドラッグ＆確定版）")

# 修正：実行ボタンの外側で変数を定義して NameError を防ぐ
test_data = {
    "name": "るか",
    "cup": "C",
    "age": 22,
    "height": 160,
    "ai_catchphrase": "ドラッグ選択テスト",
    "ai_description": "Jcropトラッカーを操作して画像を修正・確定します。",
    "image_url": "https://drive.google.com/file/d/1uF4r8coNfFkhTiB4aH2ztUWjNw33HrtW/view?usp=drive_link"
}

if st.button("🚀 登録 ＆ ドラッグ修正を実行"):
    with st.status("自動処理を実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="すべて完了！", state="complete")
        else:
            status.update(label="エラー発生", state="error")
            st.error(res["message"])
