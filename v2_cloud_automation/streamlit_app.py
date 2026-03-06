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

    # ボタンが押された後に Playwright インストールを実行

    try:

        if not os.path.exists("/home/appuser/.cache/ms-playwright"):

            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)

    except:

        pass



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



            # カップ選択

            cup_input = str(cast_data.get('カップ数', '')).strip().upper() 

            if cup_input:

                try:

                    target_label = f"{cup_input}カップ"

                    await page.locator("#form_cup").select_option(label=target_label)

                except:

                    pass

            

            # タグ選択

            await page.locator('input[name="p_genre[1]"]').check()

            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", 

                                "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", 

                                "#genre73", "#genre74"]

            for selector in target_genre_ids:

                if await page.locator(selector).count() > 0:

                    await page.locator(selector).check(force=True)



            await page.click("#form_update-btn", force=True)

            st.info("💾 保存完了を待機中...")

            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=30000)



            # 4. メイン画像アップロード

            st.info("📸 メイン画像をアップロードします")

            await page.click('a[data-target="con1"]')

            await page.locator('input[type="file"]').first.set_input_files(main_img_tmp)

            await asyncio.sleep(2) 

            

            up_btn = page.locator('button.upbtn').first

            await up_btn.wait_for(state="visible", timeout=20000)

            await up_btn.click(force=True)

            

            # Jcrop ドラッグ

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



            # 5. サブ画像

            if sub_image_paths:

                for i, sub_url in enumerate(sub_image_paths):

                    if i >= 7: break

                    sub_tmp = f"temp_sub_{i}.jpg"

                    if download_by_filename(sub_url, sub_tmp):

                        await page.click(f'a[data-target="con{i+2}"]')

                        await page.locator('input[type="file"]').first.set_input_files(sub_tmp)

                        await asyncio.sleep(1.5)

                        sub_up_btn = page.locator('button.upbtn').first

                        await sub_up_btn.wait_for(state="visible", timeout=15000)

                        await sub_up_btn.click(force=True)

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

        # スプレッドシート読み込みをボタン内に移動（フリーズ防止）

        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)

        gs_client = gspread.authorize(creds)

        

        sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")

        sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")

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

                        status.update(label="❌ エラー", state="error")

                        st.error(res["message"])

        

        if count == 0:

            st.info("登録対象のキャスト（ID/PASSがあり、未登録の方）が見つかりませんでした。")



    except Exception as e:

        st.error(f"起動エラー: {e}")

