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
            # 1. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", data['portal_id'])
            await page.fill("#form_password", data['portal_pass'])
            await page.click("#form_submit")
            await asyncio.sleep(5)

            # 2. 一覧ページへ
            st.info("📑 一覧ページへ移動中...")
            await page.evaluate("() => { const e = [...document.querySelectorAll('a, span')].find(x => x.innerText.includes('女性管理')); if(e) e.click(); }")
            await asyncio.sleep(2)
            await page.evaluate("() => { const e = [...document.querySelectorAll('a')].find(x => x.innerText.includes('女の子一覧')); if(e) e.click(); }")
            
            # ページが完全に読み込まれるまで待機
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5)

            # 3. 【新ロジック】赤いボタンのリンク先を直接解析して移動
            st.info("🔍 新規登録ボタンのリンクを解析中...")
            target_url = await page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a'));
                // hrefに 'regist' を含むリンクを探す
                const regLink = links.find(a => a.href.includes('regist'));
                return regLink ? regLink.href : null;
            }""")

            if target_url:
                st.info(f"🚀 解析したリンクへ移動します...")
                await page.goto(target_url)
            else:
                st.warning("⚠️ リンクが見つかりません。強制座標クリックを実行します。")
                await page.mouse.click(180, 520) 
            
            # 遷移待ち
            await asyncio.sleep(7)

            # 4. プロフィール入力 (ここが今回のエラー箇所)
            st.info("✍️ プロフィールを入力中...")
            # inputが見つかるまで最大20秒待機
            name_input = page.locator('input[name="name"]').first
            await name_input.wait_for(state="visible", timeout=20000)
            
            await name_input.fill(data['name'])
            await page.select_option('select[name="cup"]', data['cup'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # メッセージ入力
            await page.fill('textarea[name="comment"]', data['ai_description'])
            await page.fill('input[name="catch"]', data['ai_catchphrase'])
            
            # 5. タグ選択
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                # ID指定がダメな場合を考慮してJSでクリック
                await page.evaluate(f"() => {{ const e = document.querySelector('#genre{tag_id}'); if(e) e.click(); }}")
                await asyncio.sleep(0.3)

            # 6. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像をセット中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                # ファイル選択
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await asyncio.sleep(10)

            st.success("✨ シミュレーション成功！")
            return {"status": "success", "message": "すべての入力が完了しました。"}

        except Exception as e:
            # どこで止まったか証拠を残す
            await page.screenshot(path="debug_result.png")
            return {"status": "error", "message": f"停止位置でエラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("🤖 媒体投稿ロボ（最終調整版）")
with st.form("main_form"):
    p_id = st.text_input("ログインID")
    p_pass = st.text_input("パスワード", type="password")
    c_name = st.text_input("名前", value="テスト花子")
    c_tags = st.text_input("タグID(例: 7,10)", value="7,10")
    submit = st.form_submit_button("シミュレーション開始")

if submit:
    tag_list = [t.strip() for t in c_tags.split(",")]
    res = asyncio.run(run_automation({
        "portal_id": p_id, "portal_pass": p_pass, "name": c_name,
        "cup": "C", "age": 22, "height": 160,
        "ai_description": "AIが生成した紹介文です。", "ai_catchphrase": "キャッチコピー",
        "tag_ids": tag_list, "image_url": "https://dummyimage.com/600x800/000/fff.jpg"
    }))
    st.write(res)
    if os.path.exists("debug_result.png"):
        st.image("debug_result.png", caption="最終的な画面（エラー時の確認用）")
