import streamlit as st
import asyncio
import os
import subprocess
import gspread
import io
import sys
import random
import string
import requests
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from playwright.async_api import async_playwright
from playwright.async_api import async_playwright

# --- 設定 ---
SPREADSHEET_ID = "1Xodf14PC3urWIbu49aqMImH6REAlYenOr9YW2WvNYTI"
SCOPE = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# ==========================================
# 【修正1】変数をアプリ起動時に必ず初期化する
# これにより 302行目の NameError が物理的に発生しなくなります
# ==========================================
if 'shop_status' not in st.session_state:
    st.session_state['shop_status'] = []
shop_status = st.session_state['shop_status']

LOCAL_PW_PATH = os.path.join(os.getcwd(), "pw-browsers")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = LOCAL_PW_PATH

# --- ヘルパー関数 ---
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
    # --- 新構成(Q列まで)に基づいたインデックス設定 ---
    # A:0, B:1, C:2(名前), D:3(年齢), E:4(身長), F:5(バスト), G:6(カップ), H:7(ウエスト), I:8(ヒップ)
    # K:10(キャッチ), L:11(娘コメ), M:12(店コメ), Q:16(メイン画像)
    idx_name = 2         # C列: 名前 (スプレッドシート上の名前を使用)
    idx_age = 3          # D列: 年齢
    idx_tall = 4         # E列: 身長
    idx_bust = 5         # F列: バスト
    idx_cup = 6          # G列: カップ数
    idx_waist = 7        # H列: ウエスト
    idx_hip = 8          # I列: ヒップ
    idx_catch = 10       # K列: キャッチコピー
    idx_girl_comment = 11 # L列: 女の子コメント
    idx_shop_comment = 12 # M列: 店舗コメント
    idx_main_img = 16    # Q列: メイン画像
    
    if not os.path.exists(LOCAL_PW_PATH):
        try: subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        except: pass

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

            # フィールド入力
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

# 「駅ちか既存店コピー」の後の " を閉じました
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🚀 駅ちかキャスト自動登録", 
    "🚉 駅ちかネット予約自動登録", 
    "📋 駅ちか既存店コピー", 
    "🚀 デリじゃキャスト自動登録", 
    "📋 デリじゃ既存店コピー"
])

# ==========================================
# 【修正2】スプレッドシートの読み込みを全タブ共通で行う
# ==========================================
try:
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
    gs_client = gspread.authorize(creds)
    spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
    
    worksheet_cast = spreadsheet.worksheet("キャスト情報")
    worksheet_shops = spreadsheet.worksheet("シート3")
    
    data_info = worksheet_cast.get_all_values()
    rows_info = data_info[1:]
    data_shops = worksheet_shops.get_all_records()
    
    # shop_status を作成（駅ちか・デリじゃ両方対応）
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

