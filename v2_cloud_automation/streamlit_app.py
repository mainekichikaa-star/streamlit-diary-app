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
            viewport={'width': 1280, 'height': 1000} # 少し高めに設定
        )
        page = await context.new_page()

        try:
            # 1. ログイン
            st.info("🌐 ログイン中...")
            await page.goto("https://ranking-deli.jp/admin/login")
            await page.type("#form_email", data['portal_id'], delay=random.randint(50, 150))
            await page.type("#form_password", data['portal_pass'], delay=random.randint(50, 150))
            await page.click("#form_submit")
            await human_delay(4, 6)

            # 2. メニュー展開 & 一覧へ
            st.info("📑 女の子一覧ページへ移動中...")
            # 「女性管理」メニューをクリックして展開（重なり対策でforce=True）
            await page.get_by_text("女性管理").first.click(force=True)
            await human_delay(1, 2)
            await page.get_by_text("女の子一覧").first.click(force=True)
            await human_delay(4, 6)

            # 3. 赤い「新規登録」ボタンをクリック（ここを強化）
            st.info("🔴 新規登録ボタンを探索中...")
            # テキストで見つからない場合を考慮し、href属性や「赤いボタン」のクラスを狙う
            # 画像 image_30610b.jpg の赤いボタンを狙い撃ち
            regist_button = page.locator('a:has-text("女の子の新規登録"), a[href*="regist"]')
            await regist_button.first.wait_for(state="visible", timeout=10000)
            await regist_button.first.click(force=True)
            await human_delay(5, 7)

            # 4. プロフィール入力 (image_3e7d2a.jpg に基づく)
            st.info("✍️ プロフィールを入力中...")
            await page.fill('input[name="name"]', data['name']) # セレクタは画像内のname属性を想定
            await page.select_option('select[name="cup"]', data['cup'])
            await page.fill('input[name="age"]', str(data['age']))
            await page.fill('input[name="tall"]', str(data['height']))
            
            # メッセージ（紹介文）
            await page.fill('textarea[name="comment"]', data['ai_description'])
            await page.fill('input[name="catch"]', data['ai_catchphrase'])

            # 5. タグ（チェックボックス）の選択 (image_3e7ca6.png に基づく)
            st.info("🏷️ タグを選択中...")
            for tag_id in data.get('tag_ids', []):
                # IDが "#genre7" のような形式であればそのまま、数字だけなら "#genre" を付与
                selector = f"#{tag_id}" if tag_id.startswith("#") else f"#genre{tag_id}"
                if await page.query_selector(selector):
                    await page.check(selector, force=True)
                    await asyncio.sleep(0.3)

            # 一次保存
            st.info("💾 入力内容を登録中...")
            await page.click(".btn-red, #form_update-btn", force=True) # 赤い登録ボタン
            await human_delay(7, 10)

            # 6. 画像アップロード (image_3e792a.png / image_3e6e20.jpg)
            if data.get('image_url'):
                st.info("📸 画像アップロードを開始...")
                img_res = requests.get(data['image_url'])
                with open("upload_image.jpg", "wb") as f:
                    f.write(img_res.content)
                
                # Playwrightのファイルセット機能
                # "アップロード/編集"ボタンを押すのではなく、裏側のinput[type=file]に直接流し込む
                file_input = page.locator('input[type="file"]').first
                await file_input.set_input_files("upload_image.jpg")
                st.info("⏳ アップロード処理待ち...")
                await human_delay(10, 15)

            return {"status": "success", "message": "シミュレーション完了（画像セットまでOK）"}

        except Exception as e:
            # 失敗時に証拠写真を撮る
            await page.screenshot(path="debug_error.png")
            return {"status": "error", "message": f"エラー: {str(e)}"}
        finally:
            await browser.close()

# --- Streamlit UI ---
st.set_page_config(page_title="駅ちか投稿ロボ", layout="centered")
st.title("🤖 媒体投稿シミュレーター")

with st.form("main_form"):
    col1, col2 = st.columns(2)
    with col1:
        p_id = st.text_input("ログインID")
        c_name = st.text_input("名前", value="テスト花子")
        c_age = st.number_input("年齢", value=22)
    with col2:
        p_pass = st.text_input("パスワード", type="password")
        c_cup = st.selectbox("カップ", ["-", "A", "B", "C", "D", "E", "F", "G", "H"], index=3)
        c_height = st.number_input("身長", value=160)
    
    c_desc = st.text_area("紹介文", value="AIで生成した紹介文がここに入ります。")
    c_catch = st.text_input("キャッチコピー", value="期待の新人が登場！")
    c_img = st.text_input("画像URL", value="https://dummyimage.com/600x800/ff0000/fff.jpg")
    
    # テスト用のタグID（ジャンル）
    c_tags = st.text_input("タグID（カンマ区切り）", value="7,10,41")

    submit = st.form_submit_button("シミュレーション実行")

if submit:
    if not p_id or not p_pass:
        st.error("ログイン情報を入力してください")
    else:
        tag_list = [t.strip() for t in c_tags.split(",")]
        test_data = {
            "portal_id": p_id,
            "portal_pass": p_pass,
            "name": c_name,
            "age": c_age,
            "cup": c_cup,
            "height": c_height,
            "ai_description": c_desc,
            "ai_catchphrase": c_catch,
            "tag_ids": tag_list,
            "image_url": c_img
        }
        
        with st.status("人間らしく操作中...", expanded=True) as status:
            result = asyncio.run(run_automation(test_data))
            if result["status"] == "success":
                status.update(label="成功！", state="complete")
                st.success(result["message"])
            else:
                status.update(label="失敗", state="error")
                st.error(result["message"])
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="エラー時の画面状態")
