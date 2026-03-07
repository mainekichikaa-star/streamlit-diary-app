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

async def run_yoyaku_automation(s_id, s_pass):
    async with async_playwright() as p:
        # 人間味を出すため、スローモーション設定(ms)を入れることも可能
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--lang=ja-JP'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = await context.new_page()
        
        try:
            # 1. ランキングデリログイン
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", str(s_id).strip())
            await asyncio.sleep(1) # 入力の間の「タメ」
            await page.fill("#form_password", str(s_pass).strip())
            await asyncio.sleep(1)
            await page.click("#form_submit")
            await page.wait_for_url("**/admin/top/**", timeout=15000)
            st.info("✅ ランキングデリ ログイン完了")

            # 2. 「予約管理」を別タブで開く
            async with context.expect_page() as new_page_info:
                await page.locator("a.web_link").click()
            
            yoyaku_page = await new_page_info.value
            await yoyaku_page.wait_for_load_state()
            st.info("🔗 予約管理画面へ遷移しました")
            await asyncio.sleep(2) # 読み込み待ち（人間らしい間隔）

            # 3. 「各種設定」をクリックしてメニューを展開
            # メニューが閉じている可能性を考慮してクリック
            setting_menu = yoyaku_page.locator(".listItem.setting .menuTxt")
            await setting_menu.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await setting_menu.click()
            await asyncio.sleep(1)

            # 4. 「予約設定」をクリック
            # セレクターはHTMLに基づき、予約設定のリンクを指定
            await yoyaku_page.locator("a.acListTxt", has_text="予約設定").first.click()
            await yoyaku_page.wait_for_load_state()
            st.info("⚙️ 予約設定ページを開きました")
            await asyncio.sleep(2)

            # --- ここから人間らしい設定操作 ---

            # 5. 「公開」を選択
            # label要素をクリックすることで、人間がラジオボタンを選んでいる動きを再現
            release_label = yoyaku_page.locator("label[for='release']")
            await release_label.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await release_label.click()
            st.write("・公開を選択")

            # 6. 「受付」を選択
            accept_label = yoyaku_page.locator("label[for='freeReserveAccept']")
            await accept_label.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await accept_label.click()
            st.write("・受付を選択")

            # 7. 保存ボタンをクリック
            save_btn = yoyaku_page.locator("button.saveBt", has_text="保存")
            await save_btn.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            
            # マウスをボタンの上に移動させてからクリック（人間らしさの強化）
            box = await save_btn.bounding_box()
            if box:
                await yoyaku_page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                await asyncio.sleep(0.5)
            
            await save_btn.click()
            st.info("💾 設定を保存しました")

            # 保存後の反映待ち
            await asyncio.sleep(3)
            
            return {"status": "success", "url": yoyaku_page.url}

        except Exception as e:
            # 失敗時は証拠を残す
            if 'yoyaku_page' in locals():
                await yoyaku_page.screenshot(path=f"yoyaku_error_{s_id}.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- UI ---
st.set_page_config(page_title="キャスト一括登録", layout="wide")
st.title("👸 キャスト一括登録システム")

tab1, tab2 = st.tabs(["🚀 通常登録", "🚉 駅ちかネット予約登録"])

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
