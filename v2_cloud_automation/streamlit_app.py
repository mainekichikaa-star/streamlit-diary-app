import streamlit as st
import asyncio
import os
import re
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
from playwright.async_api import async_playwright

# --- 認証設定 ---
SCOPE = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
# StreamlitのSecretsにJSONの中身を入れている想定
# もしくは直接パス指定: Credentials.from_service_account_file("path/to/json")
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPE)
gs_client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)

SPREADSHEET_ID = "1Fta23cis4AY9j2_lytfh0OOAJq-EFinLjqp_dLIAgtM"

# --- Googleドライブからファイル名で検索してダウンロード ---
def download_by_filename(path_str, save_path):
    try:
        # "フォルダ名/ファイル名.jpg" から "ファイル名.jpg" だけを抽出
        filename = path_str.split('/')[-1]
        
        # 名前でファイルを検索
        query = f"name = '{filename}' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])

        if not items:
            st.warning(f"ファイルが見つかりません: {filename}")
            return False

        file_id = items[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        with open(save_path, "wb") as f:
            f.write(fh.getvalue())
        return True
    except Exception as e:
        st.error(f"ダウンロードエラー ({path_str}): {e}")
        return False

# --- メインの自動化処理 ---
async def run_automation(cast_data, sub_images):
    # 保存した画像のパスリスト
    downloaded_images = []
    
    # 1. メイン画像のダウンロード
    main_img_path = "main_photo.jpg"
    if download_by_filename(cast_data['メイン画像'], main_img_path):
        downloaded_images.append(main_img_path)

    # 2. サブ画像のダウンロード
    for i, sub_img_url in enumerate(sub_images):
        sub_path = f"sub_photo_{i}.jpg"
        if download_by_filename(sub_img_url, sub_path):
            downloaded_images.append(sub_path)

    if not downloaded_images:
        return {"status": "error", "message": "画像が1枚も取得できませんでした。"}

    async with async_playwright() as p:
        # --- (Playwrightのブラウザ操作部分は以前のコードを流用) ---
        # ログインや入力時に cast_data['名前'], cast_data['ID'](媒体用) 等を使用
        # 画像アップロード時は downloaded_images をループで回して登録
        
        # ... 登録処理 ...
        
        return {"status": "success"}

# --- Streamlit UI & ロジック ---
st.title("👸 キャスト一括登録システム")

if st.button("🚀 未登録キャストを確認して実行"):
    sheet_info = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト情報")
    sheet_images = gs_client.open_by_key(SPREADSHEET_ID).worksheet("キャスト画像")
    
    # 全データを取得
    data_info = sheet_info.get_all_records()
    data_images = sheet_images.get_all_records()

    for i, row in enumerate(data_info):
        # 条件: ID・PASSがあり、かつ「登録済」が空
        # 列名はスプレッドシートの1行目と完全に一致させる必要があります
        if row['ID'] and row['PASSWORD'] and not row['登録済']:
            st.info(f"⏳ {row['名前']} さんの登録を開始します...")

            # 関連するサブ画像を「キャスト画像」シートから抽出
            sub_images = [img['写真'] for img in data_images if str(img['CastID']) == str(row['ＩＤ'])]

            # 自動化実行
            result = asyncio.run(run_automation(row, sub_images))

            if result["status"] == "success":
                # 「登録済」列(16列目)に書き込み
                sheet_info.update_cell(i + 2, 16, "登録済")
                st.success(f"✅ {row['名前']} さんの登録完了！")
            else:
                st.error(f"❌ {row['名前']} さんでエラー: {result['message']}")

    st.write("すべての処理が完了しました。")
