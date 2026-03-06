import streamlit as st
import asyncio
import os
import subprocess
import gspread
import io
import re
import requests
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

# --- 3. 画像ダウンロード関数 (URLからIDを抽出) ---
def download_google_drive_image(url, save_path):
    try:
        # URLからファイルIDを抽出
        match = re.search(r'd/([a-zA-Z0-9_-]+)', str(url))
        if not match:
            # ID形式でない場合は直接ダウンロードを試みる(成功コードの方式)
            filename = str(url).split('/')[-1]
            query = f"name = '{filename}' and trashed = false"
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            items = results.get('files', [])
            if not items: return False
            file_id = items[0]['id']
        else:
            file_id = match.group(1)

        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        with open(save_path, "wb") as f:
            f.write(fh.getvalue())
        return True
    except Exception:
        return False

# --- 4. 自動化メイン処理 ---
async def run_automation(cast_data, sub_image_paths):
    main_img_tmp = "temp_main.jpg"
    if not download_google_drive_image(cast_data['メイン画像'], main_img_tmp):
        return {"status": "error", "message": f"メイン画像の取得失敗: {cast_data['メイン画像']}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン & 登録画面へ
            st.info(f"🌐 ログイン中: {cast_data['名前']}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data['ID'])) 
            await page.fill("#form_password", str(cast_data['PASSWORD'])) 
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (確実に値を代入)
            st.info("✍️ 基本情報を入力中...")
            
            # スプレッドシートの列名が不安な場合、row.get() を使って安全に取得
            name = str(cast_data.get('名前', ''))
            age = str(cast_data.get('若・妻', '') or cast_data.get('年齢', ''))
            tall = str(cast_data.get('身長', ''))
            bust = str(cast_data.get('バスト', '') or cast_data.get('B', ''))
            waist = str(cast_data.get('ウエスト', '') or cast_data.get('W', ''))
            hip = str(cast_data.get('ヒップ', '') or cast_data.get('H', ''))

            # 入力実行
            await page.fill("#form_name", name)
            await page.fill("#form_age", age)
            await page.fill("#form_tall", tall)
            await page.fill("#form_bust", bust)
            await page.fill("#form_waist", waist)
            await page.fill("#form_hip", hip)
            
            # もし上記が空欄だと保存できないため、デバッグ用ログ
            if not all([age, tall, bust]):
                return {"status": "error", "message": f"必須項目が空です (年齢:{age}, 身長:{tall})。スプレッドシートの列名を確認してください。"}
            
            # カップ数選択
            cup_text = f"{cast_data['カップ数']}カップ"
            try:
                await page.select_option("#form_cup", label=cup_text)
            except:
                pass 

            # タグ選択
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 
                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 
                                "#genre73", "#genre74"]
            for selector in target_genre_ids:
                checkbox = page.locator(selector)
                if await checkbox.count() > 0:
                    await checkbox.check(force=True)

            # 基本情報登録
            st.info("💾 基本情報を保存中...")
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # --- 画像処理共通関数 ---
            async def upload_process(target_id, file_path, label):
                st.info(f"📸 {label}をアップロード中...")
                btn_selector = f'a[data-target="{target_id}"]'
                await page.wait_for_selector(btn_selector, state="visible", timeout=20000)
                await page.click(btn_selector)
                
                await page.locator('input[type="file"]').first.set_input_files(file_path)
                await page.locator('button.upbtn').first.click()
                
                # Jcropドラッグ操作
                tracker_sel = ".jcrop-tracker.target"
                await page.wait_for_selector(tracker_sel, state="visible", timeout=15000)
                tracker = page.locator(tracker_sel).first
                box = await tracker.bounding_box()
                if box:
                    await page.mouse.move(box["x"], box["y"])
                    await page.mouse.down()
                    await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
                    await page.mouse.up()
                
                await page.get_by_role("button", name="修正する").click()
                await asyncio.sleep(2)

            # 3. メイン画像の登録 (con1)
            await upload_process("con1", main_img_tmp, "メイン画像")

            # 4. サブ画像のループ登録 (con2〜8)
            for i, sub_url in enumerate(sub_image_paths):
                if i >= 7: break 
                target_num = i + 2
                sub_tmp = f"temp_sub_{target_num}.jpg"
                if download_google_drive_image(sub_url, sub_tmp):
                    await upload_process(f"con{target_num}", sub_tmp, f"画像{target_num}")
                    if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 5. 連続登録へ移行
            next_signup_btn = page.locator("#signup3")
            await next_signup_btn.wait_for(state="visible")
            await next_signup_btn.click()
            
            return {"status": "success"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. Streamlit UI ロジック ---
st.title("👸 キャスト一括登録システム (完全統合版)")

if st.button("🚀 未登録キャストをスキャンして実行"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    data_info = sheet_info.get_all_records()
    data_images = sheet_images.get_all_records()

    processed_count = 0
    for i, row in enumerate(data_info):
        if row.get('ID') and row.get('PASSWORD') and not row.get('登録済'):
            st.subheader(f"👤 登録対象: {row['名前']}")
            # キャスト情報の「ＩＤ」とキャスト画像の「CastID」で紐付け
            sub_urls = [img['写真'] for img in data_images if str(img['CastID']) == str(row['ＩＤ'])]
            
            with st.status(f"{row['名前']} さんの自動登録を実行中...") as status:
                res = asyncio.run(run_automation(row, sub_urls))
                
                if res["status"] == "success":
                    sheet_info.update_cell(i + 2, 16, "登録済")
                    status.update(label=f"✅ {row['名前']} 完了", state="complete")
                    processed_count += 1
                else:
                    status.update(label=f"❌ {row['名前']} エラー", state="error")
                    st.error(res["message"])
                    if os.path.exists("error_log.png"):
                        st.image("error_log.png")

    if processed_count > 0:
        st.success(f"合計 {processed_count} 名の登録が完了しました！")
    else:
        st.info("対象の未登録キャストは見つかりませんでした。")
