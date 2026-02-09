import streamlit as st
import pandas as pd
import gspread
import zipfile
import datetime
import re
from io import BytesIO
from datetime import timedelta
from google.oauth2.service_account import Credentials
from google.cloud import storage 
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- 1. 定数と初期設定 ---
try:
    SHEET_ID = st.secrets["google_resources"]["spreadsheet_id"] 
    ACCOUNT_STATUS_SHEET_ID = "1_GmWjpypap4rrPGNFYWkwcQE1SoK3QOMJlozEhkBwVM"
    USABLE_DIARY_SHEET_ID = "1e-iLey43A1t0bIBoijaXP55t5fjONdb0ODiTS53beqM"
    
    GCS_BUCKET_NAME = "auto-poster-images"

    SHEET_NAMES = st.secrets["sheet_names"]
    POSTING_ACCOUNT_SHEETS = {
        "A": "投稿Aアカウント",
        "B": "投稿Bアカウント",
        "C": "投稿Cアカウント",
        "D": "投稿Dアカウント"
    }
    
    USABLE_DIARY_SHEET = "【使用可能日記文】"
    MEDIA_OPTIONS = ["駅ちか", "デリじゃ"]
    POSTING_ACCOUNT_OPTIONS = ["A", "B", "C", "D"] 
    
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/cloud-platform']
except KeyError:
    st.error("🚨 secrets.tomlの設定を確認してください。")
    st.stop()

REGISTRATION_HEADERS = ["エリア", "店名", "媒体", "投稿時間", "女の子の名前", "タイトル", "本文"]
INPUT_HEADERS = ["投稿時間", "女の子の名前", "タイトル", "本文"]

# --- 2. 各種API連携 ---
@st.cache_resource(ttl=3600)
def get_gspread_client():
    """スプレッドシートAPIのクライアントを作成"""
    return gspread.service_account_from_dict(st.secrets["gcp_service_account"])

@st.cache_resource(ttl=3600)
def get_gcs_client():
    """Google Cloud Storageのクライアントを作成"""
    from google.cloud import storage
    return storage.Client.from_service_account_info(st.secrets["gcp_service_account"])

try:
    # 1. まずクライアントを作成
    GC = get_gspread_client()
    GCS_CLIENT = get_gcs_client()
    
    # 2. スプレッドシートを開く
    SPRS = GC.open_by_key(SHEET_ID)
    STATUS_SPRS = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID)
    
except Exception as e:
    # 429エラー（制限超過）の場合は専用メッセージ
    if "429" in str(e):
        st.error("🚨 Google APIの制限を超えました。1分ほど待ってから再読み込みしてください。")
    elif "name 'get_gcs_client'" in str(e):
        st.error("🚨 関数定義が不足しています。修正コードを反映してください。")
    else:
        st.error(f"❌ API接続失敗: {e}")
    st.stop()
    
def gcs_upload_wrapper(uploaded_file, entry, area, store):
    try:
        bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
        folder_name = f"デリじゃ {store}" if st.session_state.global_media == "デリじゃ" else store
        ext = uploaded_file.name.split('.')[-1]
        blob_path = f"{area}/{folder_name}/{entry['投稿時間'].strip()}_{entry['女の子の名前'].strip()}.{ext}"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(uploaded_file.getvalue(), content_type=uploaded_file.type)
        return True
    except Exception as e:
        st.error(f"❌ GCSアップロード失敗: {e}")
        return False

def get_cached_url(blob_name):
    import urllib.parse
    # 文字列を結合するだけ（API通信なし）
    safe_path = urllib.parse.quote(blob_name)
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{safe_path}"
    
# --- 3. UI 構築 ---
st.set_page_config(layout="wide", page_title="写メ日記投稿管理")