with tab1:
    st.subheader("店舗別・未登録キャスト状況")
    
    try:
        # データ取得
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
        gs_client = gspread.authorize(creds)
        spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
        
        worksheet_cast = spreadsheet.worksheet("キャスト情報")
        worksheet_images = spreadsheet.worksheet("キャスト画像")
        worksheet_shops = spreadsheet.worksheet("シート3")

        data_info = worksheet_cast.get_all_values()
        headers_info = data_info[0]
        rows_info = data_info[1:]
        
        data_images = worksheet_images.get_all_values()
        rows_images = data_images[1:]
        
        #シート3をレコード形式で取得
        data_shops = worksheet_shops.get_all_records()
        
        # 店舗ごとの未登録数をカウント
        shop_status = []
        for shop in data_shops:
            #シート3の各列を取得
            s_name = str(shop.get('登録店舗')).strip()
            s_id = str(shop.get('店舗ID')).strip()
            s_pass = str(shop.get('店舗PASSWORD')).strip()
            
            # --- 判定ロジック ---
            # キャスト情報のO列(index 14)と、シート3の「店舗ID」を照合
            unregistered_casts = []
            for r in rows_info:
                if len(r) > 14:
                    # O列(14): 登録店舗（ここに入っている店舗IDを確認）
                    cast_shop_id = str(r[14]).strip()
                    # P列(15): 登録ステータス（「登録済」以外、または空白を対象）
                    status_field = str(r[15]).strip() if len(r) > 15 else ""
                    
                    # キャスト側のO列とシート3の店舗IDが一致し、かつ未登録の場合
                    if cast_shop_id == s_id and status_field != "登録済":
                        unregistered_casts.append(r)
            
            if s_id and s_pass:
                shop_status.append({
                    "店舗名": s_name,      # 表示用は「登録店舗」名
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
                    # ボタン表示は「店舗名 (人数)」
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
                        cast_name = cast[2] # C列の名前をそのまま使用
                        sub_urls = [img_row[2] for img_row in rows_images if str(img_row[1]).strip() == target_id]
                        
                        with st.status(f"【{shop['店舗名']}】{cast_name} さんの登録中...") as status:
                            # 自動化処理の実行
                            res = asyncio.run(run_automation(cast, shop['ID'], shop['raw_pass'], sub_urls))
                            
                            if res["status"] == "success":
                                # スプレッドシートのP列(16列目)を「登録済」に更新
                                row_idx = next((i for i, r in enumerate(data_info) if str(r[0]).strip() == target_id), None)
                                if row_idx:
                                    worksheet_cast.update_cell(row_idx + 1, 16, "登録済")
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
    
    # Tab 1で作成した shop_status を利用して店舗選択を表示
    st.write("ネット予約設定を行う店舗を選択してください:")
    selected_yoyaku_shops = []
    
    y_cols = st.columns(3)
    for idx, shop in enumerate(shop_status):
        with y_cols[idx % 3]:
            # Tab 2専用のキーでチェックボックスを作成
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
                
                # --- 自動化メイン関数 (最新の判定ロジックを保持) ---
                async def run_yoyaku_automation(s_id, s_pass):
                    async with async_playwright() as p:
                        # ブラウザ起動（日本語設定）
                        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--lang=ja-JP'])
                        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
                        page = await context.new_page()
                        
                        try:
                            # --- 1. ランキングデリ ログイン ---
                            await page.goto("https://ranking-deli.jp/admin/login")
                            await page.fill("#form_email", str(s_id).strip())
                            await page.fill("#form_password", str(s_pass).strip())
                            await page.click("#form_submit")
                            await page.wait_for_load_state("networkidle")

                            # --- 2. ランキングデリから各データを取得 ---
                            await page.goto("https://ranking-deli.jp/admin/shopcharges/")
                            
                            # 2-1. メインプラン情報 (course[0])
                            course_data = {"title": await page.locator("#form_course\\[0\\]\\[course_name\\]").get_attribute("value"), "prices": []}
                            for i in range(1, 6):
                                t_val = await page.locator(f"#form_course\\[0\\]\\[time{i}\\]").get_attribute("value")
                                p_val = await page.locator(f"#form_course\\[0\\]\\[charge{i}\\]").get_attribute("value")
                                if t_val and p_val:
                                    course_data["prices"].append({"time": t_val, "price": p_val})

                            # 2-2. その他料金 (course[1]) から 入会金・指名料 を取得
                            extra_fees = {"admission": "", "nomination": "0", "repeat": "0"}
                            for i in range(1, 6):
                                label = await page.locator(f"#form_course\\[1\\]\\[time{i}\\]").get_attribute("value") or ""
                                val = await page.locator(f"#form_course\\[1\\]\\[charge{i}\\]").get_attribute("value") or ""
                                
                                # 入会金の判定
                                if "入会金" in label:
                                    clean_val = "".join(filter(str.isdigit, val))
                                    if clean_val and clean_val != "0":
                                        extra_fees["admission"] = clean_val
                                
                                # 指名料（通常）の判定
                                if any(x in label for x in ["指名料", "ネット指名料", "指名", "写真指名料", "写真指名"]):
                                    extra_fees["nomination"] = "".join(filter(str.isdigit, val)) or "0"

                                # 本指名の判定
                                if any(x in label for x in ["本指名", "本指名料"]):
                                    extra_fees["repeat"] = "".join(filter(str.isdigit, val)) or "0"

                            # 2-3. オプション情報取得
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

                            # 2-4. 交通費情報取得
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

                            # --- 3. 予約管理（駅ちかネット）へデータ反映 ---
                            async with context.expect_page() as new_page_info:
                                await page.locator("a.web_link").click()
                            yoyaku_page = await new_page_info.value
                            await yoyaku_page.wait_for_load_state()

                            # 設定メニュー展開
                            await yoyaku_page.locator(".listItem.setting .menuTxt").click()
                            await asyncio.sleep(1)

                            # 3-1. 予約設定（公開・受付・入会金）
                            await yoyaku_page.locator("a.acListTxt", has_text="予約設定").first.click()
                            await yoyaku_page.locator("label[for='release']").click()
                            await yoyaku_page.locator("label[for='freeReserveAccept']").click()
                            await yoyaku_page.locator("input[name='admission_fee']").fill(extra_fees["admission"])
                            await yoyaku_page.locator("button.saveBt", has_text="保存").click()
                            await asyncio.sleep(1)

                            # 3-2. 料金コース同期
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

                            # 3-3. オプション同期
                            await yoyaku_page.locator("a.acListTxt", has_text="オプション").first.click()
                            for idx, opt in enumerate(option_data):
                                n_in, f_in = yoyaku_page.locator(f"input[name='options[{idx}][name]']"), yoyaku_page.locator(f"input[name='options[{idx}][fee]']")
                                if await n_in.count() > 0:
                                    await n_in.fill(opt["name"]); await f_in.fill(str(opt["fee"]))
                                else: break
                            await yoyaku_page.locator("button.js-save-btn").click()
                            await asyncio.sleep(1)

                            # 3-4. 交通費同期
                            await yoyaku_page.locator("a.acListTxt", has_text="交通費").first.click()
                            for idx, tf in enumerate(transport_data):
                                a_in, f_in = yoyaku_page.locator(f"input[name='carfares[{idx}][area_name]']"), yoyaku_page.locator(f"input[name='carfares[{idx}][fee]']")
                                if await a_in.count() > 0:
                                    await a_in.fill(tf["area"]); await f_in.fill(str(tf["fee"]))
                                else: break
                            await yoyaku_page.locator("button.js-save-btn").click()
                            await asyncio.sleep(1)

                            # 3-5. チャット設定 & 3-6. 予約通知設定
                            target_email = "isgroup0001@gmail.com"
                            for menu_name in ["チャット設定", "予約通知"]:
                                await yoyaku_page.locator("a.acListTxt", has_text=menu_name).first.click()
                                if menu_name == "チャット設定":
                                    await yoyaku_page.locator("label[for='Release']").click()
                                exs_emails = await yoyaku_page.locator("input[type='email']").all_attribute_values("value")
                                if target_email not in [e.strip() for e in exs_emails if e]:
                                    await yoyaku_page.locator("button.js-mail_user_add_button").click()
                                    await yoyaku_page.locator("input[type='email']").last.fill(target_email)
                                save_btn_sel = "button[name='sms-mail-add']" if menu_name == "予約通知" else "button.saveBt"
                                await yoyaku_page.locator(save_btn_sel).click()
                                await asyncio.sleep(1)

                            # 3-7. 女の子設定（指名料一括反映）
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

                # --- 実行 ---
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

    # 店舗リストの作成
    shop_names = [s['店舗名'] for s in shop_status] if 'shop_status' in locals() else []

    if shop_names:
        selected_sync_shop_name = st.selectbox("情報を取得する店舗を選択", shop_names, key="sync_shop_select")
        target_shop = next(s for s in shop_status if s['店舗名'] == selected_sync_shop_name)

        # --- ドライブ用ヘルパー ---
        def upload_to_drive_custom(file_content, folder_name, file_name):
            drive_service = get_drive_service()
            # フォルダを探す
            query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            folders = drive_service.files().list(q=query, fields="files(id)").execute().get('files', [])
            
            if not folders:
                folder_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
                folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
                folder_id = folder.get('id')
            else:
                folder_id = folders[0]['id']
                
            file_metadata = {'name': file_name, 'parents': [folder_id]}
            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype='image/jpeg')
            drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return f"{folder_name}/{file_name}"

        # --- 同期処理用関数 ---
        async def run_fetch_cast_data(shop_id, shop_pass, shop_name):
            if not os.path.exists(LOCAL_PW_PATH):
                try:
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                except:
                    pass

            cast_data_list = []
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True, 
                    args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
                )
                context = await browser.new_context(locale="ja-JP")
                page = await context.new_page()

                try:
                    # 1. ログイン
                    await page.goto("https://ranking-deli.jp/admin/login")
                    await page.fill("#form_email", str(shop_id).strip())
                    await page.fill("#form_password", str(shop_pass).strip())
                    await page.click("#form_submit")
                    await page.wait_for_load_state("networkidle")
                    
                    # 2. 女の子一覧ページへ
                    await page.goto("https://ranking-deli.jp/admin/girls/")
                    
                    # 3. 編集URL取得
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

                        # データ抽出
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

                        # --- 画像1の取得 ---
                        main_image_path_in_sheet = ""
                        try:
                            # セレクタから画像1の大画像URLを取得
                            img_src = await page.locator("#image-box1 .img_b img").get_attribute("src")
                            if img_src:
                                response = requests.get(img_src)
                                if response.status_code == 200:
                                    rand_str = ''.join(random.choices(string.digits, k=6))
                                    custom_id = f"{str(shop_id).strip()}{(i + 1):02d}"
                                    filename = f"{custom_id}.メイン画像.{rand_str}.jpg"
                                    # ドライブへアップロード
                                    main_image_path_in_sheet = upload_to_drive_custom(response.content, "キャスト情報_Images", filename)
                        except Exception as e:
                            st.warning(f"画像取得スキップ ({site_girl_name}): {e}")

                        # --- IDの生成 (店舗ID + 連番2桁) ---
                        custom_id = f"{str(shop_id).strip()}{(i + 1):02d}"

                        # --- 指定された列順に構成 (Q列まで拡張) ---
                        row = [
                            custom_id,                  # A: ID
                            "",                         # B: エリア
                            f"{shop_name} {site_girl_name}", # C: 店舗名 名前
                            age,                        # D: 年齢
                            tall,                       # E: 身長
                            bust,                       # F: バスト
                            cup,                        # G: カップ数
                            waist,                      # H: ウエスト
                            hip,                        # I: ヒップ
                            "",                         # J: 系統
                            catch,                      # K: キャッチコピー
                            girl_comment,               # L: 女の子コメント
                            shop_comment,               # M: 店舗コメント
                            "",                         # N: (空)
                            "",                         # O: (空)
                            "",                         # P: (空)
                            main_image_path_in_sheet    # Q: メイン画像
                        ]
                        cast_data_list.append(row)
                        progress_bar.progress((i + 1) / len(edit_links))

                    return {"status": "success", "data": cast_data_list}
                except Exception as e:
                    return {"status": "error", "message": str(e)}
                finally:
                    await browser.close()

        # --- 実行ボタン ---
        if st.button("🔄 同期を実行（スプレッドシートへ追記）", type="primary", key="exec_sync_btn"):
            with st.status("同期処理を実行中...") as status:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(run_fetch_cast_data(target_shop['ID'], target_shop['raw_pass'], target_shop['店舗名']))
                    
                    if result["status"] == "success":
                        if result["data"]:
                            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
                            gs_client = gspread.authorize(creds)
                            worksheet = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
                            
                            worksheet.append_rows(result["data"])
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


