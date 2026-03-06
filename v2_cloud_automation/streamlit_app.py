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

# --- 1. Playwright インストール (確実に実行) ---
@st.cache_resource
def install_playwright():
    try:
        # ブラウザ本体と依存関係を両方インストール
        subprocess.run(["playwright", "install", "chromium"], check=True)
        subprocess.run(["playwright", "install-deps"], check=True)
    except Exception as e:
        st.error(f"Playwrightの初期化に失敗しました: {e}")

install_playwright()

# --- 2. API 認証設定 ---
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
gs_client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)
SPREADSHEET_ID = "1Fta23cis4AY9j2_lytfh0OOAJq-EFinLjqp_dLIAgtM"

# --- 3. ドライブからのダウンロード関数 ---
def download_by_filename(path_str, save_path):
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
        while not done: _, done = downloader.next_chunk()
        with open(save_path, "wb") as f: f.write(fh.getvalue())
        return True
    except: return False

# --- 4. 自動登録メインロジック ---
async def run_automation(cast_data, sub_image_paths):
    main_img_tmp = "temp_main.jpg"
    if not download_by_filename(cast_data['メイン画像'], main_img_tmp):
        return {"status": "error", "message": "メイン画像がドライブで見つかりません"}

    async with async_playwright() as p:
        # headless=True（画面非表示）でないとCloud上では動きません
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000})
        page = await context.new_page()

        try:
            # ログイン
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data['ID']))
            await page.fill("#form_password", str(cast_data['PASSWORD']))
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # A. プロフィール入力 (HTML構造に準拠)
            st.write(f"✍️ {cast_data['名前']} のプロフィールを入力中...")
            await page.fill("#form_name", str(cast_data['名前']))
            await page.fill("#form_age", str(cast_data['若・妻']))
            await page.fill("#form_tall", str(cast_data['身長']))
            await page.fill("#form_bust", str(cast_data['バスト']))
            await page.fill("#form_waist", str(cast_data['ウエスト']))
            await page.fill("#form_hip", str(cast_data['ヒップ']))
            
            # カップ数選択 (例: "C" -> "Cカップ"を選択)
            cup_label = f"{cast_data['カップ数']}カップ"
            await page.select_option("#form_cup", label=cup_label)

            # タグ選択
            await page.locator('input[name="p_genre[1]"]').check()
            target_genres = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]
            for gid in target_genres:
                if await page.locator(gid).count() > 0:
                    await page.locator(gid).check(force=True)

            # 更新
            async with page.expect_navigation():
                await page.click("#form_update-btn")

            # B. 画像アップロード・ループ (1〜8枚目)
            async def process_image(target_id, file_path, idx):
                st.write(f"📸 画像 {idx} 枚目を処理中...")
                await page.click(f'a[data-target="{target_id}"]')
                await page.locator('input[type="file"]').set_input_files(file_path)
                await page.click('button.upbtn')
                
                # Jcrop操作
                tracker = page.locator(".jcrop-tracker.target").first
                await tracker.wait_for(state="visible", timeout=10000)
                box = await tracker.bounding_box()
                if box:
                    await page.mouse.move(box["x"], box["y"])
                    await page.mouse.down()
                    await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=10)
                    await page.mouse.up()
                
                await page.click('button:has-text("修正する")')
                await asyncio.sleep(2)

            # メイン画像 (画像:1)
            await process_image("con1", main_img_tmp, 1)

            # サブ画像 (画像:2〜)
            for i, sub_url in enumerate(sub_image_paths):
                if i >= 7: break # 合計8枚まで
                idx = i + 2
                sub_tmp = f"temp_sub_{idx}.jpg"
                if download_by_filename(sub_url, sub_tmp):
                    await process_image(f"con{idx}", sub_tmp, idx)
                    if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 最終完了ボタン
            await page.click("#signup3")
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. UI本体 ---
st.title("👸 キャスト自動登録一括システム")

if st.button("🚀 登録開始"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    data_info = sheet_info.get_all_records()
    data_images = sheet_images.get_all_records()

    for i, row in enumerate(data_info):
        if row.get('ID') and row.get('PASSWORD') and not row.get('登録済'):
            sub_urls = [img['写真'] for img in data_images if str(img['CastID']) == str(row['ＩＤ'])]
            
            with st.spinner(f"{row['名前']} を登録しています..."):
                res = asyncio.run(run_automation(row, sub_urls))
                if res["status"] == "success":
                    sheet_info.update_cell(i + 2, 16, "登録済")
                    st.success(f"✅ {row['名前']} 完了")
                else:
                    st.error(f"❌ {row['名前']} 失敗: {res['message']}")
