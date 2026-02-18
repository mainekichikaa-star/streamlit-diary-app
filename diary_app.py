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

def normalize_text(s):
    if not s: return ""
    # 全角・半角スペースをすべて削除し、小文字に統一する
    return re.sub(r'\s+', '', str(s)).replace('　', '').lower()

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

# --- 究極のAPI対策：キャッシュ読み込み関数 ---
@st.cache_data(ttl=600)
def get_full_sheet_data(sheet_id, update_tick): # 引数をシンプルに
    """全投稿シートのデータを一括で取得してキャッシュする"""
    results = {}
    # 定義済みの SHEET_MAP {"駅ちかA": "投稿駅ちかA", ...} を使う
    for acc_name, s_name in SHEET_MAP.items():
        try:
            ws = GC.open_by_key(sheet_id).worksheet(s_name)
            data = ws.get_all_values()
            results[acc_name] = data if len(data) > 1 else []
        except:
            results[acc_name] = []
    return results
    
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
# --- Tab 1: 📝 ① データ登録 ---
# =========================================================
with tab1:
    st.header("1️⃣ 浜松版：新規データ登録")
    
    # --- 投稿スケジュール案内 (UI改善版) ---
    st.markdown("""
        <div style="background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #FF4B4B; margin-bottom: 20px;">
            <p style="margin: 0; font-size: 0.9rem; color: #555;">📅 <b>投稿スケジュール説明</b></p>
            <div style="display: flex; gap: 20px; margin-top: 5px;">
                <div style="flex: 1;"><b>パターン A:</b> 月曜日・水曜日・金曜日</div>
                <div style="flex: 1;"><b>パターン B:</b> 火曜日・木曜日・土曜日・日曜日</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    # -----------------------------------
    
    # リアルタイム切り替えのためフォームの外に配置
    c1, c2, c3 = st.columns(3)
    target_acc = c1.selectbox("👤 投稿アカウント", ACCOUNT_OPTIONS, key="sel_acc_f")
    
    target_media = "駅ちか" if "駅ちか" in target_acc else "デリじゃ" if "デリじゃ" in target_acc else "デイズ" if "デイズ" in target_acc else "不明"
    
    global_area = c2.text_input("📍 エリア", key="in_area_f")
    global_store = c3.text_input("🏢 店名", key="in_store_f")

    with st.form("diary_input_form", clear_on_submit=False):
        st.subheader("🔑 ログイン情報")
        if target_media == "デイズ":
            lc1, lc2, lc3 = st.columns(3)
            login_num = lc1.text_input("管理画面ナンバー", key="login_num_f") 
            login_id = lc2.text_input("ID", key="login_id_f")
            login_pw = lc3.text_input("パスワード", key="login_pw_f")
        else:
            lc1, lc2 = st.columns(2)
            login_id = lc1.text_input("ID", key="login_id_f")
            login_pw = lc2.text_input("パスワード", key="login_pw_f")
            login_num = "" 

        st.markdown("---")
        st.subheader("📸 投稿内容入力 (最大40件)")

        # 各列の項目名を表示するように修正（collapsedを削除）
        form_entries = []
        for i in range(40):
            cols = st.columns([1, 1, 2, 3, 2])
            # 最初の1行目だけラベルを表示する設定
            l_vis = "visible" if i == 0 else "collapsed"
            
            e_time = cols[0].text_input("時間", key=f"f_t_{i}", label_visibility=l_vis)
            e_name = cols[1].text_input("名前", key=f"f_n_{i}", label_visibility=l_vis)
            e_title = cols[2].text_area("タイトル", key=f"f_ti_{i}", height=68, label_visibility=l_vis)
            e_body = cols[3].text_area("本文", key=f"f_b_{i}", height=68, label_visibility=l_vis)
            e_img = cols[4].file_uploader("画像", key=f"f_img_{i}", label_visibility=l_vis)
            form_entries.append({'投稿時間': e_time, '女の子の名前': e_name, 'タイトル': e_title, '本文': e_body, 'img': e_img})

        submit_button = st.form_submit_button("🔥 データを一括登録する", type="primary", use_container_width=True)

    if submit_button:
        valid_data = [e for e in form_entries if e['投稿時間'] and e['女の子の名前']]
        if not valid_data or not global_area or not global_store:
            st.error("⚠️ 入力不足：エリア、店名、および少なくとも1件以上の「時間・名前」を入力してください。")
        else:
            progress_text = st.empty()
            try:
                # 1. 前処理（画像フォルダ名）
                clean_store_name = normalize_text(global_store) 
                
                # 2. 画像アップロード
                progress_text.info("📸 画像をアップロード中...")
                for e in valid_data:
                    if e['img']: 
                        gcs_upload_wrapper(e['img'], e, global_area, clean_store_name, target_media, target_acc)
                
                # 3. 日記文を一括登録 (ここからインデントを修正)
                progress_text.info("📝 日記データを一括送信中...")
                ws_main = GC.open_by_key(SHEET_ID).worksheet(SHEET_MAP[target_acc])

                rows_main = []
                for e in valid_data:
                    if "デイズ" in target_acc:
                        # デイズ専用：0:エリア, 1:店名, 2:時間, 3:名前, 4:URL(空), 5:タイトル, 6:本文
                        row = [
                            global_area, 
                            global_store, 
                            f"'{e['投稿時間']}", 
                            e['女の子の名前'], 
                            "", # 4列目のURL列を空にする
                            e['タイトル'], 
                            e['本文']
                        ]
                    else:
                        # その他：0:エリア, 1:店名, 2:時間, 3:名前, 4:タイトル, 5:本文
                        row = [
                            global_area, 
                            global_store, 
                            f"'{e['投稿時間']}", 
                            e['女の子の名前'], 
                            e['タイトル'], 
                            e['本文']
                        ]
                    rows_main.append(row)

                # 書き込み実行
                ws_main.append_rows(rows_main, value_input_option='USER_ENTERED')
                
                # 4. ログイン情報を登録
                progress_text.info("🔐 ログイン情報を登録中...")
                ws_status = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID).worksheet(f"{target_media}アカウント")
                if target_media == "デイズ":
                    status_row = [global_area, global_store, login_num, login_id, login_pw]
                else:
                    status_row = [global_area, global_store, login_id, login_pw]
                ws_status.append_row(status_row, value_input_option='USER_ENTERED')
                
                # 5. 完了処理
                progress_text.empty()
                st.success(f"✅ {len(valid_data)}件のデータを正常に登録しました！")
                
                import time
                time.sleep(2) 
                st.cache_data.clear()
                st.rerun()

            except Exception as e:
                if "429" in str(e):
                    st.error("⚠️ Googleの制限により一時的に登録できません。30秒ほど待ってから再度お試しください。")
                else:
                    st.error(f"❌ 登録エラーが発生しました: {e}")
                
# =========================================================
# --- Tab 2: 📊 ② 店舗アカウント状況 ---
# =========================================================
with tab2:
    # 1. 更新用ボタンを配置
    if 'update_tick' not in st.session_state:
        st.session_state.update_tick = 0
    
    # --- 【営業時間（10時〜翌6時）を考慮した正確な曜日判定】 ---
    import datetime
    now = datetime.datetime.now()
    # 朝6時より前なら、判定用の日付を「昨日」にする
    logic_date = now - datetime.timedelta(days=1) if now.hour < 6 else now
    
    weekday = logic_date.weekday()  # 0:月...6:日
    is_pattern_a = weekday in [0, 2, 4] # 月水金判定
    
    # --- UIデザインの修正（タグ漏れ・崩れを完全に防ぐ構造） ---
    def get_card_html(p_name, p_days, is_active):
        style = (
            "flex: 1; padding: 18px; border-radius: 12px; position: relative; "
            "border: 2px solid #FF4B4B; background-color: #fff1f1; opacity: 1; box-shadow: 0 4px 12px rgba(255,75,75,0.1);"
            if is_active else
            "flex: 1; padding: 18px; border-radius: 12px; position: relative; "
            "border: 1px solid #eee; background-color: #fcfcfc; opacity: 0.4;"
        )
        badge = '<div style="color: #FF4B4B; font-weight: bold; font-size: 0.85rem; margin-top: 8px;">● 現在の稼働曜日</div>' if is_active else ""
        
        return f"""
        <div style="{style}">
            <div style="font-size: 0.8rem; color: #666; margin-bottom: 4px; letter-spacing: 0.05em;">{p_name}</div>
            <div style="font-weight: bold; font-size: 1.1rem; color: #333;">{p_days}</div>
            {badge}
        </div>
        """

    st.markdown(f"""
        <div style="display: flex; gap: 15px; margin-bottom: 30px; align-items: stretch;">
            {get_card_html("PATTERN A", "月曜 ・ 水曜 ・ 金曜", is_pattern_a)}
            {get_card_html("PATTERN B", "火曜 ・ 木曜 ・ 土曜 ・ 日曜", not is_pattern_a)}
        </div>
    """, unsafe_allow_html=True)

    # --- ヘッダー・更新ボタン ---
    col_h, col_btn = st.columns([3, 1])
    with col_h:
        st.markdown(f"## 📈 現在の稼働状況 <small style='font-size:0.5em; color:#999;'>（判定基準日: {logic_date.strftime('%m/%d')}）</small>", unsafe_allow_html=True)
    with col_btn:
        if st.button("🔄 状況を最新に更新", use_container_width=True):
            st.session_state.update_tick += 1
            st.cache_data.clear()
            st.rerun()

    st.caption("※ API保護のため10分間キャッシュされます。")
    st.divider()

    # 2. キャッシュされたデータを取得
    with st.spinner("データを取得中..."):
        all_data_cached = get_all_accounts_data_cached(st.session_state.update_tick)

    # 3. 表示ロジック（そのまま継続）
    groups = {{
        "駅ちか": ["駅ちかA", "駅ちかB"],
        "デリじゃ": ["デリじゃA", "デリじゃB"],
        "デイズ": ["デイズA", "デイズB"]
    }}

    for label, accounts in groups.items():
        with st.container():
            st.markdown(f"### 📱 {label} グループ")
            c_met1, c_met2 = st.columns(2)
            valid_dfs = []
            
            for idx, acc_name in enumerate(accounts):
                data = all_data_cached.get(acc_name, [])
                if data:
                    df = pd.DataFrame(data[1:])
                    # 空行除外（浜松版: 1列目が店名）
                    count = len(df[df[1].str.strip() != ""])
                    valid_dfs.append(df)
                else:
                    count = 0
                
                with [c_met1, c_met2][idx]:
                    st.metric(label=f"👤 {acc_name}", value=f"{count} 件")
            
            # 店舗リスト表示
            if valid_dfs:
                st.markdown("#### 📍 登録中の店舗一覧")
                full_df = pd.concat(valid_dfs)
                # 2列目（インデックス1）が店名
                full_df = full_df[full_df[1].str.strip() != ""]
                
                area_map = {}
                for _, r in full_df.iterrows():
                    a_name = r[0].strip() if r[0] else "未設定"
                    s_name = r[1].strip()
                    if a_name not in area_map: area_map[a_name] = set()
                    area_map[a_name].add(s_name)
                
                sorted_areas = sorted(area_map.keys())
                if sorted_areas:
                    area_cols = st.columns(min(len(sorted_areas), 4))
                    for i, a_name in enumerate(sorted_areas):
                        with area_cols[i % 4]:
                            shops_html = "".join([f"<div>• {s}</div>" for s in sorted(area_map[a_name])])
                            st.markdown(f"""
                                <div class="area-card">
                                    <div style="color: #FF4B4B; font-weight: bold; border-bottom: 1px solid #eee; margin-bottom: 5px;">📍 {a_name}</div>
                                    <div style="font-size: 0.9em; line-height: 1.6;">{shops_html}</div>
                                </div>
                            """, unsafe_allow_html=True)
            st.divider()
            
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





























