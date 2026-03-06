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
    """Jcropの待機エラーを解消するために必要な待機処理のみを追加"""
    try:
        # 1. モーダルを開く
        btn_open = page.locator(f'a[data-target="{target_id}"]')
        await btn_open.evaluate("node => node.click()")
        await asyncio.sleep(2)
        
        # 2. ファイルセット
        await page.locator(f'#{target_id} input[type="file"]').first.set_input_files(file_path)
        
        # 3. アップロード実行
        await page.locator(f'#{target_id} button.upbtn').first.evaluate("node => node.click()")
        
        # --- 変更箇所: アップロード後の画面安定を待つ ---
        await asyncio.sleep(6)
        await page.wait_for_load_state("networkidle")
        
        # --- 変更箇所: 編集のために再度モーダルを開く ---
        await page.locator(f'a[data-target="{target_id}"]').evaluate("node => node.click()")
        await asyncio.sleep(2)
        
        # 6. ドラッグ操作 (Jcrop)
        tracker = page.locator(f"#{target_id} .jcrop-tracker.target").first
        # 変更箇所: 見えるまでしっかり待つ
        await tracker.wait_for(state="visible", timeout=20000)
        
        box = await tracker.bounding_box()
        if box:
            await page.mouse.move(box["x"], box["y"])
            await page.mouse.down()
            await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=20)
            await page.mouse.up()
            await asyncio.sleep(1)

        # 7. 修正するボタン操作
        fix_btn = page.locator(f"#{target_id} input[value='修正する']").first
        await fix_btn.wait_for(state="attached")
        await fix_btn.evaluate("node => node.click()")
        await asyncio.sleep(3)
            
    except Exception as e:
        st.warning(f"{target_id} の画像工程でエラーが発生しました: {e}")

async def run_automation(cast_data, sub_image_paths):
    try:
        if not os.path.exists("/home/appuser/.cache/ms-playwright"):
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
    except: pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000})
        page = await context.new_page()

        try:
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data.get('ID')).strip())
            await page.fill("#form_password", str(cast_data.get('PASSWORD')).strip())
            await page.click("#form_submit")
            await asyncio.sleep(2)
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            for sel, key in [("#form_name",'名前'),("#form_tall",'身長'),("#form_bust",'バスト'),("#form_waist",'ウエスト'),("#form_hip",'ヒップ')]:
                await page.fill(sel, str(cast_data.get(key)))

            cup = str(cast_data.get('カップ数', '')).strip().upper() 
            if cup:
                try: await page.locator("#form_cup").select_option(label=f"{cup}カップ")
                except: pass
            
            await page.locator('input[name="p_genre[1]"]').check()
            for g_id in ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]:
                if await page.locator(g_id).count() > 0: await page.locator(g_id).check(force=True)

            await page.locator("#form_update-btn").evaluate("node => node.click()")
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=25000)

            all_imgs = [cast_data.get('メイン画像')] + sub_image_paths
            for i, img_path in enumerate(all_imgs):
                num = i + 1
                if num > 8 or not img_path: continue
                tmp = f"temp_{num}.jpg"
                if download_by_filename(img_path, tmp):
                    st.info(f"📸 画像{num} を処理中...")
                    await handle_image_process(page, f"con{num}", tmp)
                    if os.path.exists(tmp): os.remove(tmp)

            await page.locator("#signup3").evaluate("node => node.click()")
            await asyncio.sleep(2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
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

        targets = [row for row in data_info if str(row.get('ID')).strip() and str(row.get('PASSWORD')).strip() and not str(row.get('登録済')).strip()]

        if not targets:
            st.warning("⚠️ スプレッドシートに登録待ちのデータは見つかりませんでした。")
        else:
            for row in targets:
                st.subheader(f"👤 {row.get('名前')}")
                target_id = str(row.get('ＩＤ')).strip()
                sub_urls = [img['写真'] for img in data_images if str(img.get('CastID')).strip() == target_id]
                with st.status(f"{row.get('名前')} 登録中...") as status:
                    res = asyncio.run(run_automation(row, sub_urls))
                    if res["status"] == "success":
                        cell = sheet_info.find(row.get('名前'))
                        sheet_info.update_cell(cell.row, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                    else:
                        st.error(res["message"])
    except Exception as e:
        st.error(f"起動エラー: {e}")
