import streamlit as st
import asyncio
import os
import subprocess
import requests
from playwright.async_api import async_playwright

@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Playwrightのインストールに失敗しました: {e}")

install_playwright()

async def run_automation(data):
    async with async_playwright() as p:
        # 文字化け対策
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP']) 
        context = await browser.new_context(viewport={'width': 1280, 'height': 2000}, locale="ja-JP")
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await page.wait_for_load_state("networkidle")

            # 2. 新規登録画面へ
            st.info("📑 登録画面へ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")
            await page.wait_for_load_state("networkidle")

            # 3. 基本情報入力
            st.info("✍️ 基本情報を入力中...")
            await page.fill("#form_name", data['name'])
            
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            target_cup = cup_map.get(data['cup'].upper().replace("カップ",""), "0")
            await page.select_option("#form_cup", value=target_cup)
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # 4. キャッチコピー・本文
            await page.fill("#form_catchcopy", data['ai_catchphrase'])
            await page.fill("#form_title", "新人スタッフの紹介")
            await page.fill("#form_comments", data['ai_description'])
            
            # 5. タグ選択
            if 'tag_ids' in data:
                for tid in data['tag_ids']:
                    selector = f"#genre{tid}"
                    if await page.query_selector(selector):
                        await page.check(selector)

            # 6. 画像アップロード（モーダル対応）
            if data.get('image_url'):
                st.info("📸 画像アップロード中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                
                # 「アップロード/編集」をクリックしてモーダルを開く
                await page.click('a[data-target="con1"]')
                await asyncio.sleep(1)
                # モーダル内のファイル選択
                await page.set_input_files('#con1 #upfile', "upload.jpg")
                # アップロードボタンをクリック
                await page.click('#con1 button.upbtn')
                await asyncio.sleep(3) # アップロード完了待ち

            # 7. 登録ボタンのクリック（決定打）
            st.info("💾 登録を実行中...")
            # JSで直接クリックを発火させ、確実に送信する
            await page.evaluate('document.getElementById("form_update-btn").click()')

            # 8. 成功メッセージの確認
            # <div class="message">データを登録しました。</div> を待機
            success_msg = page.locator(".message", has_text="データを登録しました")
            await success_msg.wait_for(state="visible", timeout=30000)
            
            st.success("🎉 管理画面：『データを登録しました。』を確認しました！")
            await page.screenshot(path="success_final.png")
            return {"status": "success", "message": "登録完了"}

        except Exception as e:
            await page.screenshot(path="error_log.png")
            return {"status": "error", "message": f"エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.title("🤖 登録完了確定版ロボ")

if st.button("本番登録を開始"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "最高に可愛い新人が入店しました！",
        "ai_description": "丁寧な接客でお迎えします。ぜひ会いに来てください！",
        "tag_ids": ["10", "21"],
        "image_url": "https://pub-8416043a2901416886e06b3a2072f6a9.r2.dev/pre_v0_1739775344337.png"
    }
    
    with st.status("実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="登録成功！", state="complete")
            st.image("success_final.png")
        else:
            status.update(label="失敗", state="error")
            st.error(res["message"])
            if os.path.exists("error_log.png"):
                st.image("error_log.png")
