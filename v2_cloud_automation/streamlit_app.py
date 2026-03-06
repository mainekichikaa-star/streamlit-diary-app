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

# --- ヘルパー関数 ---
def get_drive_service():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
    return build('drive', 'v3', credentials=creds)

def download_by_filename(path_str, save_path):
    """Googleドライブ上のファイル名（パスの末尾）からファイルをダウンロードする"""
    if not path_str or str(path_str).strip() == "": return False
    try:
        drive_service = get_drive_service()
        # パス「キャスト情報_Images/xxx.jpg」から「xxx.jpg」を抽出
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
    except Exception as e:
        st.error(f"ダウンロード失敗 ({path_str}): {e}")
        return False

# --- 画像処理用サブ関数 ---
async def handle_image_upload(page, target_id, file_path):
    """個別の画像アップロードと切り抜き工程を実行"""
    try:
        # モーダルを開く
        await page.click(f'a[data-target="{target_id}"]')
        await asyncio.sleep(1)
        
        # ファイルセット
        await page.locator(f'#{target_id} input[type="file"]').first.set_input_files(file_path)
        await asyncio.sleep(1)
        
        # アップロードボタン
        up_btn = page.locator(f'#{target_id} button.upbtn').first
        await up_btn.wait_for(state="visible", timeout=20000)
        await up_btn.click(force=True)
        
        # Jcrop (切り抜き) 待機と操作
        tracker = page.locator(f"#{target_id} .jcrop-tracker.target").first
        await tracker.wait_for(state="visible", timeout=20000)
        box = await tracker.bounding_box()
        if box:
            await page.mouse.move(box["x"], box["y"])
            await page.mouse.down()
            await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
            await page.mouse.up()
            await asyncio.sleep(1)
        
        # 修正するボタン
        fix_btn = page.locator(f"#{target_id} input[value='修正する']").first
        await fix_btn.click(force=True)
        await asyncio.sleep(2)
        return True
    except Exception as e:
        st.warning(f"{target_id} の画像処理でエラー: {e}")
        return False

# --- 自動化メイン処理 ---
async def run_automation(cast_data, sub_image_paths):
    # Playwright インストール
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
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (名前、身長、3サイズ等)
            for selector, key in [("#form_name", '名前'), ("#form_tall", '身長'), ("#form_bust", 'バスト'), ("#form_waist", 'ウエスト'), ("#form_hip", 'ヒップ')]:
                await page.fill(selector, str(cast_data.get(key)))

            # カップ選択
            cup = str(cast_data.get('カップ数', '')).strip().upper()
            if cup:
                try: await page.locator("#form_cup").select_option(label=f"{cup}カップ")
                except: pass

            # タグ選択 (一括チェック)
            await page.locator('input[name="p_genre[1]"]').check()
            target_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]
            for sid in target_ids:
                if await page.locator(sid).count() > 0:
                    await page.locator(sid).check(force=True)

            # 基本情報保存
            await page.click("#form_update-btn", force=True)
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=30000)

            # 3. 画像処理 (メイン + サブ)
            # メイン画像を先頭に追加し、最大8枚まで処理
            all_image_urls = []
            if cast_data.get('メイン画像'):
                all_image_urls.append(cast_data.get('メイン画像'))
            all_image_urls.extend(sub_image_paths)

            for i, img_url in enumerate(all_image_urls):
                num = i + 1
                if num > 8: break # サイトの最大枠数
                
                tmp_name = f"temp_img_{num}.jpg"
                if download_by_filename(img_url, tmp_name):
                    st.info(f"📸 画像{num} を処理中...")
                    await handle_image_upload(page, f"con{num}", tmp_name)
                    if os.path.exists(tmp_name): os.remove(tmp_name)

            # 最終登録ボタン
            await page.locator("#signup3").click()
            await asyncio.sleep(2)
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
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

        count = 0
        for i, row in enumerate(data_info):
            # ID/PASSがあり、「登録済」が空の行を対象とする
            if str(row.get('ID')).strip() and str(row.get('PASSWORD')).strip() and not str(row.get('登録済')).strip():
                count += 1
                st.subheader(f"👤 {row.get('名前')}")
                
                # キャスト情報の「ID」と一致する画像を「キャスト画像」シートから全て取得
                target_id = str(row.get('ID')).strip()
                sub_urls = [
                    img['写真'] for img in data_images 
                    if str(img.get('CastID')).strip() == target_id
                ]
                
                with st.status(f"{row.get('名前')} さんの登録を実行中...") as status:
                    res = asyncio.run(run_automation(row, sub_urls))
                    if res["status"] == "success":
                        sheet_info.update_cell(i + 2, 16, "登録済") # P列(16列目)に「登録済」を記入
                        status.update(label="✅ 完了", state="complete")
                    else:
                        status.update(label="❌ エラー", state="error")
                        st.error(res["message"])
        
        if count == 0:
            st.info("対象のキャストが見つかりませんでした。")

    except Exception as e:
        st.error(f"起動エラー: {e}")
