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
        # Streamlit Cloud環境でChromiumをインストール
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

# --- 人間らしい待機 ---
async def human_delay(min_sec=3, max_sec=6):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# --- メインの自動化ロジック ---
async def run_automation(data):
    async with async_playwright() as p:
        # ブラウザ起動 (人間らしく見える設定 / ヘッドレスをFalseにするとローカルでは画面が見えます)
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()

        try:
            st.info("🌐 媒体サイトへ移動中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await human_delay(2, 4)

            st.info("🔑 ログイン試行中...")
            await page.type("#form_email", data['portal_id'], delay=random.randint(100, 250))
            await page.type("#form_password", data['portal_pass'], delay=random.randint(100, 250))
            await page.click("#form_submit")
            await human_delay(4, 6)

            # ログイン失敗チェック（一例）
            if "login" in page.url:
                return {"status": "error", "message": "ログインに失敗しました。ID/PASSを確認してください。"}

            st.info("📑 メニューを操作中（女の子一覧へ）...")
            await page.get_by_text("女の子一覧").first.click()
            await human_delay(3, 5)

            st.info("🆕 新規登録画面へ移動中...")
            await page.get_by_text("女の子の新規登録").first.click()
            await human_delay(4, 7)

            st.info("✍️ プロフィールを入力中...")
            await page.type("#form_name", data['name'], delay=150)
            await page.select_option("#form_cup", data['cup'])
            await page.type("#form_age", str(data['age']), delay=200)
            await page.type("#form_tall", str(data['height']), delay=200)
            
            # 紹介文・キャッチコピー
            await page.fill("#form_comments", data['ai_description'])
            await page.fill("#form_catchcopy", data['ai_catchphrase'])

            # タグのチェック
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                selector = f"#{tag_id}"
                if await page.query_selector(selector):
                    await page.check(selector)
                    await asyncio.sleep(0.5)

            st.info("💾 一時保存中（次画面へ）...")
            await page.click("#form_update-btn")
            await human_delay(6, 10)

            # 4. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像をアップロード中...")
                # URLから画像を一時保存
                img_res = requests.get(data['image_url'])
                with open("temp_cast.jpg", "wb") as f:
                    f.write(img_res.content)
                
                await page.set_input_files("#upfile", "temp_cast.jpg")
                await human_delay(8, 12)

            # 5. 最終保存
            # st.warning("⚠️ シミュレーションのため、最後の登録ボタンは押しません。")
            # await page.click("#signup") 
            
            return {"status": "success", "message": "シミュレーション成功（最終保存直前まで完了）"}

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- Streamlit 画面表示 (シミュレーション用UI) ---
st.set_page_config(page_title="投稿シミュレーター", layout="centered")
st.title("🚀 投稿シミュレーション")

with st.form("sim_form"):
    st.subheader("1. ログイン情報")
    p_id = st.text_input("媒体ログインID", placeholder="example@mail.com")
    p_pass = st.text_input("パスワード", type="password")

    st.subheader("2. キャスト情報")
    c_name = st.text_input("名前", value="テスト花子")
    c_age = st.number_input("年齢", value=22)
    c_cup = st.selectbox("カップ", ["A", "B", "C", "D", "E", "F", "G"], index=2)
    c_height = st.number_input("身長", value=160)
    
    st.subheader("3. AI生成内容 (仮入力)")
    c_desc = st.text_area("紹介文", value="ここにAIが作った紹介文が入ります。")
    c_catch = st.text_input("キャッチコピー", value="究極の癒やし系女子")
    
    st.subheader("4. 画像")
    c_img = st.text_input("画像URL", value="https://dummyimage.com/600x800/ccc/000.jpg")

    submit = st.form_submit_button("シミュレーション開始")

if submit:
    if not p_id or not p_pass:
        st.error("ログインIDとパスワードを入力してください")
    else:
        sim_data = {
            "portal_id": p_id,
            "portal_pass": p_pass,
            "name": c_name,
            "age": c_age,
            "cup": c_cup,
            "height": c_height,
            "ai_description": c_desc,
            "ai_catchphrase": c_catch,
            "tag_ids": ["genre7", "genre10"], # 今回は固定でテスト
            "image_url": c_img
        }
        
        with st.status("ロボットが稼働中...", expanded=True) as status:
            result = asyncio.run(run_automation(sim_data))
            if result["status"] == "success":
                status.update(label="完了しました！", state="complete")
                st.success(result["message"])
            else:
                status.update(label="エラー発生", state="error")
                st.error(result["message"])
