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

async def run_automation(cast_data, sub_image_paths):
    # Playwrightのインストール（初回のみ）
    try:
        if not os.path.exists("/home/appuser/.cache/ms-playwright"):
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
    except: pass

    main_img_tmp = "temp_main.jpg"
    if not download_by_filename(cast_data.get('メイン画像'), main_img_tmp):
        return {"status": "error", "message": "メイン画像取得失敗"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP', '--no-sandbox'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000})
        page = await context.new_page()

        try:
            # 1. ログイン & 移動
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data.get('ID')).strip())
            await page.fill("#form_password", str(cast_data.get('PASSWORD')).strip())
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # プロフィール入力
            await page.fill("#form_name", str(cast_data.get('名前')))
            await page.click("#form_update-btn", force=True)
            await page.wait_for_selector("text=データを登録しました。", timeout=30000)

            # 4. メイン画像アップロード
            st.info("📸 メイン画像を処理中...")
            await page.click('a[data-target="con1"]')
            await page.locator('#con1 input[type="file"]').set_input_files(main_img_tmp)
            await asyncio.sleep(2)
            await page.locator('#con1 button.upbtn').click(force=True)

            # --- 【修正】Jcrop全選択を確実に行うJavaScript実行 ---
            # 2枚目の画像の状態にするために、JcropのAPIを直接叩いて全選択させます
            st.info("✂️ サムネイルの全範囲を強制選択中...")
            await page.wait_for_selector(".jcrop-tracker.target", timeout=15000)
            
            # JSでJcropインスタンスを探し、画像サイズいっぱいに選択範囲をセット
            await page.evaluate("""
                () => {
                    const img = document.querySelector('.jcrop-holder img');
                    if (img && window.jQuery) {
                        const jcrop = jQuery.data(img, 'Jcrop');
                        if (jcrop) {
                            jcrop.setSelect([0, 0, img.width, img.height]);
                        }
                    }
                }
            """)
            await asyncio.sleep(1.5)

            # 修正ボタンをJSでクリック
            await page.locator("input[value='修正する']").evaluate("el => el.click()")
            await asyncio.sleep(1.5)

            # サブ画像処理（以下略）
            if sub_image_paths:
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        await page.click(f'a[data-target="con{i+2}"]')
                        await page.locator(f'#con{i+2} input[type="file"]').set_input_files(sub_tmp)
                        await asyncio.sleep(1.5)
                        await page.locator(f'#con{i+2} button.upbtn').click(force=True)
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 最終登録
            await page.locator("#signup3").evaluate("el => el.click()")
            await page.wait_for_load_state("networkidle")
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- Streamlit UI ---
st.title("👸 キャスト一括登録")

# セッション状態をクリアして動作を安定させる
if "running" not in st.session_state:
    st.session_state.running = False

if st.button("🚀 実行開始") and not st.session_state.running:
    st.session_state.running = True
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
        gs_client = gspread.authorize(creds)
        spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
        sheet_info = spreadsheet.worksheet("キャスト情報")
        sheet_images = spreadsheet.worksheet("キャスト画像")
        data_info = sheet_info.get_all_records()
        data_images = sheet_images.get_all_records()

        for i, row in enumerate(data_info):
            if str(row.get('ID')).strip() and str(row.get('PASSWORD')).strip() and not str(row.get('登録済')).strip():
                st.subheader(f"👤 {row.get('名前')}")
                target_id = str(row.get('ＩＤ')).strip()
                sub_urls = [img['写真'] for img in data_images if str(img.get('CastID')).strip() == target_id]
                
                with st.status(f"{row.get('名前')} さんの登録を実行中...") as status:
                    # ここで新しいイベントループを作成して確実に実行させる
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    res = loop.run_until_complete(run_automation(row, sub_urls))
                    
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label="✅ 完了", state="complete")
                    else:
                        st.error(res["message"])
                        status.update(label="❌ エラー", state="error")
    finally:
        st.session_state.running = False
