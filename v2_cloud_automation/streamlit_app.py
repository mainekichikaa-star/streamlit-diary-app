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
            # 1. ログイン & 登録画面へ (省略版)
            st.info("🌐 ログイン & 登録中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 & 登録
            await page.fill("#form_name", data['name'])
            # ... 他の項目も入力 ...
            await page.locator('input[name="p_genre[1]"]').check()
            await page.locator('input[name="genre[1]"]').check()
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # 3. 画像アップロード
            st.info("📸 画像アップロード開始...")
            await page.click('a[data-target="con1"]')
            await page.locator('input[type="file"]').first.set_input_files(tmp_image)
            await page.locator('button.upbtn').first.click()
            
            # --- 4. ドラッグ操作による範囲選択 ---
            st.info("↕️ 画像の範囲を調整中...")
            await asyncio.sleep(3) # モーダル表示待ち
            
            # プレビュー画像またはクロッパーの要素を特定
            # スクリーンショットの点線枠の左上角（ハンドル）を狙います
            # セレクタは一般的なクロッパーライブラリを想定（必要に応じて調整）
            handle = page.locator(".cropper-point.point-nw").first # 左上角
            if await handle.is_visible():
                box = await handle.bounding_box()
                # ドラッグ操作: 左上から右下へ
                await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await page.mouse.down()
                await page.mouse.move(box["x"] + 400, box["y"] + 600, steps=10) # 適当な広さまでドラッグ
                await page.mouse.up()
            
            # --- 5. 「修正する」ボタンで確定 ---
            st.info("✅ 修正内容を確定中...")
            fix_btn = page.locator('input[value="修正する"].btn')
            await fix_btn.wait_for(state="visible")
            await fix_btn.click()
            await asyncio.sleep(2)

            # 6. 連続登録のためのボタンクリック
            st.info("🔄 次の登録へ...")
            next_signup_btn = page.locator("#signup3")
            await next_signup_btn.wait_for(state="visible")
            await next_signup_btn.click()
            
            st.success("🎉 すべての工程が完了しました！")
            return {"status": "success", "message": "完了"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"実行エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(tmp_image): os.remove(tmp_image)

# Streamlit UI 部分は前回と同様
st.title("👸 女の子一括登録（画像修正・ループ対応版）")
if st.button("🚀 実行"):
    # test_dataの設定...
    res = asyncio.run(run_automation(test_data))
