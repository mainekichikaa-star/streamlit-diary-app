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

# --- 1. Playwright インストール (フォントはpackages.txtで導入) ---
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

# --- 3. 画像ダウンロード関数 (ファイル名検索) ---
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
        while not done:
            _, done = downloader.next_chunk()
        
        with open(save_path, "wb") as f:
            f.write(fh.getvalue())
        return True
    except Exception:
        return False

# --- 4. 自動化メイン処理 (列番号指定 & 成功ロジック準拠) ---
async def run_automation(row_data, sub_image_urls):
    # 【重要】スプレッドシートの列順序に合わせて番号を調整してください
    COL_ID       = 0  # A列: ログインID
    COL_PW       = 1  # B列: PASSWORD
    COL_NAME     = 2  # C列: 名前
    COL_AGE      = 3  # D列: 年齢
    COL_TALL     = 4  # E列: 身長
    COL_B        = 5  # F列: バスト
    COL_W        = 6  # G列: ウエスト
    COL_H        = 7  # H列: ヒップ
    COL_CUP      = 8  # I列: カップ
    COL_MAIN_IMG = 14 # O列: メイン画像名
    COL_STATUS   = 15 # P列: 登録済フラグ

    main_img_tmp = "temp_main.jpg"
    name = str(row_data[COL_NAME])

    if not download_by_filename(row_data[COL_MAIN_IMG], main_img_tmp):
        return {"status": "error", "message": f"メイン画像の取得失敗: {row_data[COL_MAIN_IMG]}"}

    async with async_playwright() as p:
        # 日本語環境でブラウザ起動
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info(f"🌐 ログイン中: {name}")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(row_data[COL_ID]))
            await page.fill("#form_password", str(row_data[COL_PW]))
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力
            st.info("✍️ プロフィール入力中...")
            await page.fill("#form_name", name)
            await page.fill("#form_age", str(row_data[COL_AGE]))
            await page.fill("#form_tall", str(row_data[COL_TALL]))
            await page.fill("#form_bust", str(row_data[COL_B]))
            await page.fill("#form_waist", str(row_data[COL_W]))
            await page.fill("#form_hip", str(row_data[COL_H]))
            
            # カップ選択
            cup = str(row_data[COL_CUP]).strip()
            try:
                await page.locator("#form_cup").select_option(label=re.compile(f"^{cup}", re.IGNORECASE))
            except: pass

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
            await page.click("#form_update-btn", force=True)
            
            # 画像登録ボタン(con1)が表示されるまで待つ（＝保存成功の証）
            try:
                await page.wait_for_selector('a[data-target="con1"]', state="visible", timeout=20000)
            except:
                await page.screenshot(path="save_error.png")
                return {"status": "error", "message": "保存失敗。必須項目が空か、形式エラーです。"}

            # 3. メイン画像のアップロード
            st.info("📸 メイン画像をアップロード中...")
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
            for i, sub_url in enumerate(sub_image_urls):
                if i >= 7: break # 最大枚数制限
                sub_tmp = f"temp_sub_{i}.jpg"
                if download_by_filename(sub_url, sub_tmp):
                    st.info(f"🖼️ サブ画像 {i+1} 枚目を登録中...")
                    target_id = f"con{i+2}"
                    await page.click(f'a[data-target="{target_id}"]')
                    await page.locator('input[type="file"]').first.set_input_files(sub_tmp)
                    await page.locator('button.upbtn').first.click()
                    await asyncio.sleep(1)
                    if os.path.exists(sub_tmp): os.remove(sub_tmp)

            # 5. 完了ボタン
            await page.locator("#signup3").click()
            return {"status": "success"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()
            if os.path.exists(main_img_tmp): os.remove(main_img_tmp)

# --- 5. Streamlit UI ---
st.title("👸 キャスト一括登録システム (強化版)")

if st.button("🚀 未登録キャストを実行"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    # get_all_values() で「名前指定」ではなく「列番号」で扱う
    all_data = sheet_info.get_all_values()
    img_data = sheet_images.get_all_records()
    
    rows = all_data[1:] # ヘッダー(1行目)を除外
    processed_count = 0

    for i, row in enumerate(rows):
        # 列番号で状態確認 (COL_STATUS=15 は P列)
        if len(row) > 15 and row[0] and row[1] and row[15] != "登録済":
            st.subheader(f"👤 対象: {row[2]}")
            
            # 画像紐付け (J列などにIDがある想定)
            cast_id_for_img = str(row[10]) if len(row) > 10 else ""
            sub_urls = [img['写真'] for img in img_data if str(img['CastID']) == cast_id_for_img]
            
            with st.status(f"{row[2]} さんの登録を実行中...") as status:
                res = asyncio.run(run_automation(row, sub_urls))
                
                if res["status"] == "success":
                    sheet_info.update_cell(i + 2, 16, "登録済")
                    status.update(label="✅ 完了", state="complete")
                    processed_count += 1
                else:
                    status.update(label="❌ エラー", state="error")
                    st.error(res["message"])
                    if os.path.exists("error_log.png"):
                        st.image("error_log.png", caption="エラー発生時の画面")

    if processed_count == 0:
        st.info("対象の未登録キャストは見つかりませんでした。")
    else:
        st.success(f"合計 {processed_count} 名の登録が完了しました！")
