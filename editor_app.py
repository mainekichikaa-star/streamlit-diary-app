import streamlit as st
import pandas as pd
import gspread
import datetime
import urllib.parse
import re
from google.cloud import storage

# --- 写メ日記投稿データ管理 ---

# --- 1. 定数・設定 ---
try:
    # 日記登録用シート ID
    SHEET_ID = "168X-3PJmQi07mP_FRkyhTHVtUNp5BsCM0rFgabABQUY"
    # アカウント状況用 ID
    ACCOUNT_STATUS_SHEET_ID = "1hlGAbImOpxREC25JW7xeApoYC-cJEt4O2Qz9xZT2EHE"
    
    # GCSバケット名
    GCS_BUCKET_NAME = "hamamatsu-auto-poster-images"
    
    # アカウント選択肢
    ACCOUNT_OPTIONS = ["駅ちかA", "駅ちかB", "デリじゃA", "デリじゃB", "デイズA", "デイズB"]
    SHEET_MAP = {opt: f"投稿{opt}" for opt in ACCOUNT_OPTIONS}
    
    # 全シート共通の列定義 (0:エリア, 1:店名, 2:投稿時間, 3:女の子の名前, 4:タイトル, 5:本文, 6:投稿ステータス)
    DF_COLS = ["エリア", "店名", "投稿時間", "女の子の名前", "タイトル", "本文", "投稿ステータス"]
    
except KeyError:
    st.error("🚨 secrets.tomlの設定を確認してください。")
    st.stop()

# --- 2. 補助関数 ---
def normalize_text(s):
    if not s: return ""
    return re.sub(r'\s+', '', str(s)).replace('　', '').lower()

@st.cache_data(ttl=300) # 5分間はファイル名のリストを使い回す
def get_cached_blob_names(area):
    """
    Blobオブジェクトそのものではなく、
    シリアライズ可能な「ファイル名（文字列）」のリストをキャッシュする
    """
    bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
    # blob.name (文字列) のリストにして返す
    return [blob.name for blob in bucket.list_blobs(prefix=f"{area}/")]

def get_target_blobs(bucket, area, sel_acc, store_name):
    suffix = "【A】" if "A" in sel_acc else "【B】"
    if "デリじゃ" in sel_acc:
        base_pattern = f"デリじゃ{store_name}{suffix}"
    elif "デイズ" in sel_acc:
        base_pattern = f"デイズ{store_name}{suffix}"
    else:
        base_pattern = f"{store_name}{suffix}"
    
    target_norm = normalize_text(base_pattern)
    
    # キャッシュされた「ファイル名のリスト」を取得
    full_name_list = get_cached_blob_names(area)
    
    matched_blobs = []
    for b_name in full_name_list:
        path_parts = b_name.split('/')
        if len(path_parts) < 3: continue
        
        folder_part = path_parts[1]
        if normalize_text(folder_part) == target_norm:
            if path_parts[2]:
                # 判定にマッチしたものだけ、bucket.blob() でオブジェクト化する
                matched_blobs.append(bucket.blob(b_name))
                
    return matched_blobs

def parse_to_datetime(t_str):
    t_clean = re.sub(r'[^0-9]', '', str(t_str))
    if len(t_clean) == 3: t_clean = "0" + t_clean
    if len(t_clean) == 4:
        try: return datetime.datetime.strptime(t_clean, "%H%M")
        except: return None
    return None

def is_time_match(base_time, target_filename, window_min=20):
    if not base_time: return False
    match = re.match(r'^(\d{3,4})', target_filename)
    if not match: return False
    t_target = parse_to_datetime(match.group(1))
    if not t_target: return False
    diff = abs((base_time - t_target).total_seconds()) / 60
    return diff <= window_min or diff >= (1440 - window_min)

def get_cached_url(blob_name):
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(blob_name)}"

# --- 3. API接続 & キャッシュ設定 ---
st.cache_resource(ttl=3600)
def get_clients():
    creds = st.secrets["gcp_service_account"]
    gc = gspread.service_account_from_dict(creds)
    gcs = storage.Client.from_service_account_info(creds)
    return gc, gcs

GC, GCS_CLIENT = get_clients()

# --- 究極のAPI対策：一括取得キャッシュ ---
@st.cache_data(ttl=600)
def get_all_accounts_data_cached(update_tick):
    """全てのアカウントの全データを一回で取得してキャッシュする"""
    results = {}
    for acc_name, s_name in SHEET_MAP.items():
        try:
            sh = GC.open_by_key(SHEET_ID)
            ws = sh.worksheet(s_name)
            results[acc_name] = ws.get_all_values()
        except:
            results[acc_name] = []
    return results

