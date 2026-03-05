import streamlit as st
import asyncio
import random
import os
import subprocess
import requests
from playwright.async_api import async_playwright

# --- 環境構築 ---
@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

async def run_automation(data):
    async with async_playwright() as p:
        # 【文字化け対策】言語設定を日本語に固定
        browser = await p.chromium.launch(
            headless=True,
            args=['--lang=ja-JP']
        ) 
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 2000},
            locale="ja-JP"
        )
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info("🌐 ログイン実行中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await asyncio.sleep(3)

            # 2. 一覧ページへ移動
            st.info("📑 女の子一覧ページへ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/")
            await page.wait_for_load_state("networkidle")

            # 3. 新規登録ボタンをクリック
            st.info("🔴 新規登録ボタンをクリック...")
            await page.click("#addGirl a")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5)

            # 4. プロフィール入力 (HTML解析に基づき修正)
            st.info("✍️ プロフィールを入力中...")
            
            # 基本情報
            await page.fill('input[name="name"]', data['name'])
            
            # カップ選択 (value変換)
            cup_map = {"-":"0","A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            target_cup = cup_map.get(data['cup'].upper(), "0")
            await page.select_option('#form_cup', value=target_cup)

            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # 【修正点】キャッチコピー・タイトル・本文
            st.info("📝 メッセージ類を入力中...")
            await page.fill('input[name="catchcopy"]', data['ai_catchphrase']) # catch -> catchcopy
            await page.fill('input[name="title"]', "はじめまして！")           # タイトル追加
            await page.fill('textarea[name="comments"]', data['ai_description']) # comment -> comments

            # 5. タグ選択 (提供されたリストに基づきクリック)
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                # IDが "genre7" のような形式なので直接指定
                selector = f"#genre{tag_id}"
                if await page.query_selector(selector):
                    await page.click(selector)
                    await asyncio.sleep(0.2)

            # 6. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像をアップロード中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await asyncio.sleep(5)

            # 最後に画面を保存
            await page.screenshot(path="final_form.png")
            st.success("🎉 すべての項目を入力しました！")
            
            return {"status": "success", "message": "シミュレーション完了"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"停止位置エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("🤖 投稿ロボ・属性解析完了版")

if st.button("実行開始"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "期待の新人るかちゃんです！",
        "ai_description": "一生懸命頑張りますので、ぜひ会いに来てください！",
        "tag_ids": ["40", "10", "17", "41"] # 未経験, 可愛い系, スレンダー, サービス抜群
    }
    
    with st.status("自動入力中...") as status:
        result = asyncio.run(run_automation(test_data))
        st.write(result)
        if os.path.exists("final_form.png"):
            st.image("final_form.png", caption="最終入力画面")
        if os.path.exists("error_log.png"):
            st.image("error_log.png", caption="エラー発生画面")
