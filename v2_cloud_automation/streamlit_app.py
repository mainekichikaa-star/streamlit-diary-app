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
            viewport={'width': 1280, 'height': 1500} # 縦を長めにしてボタンを確実に捉える
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

            # 2. メニューを辿って「一覧」へ
            st.info("📑 一覧ページへ移動中...")
            # JSを使って「女性管理」をクリック
            await page.evaluate("() => { const e = [...document.querySelectorAll('a, span')].find(x => x.innerText.includes('女性管理')); if(e) e.click(); }")
            await asyncio.sleep(2)
            # JSを使って「女の子一覧」をクリック
            await page.evaluate("() => { const e = [...document.querySelectorAll('a')].find(x => x.innerText.includes('女の子一覧')); if(e) e.click(); }")
            
            # ページが完全に読み込まれるまで待つ（重要！）
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5)

            # 3. 【最重要】赤いボタンをJSで探して強制実行
            st.info("🔴 新規登録ボタンを捕捉中...")
            found = await page.evaluate("""() => {
                // hrefにregistを含むか、画像パスにregistを含むリンクをすべて探す
                const links = Array.from(document.querySelectorAll('a'));
                const btn = links.find(a => 
                    a.href.includes('regist') || 
                    a.innerHTML.includes('regist') || 
                    (a.innerText && a.innerText.includes('新規登録'))
                );
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            }""")

            if not found:
                st.warning("⚠️ ボタンが見つかりません。画面上の固定座標を叩きます。")
                # 画像image_30610b.jpgの位置に基づき、赤いボタン付近を強襲
                await page.mouse.click(180, 520) 
            
            # 画面遷移を待つ
            st.info("⌛ 登録画面の読み込みを待機...")
            await asyncio.sleep(7)

            # 4. プロフィール入力
            st.info("✍️ プロフィールを入力中...")
            # ここで入力欄が見つからない＝ボタンが押せていない
            name_field = page.locator('input[name="name"]').first
            await name_field.wait_for(state="visible", timeout=15000)
            
            await name_field.fill(data['name'])
            await page.select_option('select[name="cup"]', data['cup'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            await page.fill('textarea[name="comment"]', data['ai_description'])
            await page.fill('input[name="catch"]', data['ai_catchphrase'])
            
            # 5. タグ選択（順次クリック）
            st.info("🏷️ タグを設定中...")
            for tag_id in data.get('tag_ids', []):
                await page.evaluate(f"() => document.querySelector('#genre{tag_id}')?.click()")
                await asyncio.sleep(0.3)

            # 6. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像をアップロード中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                # input要素に直接パスを渡す
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await asyncio.sleep(10)

            st.success("✨ シミュレーション成功！")
            return {"status": "success", "message": "全工程を完了しました"}

        except Exception as e:
            await page.screenshot(path="debug_final.png")
            return {"status": "error", "message": f"停止位置でエラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI (ID/PASS/名前) ---
st.title("🤖 媒体投稿ロボ・リベンジ")
with st.form("f"):
    p_id = st.text_input("ログインID")
    p_pass = st.text_input("パスワード", type="password")
    c_name = st.text_input("名前", value="テスト花子")
    btn = st.form_submit_button("実行")

if btn:
    res = asyncio.run(run_automation({
        "portal_id": p_id, "portal_pass": p_pass, "name": c_name,
        "cup": "C", "age": 22, "height": 160,
        "ai_description": "テスト文章です", "ai_catchphrase": "キャッチ",
        "tag_ids": ["7", "10"], "image_url": "https://dummyimage.com/600x800/000/fff.jpg"
    }))
    st.write(res)
    if os.path.exists("debug_final.png"):
        st.image("debug_final.png", caption="最終停止位置の画面")
