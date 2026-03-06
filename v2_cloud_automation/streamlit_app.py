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

# --- 4. 自動化メイン処理 (Playwright工程完全準拠) ---
async def run_automation(cast_data, sub_image_paths):
    # 画像ダウンロードの準備
    main_img_tmp = "temp_main.jpg"
    if not download_by_filename(cast_data['メイン画像'], main_img_tmp):
        return {"status": "error", "message": f"メイン画像の取得失敗: {cast_data['メイン画像']}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info(f"🌐 ログイン中: {cast_data['名前']}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(cast_data['ID'])) # スプレッドシートのID列
            await page.fill("#form_password", str(cast_data['PASSWORD'])) # パスワード列
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力 (ご提示の工程)
            st.info("✍️ プロフィール入力中...")
            await page.fill("#form_name", cast_data['名前'])
            
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
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # 3. 画像アップロード & ドラッグ操作 (メイン画像)
            st.info("📸 メイン画像をアップロード中...")
            await page.get_by_text("データを登録しました。").wait_for(state="visible")
            await page.click('a[data-target="con1"]')
            
            # メイン画像アップロード
            await page.locator('input[type="file"]').first.set_input_files(main_img_tmp)
            await page.locator('button.upbtn').first.click()
            
            # ドラッグ操作 (Jcrop)
            tracker = page.locator(".jcrop-tracker.target").first
            await tracker.wait_for(state="visible", timeout=10000)
            box = await tracker.bounding_box()
            if box:
                await page.mouse.move(box["x"], box["y"])
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=20)
                await page.mouse.up()
            
            fix_btn = page.get_by_role("button", name="修正する")
            await fix_btn.wait_for(state="visible")
            await fix_btn.click()
            await asyncio.sleep(2)

            # 4. サブ画像の登録 (キャスト画像シートから取得分)
            if sub_image_paths:
                st.info(f"🖼️ サブ画像({len(sub_image_paths)}枚)を登録中...")
                for i, sub_url in enumerate(sub_image_paths):
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        # 2枚目以降のアップロード枠を探して処理 (サイトの仕様に合わせて調整が必要な場合があります)
                        # ここでは最初のinputを流用する例ですが、必要に応じてセレクタを修正してください
                        try:
                            await page.locator('input[type="file"]').set_input_files(sub_tmp)
                            await page.locator('button.upbtn').click()
                            await asyncio.sleep(1)
                            if os.path.exists(sub_tmp): os.remove(sub_tmp)
                        except:
                            pass

            # 5. 連続登録へ移行
            next_signup_btn = page.locator("#signup3")
            await next_signup_btn.wait_for(state="visible")
            await next_signup_btn.click()
            
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": str(e)}
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
        # 登録条件: ID/PASSあり かつ 登録済が空
        if row.get('ID') and row.get('PASSWORD') and not row.get('登録済'):
            st.subheader(f"👤 登録対象: {row['名前']}")
            
            # サブ画像のURLリスト作成 (ID一致分)
            sub_urls = [img['写真'] for img in data_images if str(img['CastID']) == str(row['ＩＤ'])]
            
            # 実行
            with st.status(f"{row['名前']} さんの自動登録を実行中...") as status:
                res = asyncio.run(run_automation(row, sub_urls))
                
                if res["status"] == "success":
                    # スプレッドシートの16列目(登録済)を更新
                    sheet_info.update_cell(i + 2, 16, "登録済")
                    status.update(label=f"✅ {row['名前']} 完了", state="complete")
                    processed_count += 1
                else:
                    status.update(label=f"❌ {row['名前']} エラー", state="error")
                    st.error(res["message"])

    if processed_count == 0:
        st.info("対象の未登録キャストは見つかりませんでした。")
    else:
        st.success(f"合計 {processed_count} 名の登録が完了しました！")
