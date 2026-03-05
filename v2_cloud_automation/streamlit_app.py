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

# --- 人間らしい待機 ---
async def human_delay(min_sec=3, max_sec=6):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# --- メインの自動化ロジック ---
async def run_automation(data):
    async with async_playwright() as p:
        # headless=True（画面なし）で起動。User-Agentを偽装。
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

            st.info("🔑 ログイン中...")
            await page.type("#form_email", data['portal_id'], delay=random.randint(100, 200))
            await page.type("#form_password", data['portal_pass'], delay=random.randint(100, 200))
            await page.click("#form_submit")
            await human_delay(5, 7)

            # --- 重なり対策：メニュー展開 ---
            st.info("📂 メニューを展開中...")
            # 「女性管理」という親メニューがある場合、まずそれをクリック
            target_menu = page.get_by_text("女性管理")
            if await target_menu.count() > 0:
                await target_menu.first.click(force=True)
                await human_delay(1, 2)

            st.info("📑 女の子一覧をクリック...")
            # 「女の子一覧」をクリック。force=Trueで重なりを回避。
            list_btn = page.get_by_text("女の子一覧")
            await list_btn.first.click(force=True)
            await human_delay(4, 6)

            st.info("🆕 新規登録画面へ...")
            reg_btn = page.get_by_text("女の子の新規登録")
            await reg_btn.first.click(force=True)
            await human_delay(4, 6)

            # --- プロフィール入力 ---
            st.info("✍️ プロフィールを入力中...")
            await page.fill("#form_name", data['name'])
            await page.select_option("#form_cup", data['cup'])
            await page.fill("#form_age", str(data['age']))
            await page.fill("#form_tall", str(data['height']))
            
            # AI生成文
            await page.fill("#form_comments", data['ai_description'])
            await page.fill("#form_catchcopy", data['ai_catchphrase'])

            # タグ設定
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                selector = f"#{tag_id}"
                if await page.query_selector(selector):
                    await page.check(selector, force=True)

            st.info("💾 一時保存（次画面へ）...")
            await page.click("#form_update-btn", force=True)
            await human_delay(6, 10)

            # --- 画像アップロード ---
            if data.get('image_url'):
                st.info("📸 画像をアップロード中...")
                img_res = requests.get(data['image_url'])
                with open("temp_cast.jpg", "wb") as f:
                    f.write(img_res.content)
                
                # 画像選択 (input type=file は住所 #upfile)
                await page.set_input_files("#upfile", "temp_cast.jpg")
                await human_delay(10, 15)

            # 最終保存（シミュレーション完了）
            return {"status": "success", "message": "最終保存直前まで正常に動作しました！"}

        except Exception as e:
            # 失敗した時の画面キャプチャをログ代わりに残す機能（デバッグ用）
            await page.screenshot(path="error_screenshot.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.set_page_config(page_title="投稿シミュレーター", layout="centered")
st.title("🚀 投稿シミュレーション")

with st.form("sim_form"):
    st.subheader("1. ログイン情報")
    p_id = st.text_input("媒体ログインID")
    p_pass = st.text_input("パスワード", type="password")

    st.subheader("2. キャスト情報")
    c_name = st.text_input("名前", value="テスト花子")
    c_age = st.number_input("年齢", value=22)
    c_cup = st.selectbox("カップ", ["A", "B", "C", "D", "E", "F", "G", "H", "I"], index=2)
    c_height = st.number_input("身長", value=160)
    
    st.subheader("3. AI内容")
    c_desc = st.text_area("紹介文", value="AI生成テスト文...")
    c_catch = st.text_input("キャッチコピー", value="テストコピー")
    
    st.subheader("4. 画像URL")
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
            "tag_ids": ["genre7", "genre10"],
            "image_url": c_img
        }
        
        with st.status("ロボット稼働中...", expanded=True) as status:
            result = asyncio.run(run_automation(sim_data))
            if result["status"] == "success":
                status.update(label="成功！", state="complete")
                st.success(result["message"])
            else:
                status.update(label="失敗", state="error")
                st.error(result["message"])
