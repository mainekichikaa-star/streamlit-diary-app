import streamlit as st
import asyncio
import os
import subprocess
import gspread
import io
import sys
import random
import string
import time
import requests
import pandas as pd
import logging
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
from playwright.async_api import async_playwright
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

# ==========================================
# 【ロギング設定】
# ==========================================
logger = logging.getLogger("gapi_retry")
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# --- 設定 ---
SPREADSHEET_ID = "1Xodf14PC3urWIbu49aqMImH6REAlYenOr9YW2WvNYTI"
SCOPE = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# ==========================================
# 【修正1】変数をアプリ起動時に必ず初期化する
# ==========================================
if 'shop_status' not in st.session_state:
    st.session_state['shop_status'] = []
shop_status = st.session_state['shop_status']

LOCAL_PW_PATH = os.path.join(os.getcwd(), "pw-browsers")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = LOCAL_PW_PATH

# ==========================================
# 【Playwright インストール確保関数】
# ==========================================
def ensure_playwright_installed():
    """Playwright ブラウザをインストール確保"""
    if not os.path.exists(LOCAL_PW_PATH):
        try:
            st.info("🔄 Playwright ブラウザをインストール中...")
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True,
                capture_output=True
            )
            st.success("✅ Playwright インストール完了")
        except subprocess.CalledProcessError as e:
            st.error(f"❌ Playwright インストール失敗: {e}")
            logger.error(f"Playwright install failed: {e}")
            return False
    return True

# ==========================================
# 【NEW】キャッシュ・認証情報の一元管理
# ==========================================
@st.cache_resource
def get_credentials():
    """認証情報をキャッシュ"""
    return Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)

@st.cache_resource
def get_drive_service_cached():
    """Google Drive サービスをキャッシュ"""
    creds = get_credentials()
    return build('drive', 'v3', credentials=creds)

@st.cache_resource
def get_sheets_service_cached():
    """Google Sheets サービスをキャッシュ"""
    creds = get_credentials()
    return build('sheets', 'v4', credentials=creds)

