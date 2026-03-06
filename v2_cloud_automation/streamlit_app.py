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

# --- ヘルパー関数 ---
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

# --- 自動化メイン処理 ---
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
            await page.fill("#form_tall", str(cast_data.get('身長')))
            await page.fill("#form_bust", str(cast_data.get('バスト')))
            await page.fill("#form_waist", str(cast_data.get('ウエスト')))
            await page.fill("#form_hip", str(cast_data.get('ヒップ')))

            cup_input = str(cast_data.get('カップ数', '')).strip().upper() 
            if cup_input:
                try:
                    await page.locator("#form_cup").select_option(label=f"{cup_input}カップ")
                except: pass
            
            # ジャンル選択
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 
                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 
                                "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).check(force=True)

            await page.click("#form_update-btn", force=True)
            await page.wait_for_selector("text=データを登録しました。", timeout=30000)

            # 4. メイン画像アップロード
            st.info("📸 メイン画像を処理中...")
            await page.click('a[data-target="con1"]', force=True)
            await page.locator('#con1 input[type="file"]').set_input_files(main_img_tmp)
            await asyncio.sleep(2)
            await page.locator('#con1 button.upbtn').click(force=True)
            
            # --- 【修正】Jcrop ドラッグ操作 ---
            tracker = page.locator(".jcrop-tracker.target").first
            await tracker.wait_for(state="visible", timeout=15000)
            box = await tracker.bounding_box()
            if box:
                st.info("✂️ サムネイルの全範囲を選択中...")
                # 始点: 要素の左上から少し内側
                start_x = box["x"] + 10
                start_y = box["y"] + 10
                # 終点: 要素の右下から少し内側
                end_x = box["x"] + box["width"] - 10
                end_y = box["y"] + box["height"] - 10
                
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                await page.mouse.move(end_x, end_y, steps=20) # stepsを増やすことでドラッグを認識させる
                await page.mouse.up()
                await asyncio.sleep(2)
            
            # 「修正する」ボタンのクリック
            st.info("✅ 修正確定ボタンをクリック...")
            fix_btn = page.locator("input[value='修正する']").first
            await fix_btn.evaluate("el => el.click()")
            await asyncio.sleep(1)

            # 5. サブ画像
            if sub_image_paths:
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break
                    idx = i + 2 
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        st.info(f"🖼 サブ画像 {i+1} を処理中...")
                        await page.click(f'a[data-target="con{idx}"]', force=True)
                        await page.locator(f'#con{idx} input[type="file"]').set_input_files(sub_tmp)
                        await asyncio.sleep(2)
                        await page.locator(f'#con{idx} button.upbtn').click(force=True)
                        
                        try:
                            sub_fix = page.locator(f"#con{idx} input[value='修正する']").first
                            await sub_fix.evaluate("el => el.click()")
                        except: pass
                        
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 最終登録
            st.info("💾 登録確定中...")
            await page.locator("#signup3").evaluate("el => el.click()")
            await page.wait_for_load_state("networkidle")
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- UI ---
st.title("👸 キャスト一括登録システム")
if st.button("🚀 実行開始"):
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
        gs_client = gspread.authorize(creds)
        spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
        sheet_info = spreadsheet.worksheet("キャスト情報")
        sheet_images = spreadsheet.worksheet("キャスト画像")
        data_info = sheet_info.get_all_records()
        data_images = sheet_images.get_all_records()

        count = 0
        for i, row in enumerate(data_info):
            if str(row.get('ID')).strip() and str(row.get('PASSWORD')).strip() and not str(row.get('登録済')).strip():
                count += 1
                st.subheader(f"👤 {row.get('名前')}")
                target_id = str(row.get('ＩＤ')).strip()
                sub_urls = [img['写真'] for img in data_images if str(img.get('CastID')).strip() == target_id]
                
                with st.status(f"{row.get('名前')} さんの自動登録を実行中...") as status:
                    res = asyncio.run(run_automation(row, sub_urls))
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                    else:
                        st.error(res["message"])
        
        if count == 0:
            st.info("登録対象のキャストが見つかりませんでした。")
    except Exception as e:
        st.error(f"起動エラー: {e}")