st.markdown("""
    <style>
    .block-container { padding-top: 0rem !important; padding-bottom: 0rem !important; }
    header[data-testid="stHeader"] { display: none !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; height: 80px; }
    button[data-baseweb="tab"] {
        font-size: 32px !important; font-weight: 800 !important; height: 70px !important;
        padding: 0px 30px !important; background-color: #f0f2f6 !important;
        border-radius: 10px 10px 0px 0px !important; margin-right: 5px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: white !important; background-color: #FF4B4B !important;
    }
    .sticky-header-row {
        position: -webkit-sticky;
        position: sticky;
        top: 0px;
        z-index: 1000;
        background-color: white !important;
        padding: 10px 0px;
        margin-bottom: 5px;
    }
    </style>
""", unsafe_allow_html=True)

if 'diary_entries' not in st.session_state:
    st.session_state.diary_entries = [{h: "" for h in INPUT_HEADERS} for _ in range(40)]

# タブ構成の更新
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📝 ① データ登録", 
    "📊 ② 店舗アカウント状況", 
    "📂 ③ 投稿日記文管理", 
    "📸 ④ 投稿画像管理",
    "📚 ⑤ 使用可能日記文",
    "🖼 ⑥ 使用可能画像"
])

combined_data = []
acc_summary = {}; acc_counts = {}
try:
    all_ws = SPRS.worksheets()
    ws_dict = {ws.title: ws for ws in all_ws}
    for code, s_name in POSTING_ACCOUNT_SHEETS.items():
        if s_name in ws_dict:
            rows = ws_dict[s_name].get_all_values()
            if len(rows) > 1:
                for i, r in enumerate(rows[1:]):
                    if any(str(c).strip() for c in r[:7]):
                        combined_data.append([code, i+2] + [r[j] if j<len(r) else "" for j in range(7)])
                        a, s, m = str(r[0]).strip(), str(r[1]).strip(), str(r[2]).strip()
                        acc_counts[code] = acc_counts.get(code, 0) + 1
                        if code not in acc_summary: acc_summary[code] = {}
                        if a not in acc_summary[code]: acc_summary[code][a] = set()
                        acc_summary[code][a].add(f"{m} : {s}")
except: pass

