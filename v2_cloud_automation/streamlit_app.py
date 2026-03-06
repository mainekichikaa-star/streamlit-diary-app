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

# --- 1. 日本語フォント & Playwright インストール ---
@st.cache_resource
def install_dependencies():
    try:
        # 日本語文字化け対策
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "install", "-y", "fonts-noto-cjk"], check=True)
        # Playwright
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.warning(f"依存関係のインストールで警告が出ました（環境によりスキップ可）: {e}")

install_dependencies()

# --- 2. Google API 認証 ---
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
    except: return False

# --- 4. 自動化メイン (Playwright) ---
async def run_automation(cast_data, sub_image_paths):
    main_img_tmp = f"temp_main_{cast_data.get('ＩＤ')}.jpg"
    if not download_by_filename(cast_data.get('メイン画像'), main_img_tmp):
        return {"status": "error", "message": "メイン画像が取得できませんでした。"}

    async with async_playwright() as p:
        # 日本語環境を指定して起動
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 2000},
            locale="ja-JP",
            timezone_id="Asia/Tokyo"
        )
        page = await context.new_page()

        try:
            # ログイン
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data.get('ID')).strip())
            await page.fill("#form_password", str(cast_data.get('PASSWORD')).strip())
            await page.click("#form_submit")
            await asyncio.sleep(2)

            # 新規登録ページ
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 基本情報入力 (辞書のキーはシートのヘッダー名に依存)
            st.info(f"✍️ {cast_data.get('名前')} さんの情報を入力中...")
            await page.fill("#form_name", str(cast_data.get('名前')))
            await page.fill("#form_age", str(cast_data.get('年齢', '20'))) # 年齢が空なら20を仮入れ
            await page.fill("#form_tall", str(cast_data.get('身長')))
            await page.fill("#form_bust", str(cast_data.get('バスト')))
            await page.fill("#form_waist", str(cast_data.get('ウエスト')))
            await page.fill("#form_hip", str(cast_data.get('ヒップ')))
            
            # カップ選択
            cup = str(cast_data.get('カップ数', '')).strip()
            if cup:
                try:
                    await page.locator("#form_cup").select_option(label=re.compile(f"^{cup}", re.IGNORECASE))
                except: pass

            # 保存ボタン
            await page.click("#form_update-btn", force=True)

            # 画像ボタンの待機 (ここで失敗したら入力エラー)
            try:
                await page.wait_for_selector('a[data-target="con1"]', state="visible", timeout=15000)
            except:
                err_img = f"error_{cast_data.get('名前')}.png"
                await page.screenshot(path=err_img)
                return {"status": "error", "message": "入力エラーで保存できませんでした。", "image": err_img}

            # 画像アップロード
            await page.click('a[data-target="con1"]')
            await page.locator('input[type="file"]').first.set_input_files(main_img_tmp)
            await page.locator('button.upbtn').first.click()
            
            # 修正ボタン（確定）を待つ
            fix_btn = page.get_by_role("button", name="修正する")
            await fix_btn.wait_for(state="visible", timeout=15000)
            await fix_btn.click()
            await asyncio.sleep(2)

            # サブ画像
            for i, sub_url in enumerate(sub_image_paths):
                if i >= 7: break
                sub_tmp = f"sub_{i}.jpg"
                if download_by_filename(sub_url, sub_tmp):
                    await page.click(f'a[data-target="con{i+2}"]')
                    await page.locator('input[type="file"]').first.set_input_files(sub_tmp)
                    await page.locator('button.upbtn').first.click()
                    await asyncio.sleep(1)
                    if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 最終登録
            await page.locator("#signup3").click()
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"実行エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. 画面 ---
st.title("👸 キャスト登録 (文字化け・エラー対策版)")

if st.button("🚀 未登録分を実行"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    data_info = sheet_info.get_all_records()
    data_images = sheet_images.get_all_records()

    for i, row in enumerate(data_info):
        # 登録条件
        if row.get('ID') and row.get('PASSWORD') and not row.get('登録済'):
            st.subheader(f"👤 {row.get('名前')} を処理中...")
            
            # 画像紐付け
            t_id = str(row.get('ＩＤ')).strip()
            sub_urls = [img['写真'] for img in data_images if str(img.get('CastID')).strip() == t_id]
            
            with st.spinner("自動登録中..."):
                res = asyncio.run(run_automation(row, sub_urls))
                
                if res["status"] == "success":
                    sheet_info.update_cell(i + 2, 16, "登録済")
                    st.success(f"{row.get('名前')} 完了")
                else:
                    st.error(f"{row.get('名前')} エラー: {res['message']}")
                    if "image" in res:
                        st.image(res["image"], caption="この画面で止まりました")
