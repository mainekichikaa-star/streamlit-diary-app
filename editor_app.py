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

def get_target_blobs(bucket, area, sel_acc, store_name):
    """
    GCS上のフォルダを全角・半角スペース問わず検索し、
    その配下にある「ファイル」のみを抽出して返す
    """
    suffix = "【A】" if "A" in sel_acc else "【B】"
    if "デリじゃ" in sel_acc:
        base_pattern = f"デリじゃ{store_name}{suffix}"
    elif "デイズ" in sel_acc:
        base_pattern = f"デイズ{store_name}{suffix}"
    else:
        base_pattern = f"{store_name}{suffix}"
    
    target_norm = normalize_text(base_pattern)
    
    # prefixを指定して絞り込み（list化して確実に取得）
    full_list = list(bucket.list_blobs(prefix=f"{area}/"))
    
    matched_blobs = []
    for blob in full_list:
        # blob.name の例: "富山/M.O.M 【A】/0501_松浦.jpg"
        path_parts = blob.name.split('/')
        
        # 階層が足りない（フォルダ自身など）場合はスキップ
        if len(path_parts) < 3:
            continue
            
        # フォルダ名の部分（例: "M.O.M 【A】"）を抽出して比較
        folder_part = path_parts[1]
        if normalize_text(folder_part) == target_norm:
            # ファイル名が存在する場合のみ追加
            if path_parts[2]:
                matched_blobs.append(blob)
                
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
@st.cache_resource(ttl=3600)
def get_clients():
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    gcs = storage.Client.from_service_account_info(st.secrets["gcp_service_account"])
    return gc, gcs

GC, GCS_CLIENT = get_clients()

@st.cache_data(ttl=600)
def get_full_sheet_data(sheet_key, worksheet_name):
    try:
        sh = GC.open_by_key(sheet_key)
        ws = sh.worksheet(worksheet_name)
        return ws.get_all_values()
    except Exception as e:
        return None

# --- 4. UI構築 ---
st.set_page_config(layout="wide", page_title="写メ日記投稿データ管理")

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
        
        data = get_full_sheet_data(SHEET_ID, SHEET_MAP[sel_acc])
        
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
            if st.button("🔄 最新データでスキャン", key="btn_reload_tab2", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
        data_tab2 = get_full_sheet_data(SHEET_ID, SHEET_MAP[sel_acc_tab2])
        if data_tab2 and len(data_tab2) > 1:
            raw_df2 = pd.DataFrame(data_tab2[1:])
            # デイズの列ズレ補正
            if "デイズ" in sel_acc_tab2:
                df2 = raw_df2[[0, 1, 2, 3, 5, 6, 7]]
            else:
                df2 = raw_df2.iloc[:, :7]
            
            df2.columns = DF_COLS
            df2 = df2[df2["店名"].str.strip() != ""]
            bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
            
            missing_images = []
            
            # --- 高速化のための修正：店舗ごとに画像をまとめてチェック ---
            # 進捗表示
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            unique_stores = df2[["エリア", "店名"]].drop_duplicates()
            total_stores = len(unique_stores)
            
            # 店舗ごとの画像リストをキャッシュする辞書
            store_blobs_cache = {}

            for i, (_, s_row) in enumerate(unique_stores.iterrows()):
                area_val = s_row["エリア"]
                store_val = s_row["店名"]
                status_text.text(f"🔍 スキャン中: {store_val}...")
                
                # その店舗の画像を全取得
                blobs = get_target_blobs(bucket, area_val, sel_acc_tab2, store_val)
                store_blobs_cache[(area_val, store_val)] = blobs
                progress_bar.progress((i + 1) / total_stores)

            # 各行の不備チェック
            for _, row in df2.iterrows():
                b_time = parse_to_datetime(row["投稿時間"])
                n_norm = normalize_text(row["女の子の名前"])
                
                if not n_norm: continue # 名前が空ならスキップ

                # キャッシュから取得
                blobs = store_blobs_cache.get((row['エリア'], row['店名']), [])
                
                # 判定ロジック
                matched = [
                    img.name for img in blobs 
                    if (n_norm in normalize_text(img.name.split('/')[-1]) or 
                        normalize_text(img.name.split('/')[-1]) in n_norm) 
                    and is_time_match(b_time, img.name.split('/')[-1])
                ]
                
                if not matched:
                    missing_images.append(row)

            # 結果表示
            status_text.empty()
            progress_bar.empty()

            st.subheader(f"❌ 画像がない日記 ({len(missing_images)}件)")
            if missing_images:
                # 1列でスッキリ表示
                for item in missing_images:
                    st.markdown(f'''
                        <div class="error-card">
                            <b>📍 {item["エリア"]} / {item["店名"]}</b><br>
                            👤 {item["女の子の名前"]} (⏰ {item["投稿時間"]})
                        </div>
                    ''', unsafe_allow_html=True)
            else:
                st.success("✅ 全ての日記に画像が紐付いています！")

   # =========================================================================
    # TAB 3: 店舗アカウント状況
    # =========================================================================
    with tab3:
        st.markdown("## 📊 店舗アカウント状況")
        
        status_sheets = {
            "駅ちか": "駅ちかアカウント",
            "デリじゃ": "デリじゃアカウント",
            "デイズ": "デイズアカウント"
        }

        try:
            status_sprs = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID)
            cols = st.columns(3)
            
            for i, (media_name, ws_name) in enumerate(status_sheets.items()):
                with cols[i]:
                    st.markdown(f"### 📱 {media_name}")
                    
                    # --- 【修正】写メ日記登録シートから実数を集計 ---
                    for suffix in ["A", "B"]:
                        acc_key = f"{media_name}{suffix}"
                        # SHEET_MAPから対象シートの全データを取得
                        raw_data = get_full_sheet_data(SHEET_ID, SHEET_MAP.get(acc_key, ""))
                        
                        if raw_data and len(raw_data) > 1:
                            # 2行目以降で「店名（1列目）」が入力されている行のみをカウント
                            valid_rows = [r for r in raw_data[1:] if len(r) > 1 and str(r[1]).strip() != ""]
                            actual_count = len(valid_rows)
                        else:
                            actual_count = 0
                        
                        st.write(f"{acc_key}")
                        st.markdown(f"## {actual_count} 件")
                    
                    st.divider()

                    # --- 【修正】店舗リストを最初から全表示 ---
                    st.markdown("##### 📍 登録店舗一覧")
                    ws_link = status_sprs.worksheet(ws_name)
                    link_data = ws_link.get_all_values()
                    
                    if len(link_data) > 1:
                        # エリアごとにグループ化
                        area_map = {}
                        for r in link_data[1:]:
                            if len(r) >= 2:
                                area, shop = r[0].strip(), r[1].strip()
                                if not area: area = "その他"
                                if area not in area_map: area_map[area] = []
                                area_map[area].append(shop)
                        
                        # エリア名と店舗名をプレーンテキストで表示
                        for area_name, shops in area_map.items():
                            st.markdown(f"**【{area_name}】**")
                            for s in sorted(shops):
                                st.text(f"  • {s}")
                            st.write("") # スペース
                    else:
                        st.caption("管理シートに登録がありません")

        except Exception as e:
            st.error(f"データの取得中にエラーが発生しました: {e}")
