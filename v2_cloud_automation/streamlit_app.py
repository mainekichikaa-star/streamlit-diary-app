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
SCOPE = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_drive_service():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
    return build('drive', 'v3', credentials=creds)

def download_by_filename(path_str, save_path):
    if not path_str or str(path_str).strip() == "": return False
    try:
        drive_service = get_drive_service()
        filename = str(path_str).replace('\\', '/').split('/')[-1].strip()
        query = f"name = '{filename}' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        if not items: return False
        file_id = items[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        with open(save_path, "wb") as f: f.write(fh.getvalue())
        return True
    except: return False

async def upload_and_crop(page, modal_id, file_path):
    await page.locator(f"{modal_id} input[type='file']").set_input_files(file_path)
    await asyncio.sleep(2)
    up_btn = page.locator(f"{modal_id} button.upbtn")
    await up_btn.scroll_into_view_if_needed()
    await up_btn.click(force=True)
    try:
        tracker = page.locator(f"{modal_id} .jcrop-tracker.target").first
        await tracker.wait_for(state="visible", timeout=15000)
        box = await tracker.bounding_box()
        if box:
            await page.mouse.move(box["x"], box["y"])
            await page.mouse.down()
            await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
            await page.mouse.up()
        fix_btn = page.locator(f"{modal_id} input[value='修正する']").filter(has_text="")
        if await fix_btn.count() == 0:
             fix_btn = page.get_by_role("button", name="修正する")
        await fix_btn.last.click(force=True)
        await asyncio.sleep(2)
    except Exception as e:
        st.warning(f"画像編集工程でスキップが発生しました: {modal_id}")

async def run_automation(cast_row_list, shop_id, shop_pass, sub_image_paths):
    # 列番号の定義
    idx_name, idx_tall, idx_bust, idx_cup, idx_waist, idx_hip, idx_age, idx_main_img = 2, 3, 4, 5, 6, 7, 8, 11
    idx_catch, idx_girl_comment, idx_shop_comment = 14, 15, 16 # O, P, Q列
    
    try:
        if not os.path.exists("/home/appuser/.cache/ms-playwright"):
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
    except: pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(shop_id).strip())
            await page.fill("#form_password", str(shop_pass).strip())
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # プロフィール入力
            await page.fill("#form_name", str(cast_row_list[idx_name]))
            await page.fill("#form_age", str(cast_row_list[idx_age]))
            await page.fill("#form_tall", str(cast_row_list[idx_tall]))
            await page.fill("#form_bust", str(cast_row_list[idx_bust]))
            await page.fill("#form_waist", str(cast_row_list[idx_waist]))
            await page.fill("#form_hip", str(cast_row_list[idx_hip]))

            # --- 追加: キャッチコピー・コメント入力 ---
            catch_text = str(cast_row_list[idx_catch]) if len(cast_row_list) > idx_catch else ""
            girl_comment = str(cast_row_list[idx_girl_comment]) if len(cast_row_list) > idx_girl_comment else ""
            shop_comment = str(cast_row_list[idx_shop_comment]) if len(cast_row_list) > idx_shop_comment else ""

            await page.fill("#form_catchcopy", catch_text) # キャッチコピータイトル
            await page.fill("#form_girl_comments", girl_comment) # 女の子からのメッセージ
            await page.fill("#form_title", catch_text) # メッセージタイトル(キャッチコピーと同じ)
            await page.fill("#form_comments", shop_comment) # お店からのメッセージ本文
            # --------------------------------------

            cup_input = str(cast_row_list[idx_cup]).strip().upper()
            if cup_input:
                try: await page.locator("#form_cup").select_option(label=f"{cup_input}カップ")
                except: pass

            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0: await page.locator(selector).check(force=True)

            await page.click("#form_update-btn", force=True)
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=30000)

            # 画像処理
            main_tmp = "temp_main.jpg"
            if download_by_filename(cast_row_list[idx_main_img], main_tmp):
                st.info("📸 メイン画像を処理中...")
                await page.click('a[data-target="con1"]')
                await upload_and_crop(page, "#con1", main_tmp)
                if os.path.exists(main_tmp): os.remove(main_tmp)

            if sub_image_paths:
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break
                    modal_id = f"#con{i+2}"
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        st.info(f"🖼 サブ画像 {i+1} 枚目を処理中 ({modal_id})...")
                        await page.click(f'a[data-target="con{i+2}"]')
                        await upload_and_crop(page, modal_id, sub_tmp)
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            await page.locator("#signup3").click()
            return {"status": "success"}
        except Exception as e: return {"status": "error", "message": f"工程エラー: {str(e)}"}
        finally: await browser.close()

# --- UI ---
st.title("👸 キャスト一括登録システム")

# タブ分け
tab1, tab2 = st.tabs(["🚀 通常登録", "🚉 駅ちかネット予約登録"])

with tab1:
    if st.button("🚀 通常登録 実行開始"):
        try:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
            gs_client = gspread.authorize(creds)
            spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
            
            data_info = spreadsheet.worksheet("キャスト情報").get_all_values()
            rows_info = data_info[1:]
            data_images = spreadsheet.worksheet("キャスト画像").get_all_values()
            rows_images = data_images[1:]
            data_shops = spreadsheet.worksheet("シート3").get_all_records()
            shop_dict = {str(s.get('登録店舗')).strip(): s for s in data_shops}

            for i, row in enumerate(rows_info):
                target_id, cast_name, shop_name, is_registered = str(row[0]).strip(), row[2], str(row[12]).strip(), str(row[13]).strip()
                target_shop = shop_dict.get(shop_name)

                if target_id and target_shop and not is_registered:
                    sub_urls = [img_row[2] for img_row in rows_images if str(img_row[1]).strip() == target_id]
                    st.write(f"🔎 {cast_name} さん: サブ画像 {len(sub_urls)} 枚発見 (ID: {target_id})")

                    with st.status(f"{cast_name} さんの登録を実行中...") as status:
                        res = asyncio.run(run_automation(row, target_shop.get('店舗ID'), target_shop.get('店舗PASSWORD'), sub_urls))
                        if res["status"] == "success":
                            spreadsheet.worksheet("キャスト情報").update_cell(i + 2, 14, "登録済")
                            status.update(label=f"✅ {cast_name} 完了", state="complete")
                        else:
                            st.error(res["message"])
                            status.update(label="❌ エラー", state="error")
        except Exception as e: st.error(f"起動エラー: {e}")

with tab2:
    st.info("🚉 駅ちかネット予約登録は現在開発中です。")