# =========================================================
# --- Tab 1: 📝 ① データ登録 (完全リロード停止・安定版) ---
# =========================================================
with tab1:
    st.header("1️⃣ 新規データ登録")
    
    # 💡 st.form を使うことで「送信ボタンを押すまで一切リロードしない」状態を作ります
    with st.form("diary_input_form", clear_on_submit=False):
        # 基本情報
        c1, c2, c3, c4 = st.columns(4)
        target_acc = c1.selectbox("👤 投稿アカウント", POSTING_ACCOUNT_OPTIONS, key="sel_acc_f")
        target_media = c2.selectbox("🌐 媒体", MEDIA_OPTIONS, key="sel_media_f")
        global_area = c3.text_input("📍 エリア", key="in_area_f")
        global_store = c4.text_input("🏢 店名", key="in_store_f")
        
        st.subheader("🔑 ログイン情報")
        c5, c6 = st.columns(2)
        login_id = c5.text_input("ID", key="login_id_f")
        login_pw = c6.text_input("パスワード", key="login_pw_f")
        
        st.markdown("---")
        st.subheader("📸 投稿内容入力")

        # ヘッダー固定表示（HTML）
        st.markdown("""
            <div style="display: flex; flex-direction: row; border-bottom: 2px solid #444; background-color: #f0f2f6; padding: 10px; border-radius: 5px 5px 0 0;">
                <div style="flex: 1; font-weight: bold; color: black;">時間</div>
                <div style="flex: 1; font-weight: bold; color: black;">名前</div>
                <div style="flex: 2; font-weight: bold; color: black;">タイトル</div>
                <div style="flex: 3; font-weight: bold; color: black;">本文</div>
                <div style="flex: 2; font-weight: bold; color: black;">画像</div>
            </div>
        """, unsafe_allow_html=True)

        # フォーム内の入力を受け取るためのリスト
        form_entries = []
        for i in range(40):
            cols = st.columns([1, 1, 2, 3, 2])
            e_time = cols[0].text_input(f"t{i}", key=f"f_t_{i}", label_visibility="collapsed")
            e_name = cols[1].text_input(f"n{i}", key=f"f_n_{i}", label_visibility="collapsed")
            e_title = cols[2].text_area(f"ti{i}", key=f"f_ti_{i}", height=68, label_visibility="collapsed")
            e_body = cols[3].text_area(f"b{i}", key=f"f_b_{i}", height=68, label_visibility="collapsed")
            e_img = cols[4].file_uploader(f"g{i}", key=f"f_img_{i}", label_visibility="collapsed")
            
            form_entries.append({
                '投稿時間': e_time, 
                '女の子の名前': e_name, 
                'タイトル': e_title, 
                '本文': e_body, 
                'img': e_img
            })

        # 💡 Form専用の送信ボタン（これ以外の操作ではリロードが発生しません）
        submit_button = st.form_submit_button("🔥 データを一括登録する", type="primary", use_container_width=True)

    # 送信ボタンが押された後の処理（ここからAPIが動く）
    if submit_button:
        valid_data = [e for e in form_entries if e['投稿時間'] and e['女の子の名前']]
        if not valid_data or not global_area or not global_store:
            st.error("⚠️ 入力不足：エリア、店名、および少なくとも1件以上の「時間・名前」を入力してください。")
        else:
            progress_text = st.empty()
            try:
                # 1. 画像アップロード
                progress_text.info("📸 画像をアップロード中...")
                for e in valid_data:
                    if e['img']: 
                        # 画像アップロード関数をそのまま使用（e['img']を渡す）
                        gcs_upload_wrapper(e['img'], e, global_area, global_store)
                
                # 2. スプレッドシート（日記）登録
                progress_text.info("📝 日記文を登録中...")
                ws_main = SPRS.worksheet(POSTING_ACCOUNT_SHEETS[target_acc])
                rows_main = [[global_area, global_store, target_media, e['投稿時間'], e['女の子の名前'], e['タイトル'], e['本文']] for e in valid_data]
                ws_main.append_rows(rows_main, value_input_option='USER_ENTERED')
                
                # 3. スプレッドシート（ステータス）登録
                progress_text.info("🔐 ログイン情報を登録中...")
                ws_status = STATUS_SPRS.worksheet(POSTING_ACCOUNT_SHEETS[target_acc])
                ws_status.append_row([global_area, global_store, target_media, login_id, login_pw], value_input_option='USER_ENTERED')
                
                progress_text.empty()
                st.success(f"✅ {len(valid_data)}件のデータを正常に登録しました！")
                
                # キャッシュを消去して他タブにも反映
                st.cache_data.clear()
                # 登録完了後に画面をクリアするためにリロード
                st.rerun()

            except Exception as e:
                st.error(f"❌ 登録エラーが発生しました: {e}")
            
