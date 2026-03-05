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
            await page.evaluate("() => { const e = [...document.querySelectorAll('a, span')].find(x => x.innerText.includes('女性管理')); if(e) e.click(); }")
            await asyncio.sleep(2)
            await page.evaluate("() => { const e = [...document.querySelectorAll('a')].find(x => x.innerText.includes('女の子一覧')); if(e) e.click(); }")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5)

            # 3. 赤いボタンのリンク先を直接抽出して移動
            st.info("🔴 新規登録ボタンを解析してジャンプします...")
            target_url = await page.evaluate("""() => {
                const link = document.querySelector('a[href*="regist"]');
                return link ? link.href : null;
            }""")

            if target_url:
                await page.goto(target_url)
                st.info("✅ 登録画面へ遷移しました")
            else:
                st.warning("⚠️ リンクが見つかりません。座標クリック...")
                await page.mouse.click(180, 520) 
            
            await asyncio.sleep(7)

            # 4. プロフィール入力
            st.info("✍️ プロフィールを入力中...")
            name_field = page.locator('input[name="name"]').first
            await name_field.wait_for(state="visible", timeout=20000)
            
            await name_field.fill(data['name'])
            await page.select_option('select[name="cup"]', data['cup'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            await page.fill('textarea[name="comment"]', data['ai_description'])
            await page.fill('input[name="catch"]', data['ai_catchphrase'])
            
            st.success("🎉 プロフィール入力成功！")

            # 5. タグ選択（波括弧エラーを修正）
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                # Pythonのf-stringでJSの{}を使う場合は {{ }} と書く必要があります
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

            return {"status": "success", "message": "全工程を完了しました"}

        except Exception as e:
            await page.screenshot(path="debug_error.png")
            return {"status": "error", "message": f"エラー箇所: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit 表示 ---
st.set_page_config(page_title="駅ちか投稿ロボ", layout="centered")
st.title("🤖 投稿自動化シミュレーター")

st.write("ID: 38652 / PASS: 設定済み")

if st.button("シミュレーションを開始する"):
    test_data = {
        "name": "テスト花子",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_description": "AI紹介文テストです。",
        "ai_catchphrase": "期待の新人！",
        "tag_ids": ["7", "10", "41"],
        "image_url": "https://dummyimage.com/600x800/000/fff.jpg"
    }
    
    with st.status("ロボット稼働中...", expanded=True) as status:
        result = asyncio.run(run_automation(test_data))
        if result["status"] == "success":
            status.update(label="成功！", state="complete")
            st.success(result["message"])
        else:
            status.update(label="エラー発生", state="error")
            st.error(result["message"])
            if os.path.exists("debug_error.png"):
                st.image("debug_error.png")
