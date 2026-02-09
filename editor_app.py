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
    GCS上のフォルダを全角・半角スペース問わず検索する
    """
    suffix = "【A】" if "A" in sel_acc else "【B】"
    if "デリじゃ" in sel_acc:
        base_pattern = f"デリじゃ{store_name}{suffix}"
    elif "デイズ" in sel_acc:
        base_pattern = f"デイズ{store_name}{suffix}"
    else:
        base_pattern = f"{store_name}{suffix}"
    
    target_norm = normalize_text(base_pattern)
    
    # エリア配下のフォルダ一覧を取得して正規化比較
    all_blobs = list(bucket.list_blobs(prefix=f"{area}/", delimiter='/'))
    prefixes = [folder for folder in all_blobs.owner if folder] # list_blobsの副作用でフォルダ擬きを取得
    
    # delimiterを使ったフォルダ取得が環境により不安定なため、prefixスキャンで絞り込み
    full_list = list(bucket.list_blobs(prefix=f"{area}/"))
    
    matched_blobs = []
    for blob in full_list:
        # パスの中のフォルダ部分を抽出して正規化比較
        path_parts = blob.name.split('/')
        if len(path_parts) >= 3:
            folder_part = path_parts[1]
            if normalize_text(folder_part) == target_norm:
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
            full_df = pd.DataFrame(data[1:])
            full_df = full_df.iloc[:, :7]
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
                            new_title = st.text_input("タイトル", row["タイトル"], key=f"ti_{idx}")
                            new_body = st.text_area("本文", row["本文"], key=f"bo_{idx}", height=400)
                            if st.button("💾 内容を保存", key=f"sv_{idx}", type="primary"):
                                ws = GC.open_by_key(SHEET_ID).worksheet(SHEET_MAP[sel_acc])
                                ws.update_cell(row['__row__'], 5, new_title) # 5列目: タイトル
                                ws.update_cell(row['__row__'], 6, new_body)  # 6列目: 本文
                                st.toast(f"{row['女の子の名前']} の日記を保存しました")

                        with col_img:
                            if matched_files:
                                for m_path in matched_files:
                                    st.image(get_cached_url(m_path), use_container_width=True)
                                    with st.popover("🗑️ 削除"):
                                        if st.button("実行する", key=f"del_{idx}_{m_path}"):
                                            bucket.blob(m_path).delete()
                                            st.rerun()
                            else:
                                st.error("🚨 画像なし")

                        with col_ops:
                            up_file = st.file_uploader("📥 画像追加", type=["jpg","png","jpeg"], key=f"up_{idx}")
                            if up_file:
                                if st.button("🚀 アップ", key=f"u_btn_{idx}"):
                                    # フォルダ名が動的なため、既存ファイルがある場合はそのパス、ない場合は標準形式で生成
                                    if store_blobs:
                                        folder_path = "/".join(store_blobs[0].name.split('/')[:-1]) + "/"
                                    else:
                                        # フォルダが空の場合のデフォルト（半角スペース）
                                        suffix = "【A】" if "A" in sel_acc else "【B】"
                                        f_name = f"デリじゃ {sel_store} {suffix}" if "デリじゃ" in sel_acc else (f"デイズ {sel_store} {suffix}" if "デイズ" in sel_acc else f"{sel_store} {suffix}")
                                        folder_path = f"{sel_area}/{f_name}/"
                                    
                                    blob_name = f"{folder_path}{row['投稿時間']}_{row['女の子の名前']}.jpg"
                                    bucket.blob(blob_name).upload_from_string(up_file.getvalue(), content_type="image/jpeg")
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
            df2 = pd.DataFrame(data_tab2[1:], columns=DF_COLS + [f"extra_{i}" for i in range(len(data_tab2[0])-7)])
            df2 = df2[df2["店名"].str.strip() != ""]
            bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
            
            missing_images = []
            for _, row in df2.iterrows():
                b_time = parse_to_datetime(row["投稿時間"])
                n_norm = normalize_text(row["女の子の名前"])
                
                # 柔軟なフォルダ検索を適用
                blobs = get_target_blobs(bucket, row['エリア'], sel_acc_tab2, row['店名'])
                matched = [img.name for img in blobs if (n_norm in normalize_text(img.name) or normalize_text(img.name) in n_norm) and is_time_match(b_time, img.name.split('/')[-1])]
                
                if not matched and row["女の子の名前"].strip() != "":
                    missing_images.append(row)
            
            store_counts = df2["店名"].value_counts()
            low_count_stores = store_counts[store_counts <= 20]

            c_err1, c_err2 = st.columns(2)
            with c_err1:
                st.subheader(f"❌ 画像がない日記 ({len(missing_images)}件)")
                for item in missing_images:
                    st.markdown(f'<div class="error-card"><b>📍 {item["エリア"]} / {item["店名"]}</b><br>👤 {item["女の子の名前"]} ({item["投稿時間"]})</div>', unsafe_allow_html=True)
            with c_err2:
                st.subheader(f"⚠️ 日記が少ない店舗 (20件以下)")
                for s_name, count in low_count_stores.items():
                    st.warning(f"🏢 **{s_name}**: 総数 `{count}` 件")

    # =========================================================================
    # TAB 3: 店舗アカウント状況
    # =========================================================================
    with tab3:
        st.markdown("## 📊 店舗アカウント状況")
        combined_data = []
        acc_summary = {}; acc_counts = {}
        try:
            for opt in ACCOUNT_OPTIONS:
                rows = get_full_sheet_data(SHEET_ID, SHEET_MAP[opt])
                if rows and len(rows) > 1:
                    for i, r in enumerate(rows[1:]):
                        if any(str(c).strip() for c in r[:7]):
                            combined_data.append([opt, i+2] + [r[j] if j<len(r) else "" for j in range(7)])
                            a, s = str(r[0]).strip(), str(r[1]).strip()
                            acc_counts[opt] = acc_counts.get(opt, 0) + 1
                            if opt not in acc_summary: acc_summary[opt] = {}
                            if a not in acc_summary[opt]: acc_summary[opt][a] = set()
                            acc_summary[opt][a].add(s)
        except: pass

        if combined_data:
            for acc_code in ACCOUNT_OPTIONS:
                count = acc_counts.get(acc_code, 0)
                st.markdown(f"### 👤 投稿{acc_code} `{count} 件`")
                if acc_code in acc_summary:
                    areas = acc_summary[acc_code]
                    area_cols = st.columns(len(areas) if len(areas) > 0 else 1)
                    for idx, (area_name, shops) in enumerate(areas.items()):
                        with area_cols[idx]:
                            st.info(f"📍 **{area_name}**")
                            for shop in sorted(shops):
                                st.checkbox(f"{shop}", key=f"move_{acc_code}_{area_name}_{shop}")
            
            selected_shops = [{"acc": k.split('_')[1], "area": k.split('_')[2], "shop": k.split('_')[3]} for k, v in st.session_state.items() if k.startswith("move_") and v]
            if selected_shops:
                if st.button("🚀 選択した店舗を【落ち店】へ移動する", type="primary", use_container_width=True):
                    import time
                    try:
                        sh_stock = GC.open_by_key("1e-iLey43A1t0bIBoijaXP55t5fjONdb0ODiTS53beqM")
                        ws_stock = sh_stock.sheet1
                        for item in selected_shops:
                            ws_main = GC.open_by_key(SHEET_ID).worksheet(SHEET_MAP[item['acc']])
                            main_data = ws_main.get_all_values()
                            for row_idx in range(len(main_data), 0, -1):
                                row = main_data[row_idx-1]
                                if len(row) >= 2 and row[1] == item['shop']:
                                    # タイトル:4, 本文:5 (0始まり)
                                    ws_stock.append_row([None, None, row[4], row[5]], value_input_option='USER_ENTERED')
                                    time.sleep(1.0)
                                    ws_main.delete_rows(row_idx)
                            
                            status_sprs = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID)
                            sheet_type = "デイズアカウント" if "デイズ" in item['acc'] else ("デリじゃアカウント" if "デリじゃ" in item['acc'] else "駅ちかアカウント")
                            ws_link = status_sprs.worksheet(sheet_type)
                            link_data = ws_link.get_all_values()
                            for row_idx in range(len(link_data), 0, -1):
                                if len(link_data[row_idx-1]) >= 2 and link_data[row_idx-1][1] == item['shop']:
                                    ws_link.delete_rows(row_idx)
                                    break
                        st.success("🎉 移動完了！")
                    except Exception as e:
                        st.error(f"エラー: {e}")

if __name__ == "__main__":
    main()
