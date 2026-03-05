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

# --- メインの自動化ロジック ---
async def run_automation(data):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 1200}
        )
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.type("#form_email", data['portal_id'], delay=100)
            await page.type("#form_password", data['portal_pass'], delay=100)
            await page.click("#form_submit")
            await asyncio.sleep(5)

            # 2. 【変更点】ボタンを無視して登録画面へ直接ジャンプ
            st.info("🚀 登録画面へ直接移動します...")
            await page.goto("https://ranking-deli.jp/admin/girls/regist/") 
            await asyncio.sleep(5)

            # 3. プロフィール入力 (image_3e7d2a.jpg に基づく)
            st.info("✍️ プロフィールを入力中...")
            # フォームが存在するか確認
            if await page.query_selector('input[name="name"]'):
                await page.fill('input[name="name"]', data['name'])
                await page.select_option('select[name="cup"]', data['cup'])
                await page.fill('input[name="age"]', str(data['age']))
                await page.fill('input[name="tall"]', str(data['height']))
                
                # メッセージ (画像 image_3e7d2a.jpg のtextarea)
                await page.fill('textarea[name="comment"]', data['ai_description'])
                await page.fill('input[name="catch"]', data['ai_catchphrase'])
                
                st.success("✅ フォームへの入力に成功しました！")
            else:
                raise Exception("登録フォームが見つかりませんでした。URLが違う可能性があります。")

            # 4. タグ選択（image_3e7ca6.png）
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                await page.evaluate(f"() => document.querySelector('#genre{tag_id}')?.click()")
                await asyncio.sleep(0.3)

            # 5. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像をセット中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await asyncio.sleep(5)

            # 登録ボタン（最終確認）
            # await page.click("#form_update-btn", force=True)
            
            return {"status": "success", "message": "シミュレーション完了！"}

        except Exception as e:
            await page.screenshot(path="last_error.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- UI ---
st.title("🚀 駅ちか投稿ロボ（URL直撃版）")
with st.form("sim_form"):
    p_id = st.text_input("ログインID")
    p_pass = st.text_input("パスワード", type="password")
    c_name = st.text_input("名前", value="テスト花子")
    submit = st.form_submit_button("シミュレーション開始")

if submit:
    res = asyncio.run(run_automation({
        "portal_id": p_id, "portal_pass": p_pass, "name": c_name,
        "cup": "C", "age": 22, "height": 160,
        "ai_description": "紹介文テスト", "ai_catchphrase": "キャッチコピー",
        "tag_ids": ["7", "10"], "image_url": "https://dummyimage.com/600x800/000/fff.jpg"
    }))
    st.write(res)
    if os.path.exists("last_error.png"):
        st.image("last_error.png", caption="実行後の画面（入力できているか確認してください）")