# =========================================================
# --- Tab 2: 📊 全アカウント店舗アカウント状況 (修正版) ---
# =========================================================
with tab2:
    st.markdown("## 📊 店舗アカウント状況")
    if combined_data:
        for acc_code in POSTING_ACCOUNT_OPTIONS:
            count = acc_counts.get(acc_code, 0)
            st.markdown(f"### 👤 投稿{acc_code}アカウント `{count} 件`")
            if acc_code in acc_summary:
                areas = acc_summary[acc_code]
                area_cols = st.columns(len(areas) if len(areas) > 0 else 1)
                for idx, (area_name, shops) in enumerate(areas.items()):
                    with area_cols[idx]:
                        st.info(f"📍 **{area_name}**")
                        for shop in sorted(shops):
                            st.checkbox(f"{shop}", key=f"move_{acc_code}_{area_name}_{shop}")
        
        selected_shops = [
            {"acc": k.split('_')[1], "area": k.split('_')[2], "shop": k.split('_')[3].split(" : ")[-1]}
            for k, v in st.session_state.items() if k.startswith("move_") and v
        ]

        if selected_shops:
            # 💡 ここから下の行をすべて右に1段インデントしました
            if st.button("🚀 選択した店舗を【落ち店】へ移動する", type="primary", use_container_width=True):
                st.session_state.confirm_move = True

            if st.session_state.get("confirm_move"):
                st.error("❗ 本当に実行しますか？")
                col_yes, col_no = st.columns(2)
                
                if col_no.button("❌ キャンセル", use_container_width=True):
                    st.session_state.confirm_move = False
                    st.rerun()

                if col_yes.button("⭕ はい、実行します", type="primary", use_container_width=True):
                    import time
                    try:
                        sh_stock = GC.open_by_key("1e-iLey43A1t0bIBoijaXP55t5fjONdb0ODiTS53beqM")
                        ws_stock = sh_stock.sheet1
                        sh_link = GC.open_by_key(ACCOUNT_STATUS_SHEET_ID)
                        
                        for item in selected_shops:
                            # ① 日記移動
                            ws_main = SPRS.worksheet(POSTING_ACCOUNT_SHEETS[item['acc']])
                            main_data = ws_main.get_all_values()
                            for row_idx in range(len(main_data), 0, -1):
                                row = main_data[row_idx-1]
                                if len(row) >= 2 and row[1] == item['shop']:
                                    # A,B列を飛ばして、C列にタイトル(F)、D列に本文(G)を登録
                                    ws_stock.append_row([None, None, row[5], row[6]], value_input_option='USER_ENTERED')
                                    time.sleep(1.5) # API制限(429)対策
                                    ws_main.delete_rows(row_idx)

                            # ② リンク削除
                            ws_link = sh_link.worksheet(POSTING_ACCOUNT_SHEETS[item['acc']])
                            link_data = ws_link.get_all_values()
                            for row_idx in range(len(link_data), 0, -1):
                                if len(link_data[row_idx-1]) >= 2 and link_data[row_idx-1][1] == item['shop']:
                                    ws_link.delete_rows(row_idx)
                                    break
                            
                            # ③ GCS画像移動 (パス構造維持)
                            bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
                            found_blobs = []
                            for pfx in [f"{item['area']}/{item['shop']}/", f"{item['area']}/デリじゃ {item['shop']}/"]:
                                blobs = list(bucket.list_blobs(prefix=pfx))
                                if blobs:
                                    found_blobs = blobs
                                    break
                            for b in found_blobs:
                                file_name = b.name.split('/')[-1]
                                new_name = f"【落ち店】/{item['shop']}/{file_name}"
                                bucket.copy_blob(b, bucket, new_name)
                                b.delete()
                        
                        st.success("🎉 移動完了！")
                        st.session_state.confirm_move = False
                        st.cache_data.clear() 
                        if 'diary_df' in st.session_state: del st.session_state.diary_df
                        st.rerun()
                    except Exception as e:
                        st.error(f"エラー: {e}")
        