# --- tab4: デリじゃ自動登録 (日記コード流・完全再現版) ---
with tab4:
    st.subheader("🍓 デリじゃ キャスト自動登録 (安定版)")

    @st.cache_data(ttl=300)
    def fetch_data_v36():
        try:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
            gc = gspread.authorize(creds)
            ss = gc.open_by_key(SPREADSHEET_ID)
            return ss.worksheet("キャスト情報").get_all_values(), ss.worksheet("シート3").get_all_records()
        except Exception as e: return None, str(e)

    raw_cast_data, shop_records = fetch_data_v36()

    if raw_cast_data:
        rows_info = raw_cast_data[1:]
        dj_shops = []
        for s in shop_records:
            s_name = str(s.get('登録店舗', '')).strip()
            if any(k in s_name for k in ["デリじゃ", "デリジャ", "でりじゃ"]):
                sid, spass = str(s.get('店舗ID', '')).strip(), str(s.get('店舗PASSWORD', '')).strip()
                unreg = [r for r in rows_info if len(r) > 14 and str(r[14]).strip() == sid and str(r[15]).strip() != "登録済"]
                if sid and spass: dj_shops.append({"店舗名": s_name, "ID": sid, "PASS": spass, "casts": unreg})

        async def run_derija_v36(cast, sid, spass):
            import subprocess
            import sys
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            except: pass

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                target_name = str(cast[2]).strip()
                debug_path = f"final_debug_{sid}.png"

                try:
                    # 1. ログイン (日記コード同様、入力後即ログイン)
                    await page.goto("https://deli-fuzoku.jp/entry/", wait_until="domcontentloaded")
                    await page.fill("#form_username", sid)
                    await page.fill("#form_password", spass)
                    await asyncio.sleep(1)
                    await page.click("button.loginBtn")
                    await page.wait_for_load_state("networkidle")

                    # 2. メニューリンクのクリック (日記コードの time.sleep(random.uniform(1.5, 2.5)) を再現)
                    await asyncio.sleep(random.uniform(1.5, 2.5))
                    add_link = page.locator('a:has-text("在籍の追加")')
                    await add_link.scroll_into_view_if_needed()
                    # 日記コード流: execute_script("arguments[0].click();", menu_link)
                    await page.evaluate('(el) => el.click()', await add_link.element_handle())
                    
                    # 3. フォーム待機と入力 (日記コード流の dispatchEvent)
                    await page.wait_for_selector("#form_girl_name", state="attached", timeout=60000)
                    await asyncio.sleep(2)

                    await page.evaluate(f'''() => {{
                        const setData = (id, val) => {{
                            const el = document.getElementById(id);
                            if(!el) return;
                            el.value = val;
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }};
                        setData("form_girl_name", "{target_name}");
                        setData("form_girl_age", "{cast[3]}");
                        setData("form_girl_height", "{cast[4]}");
                        setData("form_girl_sizeb", "{cast[5]}");
                        setData("form_girl_sizew", "{cast[7]}");
                        setData("form_girl_sizeh", "{cast[8]}");
                        const pr = document.getElementById("form_girl_pr");
                        if(pr) {{
                            pr.value = `{cast[12]}`;
                            pr.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        }}
                    }}''')

                    # 4. 画像アップロード (日記コード流: file_input.send_keys の後の time.sleep(7) を再現)
                    img_name = cast[16]
                    if img_name:
                        tmp = f"up_{sid}.jpg"
                        if download_by_filename(img_name, tmp):
                            await page.locator("#form_file_girl_photo1").set_input_files(tmp)
                            st.write("📸 画像アップロード中（7秒待機）...")
                            await asyncio.sleep(7) 
                            if os.path.exists(tmp): os.remove(tmp)

                    # 5. 送信 (日記コード流: scrollIntoView してから random待機、そしてクリック)
                    st.write("🚀 登録ボタン実行中...")
                    await page.evaluate('''() => {
                        const submit_btn = document.getElementById('form_register_btn') || 
                                         document.querySelector('label[for="form_submit_btn"]');
                        if(submit_btn) {
                            submit_btn.scrollIntoView({block: 'center'});
                        }
                    }''')
                    
                    # 日記コードの time.sleep(random.uniform(1.0, 3.0))
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    
                    # 物理クリックとナビゲーション待ちを分離 (Page.contentエラー回避)
                    await page.evaluate('''() => {
                        const submit_btn = document.getElementById('form_register_btn') || 
                                         document.querySelector('label[for="form_submit_btn"]');
                        if(submit_btn) {
                            submit_btn.click();
                        } else if(typeof func_submit === 'function') {
                            func_submit();
                        }
                    }''')

                    # 6. 完了判定 (日記コード流: URLからeditが消えるのを粘り強く待つ)
                    success = False
                    for i in range(20):
                        await asyncio.sleep(3)
                        # URLが変わったか、あるいは「完了」の文字が出たか
                        if "edit" not in page.url or "girl_list.php" in page.url:
                            success = True
                            break
                        
                        # ページが遷移中の場合はcontent取得をスキップして待つ
                        try:
                            content = await page.content()
                            if "完了" in content or "登録済" in content:
                                success = True
                                break
                        except:
                            pass
                    
                    if success:
                        # 最終確認
                        await page.goto("https://deli-fuzoku.jp/entry/girl_list.php", wait_until="networkidle")
                        if target_name in await page.content():
                            return {"status": "success"}

                    raise Exception("送信後の完了確認ができませんでした（タイムアウト）。")

                except Exception as e:
                    await page.screenshot(path=debug_path, full_page=True)
                    return {"status": "error", "message": str(e), "screenshot": debug_path}
                finally:
                    await browser.close()

        # UI
        selected = []
        if dj_shops:
            cols = st.columns(3)
            for i, s in enumerate(dj_shops):
                with cols[i % 3]:
                    if st.checkbox(f"{s['店舗名']} ({len(s['casts'])}名)", key=f"dj_v36_cb_{i}"):
                        selected.append(s)

            if st.button("🚀 デリじゃ一括登録開始", type="primary"):
                ws_w = None
                try:
                    creds_w = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
                    ws_w = gspread.authorize(creds_w).open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
                except: pass

                for shop in selected:
                    for cast in shop['casts']:
                        with st.status(f"{cast[2]} 登録中..."):
                            res = asyncio.run(run_derija_v36(cast, shop['ID'], shop['PASS']))
                            if res["status"] == "success":
                                st.success(f"✅ {cast[2]} 完了！")
                                if ws_w:
                                    row_idx = next((i for i, r in enumerate(raw_cast_data) if r[0] == cast[0]), None)
                                    if row_idx: ws_w.update_cell(row_idx + 1, 16, "登録済")
                            else:
                                st.error(f"❌ {cast[2]} 失敗: {res['message']}")
                                if "screenshot" in res: st.image(res["screenshot"])
        
