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
        # 【文字化け対策】言語設定を日本語(ja)に固定して起動
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--lang=ja-JP',
                '--font-render-hinting=none'
            ]
        ) 
        
        # 【文字化け対策】コンテキスト生成時にも言語を設定
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 1500},
            locale="ja-JP"
        )
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info("🌐 ログイン実行中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.fill("#form_email", "38652")
            await page.fill("#form_password", "loveoppai1")
            await page.click("#form_submit")
            await asyncio.sleep(3)

            # 2. 一覧ページへ移動
            st.info("📑 女の子一覧ページへ移動中...")
            await page.goto("https://ranking-deli.jp/admin/girls/")
            await page.wait_for_load_state("networkidle")

            # 3. 新規登録ボタンをクリック
            st.info("🔴 女の子の新規登録ボタンをクリックします...")
            add_button = page.locator("#addGirl a")
            if await add_button.count() > 0:
                await add_button.click()
            else:
                await page.click('a[href*="/girls/create/"]', force=True)
            
            # 画面遷移をしっかり待つ
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5)

            # 4. プロフィール入力
            st.info("✍️ プロフィールを入力中...")
            
            # 名前
            name_field = page.locator('input[name="name"]').first
            await name_field.wait_for(state="visible", timeout=20000)
            await name_field.fill(data['name'])

            # 【修正】カップの選択方法
            # 送られてきたデータが "C" の場合、valueの "3" に変換して選択
            cup_map = {
                "-": "0", "A": "1", "B": "2", "C": "3", "D": "4", "E": "5",
                "F": "6", "G": "7", "H": "8", "I": "9", "J": "10"
            }
            target_value = cup_map.get(data['cup'].upper().replace("カップ", ""), "0")
            
            # idまたはnameで確実にセレクトボックスを指定
            await page.select_option('select#form_cup', value=target_value)
            st.info(f"✨ カップを選択しました: {data['cup']} (value={target_value})")

            # 年齢・身長
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # キャッチコピーとメッセージ
            await page.fill('input[name="catch"]', data['ai_catchphrase'])
            await page.fill('textarea[name="comment"]', data['ai_description'])
            
            st.success("🎉 入力完了しました！")
            
            # デバッグ用に完了直後のスクリーンショットを保存
            await page.screenshot(path="final_check.png")

            return {"status": "success", "message": "登録画面の入力まで完了しました！"}

        except Exception as e:
            await page.screenshot(path="error_debug.png")
            return {"status": "error", "message": f"停止位置エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit 表示 ---
st.title("🤖 投稿ロボ・文字化け＆カップ修正版")
if st.button("実行開始"):
    test_data = {
        "name": "るか", 
        "cup": "C", # ここが "C" でも自動で value="3" に変換されます
        "age": 22, 
        "height": 160,
        "ai_description": "よろしくお願いします！", 
        "ai_catchphrase": "新人です！"
    }
    with st.status("自動操作中...") as status:
        result = asyncio.run(run_automation(test_data))
        st.write(result)
        if os.path.exists("final_check.png"):
            st.image("final_check.png", caption="入力後の画面")
        if os.path.exists("error_debug.png"):
            st.image("error_debug.png", caption="エラー時の画面")
