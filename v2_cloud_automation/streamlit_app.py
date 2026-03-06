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

# --- 1. Playwright インストール ---
@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

# --- 2. Google API 認証設定 ---
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
gs_client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)

SPREADSHEET_ID = "1Fta23cis4AY9j2_lytfh0OOAJq-EFinLjqp_dLIAgtM"

# --- 3. 画像ダウンロード関数 ---
def download_by_filename(path_str, save_path):
    if not path_str or str(path_str).strip() == "": return False
    try:
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
    except:
        return False

# --- 4. 自動化メイン処理 ---
async def run_automation(row_data, sub_image_urls):
    # 列番号定義 (A=0, B=1, ...)
    COL_ID, COL_PW, COL_NAME = 0, 1, 2
    COL_AGE, COL_TALL = 3, 4
    COL_B, COL_W, COL_H, COL_CUP = 5, 6, 7, 8
    COL_MAIN_IMG = 14

    main_img_tmp = "temp_main.jpg"
    name = str(row_data[COL_NAME])

    if not download_by_filename(row_data[COL_MAIN_IMG], main_img_tmp):
        return {"status": "error", "message": f"メイン画像({row_data[COL_MAIN_IMG]})が見つかりません"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # ログイン
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(row_data[COL_ID]).strip())
            await page.fill("#form_password", str(row_data[COL_PW]).strip())
            await page.click("#form_submit")
            
            # ログイン成否確認 (URLが変わらなければ失敗)
            await asyncio.sleep(2)
            if "login" in page.url:
                return {"status": "error", "message": "ログイン失敗(ID/PWが違います)"}

            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 入力
            await page.fill("#form_name", name)
            await page.fill("#form_age", str(row_data[COL_AGE]))
            await page.fill("#form_tall", str(row_data[COL_TALL]))
            await page.fill("#form_bust", str(row_data[COL_B]))
            await page.fill("#form_waist", str(row_data[COL_W]))
            await page.fill("#form_hip", str(row_data[COL_H]))
            
            # カップ選択
            cup = str(row_data[COL_CUP]).strip()
            try:
                await page.locator("#form_cup").select_option(label=re.compile(f"^{cup}", re.IGNORECASE))
            except: pass

            # 保存
            await page.click("#form_update-btn", force=True)
            await page.wait_for_selector('a[data-target="con1"]', state="visible", timeout=15000)

            # 画像アップ
            async def up(tid, path):
                await page.click(f'a[data-target="{tid}"]')
                await page.locator('input[type="file"]').first.set_input_files(path)
                await page.locator('button.upbtn').first.click()
                await asyncio.sleep(3)
                await page.get_by_role("button", name="修正する").click()
                await asyncio.sleep(1)

            await up("con1", main_img_tmp)
            await page.locator("#signup3").click()
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": f"エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. UI ---
st.title("🤴 キャスト一括登録")

if st.button("🚀 未登録分のみ実行"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    all_rows = sheet_info.get_all_values()
    data_rows = all_rows[1:] # ヘッダー除外
    
    processed = 0
    for i, row in enumerate(data_rows):
        # 厳密な判定: ID(A列) PW(B列) メイン画像(O列) があり、かつ 登録済(P列) が空
        if len(row) > 15:
            login_id = str(row[0]).strip()
            password = str(row[1]).strip()
            main_img = str(row[14]).strip()
            status_val = str(row[15]).strip()

            if login_id and password and main_img and not status_val:
                st.subheader(f"👤 実行中: {row[2]}")
                with st.status("自動登録中...") as status:
                    res = asyncio.run(run_automation(row, []))
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                        processed += 1
                    else:
                        status.update(label="❌ エラー", state="error")
                        st.error(res["message"])

    if processed == 0:
        st.info("条件（ID, PW, 画像あり かつ 未登録）に合うキャストはいませんでした。")
