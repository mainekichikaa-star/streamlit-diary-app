import streamlit as st
import asyncio
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
        # 文字化け対策を施したブラウザ起動
        browser = await p.chromium.launch(
            headless=True,
            args=['--lang=ja-JP']
        ) 
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 2000},
            locale="ja-JP"
        )
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await page.wait_for_load_state("networkidle")

            # 2. 登録画面へ直接移動
            st.info("📑 登録画面へ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")
            await page.wait_for_load_state("networkidle")

            # 3. プロフィール入力
            st.info("✍️ 基本情報を入力中...")
            # 名前
            await page.fill("#form_name", data['name'])
            
            # カップ (value値で指定)
            cup_map = {
                "A": "1", "B": "2", "C": "3", "D": "4", "E": "5",
                "F": "6", "G": "7", "H": "8", "I": "9", "J": "10"
            }
            target_cup = cup_map.get(data['cup'].upper().replace("カップ", ""), "0")
            await page.select_option("#form_cup", value=target_cup)

            # 年齢・身長
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # 4. キャッチコピー・メッセージ (HTML解析に基づき修正)
            st.info("📢 キャッチコピー・本文を入力中...")
            # キャッチコピー (id="form_catchcopy")
            await page.fill("#form_catchcopy", data['ai_catchphrase'])
            # メッセージタイトル (id="form_title")
            await page.fill("#form_title", "新人スタッフの紹介")
            # メッセージ本文 (id="form_comments")
            await page.fill("#form_comments", data['ai_description'])
            
            # 5. タグ選択 (id="genreXX" を使用)
            st.info("🏷️ タグを選択中...")
            if 'tag_ids' in data:
                for tid in data['tag_ids']:
                    selector = f"#genre{tid}"
                    if await page.query_selector(selector):
                        await page.check(selector)

            # 6. 画像アップロード (もしURLがあれば)
            if data.get('image_url'):
                st.info("📸 画像をアップロード中...")
                img_res = requests.get(data['image_url'])
                with open("temp_girl.jpg", "wb") as f:
                    f.write(img_res.content)
                await page.set_input_files('input[type="file"]', "temp_girl.jpg")
                await asyncio.sleep(2)

            # 7. 登録実行
            st.info("💾 登録ボタンを押します...")
            # 提供されたHTMLの id="form_update-btn" をクリック
            submit_button = page.locator("#form_update-btn")
            await submit_button.scroll_into_view_if_needed()
            
            # クリック後にナビゲーション（完了画面への遷移）を待機
            async with page.expect_navigation(timeout=60000):
                await submit_button.click()
            
            st.success("🎉 登録が完了しました！")
            await page.screenshot(path="after_registration.png")

            return {"status": "success", "message": "登録完了"}

        except Exception as e:
            await page.screenshot(path="error_final.png")
            return {"status": "error", "message": f"停止エラー: {str(e)}"}
        finally:
            await browser.close()

# --- UI部分 ---
st.title("🤖 最終修正版・自動投稿ロボ")

if st.button("登録を実行する"):
    # テストデータ
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": 22,
        "height": 160,
        "ai_catchphrase": "最高に可愛い新人が入店しました！",
        "ai_description": "丁寧な接客でお迎えします。ぜひ会いに来てください！",
        "tag_ids": ["10", "21"] # 可愛い系, 美少女系
    }
    
    with st.status("自動登録を実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="登録成功！", state="complete")
            st.image("after_registration.png", caption="完了後の画面")
        else:
            status.update(label="エラー発生", state="error")
            st.error(res["message"])
            if os.path.exists("error_final.png"):
                st.image("error_final.png")