# 既存の関数は互換性のために残す（または書き換え）
@st.cache_data(ttl=600)
def get_full_sheet_data(sheet_key, worksheet_name):
    # この関数は単発用として維持
    try:
        sh = GC.open_by_key(sheet_key)
        ws = sh.worksheet(worksheet_name)
        return ws.get_all_values()
    except:
        return None

# --- 4. UI構築 ---
st.set_page_config(layout="wide", page_title="浜松・写メ日記投稿データ管理")

st.markdown("""
    <style>
    [data-testid="stHeader"] { display: none; }
    .block-container { padding-top: 1.5rem !important; padding-bottom: 0rem !important; }
    .stApp h1 { padding-top: 0px !important; margin-top: -15px !important; padding-bottom: 10px !important; margin-bottom: 0px !important; font-size: 1.8rem !important; }
    .filter-panel { background-color: #f1f3f6; padding: 12px 20px; border-radius: 10px; margin-top: 5px !important; margin-bottom: 15px; border: 1px solid #d1d5db; }
    .stTextArea textarea { font-size: 15px; line-height: 1.6; }
    .diary-divider { border-bottom: 2px solid #eee; padding-bottom: 30px; margin-bottom: 30px; }
    .error-card { background-color: #fff1f1; border-left: 5px solid #ff4b4b; padding: 10px; margin-bottom: 10px; border-radius: 5px; }
    </style>
""", unsafe_allow_html=True)

