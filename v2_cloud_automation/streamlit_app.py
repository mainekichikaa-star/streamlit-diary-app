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

# --- ヘルパー関数 ---
def get_drive_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], 
        scopes=SCOPE
    )
    return build('drive', 'v3', credentials=creds)

def download_by_filename(path_str, save_path):
    if not path_str or str(path_str).strip() == "":
        return False
    try:
        drive_service = get_drive_service()
        # パスからファイル名のみを抽出（全角・半角スラッシュ対応）
        filename = str(path_str).replace('\\', '/').split('/')[-1].strip()
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
            _, done = downloader.next_chunk()
            
        with open(save_path, "wb") as f:
            f.write(fh.getvalue())
        return True
    except:
        return False

# --- 自動化メイン処理 ---
async def run_automation(cast_data, shop_id, shop_pass, sub_image_paths):
    try:
        if not os.path.exists("/home/appuser/.cache/ms-playwright"):
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
    except:
        pass

    main_img_tmp = "temp_main.jpg"
    main_img_ok = download_by_filename(cast_data.get('メイン画像'), main_img_tmp)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(shop_id).strip())
            await page.fill("#form_password", str(shop_pass).strip())
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 2. プロフィール入力
            await page.fill("#form_name", str(cast_data.get('名前')))
            await page.fill("#form_age", str(cast_data.get('年齢')))
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
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).check(force=True)

            await page.click("#form_update-btn", force=True)
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=30000)

            # 4. メイン画像
            if main_img_ok:
                await page.click('a[data-target="con1"]')
                await page.locator('input[type="file"]').first.set_input_files(main_img_tmp)
                await asyncio.sleep(2)
                up_btn = page.locator('button.upbtn').first
                await up_btn.click(force=True)
                tracker = page.locator(".jcrop-tracker.target").first
                await tracker.wait_for(state="visible", timeout=15000)
                box = await tracker.bounding_box()
                if box:
                    await page.mouse.move(box["x"], box["y"])
                    await page.mouse.down()
                    await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
                    await page.mouse.up()
                await page.get_by_role("button", name="修正する").click()
                await asyncio.sleep(1)

            # 5. サブ画像 (ここが修正ポイント)
            if sub_image_paths:
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        # タブ（con2, con3...）を切り替えてアップロード
                        await page.click(f'a[data-target="con{i+2}"]')
                        await asyncio.sleep(0.5)
                        await page.locator('input[type="file"]').first.set_input_files(sub_tmp)
                        await asyncio.sleep(1.5)
                        sub_up_btn = page.locator('button.upbtn').first
                        await sub_up_btn.click(force=True)
                        await asyncio.sleep(1)
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            await page.locator("#signup3").click()
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
        
        data_info = spreadsheet.worksheet("キャスト情報").get_all_records()
        data_images = spreadsheet.worksheet("キャスト画像").get_all_records()
        data_shops = spreadsheet.worksheet("シート3").get_all_records()

        shop_dict = {str(s.get('登録店舗')).strip(): s for s in data_shops}

        count = 0
        for i, row in enumerate(data_info):
            cast_name = row.get('名前')
            shop_name = str(row.get('登録店舗')).strip()
            is_registered = str(row.get('登録済')).strip()
            target_shop = shop_dict.get(shop_name)

            if target_shop and not is_registered:
                count += 1
                # A列「ID」とキャスト画像「CastID」を紐付け（型の不一致を防ぐためstrに変換）
                target_id = str(row.get('ID')).strip()
                
                # 画像リスト作成（列名の空白や表記揺れを考慮）
                sub_urls = []
                for img in data_images:
                    img_cast_id = str(img.get('CastID') or img.get('Cast ID') or "").strip()
                    if img_cast_id == target_id:
                        url = img.get('写真') or img.get('画像')
                        if url: sub_urls.append(url)

                st.write(f"🔎 {cast_name} さん: サブ画像 {len(sub_urls)} 枚発見 (ID: {target_id})")

                with st.status(f"{cast_name} さんの登録を実行中...") as status:
                    res = asyncio.run(run_automation(
                        row, 
                        target_shop.get('店舗ID'), 
                        target_shop.get('店舗PASSWORD'), 
                        sub_urls
                    ))
                    if res["status"] == "success":
                        spreadsheet.worksheet("キャスト情報").update_cell(i + 2, 14, "登録済")
                        status.update(label=f"✅ {cast_name} 完了", state="complete")
                    else:
                        st.error(res["message"])
                        status.update(label="❌ エラー", state="error")

    except Exception as e:
        st.error(f"起動エラー: {e}")
