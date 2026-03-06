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

# --- 3. Googleドライブからダウンロード ---
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

# --- 4. 自動化メイン処理 (成功ベース・修正版) ---
async def run_automation(row_data, sub_image_paths):
    # 【列の定義を修正】A=0, B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, O=14
    COL_ID, COL_PW, COL_NAME = 0, 1, 2
    COL_AGE, COL_TALL = 3, 4
    COL_B, COL_W, COL_H, COL_CUP = 5, 6, 7, 8
    COL_MAIN_IMG = 14

    main_img_tmp = "temp_main.jpg"
    name = str(row_data[COL_NAME]).strip()

    if not download_by_filename(row_data[COL_MAIN_IMG], main_img_tmp):
        return {"status": "error", "message": f"メイン画像取得失敗: {row_data[COL_MAIN_IMG]}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info(f"🌐 ログイン中: {name}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(row_data[COL_ID]).strip())
            await page.fill("#form_password", str(row_data[COL_PW]).strip())
            await page.click("#form_submit")
            
            # ログイン成否チェック
            await asyncio.sleep(2)
            if "login" in page.url:
                return {"status": "error", "message": "ログイン失敗。ID/PWを確認してください。"}

            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (空欄回避のためstr()化)
            st.info("✍️ プロフィール入力中...")
            await page.fill("#form_name", name)
            await page.fill("#form_age", str(row_data[COL_AGE]).strip())
            await page.fill("#form_tall", str(row_data[COL_TALL]).strip())
            await page.fill("#form_bust", str(row_data[COL_B]).strip())
            await page.fill("#form_waist", str(row_data[COL_W]).strip())
            await page.fill("#form_hip", str(row_data[COL_H]).strip())
            
            cup = str(row_data[COL_CUP]).strip()
            try:
                await page.locator("#form_cup").select_option(label=re.compile(f"^{cup}", re.IGNORECASE))
            except: pass

            # タグ選択
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 
                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 
                                "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).check(force=True)

            # 基本情報登録
            await page.click("#form_update-btn", force=True)
            
            # 登録成功（画像ボタン出現）を待機
            await page.wait_for_selector('a[data-target="con1"]', state="visible", timeout=20000)

            # 3. 画像アップロード
            st.info("📸 画像をアップロード中...")
            await page.click('a[data-target="con1"]')
            await page.locator('input[type="file"]').first.set_input_files(main_img_tmp)
            await page.locator('button.upbtn').first.click()
            
            # ドラッグ操作
            tracker = page.locator(".jcrop-tracker.target").first
            await tracker.wait_for(state="visible", timeout=15000)
            box = await tracker.bounding_box()
            if box:
                await page.mouse.move(box["x"], box["y"])
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=20)
                await page.mouse.up()
            
            await page.get_by_role("button", name="修正する").click()
            await asyncio.sleep(2)

            # 4. 完了
            await page.locator("#signup3").click()
            return {"status": "success"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"自動化エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. Streamlit UI ---
st.title("👸 キャスト一括登録システム")

if st.button("🚀 未登録キャストをスキャンして実行"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    all_data = sheet_info.get_all_values()
    data_rows = all_data[1:] # ヘッダー除外
    
    processed_count = 0
    for i, row in enumerate(data_rows):
        # 厳格な判定: 
        # A列(ID), B列(PW), O列(メイン画像) がすべて存在し、
        # P列(登録済) が空欄(スペース除去後) であること
        if len(row) > 15:
            login_id = str(row[0]).strip()
            password = str(row[1]).strip()
            main_img = str(row[14]).strip()
            status_val = str(row[15]).strip()

            if login_id and password and main_img and not status_val:
                st.subheader(f"👤 対象: {row[2]}")
                with st.status(f"{row[2]} さんの登録を実行中...") as status:
                    res = asyncio.run(run_automation(row, []))
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                        processed_count += 1
                    else:
                        status.update(label="❌ エラー", state="error")
                        st.error(res["message"])
                        if os.path.exists("error_log.png"):
                            st.image("error_log.png")

    if processed_count == 0:
        st.info("対象の未登録キャスト（ID/PW/画像あり）は見つかりませんでした。")
    else:
        st.success(f"合計 {processed_count} 名の登録が完了しました！")
