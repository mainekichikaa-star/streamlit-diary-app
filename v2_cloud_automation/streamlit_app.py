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

# --- 3. ドライブからファイル名で検索・ダウンロード ---
def download_by_filename(path_str, save_path):
    if not path_str or str(path_str).strip() == "": return False
    try:
        # パス形式(XXX/filename.jpg)からファイル名のみ抽出
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

# --- 4. 自動化メイン処理 (指定の列構成に準拠) ---
async def run_automation(row_data, sub_image_urls):
    # 列定義 (添字は0から開始)
    # 1:ID(0), 3:名前(2), 4:身長(3), 5:バスト(4), 6:カップ数(5), 7:ウエスト(6), 8:ヒップ(7)
    # 12:メイン画像(11), 14:ログインID(13), 15:PASSWORD(14), 16:登録済(15)
    COL_NAME = 2
    COL_TALL = 3
    COL_BUST = 4
    COL_CUP  = 5
    COL_W    = 6
    COL_H    = 7
    COL_MAIN_IMG = 11
    COL_LOGIN_ID = 13
    COL_LOGIN_PW = 14

    main_img_tmp = "temp_main.jpg"
    name = str(row_data[COL_NAME])

    if not download_by_filename(row_data[COL_MAIN_IMG], main_img_tmp):
        return {"status": "error", "message": f"メイン画像が見つかりません: {row_data[COL_MAIN_IMG]}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info(f"🌐 ログイン中: {name}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(row_data[COL_LOGIN_ID]).strip())
            await page.fill("#form_password", str(row_data[COL_LOGIN_PW]).strip())
            await page.click("#form_submit")
            await asyncio.sleep(2)
            if "login" in page.url:
                return {"status": "error", "message": "ログインに失敗しました。ID/PWを確認してください。"}

            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (3-8列目のデータ)
            st.info("✍️ 基本情報を入力中...")
            await page.fill("#form_name", name)
            await page.fill("#form_tall", str(row_data[COL_TALL]).strip())
            await page.fill("#form_bust", str(row_data[COL_BUST]).strip())
            await page.fill("#form_waist", str(row_data[COL_W]).strip())
            await page.fill("#form_hip", str(row_data[COL_H]).strip())
            
            # カップ選択
            cup = str(row_data[COL_CUP]).strip()
            try:
                await page.locator("#form_cup").select_option(label=re.compile(f"^{cup}", re.IGNORECASE))
            except: pass

            # 3. 保存と画像登録
            await page.click("#form_update-btn", force=True)
            await page.wait_for_selector('a[data-target="con1"]', state="visible", timeout=20000)

            # --- アップロード共通処理 ---
            async def upload_img(target_id, file_path, label):
                st.info(f"📸 {label}をアップロード中...")
                await page.click(f'a[data-target="{target_id}"]')
                await page.locator('input[type="file"]').first.set_input_files(file_path)
                await page.locator('button.upbtn').first.click()
                
                tracker = page.locator(".jcrop-tracker.target").first
                await tracker.wait_for(state="visible", timeout=10000)
                box = await tracker.bounding_box()
                if box:
                    await page.mouse.move(box["x"], box["y"])
                    await page.mouse.down()
                    await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
                    await page.mouse.up()
                await page.get_by_role("button", name="修正する").click()
                await asyncio.sleep(2)

            # メイン画像
            await upload_img("con1", main_img_tmp, "メイン画像")

            # サブ画像 (最大7枚)
            for i, sub_url in enumerate(sub_image_urls):
                if i >= 7: break
                sub_tmp = f"temp_sub_{i}.jpg"
                if download_by_filename(sub_url, sub_tmp):
                    await upload_img(f"con{i+2}", sub_tmp, f"サブ画像{i+1}")
                    if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 完了
            await page.locator("#signup3").click()
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. Streamlit UI ---
st.title("👸 キャスト一括登録システム")

if st.button("🚀 未登録キャストを登録開始"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    info_rows = sheet_info.get_all_values()
    image_records = sheet_images.get_all_records()
    
    data_rows = info_rows[1:]
    processed = 0

    for i, row in enumerate(data_rows):
        # 判定：14列目(ID), 15列目(PW)があり、16列目(登録済)が空
        # ※添字：13, 14, 15
        if len(row) >= 15:
            login_id = str(row[13]).strip()
            login_pw = str(row[14]).strip()
            # 16列目が存在しないか空の場合
            is_registered = str(row[15]).strip() if len(row) > 15 else ""

            if login_id and login_pw and not is_registered:
                st.subheader(f"👤 対象: {row[2]}")
                
                # 紐付け：キャスト情報1列目(row[0]) と キャスト画像2列目(CastID)
                cast_id_val = str(row[0]).strip()
                sub_urls = [img['写真'] for img in image_records if str(img['CastID']).strip() == cast_id_val]
                
                with st.status("自動実行中...") as status:
                    res = asyncio.run(run_automation(row, sub_urls))
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                        processed += 1
                    else:
                        status.update(label="❌ エラー", state="error")
                        st.error(res["message"])

    if processed == 0:
        st.info("条件に一致する未登録キャストはいませんでした。")
    else:
        st.success(f"計 {processed} 名の登録を完了しました。")