# --- tab5: デリじゃ既存店コピー (Web → シート) ---
with tab5:
    st.subheader("📥 デリじゃ キャスト情報の同期")
    st.info("デリじゃ管理画面からキャスト情報を取得し、スプレッドシートへ追記します。")

    try:
        #シート3から「デリじゃ」店舗のみを抽出
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
        gs_client = gspread.authorize(creds)
        spreadsheet = gs_client.open_by_key(SPREADSHEET_ID)
        worksheet_shops = spreadsheet.worksheet("ID/Password")
        data_shops = worksheet_shops.get_all_records()

        derija_keywords = ["デリじゃ", "デリジャ", "でりじゃ"]
        derija_sync_shops = [
            {"店舗名": str(s.get('登録店舗')).strip(), "ID": str(s.get('店舗ID')).strip(), "raw_pass": str(s.get('店舗PASSWORD')).strip()}
            for s in data_shops if any(k in str(s.get('登録店舗')).strip() for k in derija_keywords)
        ]

        if derija_sync_shops:
            selected_name = st.selectbox("情報を取得するデリじゃ店舗を選択", [s['店舗名'] for s in derija_sync_shops], key="derija_sync_sel")
            target_shop = next(s for s in derija_sync_shops if s['店舗名'] == selected_name)

            # --- デリじゃ専用データ取得ロジック ---
            async def run_fetch_derija_data(shop_id, shop_pass, shop_name):
                cast_data_list = []
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
                    context = await browser.new_context(locale="ja-JP")
                    page = await context.new_page()
                    
                    try:
                        # 1. ログイン
                        await page.goto("https://deli-fuzoku.jp/entry/")
                        await page.fill('input[name="loginID"]', shop_id)
                        await page.fill('input[name="password"]', shop_pass)
                        await page.click('input[value="ログイン"]')
                        await page.wait_for_load_state("networkidle")

                        # 2. 在籍一覧ページへ移動
                        await page.goto("https://deli-fuzoku.jp/entry/girl_list.php")
                        
                        # 3. 編集ボタン（aタグ）のURLを全取得
                        edit_links = await page.locator('a:has-text("編集")').evaluate_all("nodes => nodes.map(n => n.href)")
                        
                        if not edit_links:
                            return {"status": "success", "data": []}

                        st.write(f"🔍 {len(edit_links)} 名のキャストを検出しました。")
                        progress_bar = st.progress(0)

                        for i, link in enumerate(edit_links):
                            await page.goto(link)
                            await asyncio.sleep(1)

                            # データ抽出 (デリじゃのID体系に合わせたセレクタ)
                            name = await page.input_value("#form_girl_name")
                            age = await page.input_value("#form_girl_age")
                            tall = await page.input_value("#form_girl_height")
                            bust = await page.input_value("#form_girl_sizeb")
                            waist = await page.input_value("#form_girl_sizew")
                            hip = await page.input_value("#form_girl_sizeh")
                            
                            try:
                                cup_full = await page.locator("#form_girl_cup option:checked").text_content()
                                cup = cup_full.strip() if cup_full else ""
                            except: cup = ""

                            shop_comment = await page.input_value("#form_girl_pr")
                            
                            # 画像1のURL取得
                            main_img_path = ""
                            try:
                                img_el = page.locator("img[src*='girl_photo']").first
                                if await img_el.count() > 0:
                                    img_src = await img_el.get_attribute("src")
                                    response = requests.get(img_src)
                                    if response.status_code == 200:
                                        rand_str = ''.join(random.choices(string.digits, k=6))
                                        filename = f"DJ_{shop_id}_{i+1}.{rand_str}.jpg"
                                        # 既存のヘルパー関数 upload_to_drive_custom を流用
                                        main_img_path = upload_to_drive_custom(response.content, "キャスト情報_Images", filename)
                            except: pass

                            # スプレッドシート形式 (A-Q列)
                            row = [
                                f"DJ{shop_id}{i+1:02d}", # A: ID
                                "",                      # B: エリア
                                name,                    # C: 名前
                                age,                     # D: 年齢
                                tall,                    # E: 身長
                                bust,                    # F: バスト
                                cup,                     # G: カップ
                                waist,                   # H: ウエスト
                                hip,                     # I: ヒップ
                                "",                      # J: 系統
                                "",                      # K: キャッチ
                                "",                      # L: 娘コメ
                                shop_comment,            # M: 店コメ
                                "", "", shop_id,         # N, O, P: 店舗ID
                                main_img_path            # Q: メイン画像
                            ]
                            cast_data_list.append(row)
                            progress_bar.progress((i + 1) / len(edit_links))

                        return {"status": "success", "data": cast_data_list}
                    except Exception as e:
                        return {"status": "error", "message": str(e)}
                    finally:
                        await browser.close()

            if st.button("🔄 デリじゃ情報をシートへ同期", type="primary"):
                with st.status("データ取得中...") as status:
                    res = asyncio.run(run_fetch_derija_data(target_shop['ID'], target_shop['raw_pass'], target_shop['店舗名']))
                    if res["status"] == "success" and res["data"]:
                        worksheet_cast = spreadsheet.worksheet("キャスト情報")
                        worksheet_cast.append_rows(res["data"])
                        st.success(f"✅ {len(res['data'])} 名の情報をシートへ追加しました。")
                        status.update(label="同期完了", state="complete")
                    else:
                        st.error(f"失敗: {res.get('message', 'データなし')}")
                        status.update(label="エラー", state="error")
        else:
            st.warning("シート3にデリじゃ店舗が見つかりません。")
    except Exception as e:
        st.error(f"エラー: {e}")
