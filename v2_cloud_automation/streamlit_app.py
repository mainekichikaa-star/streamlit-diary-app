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
    # Playwright インストール確認（省略せず維持）
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

            # 2. プロフィール入力 (既存通り)
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
            
            # タグ選択
            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 
                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 
                                "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).check(force=True)

            # 登録実行
            await page.click("#form_update-btn", force=True)
            await page.wait_for_selector("text=データを登録しました。", timeout=30000)

            # 4. メイン画像アップロード
            st.info("📸 メイン画像をアップロード中...")
            await page.click('a[data-target="con1"]', force=True)
            await page.locator('#con1 input[type="file"]').set_input_files(main_img_tmp)
            await asyncio.sleep(2)
            
            # アップロード実行ボタン
            up_btn = page.locator('#con1 button.upbtn')
            await up_btn.click(force=True)
            
            # 切り抜き(Jcrop)待機と実行
            tracker = page.locator(".jcrop-tracker").first
            await tracker.wait_for(state="visible", timeout=15000)
            box = await tracker.bounding_box()
            if box:
                await page.mouse.move(box["x"] + 10, box["y"] + 10)
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"] - 10, box["y"] + box["height"] - 10, steps=10)
                await page.mouse.up()
            
            # 「修正する」ボタンを JavaScript で強制クリック（オーバーレイ対策）
            await asyncio.sleep(1)
            fix_btn = page.locator("#con1 input[value='修正する']").first
            await fix_btn.evaluate("el => el.click()") 
            
            # 5. サブ画像 (1〜7枚)
            if sub_image_paths:
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break
                    idx = i + 2 # con2, con3...
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        st.info(f"🖼 サブ画像 {i+1} をアップロード中...")
                        await page.click(f'a[data-target="con{idx}"]', force=True)
                        await page.locator(f'#con{idx} input[type="file"]').set_input_files(sub_tmp)
                        await asyncio.sleep(1)
                        await page.locator(f'#con{idx} button.upbtn').click(force=True)
                        # サブ画像も修正ボタン（確定）が必要な場合はここに追加
                        try:
                             confirm_sub = page.locator(f"#con{idx} input[value='修正する']").first
                             await confirm_sub.evaluate("el => el.click()")
                        except: pass
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # --- 最終保存ボタンのクリック ---
            st.info("💾 最終登録ボタンをクリックします...")
            await asyncio.sleep(2) # モーダルが完全に消えるのを待つ
            # ログにあるエラー回避のため JavaScript でクリックを実行
            final_submit = page.locator("#signup3")
            await final_submit.evaluate("el => el.click()")
            
            # 完了確認
            await page.wait_for_load_state("networkidle")
            return {"status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- UI / メイン処理部分 ---
st.title("👸 キャスト一括登録システム")

if st.button("🚀 実行開始"):
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
        gs_client = gspread.authorize(creds)
        
        # スプレッドシートの読み込み
        spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
        sheet_info = spreadsheet.worksheet("キャスト情報")
        sheet_images = spreadsheet.worksheet("キャスト画像") # 「キャスト画像」シート
        
        data_info = sheet_info.get_all_records()
        data_images = sheet_images.get_all_records()

        count = 0
        for i, row in enumerate(data_info):
            # 1. ID・PASSがあり、かつ「登録済」が空の行を対象とする
            id_val = str(row.get('ID', '')).strip()
            pass_val = str(row.get('PASSWORD', '')).strip()
            status_val = str(row.get('登録済', '')).strip()

            if id_val and pass_val and not status_val:
                count += 1
                cast_name = row.get('名前', '不明')
                st.subheader(f"👤 {cast_name}")
                
                # 2. 「キャスト画像」シートから CastID が一致するものをすべて取得
                # row.get('ID') と sheet_images の 'CastID' を紐付け
                sub_urls = []
                for img_row in data_images:
                    if str(img_row.get('CastID', '')).strip() == id_val:
                        img_path = str(img_row.get('写真', '')).strip()
                        if img_path:
                            sub_urls.append(img_path)
                
                with st.status(f"{cast_name} さんの自動登録を実行中...") as status:
                    # 3. 自動化処理の実行 (row=メイン情報, sub_urls=紐付いた画像リスト)
                    res = asyncio.run(run_automation(row, sub_urls))
                    
                    if res["status"] == "success":
                        # 16列目（P列）の「登録済」に印を付ける
                        sheet_info.update_cell(i + 2, 16, "登録済")
                        status.update(label=f"✅ {cast_name} 完了", state="complete")
                    else:
                        status.update(label=f"❌ {cast_name} エラー", state="error")
                        st.error(res["message"])
        
        if count == 0:
            st.info("登録対象（ID/PASSあり、かつ未登録）のキャストが見つかりませんでした。")

    except Exception as e:
        st.error(f"起動エラー: {e}")
