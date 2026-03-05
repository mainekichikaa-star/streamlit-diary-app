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
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 1500}
        )
        page = await context.new_page()

        try:
            # 1. ログイン (ID/PASS固定)
            st.info("🌐 ログイン実行中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await asyncio.sleep(5)

            # 2. 一覧ページへ移動
            st.info("📑 女の子一覧ページへ移動中...")
            # メニューから辿る（念のため）
            await page.evaluate("() => { const e = [...document.querySelectorAll('a, span')].find(x => x.innerText.includes('女性管理')); if(e) e.click(); }")
            await asyncio.sleep(2)
            await page.evaluate("() => { const e = [...document.querySelectorAll('a')].find(x => x.innerText.includes('女の子一覧')); if(e) e.click(); }")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)

            # 3. 【修正の核心】提供されたHTMLに基づいてボタンを直撃
            st.info("🔴 女の子の新規登録ボタンをクリックします...")
            # id="addGirl" の中にある aタグ を狙い撃ち
            add_button = page.locator("#addGirl a")
            
            if await add_button.count() > 0:
                await add_button.click()
                st.info("✅ ボタンをクリックしました")
            else:
                # もしIDで見つからない場合は、画像パスから探す
                st.warning("⚠️ IDで見つからないため、画像URLで探索します...")
                await page.click('a[href*="/girls/create/"]', force=True)
            
            # 遷移をしっかり待つ
            await asyncio.sleep(8)

            # 4. プロフィール入力
            st.info("✍️ プロフィールを入力中...")
            # ここが動けば勝ちです
            name_field = page.locator('input[name="name"]').first
            await name_field.wait_for(state="visible", timeout=25000)
            
            await name_field.fill(data['name'])
            await page.select_option('select[name="cup"]', data['cup'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            await page.fill('textarea[name="comment"]', data['ai_description'])
            await page.fill('input[name="catch"]', data['ai_catchphrase'])
            
            st.success("🎉 プロフィール入力に成功しました！")

            # 5. タグ選択
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                await page.evaluate(f"() => {{ const e = document.querySelector('#genre{tag_id}'); if(e) e.click(); }}")
                await asyncio.sleep(0.3)

            # 6. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像を準備中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await asyncio.sleep(10)

            return {"status": "success", "message": "すべての操作が完了しました！"}

        except Exception as e:
            await page.screenshot(path="last_debug.png")
            return {"status": "error", "message": f"停止位置エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit 表示 ---
st.title("🤖 投稿ロボ・ソース解析完了版")
if st.button("シミュレーション開始"):
    test_data = {
        "name": "テスト花子", "cup": "C", "age": 22, "height": 160,
        "ai_description": "解析成功後のテストです。", "ai_catchphrase": "ついに成功か！？",
        "tag_ids": ["7", "10"],
        "image_url": "https://dummyimage.com/600x800/000/fff.jpg"
    }
    with st.status("実行中...") as status:
        result = asyncio.run(run_automation(test_data))
        st.write(result)
        if os.path.exists("last_debug.png"):
            st.image("last_debug.png")
