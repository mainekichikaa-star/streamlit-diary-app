import streamlit as st
import asyncio
import os
import subprocess
import gspread
import io
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from playwright.async_api import async_playwright

# --- 設定 ---
SPREADSHEET_ID = "1Fta23cis4AY9j2_lytfh0OOAJq-EFinLjqp_dLIAgtM"
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
    return build('drive', 'v3', credentials=creds)

def download_by_filename(path_str, save_path):
    if not path_str or str(path_str).strip() == "": return False
    try:
        drive_service = get_drive_service()
        filename = str(path_str).split('/')[-1]
        query = f"name = '{filename}' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        if not items: return False
        file_id = items[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        with open(save_path, "wb") as f:
            f.write(fh.getvalue())
        return True
    except: return False

async def run_automation(cast_data, sub_image_paths):
    try:
        if not os.path.exists("/home/appuser/.cache/ms-playwright"):
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
    except: pass

    main_img_tmp = "temp_main.jpg"
    download_by_filename(cast_data.get('メイン画像'), main_img_tmp)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000})
        page = await context.new_page()

        try:
            # 1. ログイン & ページ移動
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data.get('ID')).strip())
            await page.fill("#form_password", str(cast_data.get('PASSWORD')).strip())
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール等入力（中略 - 以前のロジック維持）
            await page.fill("#form_name", str(cast_data.get('名前')))
            await page.click("#form_update-btn", force=True)
            await page.wait_for_selector("text=データを登録しました。", timeout=30000)

            # 4. メイン画像アップロード
            st.info("📸 画像をアップロード中...")
            await page.click('a[data-target="con1"]')
            await page.locator('#con1 input[type="file"]').set_input_files(main_img_tmp)
            await asyncio.sleep(2)
            await page.locator('#con1 button.upbtn').click(force=True)
            
            # --- 【重要】サムネイル選択枠を全範囲（2枚目の画像の状態）に広げる ---
            st.info("✂️ サムネイル選択枠を最大化しています...")
            tracker = page.locator(".jcrop-tracker.target").first
            await tracker.wait_for(state="visible", timeout=15000)
            box = await tracker.bounding_box()
            
            if box:
                # 1. 左上隅をしっかり掴んで、右下まで大きくドラッグ
                # 遊びをなくすため、端ギリギリを攻めます
                await page.mouse.move(box["x"] + 2, box["y"] + 2)
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] - 2, steps=30)
                await page.mouse.up()
                await asyncio.sleep(1)

                # 2. ダメ押し：矢印キーを使って選択範囲を最大まで押し広げる
                # Jcropはフォーカスがある状態で矢印キー操作を受け付けることがあります
                await page.keyboard.press("Control+A") # 全選択を試行
                await asyncio.sleep(0.5)

            # 修正ボタンを「JavaScript」で強制発火（重なり無視）
            st.info("✅ 修正確定を実行...")
            await page.locator("input[value='修正する']").evaluate("el => el.click()")
            await asyncio.sleep(2)

            # サブ画像等の処理（既存ロジック）
            # ... (中略) ...

            await page.locator("#signup3").evaluate("el => el.click()")
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- Streamlit UI ---
st.title("👸 キャスト一括登録")
if st.button("🚀 実行開始"):
    # スプレッドシート読み込み・ループ処理（既存通り）
    # res = asyncio.run(run_automation(row, sub_urls))
    pass
