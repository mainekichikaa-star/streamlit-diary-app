import streamlit as st
import pandas as pd
import gspread
import datetime
import re
import urllib.parse
from google.cloud import storage
from google.oauth2.service_account import Credentials

# =========================================================================
# 1. 定数・設定 (浜松版オリジナル)
# =========================================================================
try:
    # スプレッドシートID
    SHEET_ID = "168X-3PJmQi07mP_FRkyhTHVtUNp5BsCM0rFgabABQUY"
    ACCOUNT_STATUS_SHEET_ID = "1hlGAbImOpxREC25JW7xeApoYC-cJEt4O2Qz9xZT2EHE"
    
    # GCS設定
    GCS_BUCKET_NAME = "hamamatsu-auto-poster-images"
    
    # アカウント設定
    ACCOUNT_OPTIONS = ["駅ちかA", "駅ちかB", "デリじゃA", "デリじゃB", "デイズA", "デイズB"]
    SHEET_MAP = {opt: f"投稿{opt}" for opt in ACCOUNT_OPTIONS}
    
    # 標準列定義
    DF_COLS = ["エリア", "店名", "投稿時間", "女の子の名前", "タイトル", "本文", "投稿ステータス"]
    
except Exception as e:
    st.error(f"🚨 設定の読み込みに失敗しました: {e}")
    st.stop()

# =========================================================================
# 2. API接続 & キャッシュ
# =========================================================================
@st.cache_resource(ttl=3600)
def get_clients():
    creds = st.secrets["gcp_service_account"]
    gc = gspread.service_account_from_dict(creds)
    gcs = storage.Client.from_service_account_info(creds)
    return gc, gcs

GC, GCS_CLIENT = get_clients()

@st.cache_data(ttl=600)
def get_full_sheet_data(sheet_key, worksheet_name):
    try:
        sh = GC.open_by_key(sheet_key)
        ws = sh.worksheet(worksheet_name)
        return ws.get_all_values()
    except:
        return None

def normalize_text(s):
    if not s: return ""
    return re.sub(r'\s+', '', str(s)).replace('　', '').lower()

# =========================================================================
# 3. UI 構築
# =========================================================================
st.set_page_config(layout="wide", page_title="浜松日記エディタ")

# タブデザイン
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    button[data-baseweb="tab"] {
        font-size: 20px !important; font-weight: bold !important;
        padding: 10px 20px !important;
    }
    </style>
""", unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 日記エディタ", "📊 店舗アカウント状況"])

# ---------------------------------------------------------
# Tab 1: 📝 日記エディタ (大宮版ベース＋デイズ補正)
# ---------------------------------------------------------
with tab1:
    c1, c2, c3, c4 = st.columns([1.5, 1.5, 1.5, 2])
    sel_acc = c1.selectbox("👤 アカウント", ACCOUNT_OPTIONS)
    
    data = get_full_sheet_data(SHEET_ID, SHEET_MAP.get(sel_acc))
    
    if data and len(data) > 1:
        # デイズの列ズレ補正 (4列目のURLを飛ばす)
        raw_df = pd.DataFrame(data[1:])
        if "デイズ" in sel_acc:
            full_df = raw_df[[0, 1, 2, 3, 5, 6, 7]] # 4列目(URL)をスキップ
        else:
            full_df = raw_df.iloc[:, :7]
            
        full_df.columns = DF_COLS
        full_df['__row__'] = range(2, len(data) + 1)
        
        # フィルタリング
        areas = sorted(full_df["エリア"].unique())
        sel_area = c2.selectbox("📍 エリア", ["未選択"] + areas)
        
        stores = []
        if sel_area != "未選択":
            stores = sorted(full_df[full_df["エリア"] == sel_area]["店名"].unique())
        sel_store = c3.selectbox("🏢 店舗", ["未選択"] + stores)
        
        search_q = c4.text_input("🔍 検索", placeholder="名前やタイトルで検索...")
        
        # 絞り込み実行
        disp_df = full_df.copy()
        if sel_area != "未選択": disp_df = disp_df[disp_df["エリア"] == sel_area]
        if sel_store != "未選択": disp_df = disp_df[disp_df["店名"] == sel_store]
        if search_q:
            disp_df = disp_df[disp_df.apply(lambda r: search_q.lower() in "".join(map(str, r)).lower(), axis=1)]

        st.divider()
        
        # エディタ表示
        for _, row in disp_df.iterrows():
            with st.expander(f"👤 {row['女の子の名前']} | {row['投稿時間']} | {row['タイトル'][:20]}..."):
                with st.form(key=f"form_{sel_acc}_{row['__row__']}"):
                    col_img, col_txt = st.columns([1, 2])
                    
                    # 画像表示 (GCSから取得)
                    with col_img:
                        bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
                        suffix = "【A】" if "A" in sel_acc else "【B】"
                        # プレフィックス作成
                        base_p = f"デリじゃ{row['店名']}" if "デリじゃ" in sel_acc else (f"デイズ{row['店名']}" if "デイズ" in sel_acc else row['店名'])
                        folder_name = f"{base_p}{suffix}"
                        
                        # 簡易的に最初の1枚を表示
                        blobs = list(bucket.list_blobs(prefix=f"{row['エリア']}/{folder_name}/"))
                        img_found = False
                        for b in blobs:
                            if b.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                                st.image(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(b.name)}", use_container_width=True)
                                img_found = True
                                break
                        if not img_found: st.caption("画像なし")

                    # テキスト編集
                    with col_txt:
                        new_title = st.text_input("タイトル", value=row["タイトル"])
                        new_body = st.text_area("本文", value=row["本文"], height=150)
                        
                        if st.form_submit_button("💾 この日記を更新"):
                            ws = GC.open_by_key(SHEET_ID).worksheet(SHEET_MAP[sel_acc])
                            # デイズなら書き込み先を+1列ずらす補正
                            offset = 1 if "デイズ" in sel_acc else 0
                            ws.update_cell(row['__row__'], 5 + offset, new_title) # タイトル
                            ws.update_cell(row['__row__'], 6 + offset, new_body)  # 本文
                            st.success("更新しました")
                            st.cache_data.clear()
                            st.rerun()
    else:
        st.info("データがありません")

# ---------------------------------------------------------
# Tab 2: 📊 店舗アカウント状況 (大宮版ロジック移植)
# ---------------------------------------------------------
with tab2:
    st.markdown("## 📊 店舗アカウント状況")
    
    status_sheets = {
        "駅ちか": "駅ちかアカウント",
        "デリじゃ": "デリじゃアカウント",
        "デイズ": "デイズアカウント"
    }

    try:
        status_sprs = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID)
        
        for media_name, ws_name in status_sheets.items():
            st.markdown(f"### 📱 {media_name}")
            
            # --- 件数表示 (B列のみ取得で爆速化) ---
            c_a, c_b = st.columns(2)
            for i, suffix in enumerate(["A", "B"]):
                acc_key = f"{media_name}{suffix}"
                with [c_a, c_b][i]:
                    try:
                        s_name = SHEET_MAP.get(acc_key)
                        ws_work = GC.open_by_key(SHEET_ID).worksheet(s_name)
                        # B列(店名)のみ取得
                        count = len([x for x in ws_work.col_values(2)[1:] if x.strip()])
                    except: count = 0
                    st.metric(label=f"{acc_key} 投稿数", value=f"{count} 件")
            
            # --- エリア別店舗リスト (横並び) ---
            ws_link = status_sprs.worksheet(ws_name)
            link_data = ws_link.get_all_values()
            
            if len(link_data) > 1:
                area_map = {}
                for r in link_data[1:]:
                    if len(r) >= 2:
                        area, shop = r[0].strip(), r[1].strip()
                        if not area: area = "不明"
                        if area not in area_map: area_map[area] = []
                        area_map[area].append(shop)
                
                # エリアごとにカラムを動的生成
                areas = sorted(area_map.keys())
                if areas:
                    cols = st.columns(len(areas))
                    for idx, a_name in enumerate(areas):
                        with cols[idx]:
                            st.info(f"📍 **{a_name}**")
                            for s in sorted(area_map[a_name]):
                                st.write(f"• {s}")
            else:
                st.caption("登録なし")
            st.divider()

    except Exception as e:
        st.error(f"ステータス取得エラー: {e}")

# --- 実行 ---
if __name__ == "__main__":
    pass
