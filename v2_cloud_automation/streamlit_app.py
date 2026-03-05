import streamlit as st
import asyncio
import os
import subprocess
import requests
from playwright.async_api import async_playwright

@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

# 画像をURLからダウンロードする関数
def download_image(url, save_path):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        st.error(f"画像ダウンロード失敗: {e}")
        return False

async def run_automation(data):
    # 一時保存用のファイル名
    tmp_image = "temp_upload.jpg"
    
    # 1. 画像の事前準備 (URLからダウンロード)
    st.info(f"📸 画像をダウンロード中: {data['image_url']}")
    if not download_image(data['image_url'], tmp_image):
        return {"status": "error", "message": "画像の取得に失敗しました。URLを確認してください。"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP']) 
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 2. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await page.wait_for_load_state("networkidle")

            # 3. 新規登録画面へ
            st.info("📑 登録画面へ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")

            # 4. プロフィール入力
            st.info("✍️ プロフィールを入力中...")
            await page.fill("#form_name", data['name'])
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            await page.select_option("#form_cup", value=cup_map.get(data['cup'].upper(), "3"))
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            await page.fill("#form_catchcopy", data['ai_catchphrase'][:15])
            await page.fill("#form_comments", data['ai_description'])

            # 5. タグ選択
            st.info("🏷️ タグを選択中...")
            await page.locator('input[name="p_genre[1]"]').check()
            await page.locator('input[name="genre[1]"]').check()

            # 6. 登録実行
            st.info("💾 登録ボタンをクリック...")
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # 7. 画像アップロード
            st.info("🔍 登録完了を確認。画像をアップロードします...")
            success_locator = page.get_by_text("データを登録しました。")
            await success_locator.wait_for(state="visible", timeout=15000)
            
            # 画像編集ボタン(モーダル)をクリック
            # ページ上の「写真設定」などのボタン(data-target="con1")を探す
            upload_btn = page.locator('a[data-target="con1"]')
            await upload_btn.wait_for(state="visible")
            await upload_btn.click()
            
            # モーダル内のファイル選択
            # サイトによって input が複数ある場合があるため .first を使用
            st.info("📤 ファイルを送信中...")
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(tmp_image)
            
            # 保存処理を待つための待機（必要に応じて「保存」ボタンのクリックを追加）
            await asyncio.sleep(5) 
            
            st.success("✅ 画像のアップロードが完了しました。")
            await page.screenshot(path="final_result.png")
            return {"status": "success", "message": "すべて完了"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"エラー: {str(e)}"}
        finally:
            await browser.close()
            # 使い終わった一時ファイルを削除
            if os.path.exists(tmp_image):
                os.remove(tmp_image)

# --- Streamlit UI ---
st.title("👸 女の子一括登録 & 画像自動DL")

# テスト用の画像URL（適宜変更してください）
# ※Googleドライブの直リンクURLなど
default_img = "https://drive.google.com/file/d/1uF4r8coNfFkhTiB4aH2ztUWjNw33HrtW/view?usp=drive_link"

if st.button("🚀 画像URLテスト込みで実行"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "URLから画像を自動取得",
        "ai_description": "スプレッドシートのURLから画像を保存してアップロードするテストです。",
        "image_url": default_img  # ここにスプレッドシートのURLが入る想定
    }
    
    with st.status("自動処理中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="完了！", state="complete")
            st.image("final_result.png")
        else:
            status.update(label="失敗", state="error")
            st.error(res["message"])
