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
        # 【文字化け対策】言語設定とフォントレンダリングを日本語に最適化
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--lang=ja-JP',
                '--disable-blink-features=AutomationControlled',
            ]
        ) 
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 2000},
            locale="ja-JP",
            timezone_id="Asia/Tokyo"
        )
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await asyncio.sleep(3)

            # 2. 一覧ページから新規登録へ
            st.info("📑 登録画面へ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/create/")
            await page.wait_for_load_state("networkidle")

            # 3. プロフィール入力 (提供されたHTMLに基づく修正)
            st.info("✍️ プロフィールを入力中...")
            
            # 名前
            await page.fill("#form_name", data['name']) if await page.query_selector("#form_name") else await page.fill('input[name="name"]', data['name'])

            # カップ (MapでValueに変換)
            cup_map = {
                "-": "0", "A": "1", "B": "2", "C": "3", "D": "4", "E": "5",
                "F": "6", "G": "7", "H": "8", "I": "9", "J": "10"
            }
            target_cup = cup_map.get(data['cup'].upper(), "0")
            await page.select_option("#form_cup", value=target_cup)

            # 年齢・身長
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # 【重要】キャッチコピー (name="catchcopy")
            st.info("📢 キャッチコピーを入力中...")
            await page.fill("#form_catchcopy", data['ai_catchphrase'])
            
            # 【重要】メッセージタイトル (name="title")
            await page.fill("#form_title", "新人スタッフの紹介")
            
            # 【重要】メッセージ本文 (name="comments")
            st.info("📝 本文を入力中...")
            await page.fill("#form_comments", data['ai_description'])
            
            # 4. タグ選択 (提供されたチェックボックス群)
            st.info("🏷️ タグを選択中...")
            for tag_id in data.get('tag_ids', []):
                # ID指定で確実にクリック
                selector = f"#genre{tag_id}"
                if await page.query_selector(selector):
                    await page.check(selector)
                    await asyncio.sleep(0.1)

            # 5. 画像アップロード
            if data.get('image_url'):
                st.info("📸 画像をアップロード中...")
                img_res = requests.get(data['image_url'])
                with open("upload.jpg", "wb") as f:
                    f.write(img_res.content)
                await page.set_input_files('input[type="file"]', "upload.jpg")
                await asyncio.sleep(5)

            # 6. 登録ボタン (id="form_update-btn")
            st.info("💾 登録ボタンを押します...")
            # 実際の登録を防ぐ場合はここをコメントアウトしてください
            # await page.click("#form_update-btn")
            
            st.success("🎉 すべての項目の入力に成功しました！")
            await page.screenshot(path="complete_screen.png")

            return {"status": "success", "message": "全項目入力完了"}

        except Exception as e:
            await page.screenshot(path="error_final.png")
            return {"status": "error", "message": f"停止エラー: {str(e)}"}
        finally:
            await browser.close()

# --- UI ---
st.title("🤖 最終調整版・自動投稿ロボ")
st.write("解析したHTML構造に基づき、キャッチコピーやタグ入力を最適化しました。")

if st.button("自動入力シミュレーション開始"):
    test_data = {
        "name": "るか",
        "cup": "C",
        "age": "22",
        "height": "160",
        "ai_catchphrase": "最高に可愛い新人が入店しました！",
        "ai_description": "丁寧な接客と最高の笑顔でお迎えします。ぜひ会いに来てください！",
        "tag_ids": ["10", "21", "41"] # 可愛い系, 美少女系, サービス抜群
    }
    
    with st.status("操作実行中...") as status:
        res = asyncio.run(run_automation(test_data))
        if res["status"] == "success":
            status.update(label="入力完了！", state="complete")
            st.image("complete_screen.png", caption="入力済みの画面（文字化け修正確認）")
        else:
            status.update(label="エラー", state="error")
            st.error(res["message"])
            if os.path.exists("error_final.png"):
                st.image("error_final.png")
