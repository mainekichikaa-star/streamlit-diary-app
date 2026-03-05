import streamlit as st
import asyncio
import random
import os
import subprocess
import requests
from playwright.async_api import async_playwright
from gemini_service import GroqService # 以前のファイルを同階層に置く前提

# --- 環境構築 (Streamlit Cloud上でPlaywrightを動かすため) ---
@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

# --- 人間らしい待機 ---
async def human_delay(min_sec=3, max_sec=7):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# --- メインの自動化ロジック ---
async def run_automation(data):
    async with async_playwright() as p:
        # ブラウザ起動 (人間らしい設定)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()

        try:
            # 1. ログイン画面
            await page.goto("https://ranking-deli.jp/admin/login")
            await human_delay(2, 4)
            await page.type("#form_email", data['portal_id'], delay=random.randint(100, 250))
            await page.type("#form_password", data['portal_pass'], delay=random.randint(100, 250))
            await page.click("#form_submit")
            await human_delay(4, 6)

            # 2. メニュー遷移 (人間と同じクリック)
            await page.get_by_text("女の子一覧").first.click()
            await human_delay(3, 5)
            await page.get_by_text("女の子の新規登録").first.click()
            await human_delay(4, 7)

            # 3. プロフィール入力
            await page.type("#form_name", data['name'], delay=150)
            await page.select_option("#form_cup", data['cup'])
            await page.type("#form_age", str(data['age']), delay=200)
            await page.type("#form_tall", str(data['height']), delay=200)
            
            # AI紹介文を入力 (既存のGroqServiceで生成した文を使用)
            await page.fill("#form_comments", data['ai_description'])
            await page.fill("#form_catchcopy", data['ai_catchphrase'])

            # タグのチェック (渡されたIDリストをループ)
            for tag_id in data.get('tag_ids', []):
                selector = f"#{tag_id}"
                if await page.query_selector(selector):
                    await page.check(selector)
                    await asyncio.sleep(0.5)

            # 登録実行（一次保存）
            await page.click("#form_update-btn")
            await human_delay(6, 10)

            # 4. 画像アップロード
            if data.get('image_url'):
                # 画像を一時的にダウンロード
                img_data = requests.get(data['image_url']).content
                with open("temp_cast.jpg", "wb") as f:
                    f.write(img_data)
                
                # ファイルを選択
                await page.set_input_files("#upfile", "temp_cast.jpg")
                await human_delay(8, 12) # アップロード待機

            # 5. 最終保存
            await page.click("#signup") 
            await human_delay(4, 6)
            
            return {"status": "success", "message": "投稿が完了しました"}

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- Streamlit 画面 & API受付 ---
st.title("Cast Automation Worker")

# スプレッドシートからのPOSTリクエストをシミュレート/受付
if st.button("テスト実行(スプレッドシートからの信号を想定)"):
    # 本番はスプレッドシートから送られてくるJSONデータを使用
    test_data = {
        "portal_id": "YOUR_ID",
        "portal_pass": "YOUR_PASS",
        "name": "テスト花子",
        "age": 22,
        "cup": "C",
        "height": 160,
        "ai_description": "AIが生成した素敵な紹介文です...",
        "ai_catchphrase": "AIキャッチコピー",
        "tag_ids": ["genre7", "genre10"], # アイドル系, 可愛い系
        "image_url": "https://example.com/photo.jpg"
    }
    with st.spinner("人間らしく動いています。しばらくお待ちください..."):
        result = asyncio.run(run_automation(test_data))
        st.write(result)
