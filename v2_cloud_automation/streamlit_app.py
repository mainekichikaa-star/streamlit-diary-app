import streamlit as st
import asyncio
import os
import subprocess
import requests
from playwright.async_api import async_playwright

# --- Playwright設定 ---
@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception:
        pass

install_playwright()

async def run_automation(data):
    async with async_playwright() as p:
        # 文字化け対策
        browser = await p.chromium.launch(headless=True, args=['--lang=ja-JP']) 
        context = await browser.new_context(viewport={'width': 1280, 'height': 1500}, locale="ja-JP")
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
            st.info("📑 登録画面へ移動...")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")
            
            # 3. 基本情報入力
            st.info("✍️ 基本情報を入力...")
            await page.fill("#form_name", data['name'])
            
            cup_map = {"A":"1","B":"2","C":"3","D":"4","E":"5","F":"6","G":"7","H":"8","I":"9","J":"10"}
            await page.select_option("#form_cup", value=cup_map.get(data['cup'].upper(), "0"))
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # キャッチコピー・メッセージ
            await page.fill("#form_catchcopy", data['ai_catchphrase'])
            await page.fill("#form_title", "新人紹介")
            await page.fill("#form_comments", data['ai_description'])
            
            # タグ（10:可愛い系, 21:美少女系）
            for tid in data.get('tag_ids', ["10", "21"]):
                await page.check(f"#genre{tid}")

            # 4. 【最難関】画像アップロード（モーダル操作）
            if data.get('image_url'):
                st.info("📸 画像アップロード開始...")
                # 画像を一時保存
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                
                # 「アップロード/編集」リンクをクリックしてモーダルを開く
                await page.click('a[data-target="con1"]')
                await asyncio.sleep(1)
                
                # モーダル内のファイル入力にセット
                await page.set_input_files('#upfile', "upload.jpg")
                
                # モーダル内の「アップロード」ボタンをクリック
                async with page.expect_response(lambda response: response.status == 200):
                    await page.click('button.upbtn')
                
                st.info("✅ 画像アップロード完了")
                await asyncio.sleep(2)

            # 5. 登録実行
            st.info("💾 最終登録ボタンをクリック...")
            # 登録ボタンをクリックして、完了メッセージが出るまで待機
            await page.click("#form_update-btn")
            
            # 「データを登録しました。」という文字が出るまで最大15秒待機
            try:
                success_locator = page.locator('div.message:has-text("データを登録しました")')
                await success_locator.wait_for(state="visible", timeout=15000)
                st.success("🎉 登録に成功しました！")
            except:
                st.warning("⚠️ 完了メッセージが確認できませんでした。入力不備があるかもしれません。")

            await page.screenshot(path="result.png")
            return {"status": "success"}

        except Exception as e:
            await page.screenshot(path="error.png")
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

# --- UI ---
st.title("🤖 投稿ロボ・画像投稿完全対応版")
if st.button("登録を実行"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "期待の新人が入店！",
        "ai_description": "明るく元気な女の子です。",
        "image_url": "https://pub-841966952e3e49ed9a441e881075775c.r2.dev/girl_sample.jpg", # サンプル画像
        "tag_ids": ["10", "21"]
    }
    with st.status("実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        st.image("result.png" if os.path.exists("result.png") else "error.png")
