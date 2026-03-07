import streamlit as st
import asyncio
import os
import subprocess
import gspread
import io
import sys
import pandas as pd
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
    idx_name, idx_tall, idx_bust, idx_cup, idx_waist, idx_hip, idx_age, idx_main_img = 2, 3, 4, 5, 6, 7, 8, 11
    idx_catch, idx_girl_comment, idx_shop_comment = 14, 15, 16 
    
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

import asyncio
from playwright.async_api import async_playwright
import streamlit as st

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
            await page.wait_for_url("**/admin/top/**", timeout=15000)
            st.info("✅ ランキングデリ ログイン完了")

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
            # 初期値設定（入会金はデフォルト空、指名料はデリから取れない場合を考慮して0）
            extra_fees = {"admission": "", "nomination": "0", "repeat": "0"}
            for i in range(1, 6):
                label = await page.locator(f"#form_course\\[1\\]\\[time{i}\\]").get_attribute("value") or ""
                val = await page.locator(f"#form_course\\[1\\]\\[charge{i}\\]").get_attribute("value") or ""
                
                # 入会金の判定（無料や0なら空、それ以外なら数字を抽出）
                if "入会金" in label:
                    clean_val = "".join(filter(str.isdigit, val))
                    if clean_val and clean_val != "0":
                        extra_fees["admission"] = clean_val
                
                # 指名料（通常）の判定
                if any(x in label for x in ["指名料", "ネット指名料", "指名", "写真指名料"]):
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
            
            st.info(f"📊 取得完了: プラン({len(course_data['prices'])}) / 入会金({extra_fees['admission'] or '無'}) / 指名料({extra_fees['nomination']})")

            # --- 3. 予約管理（駅ちかネット）へデータ反映 ---
            async with context.expect_page() as new_page_info:
                await page.locator("a.web_link").click()
            yoyaku_page = await new_page_info.value
            await yoyaku_page.wait_for_load_state()

            # 設定メニューを展開
            await yoyaku_page.locator(".listItem.setting .menuTxt").click()
            await asyncio.sleep(1)

            # 3-1. 予約設定（公開・受付・入会金）
            await yoyaku_page.locator("a.acListTxt", has_text="予約設定").first.click()
            await yoyaku_page.locator("label[for='release']").click()
            await yoyaku_page.locator("label[for='freeReserveAccept']").click()
            # 入会金の入力（空文字なら未入力、値があれば入力）
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

            # 3-5. チャット設定
            target_email = "isgroup0001@gmail.com"
            await yoyaku_page.locator("a.acListTxt", has_text="チャット設定").first.click()
            await yoyaku_page.locator("label[for='Release']").click()
            c_emails = await yoyaku_page.locator("input[type='email']").all_attribute_values("value")
            if target_email not in [e.strip() for e in c_emails if e]:
                await yoyaku_page.locator("button.js-mail_user_add_button").click()
                await yoyaku_page.locator("input[type='email']").last.fill(target_email)
            await yoyaku_page.locator("button.saveBt", has_text="保存").click()
            await asyncio.sleep(1)

            # 3-6. 予約通知設定
            await yoyaku_page.locator("a.acListTxt", has_text="予約通知").first.click()
            n_emails = await yoyaku_page.locator("input[type='email']").all_attribute_values("value")
            if target_email not in [e.strip() for e in n_emails if e]:
                await yoyaku_page.locator("button.js-mail_user_add_button").click()
                await yoyaku_page.locator("input[type='email']").last.fill(target_email)
            await yoyaku_page.locator("button[name='sms-mail-add']").click()
            await asyncio.sleep(1)

            # 3-7. 女の子設定（指名料一括反映）
            await yoyaku_page.locator("a.acListTxt", has_text="女の子").first.click()
            await yoyaku_page.wait_for_load_state()
            # 「女の子すべて」にチェック
            await yoyaku_page.locator("label[for='allGirls']").click()
            # デリ側から取得した指名料をセット
            await yoyaku_page.locator("#nomination-input").fill(extra_fees["nomination"])
            await yoyaku_page.locator("#repeat-nomination-input").fill(extra_fees["repeat"])
            # 一括保存ボタンをクリック
            await yoyaku_page.locator("button.js-bulk-form-btn").click()
            
            st.info(f"💾 同期完了 (入会金:{extra_fees['admission'] or '未設定'} / 指名:{extra_fees['nomination']} / 本指名:{extra_fees['repeat']})")
            await asyncio.sleep(2)
            return {"status": "success", "url": yoyaku_page.url}

        except Exception as e:
            if 'yoyaku_page' in locals(): await yoyaku_page.screenshot(path=f"error_{s_id}.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()
# --- UI ---
st.set_page_config(page_title="登録システム", layout="wide")
st.title("登録システム")

tab1, tab2 = st.tabs(["🚀 キャスト登録", "🚉 駅ちかネット予約登録"])

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
        
        data_shops = worksheet_shops.get_all_records()
        
        # 店舗ごとの未登録数をカウント
        shop_status = []
        for shop in data_shops:
            s_name = str(shop.get('登録店舗')).strip()
            s_id = str(shop.get('店舗ID')).strip()
            s_pass = str(shop.get('店舗PASSWORD')).strip()
            
            # この店舗に所属し、かつ「未登録」または空白の人数を出す
            unregistered_casts = [r for r in rows_info if str(r[12]).strip() == s_name and (len(r) < 14 or str(r[13]).strip() != "登録済")]
            
            if s_id and s_pass:
                shop_status.append({
                    "店舗名": s_name,
                    "ID": s_id,
                    "PW": "********",
                    "未登録数": len(unregistered_casts),
                    "raw_pass": s_pass,
                    "casts": unregistered_casts
                })

        # テーブル表示用のデータフレーム
        df_shops = pd.DataFrame(shop_status)
        
        # 実行対象の選択
        st.write("実行する店舗を選択してください:")
        selected_shops = []
        
        # 列形式でチェックボックスを並べる
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
                        
                        with st.status(f"【{shop['店舗名']}】{cast_name} さんの登録中...") as status:
                            res = asyncio.run(run_automation(cast, shop['ID'], shop['raw_pass'], sub_urls))
                            if res["status"] == "success":
                                # スプレッドシート上の行番号を特定して更新
                                # rows_infoは1行目(index 0)がデータなので、全体では index + 2
                                # 正確な行を特定するためにIDで検索
                                row_idx = next((i for i, r in enumerate(data_info) if str(r[0]).strip() == target_id), None)
                                if row_idx:
                                    worksheet_cast.update_cell(row_idx + 1, 14, "登録済")
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

    if st.button("🌐 ネット予約管理画面へログイン・設定開始", type="primary"):
        if not selected_yoyaku_shops:
            st.warning("店舗が選択されていません。")
        else:
            for shop in selected_yoyaku_shops:
                st.markdown(f"### 🏢 店舗: {shop['店舗名']} の予約管理を処理中...")
                
                async def run_yoyaku_automation(s_id, s_pass):
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--lang=ja-JP'])
                        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
                        page = await context.new_page()
                        
                        try:
                            # 1. まずはランキングデリにログイン
                            await page.goto("https://ranking-deli.jp/admin/login")
                            await page.fill("#form_email", str(s_id).strip())
                            await page.fill("#form_password", str(s_pass).strip())
                            await page.click("#form_submit")
                            await page.wait_for_url("**/admin/top/**", timeout=15000)

                            # 2. 「予約管理」リンクをクリックして新しいタブを開くのを待機
                            # context.expect_page() を使うことで、クリックで開いた別タブを捕捉
                            async with context.expect_page() as new_page_info:
                                # a.web_link が「予約管理」ボタン
                                await page.locator("a.web_link").click()
                            
                            yoyaku_page = await new_page_info.value
                            await yoyaku_page.wait_for_load_state()
                            
                            # 3. 駅ちかネット予約管理画面 (yoyaku_page) での操作
                            # ここにログイン後の登録ロジックを記述します
                            current_url = yoyaku_page.url
                            st.info(f"🔗 予約管理画面に到達: {current_url}")
                            
                            # 例: キャスト一覧ページへ移動するなど
                            # await yoyaku_page.goto("https://e-yoyaku.jp/admin/cast/") 
                            
                            # --- ここに具体的な入力・登録処理を完コピで追加 ---
                            
                            await asyncio.sleep(3) # 確認用
                            return {"status": "success", "url": current_url}

                        except Exception as e:
                            return {"status": "error", "message": str(e)}
                        finally:
                            await browser.close()

                # 実行
                with st.status(f"{shop['店舗名']} のセッションを確立中...") as status:
                    res = asyncio.run(run_yoyaku_automation(shop['ID'], shop['raw_pass']))
                    if res["status"] == "success":
                        status.update(label=f"✅ {shop['店舗名']} ログイン成功", state="complete")
                        st.success(f"予約管理画面 ({res['url']}) へのアクセスが完了しました。")
                    else:
                        st.error(f"エラー: {res['message']}")
                        status.update(label="❌ 失敗", state="error")
