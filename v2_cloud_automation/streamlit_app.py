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

async def handle_image_process(page, target_id, file_path):
    """画像アップロードからJcropドラッグ、複数箇所の修正確定まで"""
    try:
        # 1. モーダルを開く（重なりを避けるためJSで強制実行）
        btn_open = page.locator(f'a[data-target="{target_id}"]')
        await btn_open.wait_for(state="attached")
        await btn_open.evaluate("node => node.click()")
        await asyncio.sleep(2) # アニメーション待機
        
        # 2. ファイルセット
        file_input = page.locator(f'#{target_id} input[type="file"]')
        await file_input.set_input_files(file_path)
        await asyncio.sleep(2)
        
        # 3. アップロードボタン（JSで強制実行）
        up_btn = page.locator(f'#{target_id} button.upbtn')
        await up_btn.evaluate("node => node.click()")
        
        # 4. 画面リフレッシュ待機（通信が落ち着くまで）
        await asyncio.sleep(6)
        await page.wait_for_load_state("networkidle")
        
        # 5. 再度モーダルを開く（編集のため）
        await btn_open.evaluate("node => node.click()")
        await asyncio.sleep(3)
        
        # 6. Jcrop ドラッグ（左上から右下へ全ターゲット分）
        trackers = page.locator(f"#{target_id} .jcrop-tracker.target")
        t_count = await trackers.count()
        for i in range(t_count):
            tracker = trackers.nth(i)
            box = await tracker.bounding_box()
            if box:
                await page.mouse.move(box["x"], box["y"])
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
                await page.mouse.up()
                await asyncio.sleep(0.5)
                
        # 7. 「修正する」ボタン（モーダル内の全ての修正ボタンを順番に押す）
        fix_btns = page.locator(f"#{target_id} input[value='修正する']")
        b_count = await fix_btns.count()
        for i in range(b_count):
            await fix_btns.nth(i).evaluate("node => node.click()")
            await asyncio.sleep(1.5)
            
    except Exception as e:
        st.warning(f"{target_id} の処理中にスキップが発生しました: {e}")

async def run_automation(cast_data, sub_image_paths):
    try:
        if not os.path.exists("/home/appuser/.cache/ms-playwright"):
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
    except: pass

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
            await asyncio.sleep(2)
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力
            profile_fields = {
                "#form_name": '名前', "#form_tall": '身長', "#form_bust": 'バスト',
                "#form_waist": 'ウエスト', "#form_hip": 'ヒップ'
            }
            for selector, key in profile_fields.items():
                await page.fill(selector, str(cast_data.get(key)))

            cup = str(cast_data.get('カップ数', '')).strip().upper() 
            if cup:
                try: await page.locator("#form_cup").select_option(label=f"{cup}カップ")
                except: pass
            
            # タグ選択
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).check(force=True)

            # 保存
            await page.locator("#form_update-btn").evaluate("node => node.click()")
            await asyncio.sleep(3)

            # 3. 画像1〜8の処理（ある分だけ実行）
            all_imgs = [cast_data.get('メイン画像')] + sub_image_paths
            for i, img_path in enumerate(all_imgs):
                img_num = i + 1
                if img_num > 8 or not img_path: continue
                
                tmp_name = f"temp_img_{img_num}.jpg"
                if download_by_filename(img_path, tmp_name):
                    st.info(f"📸 画像{img_num} をアップロード・編集しています...")
                    await handle_image_process(page, f"con{img_num}", tmp_name)
                    if os.path.exists(tmp_name): os.remove(tmp_name)

            # 4. 最終確認保存
            await page.locator("#signup3").evaluate("node => node.click()")
            await asyncio.sleep(2)
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
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
                
                with st.status(f"{row.get('名前')} さんの登録を実行中...") as status:
                    res = asyncio.run(run_automation(row, sub_urls))
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                    else:
                        status.update(label="❌ エラー", state="error")
                        st.error(res["message"])
    except Exception as e:
        st.error(f"起動エラー: {e}")
