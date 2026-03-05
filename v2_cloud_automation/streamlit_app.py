import streamlit as st
import asyncio
import os
import subprocess
import requests
import re
from playwright.async_api import async_playwright

@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

# GoogleドライブのURLを直リンクに変換してダウンロードする関数
def download_google_drive_image(url, save_path):
    try:
        # URLからファイルIDを抽出
        match = re.search(r'd/([a-zA-Z0-9_-]+)', url)
        if not match:
            st.error("GoogleドライブのURLからIDを抽出できませんでした。")
            return False
        
        file_id = match.group(1)
        # 直リンクURLに変換
        direct_url = f'https://drive.google.com/uc?export=download&id={file_id}'
        
        response = requests.get(direct_url, timeout=15)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
        else:
            st.error(f"ダウンロード失敗 (Status: {response.status_code}) - 共有設定が「制限付き」になっていないか確認してください。")
            return False
    except Exception as e:
        st.error(f"画像取得エラー: {e}")
        return False

async def run_automation(data):
    tmp_image = "temp_girl_photo.jpg"
    
    # 1. 画像の事前準備
    st.info("📸 Googleドライブから画像をダウンロード中...")
    if not download_google_drive_image(data['image_url'], tmp_image):
        return {"status": "error", "message": "画像の取得に失敗しました。"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP']) 
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 2. ログイン処理
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
            st.info("✍️ プロフィール入力中...")
            await page.fill("#form_name", data['name'])
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            await page.select_option("#form_cup", value=cup_map.get(data['cup'].upper(), "3"))
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            await page.fill("#form_catchcopy", data['ai_catchphrase'][:15])
            await page.fill("#form_comments", data['ai_description'])

            # 5. タグ選択
            await page.locator('input[name="p_genre[1]"]').check()
            await page.locator('input[name="genre[1]"]').check()

            # 6. 登録実行
            st.info("💾 登録ボタンをクリック...")
            async with page.expect_navigation(timeout=60000):
                await page.click("#form_update-btn", force=True)

            # 7. 画像アップロード工程
            st.info("🔍 登録成功を確認。画像をアップロードします...")
            # 成功メッセージが表示されるのを待つ
            await page.get_by_text("データを登録しました。").wait_for(state="visible", timeout=15000)
            
            # 写真設定モーダルを開く
            await page.click('a[data-target="con1"]')
            
            # ファイルを選択
            st.info("📤 ファイルを選択中...")
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(tmp_image)
            
            # 8. アップロードボタンをクリック (修正箇所)
            st.info("🚀 アップロードボタンをクリック...")
            # エラー回避のため、文字指定ではなくクラス名で直接指定し、一番最初に見つかったものをクリック
            upload_btn = page.locator('button.upbtn').first
            await upload_btn.click()
            
            # 反映を待つ
            await asyncio.sleep(5) 
            
            st.success("✅ 全行程が完了しました！")
            await page.screenshot(path="final_result.png")
            return {"status": "success", "message": "画像反映まで完了"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"実行エラー: {str(e)}"}
        finally:
            await browser.close()
            # 一時ファイルの削除
            if os.path.exists(tmp_image):
                os.remove(tmp_image)

# --- Streamlit UI ---
st.title("👸 女の子一括登録（画像完全自動版）")
st.markdown("---")

# 共有用URLを入力（テスト用）
target_url = "https://drive.google.com/file/d/1uF4r8coNfFkhTiB4aH2ztUWjNw33HrtW/view?usp=drive_link"

if st.button("🚀 登録 ＆ 画像アップロードを実行"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "画像自動アップロードテスト",
        "ai_description": "Googleドライブの画像URLから直接アップロードするテストです。",
        "image_url": target_url
    }
    
    with st.status("自動処理中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="すべて成功！", state="complete")
            st.image("final_result.png", caption="最終結果スクリーンショット")
        else:
            status.update(label="エラー発生", state="error")
            st.error(res["message"])
            if os.path.exists("error_log.png"):
                st.image("error_log.png")