# ==========================================
# 【NEW】リトライデコレータ付きAPI呼び出し
# ==========================================
@retry(
    retry=retry_if_exception_type((HttpError, ConnectionError, TimeoutError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    before_sleep=before_sleep_log(logger, logging.INFO),
    reraise=True
)
def _call_drive_api(func, *args, **kwargs):
    """Google Drive API 呼び出しをリトライ対応"""
    return func(*args, **kwargs)

@retry(
    retry=retry_if_exception_type((HttpError, ConnectionError, TimeoutError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    before_sleep=before_sleep_log(logger, logging.INFO),
    reraise=True
)
def _call_sheets_api(func, *args, **kwargs):
    """Google Sheets API 呼び出しをリトライ対応"""
    return func(*args, **kwargs)

# --- ヘルパー関数 ---
def get_drive_service():
    """【修正】キャッシュされたサービスを返す"""
    return get_drive_service_cached()

def download_by_filename(path_str, save_path):
    if not path_str or str(path_str).strip() == "": return False
    try:
        drive_service = get_drive_service()
        filename = str(path_str).replace('\\', '/').split('/')[-1].strip()
        query = f"name = '{filename}' and trashed = false"
        
        # 【修正】API呼び出しにリトライを適用
        results = _call_drive_api(
            lambda: drive_service.files().list(q=query, fields="files(id, name)").execute()
        )
        
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
    except Exception as e:
        logger.error(f"download_by_filename failed: {e}")
        return False

# --- 自動化ロジック ---
async def upload_and_crop(page, modal_id, file_path):
    try:
        await page.locator(f"{modal_id} input[type='file']").set_input_files(file_path)
        await asyncio.sleep(2)
        up_btn = page.locator(f"{modal_id} button.upbtn")
        await up_btn.scroll_into_view_if_needed()
        await up_btn.click(force=True)
        
        tracker = page.locator(f"{modal_id} .jcrop-tracker.target").first
        await tracker.wait_for(state="visible", timeout=15000)
        box = await tracker.bounding_box()
        if box:
            await page.mouse.move(box["x"], box["y"])
            await page.mouse.down()
            await page.mouse.move(box["x"] + box["width"], box["y"] + box["height"], steps=15)
            await page.mouse.up()
            await asyncio.sleep(1)
        
        fix_btns = page.locator(f"{modal_id} input[value='修正する']")
        btn_count = await fix_btns.count()
        if btn_count > 0:
            for i in range(btn_count):
                target_btn = fix_btns.nth(i)
                if await target_btn.is_visible():
                    await target_btn.click(force=True)
                    await asyncio.sleep(1)
        else:
            await page.get_by_role("button", name="修正する").last.click(force=True)
        await asyncio.sleep(3) 
    except Exception as e:
        st.warning(f"画像編集工程でスキップが発生しました ({modal_id}): {e}")

async def run_automation(cast_row_list, shop_id, shop_pass, sub_image_paths):
    # --- インデックス設定（変更なし）---
    idx_name = 2
    idx_age = 3
    idx_tall = 4
    idx_bust = 5
    idx_cup = 6
    idx_waist = 7
    idx_hip = 8
    idx_catch = 10
    idx_girl_comment = 11
    idx_shop_comment = 12
    idx_main_img = 16
    
    if not ensure_playwright_installed():
        return {"status": "error", "message": "Playwright browser not available"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(shop_id).strip())
            await page.fill("#form_password", str(shop_pass).strip())
            await page.click("#form_submit")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            await page.fill("#form_name", str(cast_row_list[idx_name]))
            await page.fill("#form_age", str(cast_row_list[idx_age]))
            await page.fill("#form_tall", str(cast_row_list[idx_tall]))
            await page.fill("#form_bust", str(cast_row_list[idx_bust]))
            await page.fill("#form_waist", str(cast_row_list[idx_waist]))
            await page.fill("#form_hip", str(cast_row_list[idx_hip]))

            if len(cast_row_list) > idx_catch:
                await page.fill("#form_catchcopy", str(cast_row_list[idx_catch]))
                await page.fill("#form_title", str(cast_row_list[idx_catch]))
            if len(cast_row_list) > idx_girl_comment:
                await page.fill("#form_girl_comments", str(cast_row_list[idx_girl_comment]))
            if len(cast_row_list) > idx_shop_comment:
                await page.fill("#form_comments", str(cast_row_list[idx_shop_comment]))

            cup_input = str(cast_row_list[idx_cup]).strip().upper()
            if cup_input:
                try: await page.locator("#form_cup").select_option(label=f"{cup_input}カップ")
                except: pass

            await page.locator('input[name="p_genre[1]"]').check()
            target_genre_ids = ["#genre17", "#genre30", "#genre31", "#genre33", "#genre34", "#genre36", "#genre25", "#genre35", "#genre41", "#genre43", "#genre44", "#genre55", "#genre73", "#genre74"]
            for selector in target_genre_ids:
                if await page.locator(selector).count() > 0: await page.locator(selector).check(force=True)

            await page.click("#form_update-btn", force=True)
            try: await page.wait_for_selector("text=データを登録しました。", timeout=15000)
            except: pass

            await asyncio.sleep(2)
            main_tmp = "temp_main.jpg"
            if download_by_filename(cast_row_list[idx_main_img], main_tmp):
                main_tab = page.locator('a[data-target="con1"]')
                await main_tab.scroll_into_view_if_needed()
                await main_tab.click(force=True)
                await asyncio.sleep(2)
                await upload_and_crop(page, "#con1", main_tmp)
                if os.path.exists(main_tmp): os.remove(main_tmp)

            if sub_image_paths:
                for i, sub_url in enumerate(sub_image_paths):
                    if i >= 7: break 
                    modal_id = f"#con{i+2}"
                    sub_tmp = f"temp_sub_{i}.jpg"
                    if download_by_filename(sub_url, sub_tmp):
                        sub_tab = page.locator(f'a[data-target="con{i+2}"]')
                        await sub_tab.scroll_into_view_if_needed()
                        await sub_tab.click(force=True)
                        await asyncio.sleep(2)
                        await upload_and_crop(page, modal_id, sub_tmp)
                        if os.path.exists(sub_tmp): os.remove(sub_tmp)

            await page.locator("#signup3").click()
            await asyncio.sleep(2)
            return {"status": "success"}
        except Exception as e:
            await page.screenshot(path=f"error_{cast_row_list[idx_name]}.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- UI ---
st.set_page_config(page_title="自動登録システム", layout="wide")
st.title("自動登録システム")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🚀 駅ちかキャスト自動登録", 
    "🚉 駅ちかネット予約自動登録", 
    "📋 駅ちか既存店コピー", 
    "🚀 デリじゃキャスト自動登録", 
    "📋 デリじゃ既存店コピー"
])

# ==========================================
# 【修正2】スプレッドシート読み込みにリトライ適用
# ==========================================
try:
    creds = get_credentials()
    gs_client = gspread.authorize(creds)
    
    # 【修正】API呼び出しにリトライを適用
    spreadsheet = _call_sheets_api(
        lambda: gs_client.open_by_key(SPREADSHEET_ID)
    )
    
    worksheet_cast = _call_sheets_api(
        lambda: spreadsheet.worksheet("キャスト情報")
    )
    worksheet_shops = _call_sheets_api(
        lambda: spreadsheet.worksheet("シート3")
    )
    
    data_info = _call_sheets_api(
        lambda: worksheet_cast.get_all_values()
    )
    rows_info = data_info[1:]
    data_shops = _call_sheets_api(
        lambda: worksheet_shops.get_all_records()
    )
    
    temp_shops = []
    for s in data_shops:
        s_id = str(s.get('店舗ID', '')).strip()
        s_pass = str(s.get('店舗PASSWORD', '')).strip()
        if s_id and s_pass:
            unreg = [r for r in rows_info if len(r) > 15 and str(r[14]).strip() == s_id and str(r[15]).strip() != "登録済"]
            temp_shops.append({
                "店舗名": str(s.get('登録店舗', '')).strip(),
                "ID": s_id,
                "raw_pass": s_pass,
                "未登録数": len(unreg),
                "casts": unreg
            })
    shop_status = temp_shops
    st.session_state['shop_status'] = shop_status
except Exception as e:
    st.error(f"初期化エラー: {e}")
    logger.error(f"Initialization failed: {e}")

with tab1:
    st.subheader("店舗別・未登録キャスト状況")
    
    try:
        # データ取得
        creds = get_credentials()
        gs_client = gspread.authorize(creds)
        spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
        
        worksheet_cast = _call_sheets_api(lambda: spreadsheet.worksheet("キャスト情報"))
        worksheet_images = _call_sheets_api(lambda: spreadsheet.worksheet("キャスト画像"))
        worksheet_shops = _call_sheets_api(lambda: spreadsheet.worksheet("シート3"))

        data_info = _call_sheets_api(lambda: worksheet_cast.get_all_values())
        headers_info = data_info[0]
        rows_info = data_info[1:]
        
        data_images = _call_sheets_api(lambda: worksheet_images.get_all_values())
        rows_images = data_images[1:]
        
        data_shops = _call_sheets_api(lambda: worksheet_shops.get_all_records())
        
        # 店舗ごとの未登録数をカウント
        shop_status = []
        # 除外したいキーワードのリスト
        exclude_keywords = ["デリじゃ", "デリジャ", "でりじゃ"]
        
        for shop in data_shops:
            s_name = str(shop.get('登録店舗')).strip()

            # --- 追加: 除外キーワードが含まれているかチェック ---
            if any(keyword in s_name for keyword in exclude_keywords):
                continue  # キーワードが含まれていたら、この店舗の処理をスキップ
            # ----------------------------------------------
            
            s_id = str(shop.get('店舗ID')).strip()
            s_pass = str(shop.get('店舗PASSWORD')).strip()
            
            unregistered_casts = []
            for r in rows_info:
                if len(r) > 14:
                    cast_shop_id = str(r[14]).strip()
                    status_field = str(r[15]).strip() if len(r) > 15 else ""
                    
                    if cast_shop_id == s_id and status_field != "登録済":
                        unregistered_casts.append(r)
            
            if s_id and s_pass:
                shop_status.append({
                    "店舗名": s_name,
                    "ID": s_id,
                    "PW": "********",
                    "未登録数": len(unregistered_casts),
                    "raw_pass": s_pass,
                    "casts": unregistered_casts
                })

        # 実行対象の選択表示
        st.write("実行する店舗を選択してください:")
        selected_shops = []
        
        if not shop_status:
            st.info("表示できる店舗データがありません。")
        else:
            cols = st.columns(3)
            for idx, shop in enumerate(shop_status):
                with cols[idx % 3]:
                    is_selected = st.checkbox(f"{shop['店舗名']} ({shop['未登録数']}名)", key=f"shop_{idx}")
                    if is_selected:
                        selected_shops.append(shop)

        st.divider()
        
        if st.button("🚀 選択した店舗の登録を開始", type="primary"):
            if not selected_shops:
                st.warning("店舗が選択されていません。")
            else:
                for shop in selected_shops:
                    st.markdown(f"### 🏢 店舗: {shop['店舗名']}")
                    for cast in shop['casts']:
                        target_id = str(cast[0]).strip()
                        cast_name = cast[2]
                        sub_urls = [img_row[2] for img_row in rows_images if str(img_row[1]).strip() == target_id]
                        
                        with st.status(f"【{shop['店舗名']}】{cast_name} さ��の登録中...") as status:
                            res = asyncio.run(run_automation(cast, shop['ID'], shop['raw_pass'], sub_urls))
                            
                            if res["status"] == "success":
                                row_idx = next((i for i, r in enumerate(data_info) if str(r[0]).strip() == target_id), None)
                                if row_idx:
                                    _call_sheets_api(
                                        lambda: worksheet_cast.update_cell(row_idx + 1, 16, "登録済")
                                    )
                                status.update(label=f"✅ {cast_name} 完了", state="complete")
                            else:
                                st.error(f"{cast_name} エラー: {res['message']}")
                                if os.path.exists(f"error_{cast_name}.png"): st.image(f"error_{cast_name}.png")
                                status.update(label="❌ エラー", state="error")
                st.success("全ての処理が完了しました。")

    except Exception as e:
        st.error(f"初期化エラー: {e}")

with tab2:
    st.subheader("🚉 駅ちかネット予約登録 (e-yoyaku.jp)")
    
    st.write("ネット予約設定を行う店舗を選択してください:")
    selected_yoyaku_shops = []
    
    y_cols = st.columns(3)
    for idx, shop in enumerate(shop_status):
        with y_cols[idx % 3]:
            is_y_selected = st.checkbox(f"{shop['店舗名']} を設定", key=f"yoyaku_{idx}")
            if is_y_selected:
                selected_yoyaku_shops.append(shop)

    st.divider()

    if st.button("🌐 ネット予約管理画面へログイン・一括設定開始", type="primary"):
        if not selected_yoyaku_shops:
            st.warning("店舗が選択されていません。")
        else:
            for shop in selected_yoyaku_shops:
                st.markdown(f"### 🏢 店舗: {shop['店舗名']} の同期処理を実行中...")
                
                async def run_yoyaku_automation(s_id, s_pass):
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--lang=ja-JP'])
                        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
                        page = await context.new_page()
                        
                        try:
                            await page.goto("https://ranking-deli.jp/admin/login")
                            await page.fill("#form_email", str(s_id).strip())
                            await page.fill("#form_password", str(s_pass).strip())
                            await page.click("#form_submit")
                            await page.wait_for_load_state("networkidle")

                            await page.goto("https://ranking-deli.jp/admin/shopcharges/")
                            
                            course_data = {"title": await page.locator("#form_course\\[0\\]\\[course_name\\]").get_attribute("value"), "prices": []}
                            for i in range(1, 6):
                                t_val = await page.locator(f"#form_course\\[0\\]\\[time{i}\\]").get_attribute("value")
                                p_val = await page.locator(f"#form_course\\[0\\]\\[charge{i}\\]").get_attribute("value")
                                if t_val and p_val:
                                    course_data["prices"].append({"time": t_val, "price": p_val})

                            extra_fees = {"admission": "", "nomination": "0", "repeat": "0"}
                            for i in range(1, 6):
                                label = await page.locator(f"#form_course\\[1\\]\\[time{i}\\]").get_attribute("value") or ""
                                val = await page.locator(f"#form_course\\[1\\]\\[charge{i}\\]").get_attribute("value") or ""
                                
                                if "入会金" in label:
                                    clean_val = "".join(filter(str.isdigit, val))
                                    if clean_val and clean_val != "0":
                                        extra_fees["admission"] = clean_val
                                
                                if any(x in label for x in ["指名料", "ネット指名料", "指名", "写真指名料", "写真指名"]):
                                    extra_fees["nomination"] = "".join(filter(str.isdigit, val)) or "0"

                                if any(x in label for x in ["本指名", "本指名料"]):
                                    extra_fees["repeat"] = "".join(filter(str.isdigit, val)) or "0"

                            await page.goto("https://ranking-deli.jp/admin/shopoptions/")
                            option_data = []
                            for i in range(20):
                                opt_name_el = page.locator(f"#form_option\\[{i}\\]\\[option_name\\]")
                                opt_fee_el = page.locator(f"#form_option\\[{i}\\]\\[option_fee\\]")
                                if await opt_name_el.count() > 0:
                                    name = await opt_name_el.get_attribute("value")
                                    fee = await opt_fee_el.get_attribute("value")
                                    if name and name.strip():
                                        option_data.append({"name": name.strip(), "fee": fee or "0"})
                                else: break

                            await page.goto("https://ranking-deli.jp/admin/shop/transportation")
                            transport_data = []
                            fee_divs = await page.locator(".carfare-fee-div").all()
                            for div in fee_divs:
                                selected_text = await div.locator("select.select-fee option:checked").inner_text()
                                fee_val = "".join(filter(str.isdigit, selected_text)) if "無料" not in selected_text else "0"
                                area_elements = await div.locator(".draggable.shop-area").all()
                                for area_el in area_elements:
                                    area_name = (await area_el.inner_text()).strip()
                                    if area_name:
                                        transport_data.append({"area": area_name, "fee": fee_val})

                            async with context.expect_page() as new_page_info:
                                await page.locator("a.web_link").click()
                            yoyaku_page = await new_page_info.value
                            await yoyaku_page.wait_for_load_state()

                            await yoyaku_page.locator(".listItem.setting .menuTxt").click()
                            await asyncio.sleep(1)

                            await yoyaku_page.locator("a.acListTxt", has_text="予約設定").first.click()
                            await yoyaku_page.locator("label[for='release']").click()
                            await yoyaku_page.locator("label[for='freeReserveAccept']").click()
                            await yoyaku_page.locator("input[name='admission_fee']").fill(extra_fees["admission"])
                            await yoyaku_page.locator("button.saveBt", has_text="保存").click()
                            await asyncio.sleep(1)

                            await yoyaku_page.locator("a.acListTxt", has_text="料金コース").first.click()
                            if course_data["title"]:
                                await yoyaku_page.locator("input[name='courses[0][name]']").fill(course_data["title"])
                            for idx, item in enumerate(course_data["prices"]):
                                time_sel = yoyaku_page.locator(f"select[name='courses[0][content][{idx}][time]']")
                                price_in = yoyaku_page.locator(f"input[name='courses[0][content][{idx}][fee]']")
                                if await time_sel.count() > 0:
                                    await time_sel.select_option(value=str(item["time"]))
                                    await price_in.fill(str(item["price"]))
                            await yoyaku_page.locator("button.js-save-btn").click()
                            await asyncio.sleep(1)

                            await yoyaku_page.locator("a.acListTxt", has_text="オプション").first.click()
                            for idx, opt in enumerate(option_data):
                                n_in, f_in = yoyaku_page.locator(f"input[name='options[{idx}][name]']"), yoyaku_page.locator(f"input[name='options[{idx}][fee]']")
                                if await n_in.count() > 0:
                                    await n_in.fill(opt["name"]); await f_in.fill(str(opt["fee"]))
                                else: break
                            await yoyaku_page.locator("button.js-save-btn").click()
                            await asyncio.sleep(1)

                            await yoyaku_page.locator("a.acListTxt", has_text="交通費").first.click()
                            for idx, tf in enumerate(transport_data):
                                a_in, f_in = yoyaku_page.locator(f"input[name='carfares[{idx}][area_name]']"), yoyaku_page.locator(f"input[name='carfares[{idx}][fee]']")
                                if await a_in.count() > 0:
                                    await a_in.fill(tf["area"]); await f_in.fill(str(tf["fee"]))
                                else: break
                            await yoyaku_page.locator("button.js-save-btn").click()
                            await asyncio.sleep(1)

                            target_email = "isgroup0001@gmail.com"
                            for menu_name in ["チャット設定", "予約通知"]:
                                await yoyaku_page.locator("a.acListTxt", has_text=menu_name).first.click()
                                if menu_name == "チャッ��設定":
                                    await yoyaku_page.locator("label[for='Release']").click()
                                exs_emails = await yoyaku_page.locator("input[type='email']").all_attribute_values("value")
                                if target_email not in [e.strip() for e in exs_emails if e]:
                                    await yoyaku_page.locator("button.js-mail_user_add_button").click()
                                    await yoyaku_page.locator("input[type='email']").last.fill(target_email)
                                save_btn_sel = "button[name='sms-mail-add']" if menu_name == "予約通知" else "button.saveBt"
                                await yoyaku_page.locator(save_btn_sel).click()
                                await asyncio.sleep(1)

                            await yoyaku_page.locator("a.acListTxt", has_text="女の子").first.click()
                            await yoyaku_page.wait_for_load_state()
                            await yoyaku_page.locator("label[for='allGirls']").click()
                            await yoyaku_page.locator("#nomination-input").fill(extra_fees["nomination"])
                            await yoyaku_page.locator("#repeat-nomination-input").fill(extra_fees["repeat"])
                            await yoyaku_page.locator("button.js-bulk-form-btn").click()
                            
                            return {"status": "success", "fees": extra_fees, "url": yoyaku_page.url}

                        except Exception as e:
                            return {"status": "error", "message": str(e)}
                        finally:
                            await browser.close()

                with st.status(f"🔄 {shop['店舗名']} の同期を実行中...") as status:
                    res = asyncio.run(run_yoyaku_automation(shop['ID'], shop['raw_pass']))
                    if res["status"] == "success":
                        status.update(label=f"✅ {shop['店舗名']} 同期完了", state="complete")
                        st.success(f"同期成功: 入会金={res['fees']['admission'] or '無'}, 指名={res['fees']['nomination']}, 本指名={res['fees']['repeat']}")
                    else:
                        st.error(f"❌ {shop['店舗名']} エラー: {res['message']}")
                        status.update(label="❌ 同期失敗", state="error")

with tab3:
    st.subheader("📥 既存店キャスト情報の同期 (Web → シート)")
    st.info("選択した店舗の管理画面にログインし、登録されている全てのキャスト情報をスプレッドシートへ書き出します。")

    shop_names = [s['店舗名'] for s in shop_status] if 'shop_status' in locals() else []

    if shop_names:
        selected_sync_shop_name = st.selectbox("情報を取得する店舗を選択", shop_names, key="sync_shop_select")
        target_shop = next(s for s in shop_status if s['店舗名'] == selected_sync_shop_name)

        def upload_to_drive_custom(file_content, folder_name, file_name):
            drive_service = get_drive_service()
            query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            folders = _call_drive_api(
                lambda: drive_service.files().list(q=query, fields="files(id)").execute().get('files', [])
            )
            
            if not folders:
                folder_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
                folder = _call_drive_api(
                    lambda: drive_service.files().create(body=folder_metadata, fields='id').execute()
                )
                folder_id = folder.get('id')
            else:
                folder_id = folders[0]['id']
                
            file_metadata = {'name': file_name, 'parents': [folder_id]}
            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype='image/jpeg')
            _call_drive_api(
                lambda: drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            )
            return f"{folder_name}/{file_name}"

        async def run_fetch_cast_data(shop_id, shop_pass, shop_name):
            if not ensure_playwright_installed():
                return {"status": "error", "message": "Playwright browser not available"}

            cast_data_list = []
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True, 
                    args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
                )
                context = await browser.new_context(locale="ja-JP")
                page = await context.new_page()

                try:
                    await page.goto("https://ranking-deli.jp/admin/login")
                    await page.fill("#form_email", str(shop_id).strip())
                    await page.fill("#form_password", str(shop_pass).strip())
                    await page.click("#form_submit")
                    await page.wait_for_load_state("networkidle")
                    
                    await page.goto("https://ranking-deli.jp/admin/girls/")
                    
                    edit_links = await page.locator('.girl-btn a[href*="edit"]').evaluate_all(
                        "nodes => nodes.map(n => n.href)"
                    )
                    
                    if not edit_links:
                        return {"status": "success", "data": []}

                    st.write(f"🔍 {len(edit_links)} 名のキャストを検出しました。取得を開始します...")
                    
                    progress_bar = st.progress(0)
                    for i, link in enumerate(edit_links):
                        await page.goto(link)
                        await asyncio.sleep(1) 

                        site_girl_name = await page.input_value("#form_name")
                        age = await page.input_value("#form_age")
                        tall = await page.input_value("#form_tall")
                        bust = await page.input_value("#form_bust")
                        waist = await page.input_value("#form_waist")
                        hip = await page.input_value("#form_hip")
                        
                        try:
                            cup_full = await page.locator("#form_cup option:checked").text_content()
                            cup = cup_full.replace("カップ", "").strip() if cup_full else ""
                        except:
                            cup = ""

                        catch = await page.input_value("#form_catchcopy")
                        girl_comment = await page.input_value("#form_girl_comments")
                        shop_comment = await page.input_value("#form_comments")

                        main_image_path_in_sheet = ""
                        try:
                            img_src = await page.locator("#image-box1 .img_b img").get_attribute("src")
                            if img_src:
                                response = requests.get(img_src)
                                if response.status_code == 200:
                                    rand_str = ''.join(random.choices(string.digits, k=6))
                                    custom_id = f"{str(shop_id).strip()}{(i + 1):02d}"
                                    filename = f"{custom_id}.メイン画像.{rand_str}.jpg"
                                    main_image_path_in_sheet = upload_to_drive_custom(response.content, "キャスト情報_Images", filename)
                        except Exception as e:
                            st.warning(f"画像取得スキップ ({site_girl_name}): {e}")

                        custom_id = f"{str(shop_id).strip()}{(i + 1):02d}"

                        row = [
                            custom_id,
                            "",
                            f"{shop_name} {site_girl_name}",
                            age,
                            tall,
                            bust,
                            cup,
                            waist,
                            hip,
                            "",
                            catch,
                            girl_comment,
                            shop_comment,
                            "",
                            "",
                            "",
                            main_image_path_in_sheet
                        ]
                        cast_data_list.append(row)
                        progress_bar.progress((i + 1) / len(edit_links))

                    return {"status": "success", "data": cast_data_list}
                except Exception as e:
                    return {"status": "error", "message": str(e)}
                finally:
                    await browser.close()

        if st.button("🔄 同期を実行（スプレッドシートへ追記）", type="primary", key="exec_sync_btn"):
            with st.status("同期処理を実行中...") as status:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(run_fetch_cast_data(target_shop['ID'], target_shop['raw_pass'], target_shop['店舗名']))
                    
                    if result["status"] == "success":
                        if result["data"]:
                            creds = get_credentials()
                            gs_client = gspread.authorize(creds)
                            worksheet = _call_sheets_api(
                                lambda: gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
                            )
                            
                            _call_sheets_api(lambda: worksheet.append_rows(result["data"]))
                            st.success(f"✅ {len(result['data'])} 名の情報を画像と共にシートに追加しました。")
                            st.dataframe(pd.DataFrame(result["data"], columns=["ID", "エリア", "名前", "年齢", "身長", "バスト", "カップ", "ウエスト", "ヒップ", "系統", "キャッチ", "女コメント", "店コメント", "空1", "空2", "空3", "メイン画像"]))
                        else:
                            st.warning("キャスト情報が見つかりませんでした。")
                        status.update(label="同期完了", state="complete")
                    else:
                        st.error(f"エラーが発生しました: {result['message']}")
                        status.update(label="エラー終了", state="error")
                finally:
                    loop.close()

    else:
        st.error("店舗データが読み込まれていません。")

with tab4:
    st.subheader("🍓 デリじゃ キャスト自動登録")

    @st.cache_data(ttl=300)
    def fetch_data_v38():
        try:
            creds = get_credentials()
            gc = gspread.authorize(creds)
            ss = _call_sheets_api(lambda: gc.open_by_key(SPREADSHEET_ID))
            return (
                _call_sheets_api(lambda: ss.worksheet("キャスト情報").get_all_values()),
                _call_sheets_api(lambda: ss.worksheet("シート3").get_all_records())
            )
        except Exception as e: return None, str(e)

    raw_cast_data, shop_records = fetch_data_v38()

    if raw_cast_data:
        rows_info = raw_cast_data[1:]
        dj_shops = []
        for s in shop_records:
            s_name = str(s.get('登録店舗', '')).strip()
            if any(k in s_name for k in ["デリじゃ", "デリジャ", "でりじゃ"]):
                sid, spass = str(s.get('店舗ID', '')).strip(), str(s.get('店舗PASSWORD', '')).strip()
                unreg = [r for r in rows_info if len(r) > 14 and str(r[14]).strip() == sid and str(r[15]).strip() != "登録済"]
                if sid and spass: dj_shops.append({"店舗名": s_name, "ID": sid, "PASS": spass, "casts": unreg})

        async def run_derija_v38(cast, sid, spass):
            if not ensure_playwright_installed():
                return {"status": "error", "message": "Playwright browser not available"}

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    viewport={'width': 1280, 'height': 2000}
                )
                page = await context.new_page()
                target_name, debug_path, tmp_img_path = str(cast[2]).strip(), f"debug_{sid}.png", None

                try:
                    await page.goto("https://deli-fuzoku.jp/entry/", wait_until="networkidle")
                    await page.type("#form_username", sid, delay=random.randint(50, 120))
                    await page.type("#form_password", spass, delay=random.randint(50, 120))
                    await asyncio.sleep(1)
                    await page.click("button.loginBtn")
                    await page.wait_for_load_state("networkidle")

                    await asyncio.sleep(random.uniform(2.0, 4.0))
                    await page.mouse.wheel(0, 400)
                    add_link = page.get_by_role("link", name="在籍の追加")
                    await add_link.first.click()
                    await page.wait_for_selector("#form_girl_name", state="visible", timeout=60000)

                    async def human_input(selector, text, is_long=False):
                        if not text: return
                        el = page.locator(selector)
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.3, 0.7))
                        await el.click()
                        d = random.randint(30, 70) if is_long else random.randint(100, 250)
                        await page.type(selector, str(text), delay=d, timeout=300000)
                        await page.mouse.click(0, 0) 
                        await asyncio.sleep(random.uniform(0.5, 1.2))

                    await human_input("#form_girl_name", target_name)
                    await human_input("#form_girl_age", cast[3])
                    await human_input("#form_girl_height", cast[4])
                    
                    cup_val = str(cast[6]).strip().replace("カップ", "").upper()
                    if cup_val:
                        st.write(f"🍷 カップ数を選択中: {cup_val}")
                        await page.select_option("#form_girl_cup", value=cup_val)
                        await asyncio.sleep(0.5)

                    await human_input("#form_girl_sizeb", cast[5])
                    await human_input("#form_girl_sizew", cast[7])
                    await human_input("#form_girl_sizeh", cast[8])
                    
                    st.write(f"✍️ 自己紹介文を入力中...")
                    await human_input("#form_girl_pr", cast[12], is_long=True)

                    st.write("🏷️ 指定タグ（画像準拠）をセット中...")
                    target_tags = [
                        "美脚", "美乳", "美尻", "美肌", "色白",
                        "スタイル抜群", "愛嬌抜群", "サービス抜群", "要予約", "プレミア",
                        "人懐っこい", "空気を読む", "しっかり者", "感度抜群", "話し好き",
                        "エロい", "敏感", "聖水", "スレンダー", "ｲﾁｬｲﾁｬ好き",
                        "店長オススメ", "聞き上手"
                    ]
                    
                    for tag_text in target_tags:
                        try:
                            label = page.locator(f"td.girl_tags label:has-text('{tag_text}')")
                            if await label.count() > 0:
                                await label.scroll_into_view_if_needed()
                                await label.click()
                                await asyncio.sleep(random.uniform(0.1, 0.3))
                        except: 
                            pass

                    img_name = cast[16]
                    if img_name:
                        tmp_img_path = os.path.abspath(f"up_{sid}_{random.randint(1000,9999)}.jpg")
                        if download_by_filename(img_name, tmp_img_path):
                            await page.locator("#form_file_girl_photo1").set_input_files(tmp_img_path)
                            st.write("📸 画像反映待ち...")
                            await asyncio.sleep(12)

                    st.write("🚀 最終送信...")
                    submit_label = page.locator('label[for="form_submit_btn"]')
                    await submit_label.scroll_into_view_if_needed()
                    async with page.expect_navigation(timeout=120000):
                        await submit_label.click()

                    for _ in range(30):
                        await asyncio.sleep(3)
                        if "girl_list.php" in page.url or "完了" in await page.content():
                            return {"status": "success"}
                    
                    raise Exception("完了画面への遷移が確認できませんでした。")

                except Exception as e:
                    await page.screenshot(path=debug_path, full_page=True)
                    return {"status": "error", "message": str(e), "screenshot": debug_path}
                finally:
                    if tmp_img_path and os.path.exists(tmp_img_path): os.remove(tmp_img_path)
                    await browser.close()

        selected = []
        if dj_shops:
            cols = st.columns(3)
            for i, s in enumerate(dj_shops):
                with cols[i % 3]:
                    if st.checkbox(f"{s['店舗名']} ({len(s['casts'])}名)", key=f"dj_v38_cb_{i}"):
                        selected.append(s)

            if st.button("🚀 デリじゃ一括登録開始", type="primary"):
                ws_w = None
                try:
                    creds_w = get_credentials()
                    ws_w = _call_sheets_api(
                        lambda: gspread.authorize(creds_w).open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
                    )
                except: pass

                for shop in selected:
                    for cast in shop['casts']:
                        with st.status(f"{cast[2]} 登録中..."):
                            res = asyncio.run(run_derija_v38(cast, shop['ID'], shop['PASS']))
                            if res["status"] == "success":
                                st.success(f"✅ {cast[2]} 完了！")
                                if ws_w:
                                    row_idx = next((i for i, r in enumerate(raw_cast_data) if r[0] == cast[0]), None)
                                    if row_idx: 
                                        _call_sheets_api(
                                            lambda: ws_w.update_cell(row_idx + 1, 16, "登録済")
                                        )
                            else:
                                st.error(f"❌ {cast[2]} 失敗: {res['message']}")
                                if "screenshot" in res: st.image(res["screenshot"])

