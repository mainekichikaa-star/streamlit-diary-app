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
            await page.type("#form_email", data['portal_id'], delay=random.randint(50, 150))
            await page.type("#form_password", data['portal_pass'], delay=random.randint(50, 150))
            await page.click("#form_submit")
            await human_delay(4, 6)

            # 2. 一覧ページへ
            st.info("📑 一覧ページへ移動中...")
            await page.get_by_text("女性管理").first.click(force=True)
            await human_delay(1, 2)
            await page.get_by_text("女の子一覧").first.click(force=True)
            await human_delay(5, 8) # ページ読み込みを長めに待機

            # 3. 【最重要】赤い「新規登録」ボタンを座標とリンクで狙い撃ち
            st.info("🔴 赤い新規登録ボタンを強制クリックします...")
            # hrefの中に 'regist' が入っているaタグを、テキスト無視で探す
            regist_btn = page.locator('a[href*="/regist/"], a[href*="regist"]').first
            
            # もし見つからなければ、赤いボタンのアイコン（img）を起点に探す
            if await regist_btn.count() == 0:
                 regist_btn = page.locator('.btn-red, .btn-danger, .regist-btn').first

            await regist_btn.wait_for(state="visible", timeout=15000)
            # 重なりを無視してクリック
            await regist_btn.click(force=True)
            await human_delay(5, 7)

            # 4. プロフィール入力 (image_3e7d2a.jpgの項目名に基づき修正)
            st.info("✍️ プロフィールを入力中...")
            # IDやname属性で直接狙う
            await page.fill('input[name="name"]', data['name'])
            await page.select_option('select[name="cup"]', data['cup'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # メッセージ関連
            await page.fill('textarea[name="comment"]', data['ai_description'])
            await page.fill('input[name="catch"]', data['ai_catchphrase'])

            # 5. タグの自動チェック (image_3e7ca6.pngのID形式)
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                # プレフィックスを付けてチェック
                selector = f"#genre{tag_id}"
                if await page.query_selector(selector):
                    await page.check(selector, force=True)
                    await asyncio.sleep(0.4)

            # 一次保存ボタン
            await page.click("#form_update-btn, .btn-update", force=True)
            await human_delay(8, 12)

            # 6. 画像アップロード (image_3e6e20.jpg のウィンドウ対策)
            if data.get('image_url'):
                st.info("📸 画像をセット中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                
                # ウィンドウが開くのを待つのではなく、input要素に直接ファイルを流し込む
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await human_delay(10, 15)

            return {"status": "success", "message": "シミュレーション完了！"}

        except Exception as e:
            await page.screenshot(path="error_detail.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- UI部分は前回と同様 ---
st.title("🤖 媒体投稿ロボ（強化版）")
with st.form("sim_form"):
    p_id = st.text_input("ログインID")
    p_pass = st.text_input("パスワード", type="password")
    c_name = st.text_input("名前", value="テスト花子")
    c_tags = st.text_input("タグID(例: 7,10)", value="7,10")
    submit = st.form_submit_button("実行")

if submit:
    tag_list = [t.strip() for t in c_tags.split(",")]
    res = asyncio.run(run_automation({
        "portal_id": p_id, "portal_pass": p_pass, "name": c_name,
        "cup": "C", "age": 22, "height": 160,
        "ai_description": "テストです", "ai_catchphrase": "テスト",
        "tag_ids": tag_list, "image_url": "https://dummyimage.com/600x800/000/fff.jpg"
    }))
    st.write(res)
    if os.path.exists("error_detail.png"):
        st.image("error_detail.png")
