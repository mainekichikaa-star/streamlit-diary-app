import streamlit as st
import pandas as pd
import gspread
import zipfile
import datetime
import re
import urllib.parse
from io import BytesIO
from google.cloud import storage 
from google.oauth2.service_account import Credentials

# =========================================================
# --- 1. 定数と初期設定 (浜松版オリジナル) ---
# =========================================================
try:
    # 浜松版スプレッドシートID
    SHEET_ID = "168X-3PJmQi07mP_FRkyhTHVtUNp5BsCM0rFgabABQUY"
    ACCOUNT_STATUS_SHEET_ID = "1hlGAbImOpxREC25JW7xeApoYC-cJEt4O2Qz9xZT2EHE"
    USABLE_DIARY_SHEET_ID = "1e-iLey43A1t0bIBoijaXP55t5fjONdb0ODiTS53beqM"
    
    # 浜松版GCSバケット
    GCS_BUCKET_NAME = "hamamatsu-auto-poster-images"

    # 投稿アカウント設定
    ACCOUNT_OPTIONS = ["駅ちかA", "駅ちかB", "デリじゃA", "デリじゃB", "デイズA", "デイズB"]
    SHEET_MAP = {opt: f"投稿{opt}" for opt in ACCOUNT_OPTIONS}
    
    MEDIA_OPTIONS = ["駅ちか", "デリじゃ", "デイズ"]
    
except Exception as e:
    st.error(f"🚨 設定の読み込みに失敗しました: {e}")
    st.stop()

INPUT_HEADERS = ["投稿時間", "女の子の名前", "タイトル", "本文"]

# =========================================================
# --- 2. 各種API連携 ---
# =========================================================
@st.cache_resource(ttl=3600)
def get_clients():
    creds_dict = st.secrets["gcp_service_account"]
    gc = gspread.service_account_from_dict(creds_dict)
    gcs = storage.Client.from_service_account_info(creds_dict)
    return gc, gcs

GC, GCS_CLIENT = get_clients()

def gcs_upload_wrapper(uploaded_file, entry, area, store, media, sel_acc):
    try:
        bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
        # 浜松版ルール: A/Bの接尾辞をフォルダ名に付与
        suffix = "【A】" if "A" in sel_acc else "【B】"
        base_folder = f"{media}{store}" if media in ["デリじゃ", "デイズ"] else store
        folder_name = f"{base_folder}{suffix}"
        
        ext = uploaded_file.name.split('.')[-1]
        blob_path = f"{area}/{folder_name}/{entry['投稿時間'].strip()}_{entry['女の子の名前'].strip()}.{ext}"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(uploaded_file.getvalue(), content_type=uploaded_file.type)
        return True
    except Exception as e:
        st.error(f"❌ GCSアップロード失敗: {e}")
        return False

def get_cached_url(blob_name):
    safe_path = urllib.parse.quote(blob_name)
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{safe_path}"

# =========================================================
# --- 3. UI 構築 ---
# =========================================================
st.set_page_config(layout="wide", page_title="浜松・写メ日記投稿登録")

