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

# --- 1. Playwright インストール設定 ---
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

# --- 3. Googleドライブからファイル名で検索してダウンロード ---
def download_by_filename(path_str, save_path):
    if not path_str or str(path_str).strip() == "": return False
    try:
        filename = path_str.split('/')[-1]
        query = f"name = '{filename}' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])

        if not items:
            return False

        file_id = items[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        with open(save_path, "wb") as f:
            f.write(fh.getvalue())
        return True
    except Exception:
        return False

# --- 4. 自動化メイン処理 (シート構成準拠版) ---
async def run_automation(cast_data, sub_image_paths):
    main_img_tmp = "temp_main.jpg"
    # スプレッドシートの「メイン画像」列のパスから取得
    if not download_by_filename(cast_data.get('メイン画像'), main_img_tmp):
        return {"status": "error", "message": f"メイン画像の取得失敗: {cast_data.get('メイン画像')}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info(f"🌐 ログイン中: {cast_data.get('名前')}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data.get('ID')))
            await page.fill("#form_password", str(cast_data.get('PASSWORD')))
            await page.click("#form_submit")
            
            # ログイン確認
            await asyncio.sleep(2)
            if "login" in page.url:
                return {"status": "error", "message": "ログイン失敗。ID/PASSWORDを確認してください。"}
            
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力
            st.info("✍️ プロフィール入力中...")
            await page.fill("#form_name", str(cast_data.get('名前')))
            await page.fill("#form_tall", str(cast_data.get('身長')))
            await page.fill("#form_bust", str(cast_data.get('バスト')))
            await page.fill("#form_waist", str(cast_data.get('ウエスト')))
            await page.fill("#form_hip", str(cast_data.get('ヒップ')))
            
            cup = str(cast_data.get('カップ数')).strip()
            try:
                await page.locator("#form_cup").select_option(label=re.compile(f"^{cup}", re.IGNORECASE))
            except: pass

            # タグ選択 (デフォルト設定)
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 
                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 
                                "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).check(force=True)

            # 基本情報登録
            await page.click("#form_update-btn", force=True)

            # 3. 画像アップロード (ここでタイムアウトする場合は入力不備によるエラー画面)
            st.info("📸 メイン画像をアップロード中...")
            await page.wait_for_selector('a[data-target="con1"]', state="visible", timeout=20000)
            await page.click('a[data-target="con1"]')
            
            await page.locator('input[type="file"]').first.set_input_files(main_img_tmp)
            await page.locator('button.upbtn').first.click()
            
            # ドラッグ操作 (Jcrop)
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

            # 4. サブ画像の登録
            if sub_image_paths:
                st.info(f"🖼️ サブ画像登録中...")
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break # 媒体制限
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        target_id = f"con{i+2}"
                        await page.click(f'a[data-target="{target_id}"]')
                        await page.locator('input[type="file"]').first.set_input_files(sub_tmp)
                        await page.locator('button.upbtn').first.click()
                        await asyncio.sleep(2)
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 5. 完了
            await page.locator("#signup3").click()
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. UI ロジック ---
st.title("👸 キャスト一括登録システム")

if st.button("🚀 未登録キャストをスキャンして実行"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    # 全データを取得
    data_info = sheet_info.get_all_records()
    data_images = sheet_images.get_all_records()

    processed_count = 0
    for i, row in enumerate(data_info):
        # 判定：ID/PASSWORDあり、かつ「登録済」が空
        login_id = str(row.get('ID', '')).strip()
        login_pw = str(row.get('PASSWORD', '')).strip()
        status = str(row.get('登録済', '')).strip()

        if login_id and login_pw and not status:
            st.subheader(f"👤 登録対象: {row.get('名前')}")
            
            # 紐付け：キャスト情報の「ＩＤ」(1列目) と キャスト画像の「CastID」
            # row.get('ＩＤ') は全角のＩＤに対応
            target_id = str(row.get('ＩＤ', '')).strip()
            sub_urls = [img['写真'] for img in data_images if str(img.get('CastID', '')).strip() == target_id]
            
            with st.status(f"{row.get('名前')} さんの自動登録を実行中...") as st_status:
                res = asyncio.run(run_automation(row, sub_urls))
                
                if res["status"] == "success":
                    # 16列目(登録済)を更新
                    sheet_info.update_cell(i + 2, 16, "登録済")
                    st_status.update(label=f"✅ {row.get('名前')} 完了", state="complete")
                    processed_count += 1
                else:
                    st_status.update(label=f"❌ {row.get('名前')} エラー", state="error")
                    st.error(res["message"])

    if processed_count == 0:
        st.info("条件に合う未登録キャストは見つかりませんでした。")
    else:
        st.success(f"合計 {processed_count} 名の登録が完了しました！")
