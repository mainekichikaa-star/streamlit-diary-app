import streamlit as st
import asyncio
import os
import subprocess
import gspread
import io
import re
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

async def handle_jcrop_and_fix(page, target_id):
    """
    指定されたモーダル内のすべてのJcropを処理し、すべての『修正する』ボタンを押す
    """
    # Jcropのターゲットをすべて取得
    trackers = page.locator(f"#{target_id} .jcrop-tracker.target")
    count = await trackers.count()
    
    for i in range(count):
        tracker = trackers.nth(i)
        if await tracker.is_visible():
            box = await tracker.bounding_box()
            if box:
                # 左上から右下へドラッグ
                await page.mouse.move(box["x"], box["y"])
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=10)
                await page.mouse.up()
                await asyncio.sleep(0.5)

    # モーダル内の「修正する」ボタンをすべて順番に押す（JS実行で重なり回避）
    fix_buttons = page.locator(f"#{target_id} input[value='修正する']")
    btn_count = await fix_buttons.count()
    for i in range(btn_count):
        btn = fix_buttons.nth(i)
        if await btn.is_visible():
            await btn.evaluate("node => node.click()") # 強制クリック
            await asyncio.sleep(1)

async def run_automation(cast_data, sub_image_paths):
    try:
        if not os.path.exists("/home/appuser/.cache/ms-playwright"):
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
    except: pass

    main_img_tmp = "temp_main.jpg"
    if not download_by_filename(cast_data.get('メイン画像'), main_img_tmp):
        return {"status": "error", "message": "メイン画像取得失敗"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data.get('ID')).strip())
            await page.fill("#form_password", str(cast_data.get('PASSWORD')).strip())
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力
            await page.fill("#form_name", str(cast_data.get('名前')))
            # ... (身長、バスト等の入力は省略せず維持)
            for key, selector in [('身長','#form_tall'), ('バスト','#form_bust'), ('ウエスト','#form_waist'), ('ヒップ','#form_hip')]:
                await page.fill(selector, str(cast_data.get(key)))

            cup_input = str(cast_data.get('カップ数', '')).strip().upper() 
            if cup_input:
                try: await page.locator("#form_cup").select_option(label=f"{cup_input}カップ")
                except: pass
            
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0: await page.locator(selector).check(force=True)

            await page.click("#form_update-btn", force=True)
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=30000)

            # 4. 画像1〜8の処理
            all_images = [cast_data.get('メイン画像')] + sub_image_paths
            
            for idx, img_path in enumerate(all_images):
                img_num = idx + 1
                if img_num > 8: break
                
                target_id = f"con{img_num}"
                tmp_file = f"temp_{img_num}.jpg"
                
                if download_by_filename(img_path, tmp_file):
                    st.info(f"📸 画像{img_num}を処理中...")
                    
                    # モーダルを開く (JSクリックで重なり回避)
                    btn_open = page.locator(f'a[data-target="{target_id}"]')
                    await btn_open.evaluate("node => node.click()")
                    
                    # アップロード
                    await page.locator(f'#{target_id} input[type="file"]').set_input_files(tmp_file)
                    await asyncio.sleep(2)
                    
                    # アップロードボタン実行
                    up_btn = page.locator(f'#{target_id} button.upbtn')
                    await up_btn.evaluate("node => node.click()")
                    
                    # リロード待機
                    await asyncio.sleep(5)
                    await page.wait_for_load_state("networkidle")
                    
                    # 再展開して編集
                    await page.locator(f'a[data-target="{target_id}"]').evaluate("node => node.click()")
                    await asyncio.sleep(2)
                    
                    # Jcropドラッグ & 修正するボタン(複数対応)
                    await handle_jcrop_and_fix(page, target_id)
                    
                    if os.path.exists(tmp_file): os.remove(tmp_file)

            await page.locator("#signup3").evaluate("node => node.click()")
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally:
            await browser.close()

# --- UI ---
st.title("👸 キャスト一括登録システム")
if st.button("🚀 実行開始"):
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
        gs_client = gspread.authorize(creds)
        sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
        sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
        data_info = sheet_info.get_all_records()
        data_images = sheet_images.get_all_records()

        for i, row in enumerate(data_info):
            if str(row.get('ID')).strip() and str(row.get('PASSWORD')).strip() and not str(row.get('登録済')).strip():
                st.subheader(f"👤 {row.get('名前')}")
                target_id = str(row.get('ＩＤ')).strip()
                sub_urls = [img['写真'] for img in data_images if str(img.get('CastID')).strip() == target_id]
                with st.status(f"{row.get('名前')} 登録中...") as status:
                    res = asyncio.run(run_automation(row, sub_urls))
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                    else:
                        status.update(label="❌ エラー", state="error")
                        st.error(res["message"])
    except Exception as e: st.error(f"起動エラー: {e}")