# 大宮版スタイルのCSS
st.markdown("""
    <style>
    .block-container { padding-top: 0rem !important; padding-bottom: 0rem !important; }
    header[data-testid="stHeader"] { display: none !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; height: 80px; }
    button[data-baseweb="tab"] {
        font-size: 28px !important; font-weight: 800 !important; height: 70px !important;
        padding: 0px 30px !important; background-color: #f0f2f6 !important;
        border-radius: 10px 10px 0px 0px !important; margin-right: 5px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: white !important; background-color: #FF4B4B !important;
    }
    </style>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs([
    "📝 ① データ登録", 
    "📊 ② 店舗アカウント状況", 
    "📚 ③ 使用可能日記文",
    "🖼 ④ 使用可能画像"
])

# =========================================================
# --- Tab 1: 📝 ① データ登録 (大宮版の一括登録を完全移植) ---
# =========================================================
with tab1:
    st.header("1️⃣ 浜松版：新規データ登録")
    
    with st.form("diary_input_form", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns(4)
        target_acc = c1.selectbox("👤 投稿アカウント", ACCOUNT_OPTIONS, key="sel_acc_f")
        target_media = c2.selectbox("🌐 媒体", MEDIA_OPTIONS, key="sel_media_f")
        global_area = c3.text_input("📍 エリア", key="in_area_f")
        global_store = c4.text_input("🏢 店名", key="in_store_f")
        
        st.subheader("🔑 ログイン情報")
        c5, c6 = st.columns(2)
        login_id = c5.text_input("ID", key="login_id_f")
        login_pw = c6.text_input("パスワード", key="login_pw_f")
        
        st.markdown("---")
        st.subheader("📸 投稿内容入力 (最大40件)")

        st.markdown("""
            <div style="display: flex; flex-direction: row; border-bottom: 2px solid #444; background-color: #f0f2f6; padding: 10px; border-radius: 5px 5px 0 0;">
                <div style="flex: 1; font-weight: bold; color: black;">時間</div>
                <div style="flex: 1; font-weight: bold; color: black;">名前</div>
                <div style="flex: 2; font-weight: bold; color: black;">タイトル</div>
                <div style="flex: 3; font-weight: bold; color: black;">本文</div>
                <div style="flex: 2; font-weight: bold; color: black;">画像</div>
            </div>
        """, unsafe_allow_html=True)

        form_entries = []
        for i in range(40):
            cols = st.columns([1, 1, 2, 3, 2])
            e_time = cols[0].text_input(f"t{i}", key=f"f_t_{i}", label_visibility="collapsed")
            e_name = cols[1].text_input(f"n{i}", key=f"f_n_{i}", label_visibility="collapsed")
            e_title = cols[2].text_area(f"ti{i}", key=f"f_ti_{i}", height=68, label_visibility="collapsed")
            e_body = cols[3].text_area(f"b{i}", key=f"f_b_{i}", height=68, label_visibility="collapsed")
            e_img = cols[4].file_uploader(f"g{i}", key=f"f_img_{i}", label_visibility="collapsed")
            form_entries.append({'投稿時間': e_time, '女の子の名前': e_name, 'タイトル': e_title, '本文': e_body, 'img': e_img})

        submit_button = st.form_submit_button("🔥 データを一括登録する", type="primary", use_container_width=True)

    if submit_button:
        valid_data = [e for e in form_entries if e['投稿時間'] and e['女の子の名前']]
        if not valid_data or not global_area or not global_store:
            st.error("⚠️ 入力不足：エリア、店名、および少なくとも1件以上の「時間・名前」を入力してください。")
        else:
            progress_text = st.empty()
            try:
                progress_text.info("📸 画像をアップロード中...")
                for e in valid_data:
                    if e['img']: gcs_upload_wrapper(e['img'], e, global_area, global_store, target_media, target_acc)
                
                progress_text.info("📝 日記文を登録中...")
                ws_main = GC.open_by_key(SHEET_ID).worksheet(SHEET_MAP[target_acc])
                
                # デイズ補正ロジック: 空のURL列を4列目に挿入
                if "デイズ" in target_acc:
                    rows_main = [[global_area, global_store, target_media, e['投稿時間'], e['女の子の名前'], "", e['タイトル'], e['本文']] for e in valid_data]
                else:
                    rows_main = [[global_area, global_store, target_media, e['投稿時間'], e['女の子の名前'], e['タイトル'], e['本文']] for e in valid_data]
                
                ws_main.append_rows(rows_main, value_input_option='USER_ENTERED')
                
                progress_text.info("🔐 ログイン情報を登録中...")
                ws_status = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID).worksheet(f"{target_media}アカウント")
                ws_status.append_row([global_area, global_store, target_media, login_id, login_pw], value_input_option='USER_ENTERED')
                
                progress_text.empty()
                st.success(f"✅ {len(valid_data)}件のデータを正常に登録しました！")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ 登録エラーが発生しました: {e}")

# =========================================================
# --- Tab 2: 📊 ② 店舗アカウント状況 (大宮版＋浜松定数) ---
# =========================================================
with tab2:
    st.markdown("## 📊 店舗アカウント状況")
    c_a, c_b = st.columns(2)
    for idx, acc_code in enumerate(ACCOUNT_OPTIONS):
        with [c_a, c_b][idx % 2]:
            try:
                ws_work = GC.open_by_key(SHEET_ID).worksheet(SHEET_MAP[acc_code])
                count = len([x for x in ws_work.col_values(2)[1:] if x.strip()])
            except: count = 0
            st.metric(label=f"👤 {acc_code}", value=f"{count} 件")

# =========================================================
# --- Tab 3: 📚 ③ 使用可能日記文 (大宮版移植) ---
# =========================================================
with tab3:
    st.header("3️⃣ 使用可能日記文")
    @st.cache_data(ttl=600)
    def get_usable_diary_data():
        tmp_sprs = GC.open_by_key(USABLE_DIARY_SHEET_ID)
        return tmp_sprs.sheet1.get_all_values()

    if st.button("🔄 データを更新"): st.cache_data.clear(); st.rerun()

    try:
        tmp_data = get_usable_diary_data()
        if len(tmp_data) > 1:
            df_usable = pd.DataFrame(tmp_data[1:], columns=tmp_data[0])
            st.dataframe(df_usable, use_container_width=True, height=600, hide_index=True)
    except Exception as e: st.error(f"読み込みエラー: {e}")

# =========================================================
# --- Tab 4: 🖼 ④ 使用可能画像 (大宮版の画像処理を移植) ---
# =========================================================
with tab4:
    st.header("🖼 使用可能画像ブラウザ（落ち店）")
    ROOT_PATH = "【落ち店】/"
    bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)

    @st.cache_data(ttl=300)
    def get_ochimise_folders():
        blobs = GCS_CLIENT.list_blobs(GCS_BUCKET_NAME, prefix=ROOT_PATH, delimiter='/')
        list(blobs)
        return blobs.prefixes

    folders = get_ochimise_folders()
    show_all = st.checkbox("📂 全画像表示（一括モード）")

    # 画像取得・ZIP・削除ロジック
    if folders or show_all:
        if not show_all:
            folder_opts = {f.replace(ROOT_PATH, "").replace("/", ""): f for f in folders}
            sel = st.selectbox("📁 店舗を選択", ["未選択"] + list(folder_opts.keys()))
            if sel == "未選択": st.stop()
            target_p = folder_opts[sel]
        else: target_p = ROOT_PATH

        blobs = list(bucket.list_blobs(prefix=target_p))
        img_names = [b.name for b in blobs if b.name.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        if img_names:
            selected = [n for n in img_names if st.sidebar.checkbox(n.split('/')[-1], key=f"side_{n}")] if len(img_names)<50 else []
            # ZIPダウンロード
            if st.button("📦 選択した画像をZIPで固める"):
                zip_buf = BytesIO()
                with zipfile.ZipFile(zip_buf, "w") as zf:
                    for p in img_names: # ここでは簡易的に全件対象
                        zf.writestr(p.split('/')[-1], bucket.blob(p).download_as_bytes())
                st.download_button("💾 ZIPをダウンロード", zip_buf.getvalue(), "images.zip")
            
            # 画像グリッド表示
            cols = st.columns(6)
            for idx, b_name in enumerate(img_names):
                with cols[idx % 6]:
                    st.image(get_cached_url(b_name), use_container_width=True)
                    if st.button("🗑 削除", key=f"del_{b_name}"):
                        bucket.blob(b_name).delete()
                        st.cache_data.clear(); st.rerun()