# =========================================================
# --- Tab 3: 📂 ③ 投稿日記文管理 (手動更新・エラー防止版) ---
# =========================================================
with tab3:
    st.markdown("### 📂 投稿日記文管理 (一括編集)")
    st.caption("※「一括保存」または「編集をリセット」を押すまで、最新のスプレッドシート状態は反映されません。")

    # 💡 API負荷軽減：セッションにデータがない時だけ読み込む
    if combined_data:
        # 1. 編集用データの初期化（キャッシュとしての役割）
        if 'edited_df_3' not in st.session_state:
            # 読み込み時のスナップショットを作成
            st.session_state.df_orig_snapshot = pd.DataFrame(combined_data, columns=["アカウント", "行番号"] + REGISTRATION_HEADERS)
            st.session_state.edited_df_3 = st.session_state.df_orig_snapshot.copy()

        # 2. 検索・フィルタ機能（UIのみ。APIは叩かない）
        c_search1, c_search2 = st.columns([1, 2])
        filter_acc = c_search1.multiselect("👤 アカウントで絞り込み", POSTING_ACCOUNT_OPTIONS, key="filter_acc_3")
        filter_text = c_search2.text_input("🔍 キーワード検索 (店名・名前など)", key="filter_text_3")

        # 編集用ワークデータのコピー
        working_df = st.session_state.edited_df_3.copy()
        df_orig = st.session_state.df_orig_snapshot

        # 3. 変更をチェックしてフラグを立てる (ValueErrorを完全に防止)
        try:
            # 常に同じタイミングで作成された snapshot と比較するため形状不一致が起きない
            diff_mask = (working_df != df_orig).any(axis=1)
        except ValueError:
            # 万が一の事故時のみリセット
            if 'edited_df_3' in st.session_state: del st.session_state.edited_df_3
            st.rerun()

        working_df.insert(0, "状態", diff_mask.map({True: "🔴 変更あり", False: "ー"}))

        # 4. ソート・フィルタ
        working_df = working_df.sort_values(by=["状態", "アカウント"], ascending=[False, True])
        if filter_acc:
            working_df = working_df[working_df["アカウント"].isin(filter_acc)]
        if filter_text:
            working_df = working_df[working_df.astype(str).apply(lambda x: filter_text.lower() in x.str.lower().any(), axis=1)]

        # 5. スタイリング
        def highlight_changes(row):
            if row["状態"] == "🔴 変更あり":
                return ['background-color: #ffebee; color: #b71c1c; font-weight: bold'] * len(row)
            return [''] * len(row)

        styled_df = working_df.style.apply(highlight_changes, axis=1)

        # 6. データエディタ
        new_edited_df = st.data_editor(
            styled_df,
            key="main_editor_3",
            use_container_width=True,
            hide_index=True,
            disabled=["状態", "アカウント", "行番号"],
            height=600
        )

        # 編集内容をセッションに即時保存
        st.session_state.edited_df_3 = new_edited_df.drop(columns=["状態"])

        # 7. 保存・リセット処理
        c_save1, c_save2 = st.columns([4, 1])
        
        # --- 保存ボタン：ここで初めてAPIを叩く ---
        if c_save2.button("🔥 一括保存", type="primary", use_container_width=True):
            changed_rows = new_edited_df[new_edited_df["状態"] == "🔴 変更あり"]
            if changed_rows.empty:
                st.warning("変更箇所がありません。")
            else:
                with st.spinner("スプレッドシートを更新中..."):
                    import time
                    try:
                        for acc_code in POSTING_ACCOUNT_OPTIONS:
                            acc_changes = changed_rows[changed_rows["アカウント"] == acc_code]
                            if acc_changes.empty: continue
                            
                            ws = SPRS.worksheet(POSTING_ACCOUNT_SHEETS[acc_code])
                            for _, row in acc_changes.iterrows():
                                row_idx = int(row["行番号"])
                                update_values = [str(row[h]) for h in REGISTRATION_HEADERS]
                                ws.update(f"A{row_idx}:G{row_idx}", [update_values], value_input_option='USER_ENTERED')
                                time.sleep(1.2) # API制限対策
                        
                        st.success("🎉 保存完了！最新情報を読み込みます。")
                        # 保存成功後にキャッシュを消して最新化
                        if 'edited_df_3' in st.session_state: del st.session_state.edited_df_3
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"保存エラー: {e}")

        # --- リセットボタン：最新のスプレッドシート状態に更新する役割 ---
        if c_save1.button("🔄 編集をリセット（最新状態に更新）"):
            if 'edited_df_3' in st.session_state: del st.session_state.edited_df_3
            st.cache_data.clear()
            st.rerun()

    else:
        st.info("編集可能なデータはありません。")
        
