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
            # 1. ログイン（ここは成功済み）
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.type("#form_email", data['portal_id'], delay=random.randint(50, 100))
            await page.type("#form_password", data['portal_pass'], delay=random.randint(50, 100))
            await page.click("#form_submit")
            await human_delay(4, 6)

            # 2. 一覧ページへ
            st.info("📑 一覧ページへ移動中...")
            # 「女性管理」をJSで直接クリック
            await page.evaluate("() => { [...document.querySelectorAll('a, span')].find(e => e.innerText.includes('女性管理'))?.click(); }")
            await human_delay(2, 3)
            # 「女の子一覧」をJSで直接クリック
            await page.evaluate("() => { [...document.querySelectorAll('a')].find(e => e.innerText.includes('女の子一覧'))?.click(); }")
            await human_delay(6, 8)

            # 3. 【超強化】赤い「新規登録」ボタンを力技で踏む
            st.info("🔴 赤いボタンを解析中...")
            
            # 対策A: ページ内の全リンクから「regist」を含むものを探して強制クリック
            found = await page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a'));
                const registLink = links.find(a => a.href.includes('regist') || a.className.includes('red'));
                if (registLink) {
                    registLink.click();
                    return true;
                }
                return false;
            }""")

            if not found:
                # 対策B: もしAがダメなら、ボタンの「座標」を直接叩く
                # image_30610b.jpg の位置関係から、青いボタンの左側を狙う
                st.warning("⚠️ ボタンが特定できません。座標クリックを試みます。")
                await page.mouse.click(180, 520) # 画面左上の「新規登録」がありそうな位置
            
            await human_delay(5, 7)

            # 4. 入力フォーム（image_3e7d2a.jpg に基づく）
            st.info("✍️ プロフィールを入力中...")
            # セレクタをIDベースに変更
            await page.fill('input[name="name"]', data['name'])
            await page.select_option('select[name="cup"]', data['cup'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # メッセージ (画像 image_3e7d2a.jpg のtextarea)
            await page.fill('textarea[name="comment"]', data['ai_description'])
            await page.fill('input[name="catch"]', data['ai_catchphrase'])

            # 5. タグ選択（image_3e7ca6.png）
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                await page.evaluate(f"() => document.querySelector('#genre{tag_id}')?.click()")
                await asyncio.sleep(0.3)

            # 6. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像をセット中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                
                # input要素を探して直接流し込む
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await human_delay(10, 15)

            # 登録実行
            await page.click(".btn-red, #form_update-btn, button[type='submit']", force=True)
            
            return {"status": "success", "message": "シミュレーション完了！"}

        except Exception as e:
            await page.screenshot(path="error_capture.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- UI (前回と同じ) ---
st.title("🚀 駅ちか投稿ロボ・アルティメット")
with st.form("sim_form"):
    p_id = st.text_input("ログインID")
    p_pass = st.text_input("パスワード", type="password")
    c_name = st.text_input("名前", value="テスト花子")
    submit = st.form_submit_button("シミュレーション開始")

if submit:
    res = asyncio.run(run_automation({
        "portal_id": p_id, "portal_pass": p_pass, "name": c_name,
        "cup": "C", "age": 22, "height": 160,
        "ai_description": "AI紹介文...", "ai_catchphrase": "キャッチコピー",
        "tag_ids": ["7", "10"], "image_url": "https://dummyimage.com/600x800/000/fff.jpg"
    }))
    st.write(res)
    if os.path.exists("error_capture.png"):
        st.image("error_capture.png")
