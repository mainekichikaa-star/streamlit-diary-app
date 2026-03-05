import streamlit as st
import asyncio
from playwright.async_api import async_playwright
import random

# 人間らしい動きをさせるための待機関数
async def human_delay(min_sec=2, max_sec=5):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

async def run_automation(data):
    async with async_playwright() as p:
        # ブラウザの起動（人間らしく見える設定）
        browser = await p.chromium.launch(headless=True) # クラウド上は画面なし
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # 1. ログイン（URLからではなく、トップから入る想定なら適宜調整）
        await page.goto("https://ranking-deli.jp/admin/login)")
        await human_delay(3, 6)
        
        # IDとパスを1文字ずつ入力
        await page.type("#form_email", data['id'], delay=random.randint(100, 300))
        await page.type("#form_password", data['pass'], delay=random.randint(100, 300))
        await page.click("#form_submit")
        await human_delay(5, 8)

        # 2. メニューを辿って新規登録へ（人間と同じクリック操作）
        # ここは実際のメニューのテキスト等に合わせて調整
        await page.get_by_text("女の子一覧").click()
        await human_delay(2, 4)
        await page.get_by_text("女の子の新規登録").click()
        await human_delay(4, 7)

        # 3. プロフィール入力
        await page.type("#form_name", data['name'], delay=200)
        await page.select_option("#form_cup", data['cup'])
        await page.fill("#form_comments", data['ai_description']) # AI生成文
        
        # タグの自動チェック
        for tag_id in data['tag_ids']:
            await page.check(f"#{tag_id}")
        
        await page.click("#form_update-btn") # 登録実行
        await human_delay(5, 10)

        # 4. 画像アップロード
        if data['image_url']:
            # ファイルを選択してアップロード
            await page.set_input_files("#upfile", data['image_path'])
            await human_delay(10, 15) # アップロード完了を待つ

        await page.click("#signup") # 最終保存
        await browser.close()
        return "成功"