def main():
    st.title("📸 写メ日記投稿データ管理")
    
    # API更新用のカウンター
    if 'update_tick' not in st.session_state:
        st.session_state.update_tick = 0
    
    # 全データを一括取得（全タブでこれを使い回す）
    all_data_cached = get_all_accounts_data_cached(st.session_state.update_tick)
    
    tab1, tab2, tab3 = st.tabs(["📝 日記編集・画像管理", "🔍 データ不備チェック", "📊 店舗アカウント状況"])

    # =========================================================================
    # TAB 1: 日記編集・画像管理
    # =========================================================================
    with tab1:
        st.markdown('<div class="filter-panel">', unsafe_allow_html=True)
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1.5, 1, 0.8])
        
        with c1:
            sel_acc = st.selectbox("👤 アカウント", ACCOUNT_OPTIONS, index=0, key="acc_tab1")
        
        with c6:
            st.write("") 
            if st.button("🔄 更新", key="btn_reload_tab1", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        
        data = all_data_cached.get(sel_acc, [])
        
        if not data or len(data) <= 1:
            st.warning("有効なデータがありません。")
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            # --- 【修正点1】デイズの列ズレ補正ロジック ---
            raw_df = pd.DataFrame(data[1:])
            if "デイズ" in sel_acc:
                # デイズは 0:エリア, 1:店名, 2:投稿時間, 3:名前, 4:URL(skip), 5:タイトル, 6:本文, 7:ステータス
                # 4列目を除外して取得
                full_df = raw_df[[0, 1, 2, 3, 5, 6, 7]]
            else:
                full_df = raw_df.iloc[:, :7]
            
            while full_df.shape[1] < 7: full_df[full_df.shape[1]] = ""
            full_df.columns = DF_COLS
            full_df['__row__'] = range(2, len(data) + 1)
            full_df = full_df[full_df["店名"].str.strip() != ""]
            
            with c2:
                areas = sorted(full_df["エリア"].unique())
                sel_area = st.selectbox("📍 エリア", ["未選択"] + areas)
            
            sel_store = "未選択"
            with c3:
                if sel_area != "未選択":
                    stores = sorted(full_df[full_df["エリア"] == sel_area]["店名"].unique())
                    sel_store = st.selectbox("🏢 店舗", ["未選択"] + stores)
                else:
                    st.selectbox("🏢 店舗", ["エリアを選択"], disabled=True)
                    
            with c4:
                search_query = st.text_input("🔍 検索", placeholder="キーワード入力...")

            with c5:
                st.write("")
                bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
                if sel_store != "未選択":
                    matched_blobs = get_target_blobs(bucket, sel_area, sel_acc, sel_store)
                    if matched_blobs:
                        from io import BytesIO
                        import zipfile
                        buf = BytesIO()
                        with zipfile.ZipFile(buf, "w") as zf:
                            for b in matched_blobs:
                                zf.writestr(b.name.split('/')[-1], b.download_as_bytes())
                        st.download_button("📥 画像一括保存", buf.getvalue(), f"{sel_store}.zip", use_container_width=True)
                    else:
                        st.button("📥 画像なし", disabled=True, use_container_width=True)
                else:
                    st.button("📥 店舗選択", disabled=True, use_container_width=True)

            st.markdown('</div>', unsafe_allow_html=True)

            if sel_store != "未選択":
                target_df = full_df[(full_df["エリア"] == sel_area) & (full_df["店名"] == sel_store)]
                if search_query:
                    q = normalize_text(search_query)
                    target_df = target_df[target_df.apply(lambda r: q in normalize_text(r["女の子の名前"]) or q in normalize_text(r["タイトル"]), axis=1)]

                st.subheader(f"📊 {sel_store} ({len(target_df)} 件)")
                
                # 店舗配下の全画像をキャッシュ的に取得
                store_blobs = get_target_blobs(bucket, sel_area, sel_acc, sel_store)

                for idx, row in target_df.iterrows():
                    base_time = parse_to_datetime(row["投稿時間"])
                    name_norm = normalize_text(row["女の子の名前"])
                    
                    matched_files = [
                        img.name for img in store_blobs 
                        if (name_norm in normalize_text(img.name.split('/')[-1]) or normalize_text(img.name.split('/')[-1]) in name_norm) 
                        and is_time_match(base_time, img.name.split('/')[-1])
                    ]

                    with st.container():
                        st.markdown(f"#### 👤 {row['女の子の名前']} / ⏰ {row['投稿時間']} / 📱 {sel_acc}")
                        col_txt, col_img, col_ops = st.columns([2.5, 1, 1])

                        with col_txt:
                            # --- 投稿時間・タイトル・本文の入力 ---
                            new_time = st.text_input("投稿時間", row["投稿時間"], key=f"tm_{idx}")
                            new_title = st.text_input("タイトル", row["タイトル"], key=f"ti_{idx}")
                            new_body = st.text_area("本文", row["本文"], key=f"bo_{idx}", height=400)
                            
                            if st.button("💾 内容を保存", key=f"sv_{idx}", type="primary"):
                                ws = GC.open_by_key(SHEET_ID).worksheet(SHEET_MAP[sel_acc])
                                
                                # 1. GCS画像のリネーム（投稿時間が変更された場合）
                                if new_time != row["投稿時間"] and matched_files:
                                    for old_path in matched_files:
                                        folder_part = "/".join(old_path.split('/')[:-1]) + "/"
                                        old_filename = old_path.split('/')[-1]
                                        # ファイル名の先頭の時間を置換 (例: 0900_名前.jpg -> 1000_名前.jpg)
                                        new_filename = old_filename.replace(row["投稿時間"], new_time, 1)
                                        new_path = f"{folder_part}{new_filename}"
                                        
                                        # GCS上でコピー＆削除（リネーム）
                                        bucket.copy_blob(bucket.blob(old_path), bucket, new_path)
                                        bucket.blob(old_path).delete()

                                # 2. スプレッドシートの更新
                                # 投稿時間は共通で3列目(C列)
                                ws.update_cell(row['__row__'], 3, new_time)
                                
                                # デイズならURL列がある分、書き込み先を+1する (タイトル:5+offset, 本文:6+offset)
                                offset = 1 if "デイズ" in sel_acc else 0
                                ws.update_cell(row['__row__'], 5 + offset, new_title)
                                ws.update_cell(row['__row__'], 6 + offset, new_body)
                                
                                st.toast(f"{row['女の子の名前']} のデータを更新しました")
                                st.cache_data.clear()
                                st.rerun()

                        with col_img:
                            if matched_files:
                                for m_path in matched_files:
                                    st.image(get_cached_url(m_path), use_container_width=True)
                                    with st.popover("🗑️ 削除"):
                                        if st.button("実行する", key=f"del_{idx}_{m_path}"):
                                            bucket.blob(m_path).delete()
                                            st.cache_data.clear()
                                            st.rerun()
                            else:
                                st.error("🚨 画像なし")

                        with col_ops:
                            up_file = st.file_uploader("📥 画像追加", type=["jpg","png","jpeg"], key=f"up_{idx}")
                            if up_file:
                                if st.button("🚀 アップ", key=f"u_btn_{idx}"):
                                    if store_blobs:
                                        folder_path = "/".join(store_blobs[0].name.split('/')[:-1]) + "/"
                                    else:
                                        suffix = "【A】" if "A" in sel_acc else "【B】"
                                        f_name = f"デリじゃ {sel_store} {suffix}" if "デリじゃ" in sel_acc else (f"デイズ {sel_store} {suffix}" if "デイズ" in sel_acc else f"{sel_store} {suffix}")
                                        folder_path = f"{sel_area}/{f_name}/"
                                    
                                    # 現在入力されている時間でアップロード
                                    blob_name = f"{folder_path}{new_time}_{row['女の子の名前']}.jpg"
                                    bucket.blob(blob_name).upload_from_string(up_file.getvalue(), content_type="image/jpeg")
                                    st.cache_data.clear()
                                    st.rerun()
                        
                        st.markdown("<div class='diary-divider'></div>", unsafe_allow_html=True)

    # =========================================================================
    # TAB 2: データ不備チェック
    # =========================================================================
    with tab2:
        st.markdown('<div class="filter-panel">', unsafe_allow_html=True)
        ce1, ce2 = st.columns([5, 1])
        with ce1:
            sel_acc_tab2 = st.selectbox("👤 対象アカウント", ACCOUNT_OPTIONS, index=0, key="acc_tab2")
        with ce2:
            st.write("")
            if st.button("🔄 キャッシュクリア", key="btn_clear_tab2", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # 自動実行を防ぎ、ボタン押下時のみスキャンする
        if st.button("🔍 不備チェック（画像なし確認）を開始", key="run_scan_tab2", type="primary", use_container_width=True):
            data_tab2 = all_data_cached.get(sel_acc_tab2, [])
            if data_tab2 and len(data_tab2) > 1:
                raw_df2 = pd.DataFrame(data_tab2[1:])
                if "デイズ" in sel_acc_tab2:
                    df2 = raw_df2[[0, 1, 2, 3, 5, 6, 7]]
                else:
                    df2 = raw_df2.iloc[:, :7]
                
                df2.columns = DF_COLS
                df2 = df2[df2["店名"].str.strip() != ""]
                bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
                
                missing_images = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                unique_stores = df2[["エリア", "店名"]].drop_duplicates()
                total_stores = len(unique_stores)
                store_blobs_cache = {}

                for i, (_, s_row) in enumerate(unique_stores.iterrows()):
                    area_val, store_val = s_row["エリア"], s_row["店名"]
                    status_text.text(f"🔍 スキャン中: {store_val}...")
                    # 通信回数を抑えるため店舗ごとに取得
                    store_blobs_cache[(area_val, store_val)] = get_target_blobs(bucket, area_val, sel_acc_tab2, store_val)
                    progress_bar.progress((i + 1) / total_stores)

                for _, row in df2.iterrows():
                    b_time = parse_to_datetime(row["投稿時間"])
                    n_norm = normalize_text(row["女の子の名前"])
                    if not n_norm: continue
                    
                    blobs = store_blobs_cache.get((row['エリア'], row['店名']), [])
                    matched = [img.name for img in blobs if (n_norm in normalize_text(img.name.split('/')[-1]) or normalize_text(img.name.split('/')[-1]) in n_norm) and is_time_match(b_time, img.name.split('/')[-1])]
                    
                    if not matched:
                        missing_images.append(row)

                status_text.empty()
                progress_bar.empty()

                st.subheader(f"❌ 画像がない日記 ({len(missing_images)}件)")
                for item in missing_images:
                    st.markdown(f'<div class="error-card"><b>📍 {item["エリア"]} / {item["店名"]}</b><br>👤 {item["女の子の名前"]} ({item["投稿時間"]})</div>', unsafe_allow_html=True)
        else:
            st.info("「不備チェックを開始」ボタンを押すと、スプレッドシートと画像の照合を開始します。")

    # =========================================================================
    # --- TAB 3: 店舗アカウント状況 (UIブラッシュアップ版) ---
    # =========================================================================
    with tab3:
        # --- スタイル定義 ---
        st.markdown("""
            <style>
            [data-testid="stMetric"] {
                background-color: #f8f9fb;
                padding: 15px;
                border-radius: 10px;
                box-shadow: inset 0 0 5px rgba(0,0,0,0.05);
                border: 1px solid #eee;
            }
            .status-area-card {
                background-color: #ffffff;
                border: 1px solid #e1e4e8;
                padding: 12px;
                border-radius: 8px;
                margin-bottom: 12px;
                min-height: 100px;
            }
            .area-title {
                color: #FF4B4B;
                font-weight: 800;
                font-size: 0.9em;
                border-bottom: 1.5px solid #f0f2f6;
                margin-bottom: 8px;
                padding-bottom: 4px;
            }
            .shop-list {
                font-size: 0.85em;
                line-height: 1.5;
                color: #333;
            }
            </style>
        """, unsafe_allow_html=True)

        # --- 曜日判定ロジック ---
        import datetime
        now = datetime.datetime.now()
        logic_date = now - datetime.timedelta(days=1) if now.hour < 6 else now
        weekday = logic_date.weekday()
        is_pattern_a = weekday in [0, 2, 4] # 月水金判定

        def get_status_card_html(p_name, p_days, is_active):
            style = (
                "flex: 1; padding: 15px; border-radius: 12px; position: relative; "
                "border: 2px solid #FF4B4B; background-color: #fff1f1; opacity: 1;"
                if is_active else
                "flex: 1; padding: 15px; border-radius: 12px; position: relative; "
                "border: 1px solid #eee; background-color: #fcfcfc; opacity: 0.4;"
            )
            badge = '<div style="color: #FF4B4B; font-weight: bold; font-size: 0.8rem; margin-top: 5px;">● 現在の稼働曜日</div>' if is_active else ""
            return f"""
            <div style="{style}">
                <div style="font-size: 0.75rem; color: #666; margin-bottom: 2px;">{p_name}</div>
                <div style="font-weight: bold; font-size: 1rem; color: #333;">{p_days}</div>
                {badge}
            </div>
            """

        # 共通の稼働表示
        st.markdown(f"""
            <div style="display: flex; gap: 12px; margin-bottom: 20px; align-items: stretch;">
                {get_status_card_html("PATTERN A", "月曜 ・ 水曜 ・ 金曜", is_pattern_a)}
                {get_status_card_html("PATTERN B", "火曜 ・ 木曜 ・ 土曜 ・ 日曜", not is_pattern_a)}
            </div>
        """, unsafe_allow_html=True)

        st.markdown(f"## 📊 店舗稼働ステータス <small style='font-size:0.5em; color:#999;'>（判定基準日: {logic_date.strftime('%m/%d')}）</small>", unsafe_allow_html=True)
        st.caption("管理シートに基づいた店舗リストと、現在のアカウント投稿件数を表示しています。")
        st.divider()

        # --- 管理シート読み込み ---
        status_sheets = {
            "駅ちか": "駅ちかアカウント",
            "デリじゃ": "デリじゃアカウント",
            "デイズ": "デイズアカウント"
        }

        try:
            status_sprs = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID)
            for media_name, ws_name in status_sheets.items():
                st.markdown(f"### 📱 {media_name} グループ")
                m_col1, m_col2 = st.columns(2)
                
                def count_valid_rows(rows):
                    if not rows or len(rows) <= 1: return 0
                    count = 0
                    for r in rows[1:]:
                        if len(r) < 2: continue
                        shop_name = r[1].strip()
                        post_time = r[2].strip() if len(r) > 2 else ""
                        if shop_name != "" and post_time != "":
                            count += 1
                    return count

                count_a = count_valid_rows(all_data_cached.get(f"{media_name}A", []))
                count_b = count_valid_rows(all_data_cached.get(f"{media_name}B", []))

                with m_col1:
                    st.metric(label=f"👤 {media_name}A 投稿数", value=f"{count_a} 件")
                with m_col2:
                    st.metric(label=f"👤 {media_name}B 投稿数", value=f"{count_b} 件")

                ws_link = status_sprs.worksheet(ws_name)
                link_data = ws_link.get_all_values()
                
                if len(link_data) > 1:
                    area_map = {}
                    for r in link_data[1:]:
                        if len(r) >= 2:
                            area = r[0].strip() if r[0].strip() else "未設定"
                            shop = r[1].strip()
                            if shop:
                                if area not in area_map: area_map[area] = []
                                area_map[area].append(shop)
                    
                    sorted_areas = sorted(area_map.keys())
                    if sorted_areas:
                        cols_status = st.columns(4)
                        for idx, area_name in enumerate(sorted_areas):
                            with cols_status[idx % 4]:
                                shops_html = "".join([f"<div>• {s}</div>" for s in sorted(area_map[area_name])])
                                st.markdown(f"""
                                    <div class="status-area-card">
                                        <div class="area-title">📍 {area_name} ({len(area_map[area_name])})</div>
                                        <div class="shop-list">
                                            {shops_html}
                                        </div>
                                    </div>
                                """, unsafe_allow_html=True)
                else:
                    st.info("💡 管理シートに登録されている店舗はありません。")
                
                st.divider()

        except Exception as e:
            st.error(f"❌ データの取得中にエラーが発生しました: {e}")
            
if __name__ == "__main__":
    main()