# =========================================================
# --- Tab 4: 📸 ④ 投稿画像管理 (API節約・Fragment版) ---
# =========================================================
with tab4:
    st.header("📸 投稿画像管理")
    
    # --- 1. エリア・店舗リスト取得をキャッシュ化 (API消費を最小限に) ---
    @st.cache_data(show_spinner=False)
    def get_gcs_hierarchy_v9(update_tick):
        try:
            # delimiter='/' を使い、階層を絞って効率的にスキャン
            blobs = GCS_CLIENT.list_blobs(GCS_BUCKET_NAME, prefix="", delimiter='/')
            list(blobs) 
            areas = [p.replace("/", "") for p in blobs.prefixes if "【落ち店】" not in p and p != "/"]
            
            hierarchy = {}
            for area in areas:
                area_blobs = GCS_CLIENT.list_blobs(GCS_BUCKET_NAME, prefix=f"{area}/", delimiter='/')
                list(area_blobs)
                hierarchy[area] = [p for p in area_blobs.prefixes]
            return hierarchy
        except: return {}

    if 'tab4_tick' not in st.session_state:
        st.session_state.tab4_tick = 0

    # リスト更新ボタン
    col_ref, _ = st.columns([1.5, 4])
    if col_ref.button("🔄 エリア・店舗リストを更新", key="ref_hierarchy_4_v9"):
        st.session_state.tab4_tick += 1
        st.cache_data.clear()
        st.rerun()

    hierarchy = get_gcs_hierarchy_v9(st.session_state.tab4_tick)

    if hierarchy:
        c_sel1, c_sel2 = st.columns(2)
        selected_area = c_sel1.selectbox("📍 エリア", ["選択してください"] + list(hierarchy.keys()), key="sel_area_4_v9")
        
        if selected_area != "選択してください":
            store_paths = hierarchy[selected_area]
            store_options = {p.split('/')[-2]: p for p in store_paths}
            selected_store_name = c_sel2.selectbox("🏢 店舗", ["選択してください"] + list(store_options.keys()), key="sel_store_4_v9")

            if selected_store_name != "選択してください":
                target_path = store_options[selected_store_name]
                active_bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)

                # --- 2. 画像操作Fragment (ここがAPI制限を回避する核です) ---
                @st.fragment
                def image_grid_fragment_v9(path, store_name):
                    # 画像リスト取得（API負荷軽減のためキャッシュを利用）
                    @st.cache_data(ttl=600, show_spinner=False)
                    def get_images_in_store(p):
                        blobs = list(active_bucket.list_blobs(prefix=p))
                        return [bl.name for bl in blobs if bl.name != p and bl.name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                    
                    img_names = get_images_in_store(path)

                    if not img_names:
                        st.info("画像がありません。")
                        return

                    search_query = st.text_input("🔍 名前で検索", key="search_4_v9_f")
                    display_names = [n for n in img_names if search_query.lower() in n.split('/')[-1].lower()]

                    # 操作ボタン（UIと仕様はそのまま維持）
                    btn_c1, btn_c2, btn_c3, btn_c4 = st.columns([1, 1, 2, 2])
                    selected_items = [n for n in display_names if st.session_state.get(f"del_4_{n}")]

                    if selected_items:
                        if len(selected_items) == 1:
                            btn_c3.download_button("💾 1枚保存", active_bucket.blob(selected_items[0]).download_as_bytes(), file_name=selected_items[0].split('/')[-1], type="primary", use_container_width=True)
                        else:
                            zip_buf = BytesIO()
                            with zipfile.ZipFile(zip_buf, "w") as zf:
                                for p in selected_items:
                                    zf.writestr(f"{store_name}/{p.split('/')[-1]}", active_bucket.blob(p).download_as_bytes())
                            btn_c3.download_button(f"⬇️ {len(selected_items)}枚ZIP保存", zip_buf.getvalue(), file_name=f"{store_name}.zip", type="primary", use_container_width=True)

                        if btn_c4.button(f"🗑 {len(selected_items)}枚削除", type="secondary", use_container_width=True):
                            st.session_state.confirm_del_4 = True

                    if st.session_state.get("confirm_del_4"):
                        st.error("⚠️ 本当に削除しますか？")
                        if st.button("⭕ 実行"):
                            for n in selected_items: active_bucket.blob(n).delete()
                            st.session_state.confirm_del_4 = False
                            st.cache_data.clear()
                            st.rerun()

                    st.markdown(f"**表示中: {len(display_names)} 枚**")
                    
                    # 画像グリッド（API消費の多いURL生成をキャッシュでスキップ）
                    cols = st.columns(8)
                    for idx, b_name in enumerate(display_names):
                        with cols[idx % 8]:
                            # get_cached_url (有効期限7日間) を使用
                            st.image(get_cached_url(b_name), use_container_width=True)
                            st.caption(b_name.split('/')[-1])
                            st.checkbox("選", key=f"del_4_{b_name}", label_visibility="collapsed")

                # Fragment実行
                image_grid_fragment_v9(target_path, selected_store_name)

                # アップロード機能（Fragment外に配置しUIを維持）
                with st.expander("➕ 画像をこの店舗に追加"):
                    up_files = st.file_uploader("画像をドロップ", accept_multiple_files=True, type=["jpg","jpeg","png","webp"], key="uploader_4")
                    if st.button("🚀 アップロード開始", key="up_btn_4"):
                        if up_files:
                            for f in up_files:
                                active_bucket.blob(f"{target_path}{f.name}").upload_from_string(f.getvalue(), content_type=f.type)
                            st.cache_data.clear()
                            st.rerun()
                            
# =========================================================
# --- Tab 5: 📚 ⑤ 使用可能日記文 (手動更新・API負荷最小版) ---
# =========================================================
with tab5:
    st.header("5️⃣ 使用可能日記文")
    
    # 💡 引数に「更新用キー」を持たせることで、ボタン押下時のみ中身を実行させる
    @st.cache_data
    def get_usable_diary_data(update_tick):
        # この中身は update_tick が変わらない限り、何度リロードしても実行されません
        tmp_sprs = GC.open_by_key("1e-iLey43A1t0bIBoijaXP55t5fjONdb0ODiTS53beqM")
        tmp_ws = tmp_sprs.sheet1 
        return tmp_ws.get_all_values()

    # セッションで更新用キーを管理
    if 'tab5_update_tick' not in st.session_state:
        st.session_state.tab5_update_tick = 0

    # --- 更新ボタンの配置 ---
    col_refresh, _ = st.columns([1, 4])
    if col_refresh.button("🔄 データを最新に更新", key="refresh_tab5", use_container_width=True):
        st.session_state.tab5_update_tick += 1  # キーを増やすことでキャッシュを更新させる
        st.cache_data.clear()
        st.rerun()

    try:
        # キャッシュされたデータを取得
        tmp_data = get_usable_diary_data(st.session_state.tab5_update_tick)
        
        if len(tmp_data) > 1:
            df_usable = pd.DataFrame(tmp_data[1:], columns=tmp_data[0])
            st.dataframe(df_usable, use_container_width=True, height=600, hide_index=True)
        else:
            st.info("表示できる日記文がありません。")

    except Exception as e:
        if "429" in str(e):
            st.error("🚨 API制限中です。1分待ってから「最新に更新」を押してください。")
        else:
            st.error(f"読み込みエラー: {e}")
        
# =========================================================
# --- Tab 6: 🖼 ⑥ 落ち店 (API制限対策・完全版) ---
# =========================================================
with tab6:
    st.header("🖼 使用可能画像ブラウザ（落ち店）")
    ROOT_PATH = "【落ち店】/"

    # --- 1. フォルダ情報のマニュアル取得（API消費1回のみ） ---
    @st.cache_data(show_spinner=False)
    def get_ochimise_folders_v9(update_tick):
        # ボタンを押さない限り、ここは二度と実行されない
        blobs = GCS_CLIENT.list_blobs(GCS_BUCKET_NAME, prefix=ROOT_PATH, delimiter='/')
        list(blobs)
        return blobs.prefixes

    if 'tab6_tick' not in st.session_state: st.session_state.tab6_tick = 0

    c_btn, _ = st.columns([1.5, 4])
    if c_btn.button("🔄 店舗リストを強制更新", key="update_6"):
        st.session_state.tab6_tick += 1
        st.cache_data.clear() # キャッシュを掃除
        st.rerun()

    folders = get_ochimise_folders_v9(st.session_state.tab6_tick)
    show_all = st.checkbox("📂 全画像表示（一括モード）", key="all_check_6")

    # --- 2. Fragment（ここが「勝手に再読み込み」を止める心臓部） ---
    @st.fragment
    def ochimise_action_fragment(folders, show_all):
        bucket = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
        
        # 画像リスト取得（ここもキャッシュでAPI保護）
        @st.cache_data(ttl=600, show_spinner=False)
        def get_img_list_fast(path, is_all):
            if is_all:
                blobs = list(bucket.list_blobs(prefix=ROOT_PATH))
            else:
                blobs = list(bucket.list_blobs(prefix=path, delimiter='/'))
            return [bl.name for bl in blobs if bl.name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]

        target_path = ROOT_PATH
        current_label = "一括"
        
        if not show_all:
            if folders:
                folder_opts = {f.replace(ROOT_PATH, "").replace("/", ""): f for f in folders}
                sel = st.selectbox("📁 店舗を選択", ["未選択"] + list(folder_opts.keys()), key="sel_f_6")
                if sel == "未選択": return
                target_path = folder_opts[sel]
                current_label = sel
            else: return

        img_names = get_img_list_fast(target_path, show_all)
        
        if img_names:
            # 検索バーなどの操作（Fragment内なのでAPI消費なし）
            search_q = st.text_input("🔍 絞り込み検索", key="q_6")
            display_imgs = [n for n in img_names if search_q.lower() in n.lower()]

            c1, c2, c3, c4 = st.columns([1, 1, 2, 2])
            # 全選択・解除
            if c1.button("✅ 全選択"):
                for n in display_imgs: st.session_state[f"s6_{n}"] = True
                st.rerun()
            if c2.button("⬜️ 解除"):
                for n in display_imgs: st.session_state[f"s6_{n}"] = False
                st.rerun()

            selected = [n for n in display_imgs if st.session_state.get(f"s6_{n}")]

            # --- 削除の2段構え ---
            if selected:
                zip_buf = BytesIO()
                with zipfile.ZipFile(zip_buf, "w") as zf:
                    for p in selected:
                        zf.writestr(p.split('/')[-1], bucket.blob(p).download_as_bytes())
                
                c3.download_button(f"① {len(selected)}枚を保存(ZIP)", zip_buf.getvalue(), f"{current_label}.zip", type="primary", use_container_width=True)
                
                if c4.button(f"② 保存完了・削除実行", type="secondary", use_container_width=True):
                    for n in selected: bucket.blob(n).delete()
                    for n in selected: st.session_state[f"s6_{n}"] = False
                    st.cache_data.clear() # 削除したのでキャッシュを消す
                    st.rerun()
                st.warning("⚠️ 保存後、必ず②を押して消去してください（使い回し防止）")

            # --- 画像表示（URL生成をキャッシュでスキップ） ---
            cols = st.columns(8)
            for idx, b_name in enumerate(display_imgs):
                with cols[idx % 8]:
                    st.image(get_cached_url(b_name), use_container_width=True)
                    st.checkbox("選", key=f"s6_{b_name}", label_visibility="collapsed")
                    st.caption(f":grey[{b_name.split('/')[-1][:10]}]") # 名前は短く表示

    # 実行
    ochimise_action_fragment(folders, show_all)