# ==========================================
# 【Tab5: デリじゃ既存店コピー (Web → シート)】
# 命名規則対応版
# ==========================================

with tab5:
    st.subheader("📥 デリじゃ キャスト情報の同期")
    debug_image_space = st.empty()

    try:
        creds = get_credentials()
        gs_client = gspread.authorize(creds)
        spreadsheet = _call_sheets_api(lambda: gs_client.open_by_key(SPREADSHEET_ID))
        worksheet_shops = _call_sheets_api(lambda: spreadsheet.worksheet("シート3"))
        data_shops = _call_sheets_api(lambda: worksheet_shops.get_all_records())

        derija_keywords = ["デリじゃ", "デリジャ", "でりじゃ"]
        derija_sync_shops = [
            {"店舗名": str(s.get('登録店舗')).strip(), "ID": str(s.get('店舗ID')).strip(), "raw_pass": str(s.get('店舗PASSWORD')).strip()}
            for s in data_shops if any(k in str(s.get('登録店舗')).strip() for k in derija_keywords)
        ]

        if derija_sync_shops:
            selected_name = st.selectbox("同期店舗を選択", [s['店舗名'] for s in derija_sync_shops], key="derija_sync_sel")
            target_shop = next(s for s in derija_sync_shops if s['店舗名'] == selected_name)

            async def run_fetch_derija_data(shop_id, shop_pass, shop_name):
                """
                【修正版】命名規則対応
                - A列: shop_id + 3桁連番 (例: gyal001, gyal002...)
                - C列: 登録店舗名 + 全角スペース + 女の子の名前
                """
                
                # 【修正】Playwrightインストール確保
                if not ensure_playwright_installed():
                    return {"status": "error", "message": "Playwright browser not available"}

                cast_data_list = []
                
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True, 
                        args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
                    )
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        viewport={'width': 1280, 'height': 1200}
                    )
                    page = await context.new_page()
                    
                    try:
                        # ==========================================
                        # 【Step 1】ログイン画面へ移動
                        # ==========================================
                        st.write("🔄 ログイン画面へ移動中...")
                        await page.goto("https://deli-fuzoku.jp/entry/", wait_until="networkidle")
                        await asyncio.sleep(random.uniform(1.0, 2.0))

                        # ==========================================
                        # 【Step 2】ログイン処理（Bot検知回避）
                        # ==========================================
                        st.write("🔐 ログイン処理を実行中...")
                        
                        # ユーザー名入力（人間らしい速度）
                        username_input = page.locator('input#form_username')
                        await username_input.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        await username_input.click()
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        
                        for char in shop_id:
                            await page.type('input#form_username', char, delay=random.randint(50, 150))
                            await asyncio.sleep(random.uniform(0.05, 0.1))
                        
                        await asyncio.sleep(random.uniform(0.5, 1.0))

                        # パスワード入力（人間らしい速度）
                        password_input = page.locator('input#form_password')
                        await password_input.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        await password_input.click()
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                        
                        for char in shop_pass:
                            await page.type('input#form_password', char, delay=random.randint(50, 150))
                            await asyncio.sleep(random.uniform(0.05, 0.1))
                        
                        await asyncio.sleep(random.uniform(0.5, 1.5))

                        # マウス移動（人間らしい動き）
                        await page.mouse.move(random.randint(100, 800), random.randint(100, 600))
                        await asyncio.sleep(random.uniform(0.2, 0.5))

                        # ボタン無効化を強制除去
                        await page.evaluate("""() => {
                            const btn = document.querySelector('button#button');
                            if (btn) {
                                btn.removeAttribute('disabled');
                                btn.disabled = false;
                            }
                        }""")
                        
                        await asyncio.sleep(random.uniform(0.3, 0.7))

                        # ログインボタンをクリック
                        login_button = page.locator('button#button')
                        await login_button.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.3, 0.6))
                        await login_button.click()
                        
                        st.write("⏳ ログイン処理待機中...")
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        await asyncio.sleep(random.uniform(2.0, 3.5))

                        logger.info(f"ログイン後URL: {page.url}")

                        # ==========================================
                        # 【Step 3】メニューから「在籍嬢一覧」へ遷移
                        # ==========================================
                        st.write("📋 在籍嬢一覧へ移動中...")
                        
                        menu_patterns = [
                            'a:has-text("在籍嬢一覧")',
                            '//a[contains(text(), "在籍嬢一覧")]',
                            'li.hover a:has-text("在籍嬢一覧")',
                        ]
                        
                        menu_clicked = False
                        for pattern in menu_patterns:
                            try:
                                menu_element = page.locator(pattern)
                                if await menu_element.count() > 0:
                                    await menu_element.first.scroll_into_view_if_needed()
                                    await asyncio.sleep(random.uniform(0.5, 1.0))
                                    await page.mouse.move(random.randint(100, 800), random.randint(100, 600))
                                    await asyncio.sleep(random.uniform(0.2, 0.4))
                                    await menu_element.first.click()
                                    menu_clicked = True
                                    st.success("✅ メニュークリック成功")
                                    break
                            except Exception as e:
                                logger.debug(f"Menu pattern failed: {pattern} - {e}")
                                continue
                        
                        if not menu_clicked:
                            st.info("ℹ️ メニュー要素が見つからないため、URL直接遷移を実行")
                            await page.goto("https://deli-fuzoku.jp/entry/girls", wait_until="networkidle")
                        
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        await asyncio.sleep(random.uniform(1.5, 2.5))

                        # ==========================================
                        # 【Step 4】ページスクリーンショット（デバッグ用）
                        # ==========================================
                        st.write("📸 ページ状態をキャプチャ中...")
                        screenshot = await page.screenshot(full_page=False)
                        debug_image_space.image(screenshot, caption="在籍嬢一覧ページ")

                        # ==========================================
                        # 【Step 5】キャスト要素の検出
                        # ==========================================
                        st.write("🔍 キャスト要素を検索中...")
                        
                        # HTML構造に基づいた要素取得
                        # ul#ul_sortable1 > li.ui-state-default
                        cast_list_ul = page.locator('div#search_area ul#ul_sortable1')
                        
                        if await cast_list_ul.count() == 0:
                            st.error("❌ キャストリスト要素(ul#ul_sortable1)が見つかりません")
                            logger.error("ul#ul_sortable1 not found")
                            return {"status": "error", "message": "キャストリスト要素が見つかりません"}
                        
                        st.success("✅ キャストリスト要素を検���")

                        # ul内の全てのli要素を取得
                        cast_items = page.locator('ul#ul_sortable1 > li.ui-state-default')
                        cast_count = await cast_items.count()
                        
                        if cast_count == 0:
                            st.warning("⚠️ キャスト情報が見つかりません")
                            logger.warning("No cast items found in ul#ul_sortable1")
                            return {"status": "success", "data": [], "debug_msg": "キャスト情報がありません"}
                        
                        st.write(f"🔍 {cast_count} 名のキャストを検出しました。取得を開始します...")
                        logger.info(f"Found {cast_count} cast items")
                        progress_bar = st.progress(0)

                        # ==========================================
                        # 【Step 6】キャストループ処理
                        # ==========================================
                        for i in range(cast_count):
                            try:
                                st.write(f"⏳ {i+1}/{cast_count} 番目のキャストを処理中...")
                                
                                # ==========================================
                                # 【Step 6-1】編集ボタンを再取得（DOM更新対応）
                                # ==========================================
                                await asyncio.sleep(random.uniform(0.5, 1.0))
                                
                                # 最新のキャスト要素を取得
                                current_cast_li = page.locator('ul#ul_sortable1 > li.ui-state-default').nth(i)
                                
                                # スクロール
                                await current_cast_li.scroll_into_view_if_needed()
                                await asyncio.sleep(random.uniform(0.5, 1.0))

                                # 編集ボタンをセレクタで特定
                                # li.ui-state-default内のinput[value="編集"]
                                edit_button = current_cast_li.locator('input[value="編集"]')
                                
                                edit_button_count = await edit_button.count()
                                logger.info(f"Cast {i}: Found {edit_button_count} edit buttons")
                                
                                if edit_button_count == 0:
                                    st.warning(f"⚠️ {i+1}番目のキャストで編集ボタンが見つかりません")
                                    logger.warning(f"Edit button not found for cast {i}")
                                    continue
                                
                                # ==========================================
                                # 【Step 6-2】人間らしい動きでボタンクリック
                                # ==========================================
                                st.write(f"🖱️ {i+1}番目のキャストの編集ボタンをクリック中...")
                                
                                # マウスを移動
                                await page.mouse.move(random.randint(100, 800), random.randint(100, 600))
                                await asyncio.sleep(random.uniform(0.3, 0.6))
                                
                                # ボタンをクリック
                                await edit_button.first.click()
                                await asyncio.sleep(random.uniform(1.5, 2.5))
                                
                                # ページロード待機
                                try:
                                    await page.wait_for_load_state("networkidle", timeout=15000)
                                except:
                                    await asyncio.sleep(random.uniform(1.0, 2.0))
                                
                                logger.info(f"Cast {i}: Edit screen loaded - {page.url}")

                                # ==========================================
                                # 【Step 6-3��詳細画面から情報を抽出
                                # ==========================================
                                st.write(f"📝 {i+1}番目のキャストの情報を取得中...")
                                
                                try:
                                    # 【修正】名前を取得
                                    raw_name = await page.input_value("#form_girl_name")
                                    
                                    # 【修正】命名規則を適用
                                    # C列の形式: 登録店舗名 + 全角スペース + 女の子の名前
                                    formatted_name = f"{shop_name}　{raw_name}"
                                    
                                    # A列の形式: shop_id + 3桁連番
                                    custom_id = f"{shop_id}{i+1:03d}"
                                    
                                    # 年齢
                                    age = await page.input_value("#form_girl_age")
                                    
                                    # 身長
                                    tall = await page.input_value("#form_girl_height")
                                    
                                    # バスト
                                    b = await page.input_value("#form_girl_sizeb")
                                    
                                    # ウエスト
                                    w = await page.input_value("#form_girl_sizew")
                                    
                                    # ヒップ
                                    h = await page.input_value("#form_girl_sizeh")
                                    
                                    # カップ
                                    try: 
                                        cup = await page.locator("#form_girl_cup").input_value()
                                    except: 
                                        cup = ""
                                    
                                    # PR文
                                    pr = await page.input_value("#form_girl_pr")
                                    
                                    logger.info(f"Cast {i}: Extracted - ID={custom_id}, name={formatted_name}, age={age}")

                                    # 画像取得（Drive API対応）
                                    img_path = ""
                                    try:
                                        img_src = await page.locator("div.girl_photo_box img").first.get_attribute("src")
                                        if img_src and img_src.startswith("http"):
                                            res_img = requests.get(img_src, timeout=10)
                                            if res_img.status_code == 200:
                                                img_path = _call_drive_api(
                                                    lambda: upload_to_drive_custom(
                                                        res_img.content, 
                                                        "キャスト情報_Images", 
                                                        f"{custom_id}.メイン画像.jpg"
                                                    )
                                                )
                                                st.write(f"📸 {i+1}番目の画像をアップロード完了")
                                    except Exception as e:
                                        logger.debug(f"Image fetch skip for cast {i} ({formatted_name}): {e}")

                                    # 【修正】データを追加（命名規則適用版）
                                    cast_data_list.append([
                                        custom_id,             # A列: shop_id + 3桁連番
                                        "",                    # B列: エリア
                                        formatted_name,        # C列: 店舗名 + 全角スペース + 名前
                                        age,                   # D列: 年齢
                                        tall,                  # E列: 身長
                                        b,                     # F列: バスト
                                        cup,                   # G列: カップ
                                        w,                     # H列: ウエスト
                                        h,                     # I列: ヒップ
                                        "",                    # J列: 系統
                                        "",                    # K列: キャッチ
                                        "",                    # L列: 女コメント
                                        pr,                    # M列: PR文
                                        "",                    # N列: 空
                                        "",                    # O列: 空
                                        shop_id,               # P列: 店舗ID
                                        img_path               # Q列: メイン画像
                                    ])
                                    
                                    st.success(f"✅ {i+1}番目のキャスト({formatted_name})のデータ取得完了")

                                except Exception as e:
                                    st.warning(f"⚠️ {i+1}番目のキャスト情報取得に失敗: {e}")
                                    logger.error(f"Cast {i}: Info extraction failed - {e}")
                                
                                # ==========================================
                                # 【Step 6-4】一覧ページに戻る
                                # ==========================================
                                st.write(f"🔙 {i+1}番目のキャスト処理後、一覧に戻ります...")
                                await asyncio.sleep(random.uniform(1.0, 2.0))
                                
                                # go_back() で戻る
                                await page.go_back()
                                await asyncio.sleep(random.uniform(1.5, 2.5))
                                
                                try:
                                    await page.wait_for_load_state("networkidle", timeout=15000)
                                except:
                                    await asyncio.sleep(random.uniform(1.0, 2.0))
                                
                                logger.info(f"Cast {i}: Returned to list - {page.url}")

                                # ==========================================
                                # 【Step 6-5】一覧のDOMが再度読み込まれるまで待機
                                # ==========================================
                                await asyncio.sleep(random.uniform(0.5, 1.5))

                            except Exception as e:
                                st.error(f"❌ {i+1}番目のキャスト処理でエラー: {e}")
                                logger.error(f"Cast {i} loop error: {e}")
                                
                                # エラー時もgo_back()を試す
                                try:
                                    await page.go_back()
                                    await asyncio.sleep(random.uniform(1.0, 2.0))
                                    await page.wait_for_load_state("networkidle", timeout=15000)
                                except:
                                    pass
                                
                                continue
                            
                            progress_bar.progress((i + 1) / cast_count)

                        # ==========================================
                        # 【完了】
                        # ==========================================
                        st.success(f"✅ スクレイピング完了: {len(cast_data_list)}名のデータを取得")
                        logger.info(f"Scraping completed: {len(cast_data_list)} cast records")
                        return {"status": "success", "data": cast_data_list, "debug_msg": f"{len(cast_data_list)}名のデータを取得"}

                    except Exception as e:
                        st.error(f"❌ スクレイピング処理でエラー: {e}")
                        logger.error(f"Tab5 scraping error: {e}")
                        return {"status": "error", "message": str(e)}
                    
                    finally:
                        await browser.close()

            # ==========================================
            # 【実行ボタン】
            # ==========================================
            if st.button("🔄 同期を実行", type="primary", key="derija_sync_exec"):
                with st.status("同期処理中...") as status:
                    st.write("⏳ スクレイピング処理を開始します...")
                    
                    # 【修正】shop_name を引数に追加
                    res = asyncio.run(run_fetch_derija_data(target_shop['ID'], target_shop['raw_pass'], target_shop['店舗名']))
                    
                    if res["status"] == "success":
                        if res["data"]:
                            st.write(f"📝 {len(res['data'])} 名のデータを取得しました")
                            st.write("📤 スプレッドシートへ追記中...")
                            
                            # スプレッドシート更新
                            worksheet_cast = _call_sheets_api(
                                lambda: spreadsheet.worksheet("キャスト情報")
                            )
                            _call_sheets_api(
                                lambda: worksheet_cast.append_rows(res["data"])
                            )
                            
                            st.success(f"✅ {len(res['data'])} 名同期完了")
                            status.update(label="✅ 完了", state="complete")
                            
                            # 【デバッグ表示】命名規則確認
                            st.write("### 📋 書き込まれたデータプレビュー")
                            st.dataframe(
                                pd.DataFrame(
                                    res["data"], 
                                    columns=[
                                        "ID", "エリア", "名前", "年齢", "身長", "バスト", "カップ", 
                                        "ウエスト", "ヒップ", "系統", "キャッチ", "女コメント", 
                                        "PR文", "空1", "空2", "店舗ID", "メイン画像"
                                    ]
                                )
                            )
                        else:
                            st.warning(f"⚠️ 取得失敗: {res.get('debug_msg')}")
                            status.update(label="⚠️ データなし", state="error")
                    else:
                        st.error(f"❌ エラー: {res.get('message')}")
                        status.update(label="❌ エラー", state="error")
        
        else:
            st.error("❌ デリじゃ店舗が見つかりません")
    
    except Exception as e:
        st.error(f"❌ システムエラー: {e}")
        logger.error(f"Tab5 system error: {e}")
