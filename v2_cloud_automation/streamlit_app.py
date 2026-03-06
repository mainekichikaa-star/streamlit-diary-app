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

# --- 1. 環境設定：Playwright & 日本語フォント ---
@st.cache_resource
def install_environment():
    try:
        # 文字化け対策（fonts-noto-cjk）
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "install", "-y", "fonts-noto-cjk"], check=True)
        # Playwright本体
        subprocess.run(["playwright", "install", "chromium"], check=True)
        subprocess.run(["playwright", "install-deps"], check=True)
    except Exception as e:
        st.error(f"初期設定エラー（再起動で治る場合があります）: {e}")

install_environment()

# --- 2. Google API 認証 ---
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
gs_client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)
SPREADSHEET_ID = "1Fta23cis4AY9j2_lytfh0OOAJq-EFinLjqp_dLIAgtM"

# --- 3. 画像ダウンロード関数 ---
def download_drive_img(url_or_id, save_path):
    try:
        file_id = ""
        match = re.search(r'd/([a-zA-Z0-9_-]+)', str(url_or_id))
        if match:
            file_id = match.group(1)
        else:
            # ID形式でない場合はファイル名検索
            query = f"name = '{url_or_id}' and trashed = false"
            res = drive_service.files().list(q=query, fields="files(id)").execute()
            items = res.get('files', [])
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
    # 【列番号設定】スプレッドシートの左からの順番に合わせて調整してください
    # 0=A, 1=B, 2=C...
    COL_LOGIN_ID = 0  # A列: ID
    COL_PW       = 1  # B列: PASSWORD
    COL_NAME     = 2  # C列: 名前
    COL_AGE      = 3  # D列: 若・妻/年齢
    COL_TALL     = 4  # E列: 身長
    COL_B        = 5  # F列: バスト
    COL_W        = 6  # G列: ウエスト
    COL_H        = 7  # H列: ヒップ
    COL_CUP      = 8  # I列: カップ
    COL_MAIN_IMG = 14 # O列: メイン画像URL（例）

    name = row_data[COL_NAME]
    main_img_tmp = "temp_main.jpg"

    if not download_drive_img(row_data[COL_MAIN_IMG], main_img_tmp):
        return {"status": "error", "message": f"メイン画像の取得失敗: {row_data[COL_MAIN_IMG]}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info(f"🌐 ログイン: {name}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(row_data[COL_LOGIN_ID]))
            await page.fill("#form_password", str(row_data[COL_PW]))
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (row_dataから直接入力)
            st.info("✍️ 基本情報を入力中...")
            await page.fill("#form_name", str(row_data[COL_NAME]))
            await page.fill("#form_age", str(row_data[COL_AGE]))
            await page.fill("#form_tall", str(row_data[COL_TALL]))
            await page.fill("#form_bust", str(row_data[COL_B]))
            await page.fill("#form_waist", str(row_data[COL_W]))
            await page.fill("#form_hip", str(row_data[COL_H]))
            
            # カップ数
            cup = str(row_data[COL_CUP]).strip()
            try:
                await page.locator("#form_cup").select_option(label=re.compile(f"^{cup}", re.IGNORECASE))
            except: pass

            # 3. 保存ボタン
            st.info("💾 保存中...")
            await page.click("#form_update-btn", force=True)
            
            # 保存が通ればcon1が出る。出なければエラー。
            try:
                await page.wait_for_selector('a[data-target="con1"]', state="visible", timeout=15000)
            except:
                await page.screenshot(path="save_error.png")
                return {"status": "error", "message": "保存失敗。入力項目が空か、サイト側のバリデーションエラーです。"}

            # --- 画像処理関数 ---
            async def upload_process(target_id, file_path, label):
                st.info(f"📸 {label}アップロード...")
                btn = f'a[data-target="{target_id}"]'
                await page.wait_for_selector(btn, state="visible")
                await page.click(btn)
                await page.locator('input[type="file"]').first.set_input_files(file_path)
                await page.locator('button.upbtn').first.click()
                
                tracker = page.locator(".jcrop-tracker.target").first
                await tracker.wait_for(state="visible", timeout=10000)
                box = await tracker.bounding_box()
                if box:
                    await page.mouse.move(box["x"], box["y"])
                    await page.mouse.down()
                    await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=10)
                    await page.mouse.up()
                await page.get_by_role("button", name="修正する").click()
                await asyncio.sleep(2)

            # メイン画像
            await upload_process("con1", main_img_tmp, "メイン")

            # サブ画像
            for i, sub_url in enumerate(sub_image_urls):
                if i >= 7: break
                sub_tmp = f"temp_sub_{i}.jpg"
                if download_drive_img(sub_url, sub_tmp):
                    await upload_process(f"con{i+2}", sub_tmp, f"サブ{i+1}")
                    if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 完了
            await page.locator("#signup3").click()
            return {"status": "success"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. Streamlit UI ---
st.title("🤴 キャスト一括登録システム (列番号指定版)")

if st.button("🚀 登録開始"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    all_data = sheet_info.get_all_values() # リスト形式で取得
    img_data = sheet_images.get_all_records()
    
    headers = all_data[0]
    rows = all_data[1:]

    for i, row in enumerate(rows):
        # A列(row[0])、B列(row[1])、P列(row[15])をチェック
        if len(row) > 15 and row[0] and row[1] and row[15] != "登録済":
            st.subheader(f"👤 処理中: {row[2]}")
            # 画像検索 (row[10]などをIDとして利用する場合)
            cast_id = str(row[10]) if len(row) > 10 else ""
            sub_urls = [img['写真'] for img in img_data if str(img['CastID']) == cast_id]
            
            with st.status("自動実行中...") as status:
                res = asyncio.run(run_automation(row, sub_urls))
                if res["status"] == "success":
                    sheet_info.update_cell(i + 2, 16, "登録済")
                    status.update(label="✅ 完了", state="complete")
                else:
                    status.update(label="❌ エラー", state="error")
                    st.error(res["message"])
                    if os.path.exists("save_error.png"): st.image("save_error.png")
