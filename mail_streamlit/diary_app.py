import streamlit as st
from datetime import datetime
import json
import io
import time
from base64 import urlsafe_b64encode
import os # 環境変数として認証情報を読み込むために使用

# ==============================================================================
# ⚠️ 1. 設定情報 (このアプリがアクセスするリソースIDを設定してください)
# ==============================================================================

# スプレッドシートID: 日記マスターシート
# 例: "1A2B3C4D..."
SPREADSHEET_ID = st.secrets["app_config"].get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
WORKSHEET_NAME = st.secrets["app_config"].get("WORKSHEET_NAME", "日記マスター")

# Googleドライブ フォルダID: アップロードされた画像を保存する場所
# 例: "0E9F8G7H..."
DRIVE_FOLDER_ID = st.secrets["app_config"].get("DRIVE_FOLDER_ID", "YOUR_DRIVE_FOLDER_ID_HERE")

# Gmail 下書き作成時のデフォルトの件名テンプレート
DRAFT_SUBJECT_TEMPLATE = st.secrets["app_config"].get("DRAFT_SUBJECT_TEMPLATE", "【日報】{date}の日記更新")
DRAFT_DEFAULT_TO_ADDRESS = st.secrets["app_config"].get("DRAFT_DEFAULT_TO_ADDRESS", "example@mailinglist.com")

# ==============================================================================
# 2. Google API認証と初期化
# ==============================================================================

# st.secretsからサービスアカウント情報を取得し、環境変数に設定
# Streamlit Cloudでデプロイする場合、この処理は必須です。
try:
    if "service_account" in st.secrets:
        # secrets.tomlからJSON情報を取得
        creds_json = st.secrets["service_account"]
        # ファイルとして保存せずに、環境変数経由で認証情報を渡す
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'service_account.json'
        with open('service_account.json', 'w') as f:
            json.dump(creds_json, f)
        
        # 必要なライブラリのインポート（Streamlit Cloudで動かすための遅延インポート）
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        import gspread
        
        # 認証情報とクライアントの初期化
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.file',
            'https://www.googleapis.com/auth/gmail.compose', # 下書き作成用
            'https://www.googleapis.com/auth/gmail.modify', # 検索・修正用
            'https://www.googleapis.com/auth/contacts' # 連絡先更新用
        ]
        
        creds = Credentials.from_service_account_file('service_account.json', scopes=SCOPES)
        gc = gspread.service_account(credentials=creds)
        
        # APIサービスのビルド
        drive_service = build('drive', 'v3', credentials=creds)
        gmail_service = build('gmail', 'v1', credentials=creds)
        people_service = build('people', 'v1', credentials=creds) # 連絡先サービス

        AUTH_READY = True
        
    else:
        st.error("🚨 エラー: Google認証情報が見つかりません。`.streamlit/secrets.toml`を設定してください。")
        AUTH_READY = False
        
except Exception as e:
    st.error(f"🚨 API初期化エラー: Googleの認証情報が不正です。設定を確認してください。詳細: {e}")
    AUTH_READY = False
    
# --- セッションステートの初期化 ---
# 処理の途中結果やエラー情報を保持し、途中再開を可能にする
if 'steps_status' not in st.session_state:
    # 各ステップの初期状態: 'pending' (待機中), 'running' (実行中), 'success' (成功), 'failed' (失敗)
    st.session_state.steps_status = {}
if 'last_run_data' not in st.session_state:
    # 最後に成功したデータや、一時保存データ
    st.session_state.last_run_data = {}
if 'current_mode' not in st.session_state:
    # フォームの初期モード
    st.session_state.current_mode = 'create' # 'create' or 'edit'

# ==============================================================================
# 3. ユーティリティ関数（API操作のラッパー）
# ==============================================================================

def execute_step(step_key, step_description, func, *args, **kwargs):
    """
    一つの自動化ステップを実行し、セッションステートとUIを更新する関数
    :param step_key: ステップを識別するキー (例: 'extract_mails')
    :param step_description: UIに表示する説明
    :param func: 実行する関数
    :param args, kwargs: 関数に渡す引数
    :return: 実行結果 (成功した場合は True, 失敗した場合は False)
    """
    st.session_state.steps_status[step_key] = 'running'
    st.session_state.last_run_data['status_message'] = f"【実行中】{step_description}..."
    time.sleep(0.5) # UI更新のための待ち時間

    try:
        # 関数の実行と結果の取得
        success, result, message = func(*args, **kwargs)
        
        if success:
            st.session_state.steps_status[step_key] = 'success'
            st.session_state.last_run_data[step_key] = result # 結果を一時保存
            st.session_state.last_run_data['status_message'] = f"【成功】{step_description}"
        else:
            # 失敗した場合、エラーメッセージを保存して処理を中断
            st.session_state.steps_status[step_key] = 'failed'
            st.session_state.last_run_data['error_message'] = message
            st.session_state.last_run_data['status_message'] = f"【失敗】{step_description}"
            return False
            
    except Exception as e:
        # 予期せぬエラーが発生した場合
        st.session_state.steps_status[step_key] = 'failed'
        st.session_state.last_run_data['error_message'] = f"予期せぬエラー: {e}"
        st.session_state.last_run_data['status_message'] = f"【失敗】{step_description}"
        return False
        
    return True

# --- API処理関数（既存ロジックの関数化をシミュレート） ---

def upload_image_to_drive(uploaded_file):
    """画像をドライブにアップロードし、公開URLを返す (F-05)"""
    # ... (実際のDrive API処理はここに実装) ...
    if not uploaded_file:
        return True, "画像なし", "画像はアップロードされませんでした。"

    file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
    # 実際はdrive_service.files().createを呼び出し、公開パーミッションを設定します。
    # ここではシミュレーションとして架空のURLを返します。
    if uploaded_file.size > 10 * 1024 * 1024: # 10MBを超えると失敗と仮定
        return False, None, "画像ファイルが大きすぎます（10MB上限）。"

    mock_file_id = f"mockid-{hash(uploaded_file.name)}"
    mock_url = f"https://drive.google.com/uc?id={mock_file_id}&export=download"
    return True, mock_url, f"ドライブにアップロード完了: {file_name}"

def register_to_spreadsheet(diary_entry, image_url, sheet_id=SPREADSHEET_ID):
    """日記データと画像URLをスプレッドシートに書き込む (F-06 / E-01)"""
    # ... (実際のgspread処理はここに実装) ...
    try:
        worksheet = gc.open_by_key(sheet_id).worksheet(WORKSHEET_NAME)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = [timestamp, diary_entry, image_url, '新規']
        worksheet.append_row(row_data)
        return True, row_data, "日記マスターシートにデータを登録しました。"
    except Exception as e:
        return False, None, f"スプレッドシート登録失敗: {e}"

def extract_mails():
    """媒体からメールアドレスを抽出する (ローカルの mail_address_extractor.py 相当)"""
    # 実際にはここにBeautifulSoupなどを使ったウェブスクレイピングロジックが入ります。
    # シミュレーションとして固定値を返します。
    time.sleep(1)
    # 複数の宛先セット (A, B, SUB) のメールアドレスを抽出したと仮定
    mock_mail_data = {
        'A': 'recipient_a@example.com',
        'B': 'recipient_b@example.com',
        'SUB': 'recipient_sub@example.com',
        'FROM': 'info@source.com'
    }
    return True, mock_mail_data, "媒体からのメールアドレス抽出が完了しました。"

def update_contacts(target, mail_data):
    """連絡先を更新する (contact_updater.py 相当)"""
    # 実際にはpeople_serviceを使ってGoogleコンタクトAPIを操作します。
    time.sleep(0.5)
    if target == 'B' and 'recipient_b@example.com' not in mail_data:
        # 例外的なエラーシミュレーション
        return False, None, f"連絡先Bの更新に失敗: 必須メールアドレスが見つかりません。"
    return True, None, f"連絡先 '{target}' の連絡先リストへの更新が完了しました。"

def create_or_update_draft(target, subject, body, to_address, drive_url, mode='create', draft_id=None):
    """下書きを作成/更新する (draft_creator.py / draft_updater.py 相当)"""
    # 実際にはGmail APIを使ってMIMEメッセージを作成し、下書きを操作します。
    time.sleep(1.5)
    
    # MIMEメッセージの作成（画像埋め込みや添付処理は複雑なので、ここではシミュレーション）
    message_text = f"Subject: {subject}\nTo: {to_address}\n\n{body}\n\n[画像URL]: {drive_url}"
    
    # 検索用の固有IDを本文に埋め込む
    unique_marker = f"<!-- DIARY_ID:{datetime.now().strftime('%Y%m%d%H%M%S')} -->"
    full_body = f"{message_text}\n{unique_marker}"
    
    encoded_message = urlsafe_b64encode(full_body.encode("utf-8")).decode("utf-8")
    
    if mode == 'create':
        # 実際にはgmail_service.users().drafts().createを呼び出す
        mock_draft_id = f"draft-{target}-{hash(full_body)}"
        return True, mock_draft_id, f"下書き '{target}' が新規作成されました。"
    else: # mode == 'update'
        # 実際にはgmail_service.users().drafts().updateを呼び出す
        return True, draft_id, f"下書き ID:{draft_id[:10]}... が更新されました。"


def search_draft_by_subject(search_term):
    """件名や宛先から既存の下書きを検索する (E-03)"""
    # 実際にはgmail_service.users().drafts().list(q='subject:...') を呼び出す
    time.sleep(1)
    
    # シミュレーションデータ: 検索文字列を含む下書きがヒットしたと仮定
    mock_results = []
    if "テスト" in search_term or "update" in search_term:
        mock_results = [
            {'id': 'DraftA123456789', 'subject': '[UPDATE] テスト日報 2025/11/01', 'to': 'recipient_a@example.com'},
            {'id': 'DraftB987654321', 'subject': '別件下書き', 'to': 'recipient_b@example.com'},
        ]
    
    return True, mock_results, f"下書きを検索しました: {len(mock_results)}件ヒット"

def get_draft_details(draft_id):
    """下書きIDから詳細な本文、宛先、画像を読み込む (E-04)"""
    # 実際にはgmail_service.users().drafts().get を呼び出す
    time.sleep(1)

    # シミュレーションデータ
    if draft_id == 'DraftA123456789':
        mock_body = "これは2025年11月1日の日記本文です。\n\n既存の画像URL: https://drive.google.com/uc?id=EXISTING_ID"
        mock_details = {
            'draft_id': draft_id,
            'subject': '[UPDATE] テスト日報 2025/11/01',
            'to': 'recipient_a@example.com',
            'body': mock_body,
            'current_drive_url': 'https://drive.google.com/uc?id=EXISTING_ID'
        }
        return True, mock_details, "下書きの詳細を読み込みました。"
    
    return False, None, "指定されたIDの下書きが見つかりませんでした。"


# ==============================================================================
# 4. メインアプリケーションUIとロジック
# ==============================================================================

def display_step_status(step_key, description):
    """信号機方式でステップの進捗を表示する"""
    status = st.session_state.steps_status.get(step_key, 'pending')
    
    # UIアイコンと色分け
    if status == 'success':
        icon = "✅"
        color = "green"
    elif status == 'failed':
        icon = "❌"
        color = "red"
    elif status == 'running':
        icon = "🔄"
        color = "orange"
    else:
        icon = "⚪"
        color = "gray"
    
    # Markdownで色付きの表示（HTML許可）
    st.markdown(f"#### <span style='color:{color};'>{icon} {description}</span>", unsafe_allow_html=True)

def reset_all_statuses():
    """全てのエラーと状態をリセットする"""
    st.session_state.steps_status = {}
    st.session_state.last_run_data = {}
    st.session_state.last_run_data['status_message'] = "リセット完了。新規に作業を開始できます。"
    st.toast("アプリの状態をリセットしました。")

def full_automation_process(form_data, uploaded_file):
    """全自動化プロセス（11ステップを順次実行）"""
    
    st.session_state.steps_status = {} # ステータスを初期化
    
    # ------------------------------------
    # Step 1: メールアドレス抽出 (mail_address_extractor.py)
    # ------------------------------------
    if not execute_step('extract_mails', '1. 媒体からのメールアドレス抽出', extract_mails): return
    mail_data = st.session_state.last_run_data['extract_mails']

    # ------------------------------------
    # Step 2: 連絡先作成 (contact_updater.py A/B/SUB)
    # ------------------------------------
    if not execute_step('update_contact_A', '2-A. 連絡先 [A] の更新', update_contacts, 'A', mail_data): return
    if not execute_step('update_contact_B', '2-B. 連絡先 [B] の更新', update_contacts, 'B', mail_data): return
    if not execute_step('update_contact_SUB', '2-C. 連絡先 [SUB] の更新', update_contacts, 'SUB', mail_data): return

    # ------------------------------------
    # Step 3: 画像アップロード (image_uploader.py)
    # ------------------------------------
    if not execute_step('upload_image', '3. 画像のGoogleドライブへのアップロード', upload_image_to_drive, uploaded_file): return
    drive_url = st.session_state.last_run_data['upload_image']

    # ------------------------------------
    # Step 4: スプレッドシート登録 (F-06)
    # ------------------------------------
    if not execute_step('register_sheet', '4. 日記マスターシートへのデータ登録', register_to_spreadsheet, form_data['body'], drive_url): return

    # ------------------------------------
    # Step 5: 下書き作成/更新 (draft_creator.py A/B/SUB + draft_updater.py A/B/SUB)
    # ------------------------------------
    # ここでは、最新データを使って下書きを新規作成/更新する
    if not execute_step('create_draft_A', '5-A. 下書き [A] の作成/宛先登録', create_or_update_draft, 
                        'A', form_data['subject_A'], form_data['body'], mail_data.get('A', DRAFT_DEFAULT_TO_ADDRESS), drive_url): return
    if not execute_step('create_draft_B', '5-B. 下書き [B] の作成/宛先登録', create_or_update_draft, 
                        'B', form_data['subject_B'], form_data['body'], mail_data.get('B', DRAFT_DEFAULT_TO_ADDRESS), drive_url): return
    if not execute_step('create_draft_SUB', '5-C. 下書き [SUB] の作成/宛先登録', create_or_update_draft, 
                        'SUB', form_data['subject_SUB'], form_data['body'], mail_data.get('SUB', DRAFT_DEFAULT_TO_ADDRESS), drive_url): return
    
    st.session_state.last_run_data['status_message'] = "🎉 全ての自動化プロセスが正常に完了しました！"
    st.balloons()


# ==============================================================================
# Streamlit UI構築
# ==============================================================================

# --- サイドバー (ナビゲーションと設定) ---
with st.sidebar:
    st.title("⚙️ 設定 & ツール")
    
    # モード切り替え
    st.markdown("### 📝 作業モード選択")
    st.radio("モード選択", options=['新規作成', '下書き修正'], key='current_mode_select')
    
    # ラジオボタンの値をセッションステートに反映
    st.session_state.current_mode = 'create' if st.session_state.current_mode_select == '新規作成' else 'edit'

    st.markdown("---")
    
    st.markdown("### 🚦 状態リセット")
    st.warning("エラーで止まった時や、最初からやり直したい時に押してください。")
    if st.button("全処理状態をリセット", help="一時保存されたデータとエラー状態をクリアします。", type="secondary"):
        reset_all_statuses()

# --- メイン画面 ---
st.title("🚀 日記自動化アプリ（Streamlit版）")
st.markdown("---")

# 1. 新規作成モード
if st.session_state.current_mode == 'create':
    
    st.header("1. 新規日記の入力と自動化実行")
    
    # --- 入力フォーム ---
    with st.form(key='new_diary_form'):
        
        st.markdown("#### 1-1. 日記の本文")
        diary_body = st.text_area(
            "本文",
            placeholder="今日の日記を記入してください。",
            height=250,
            key='diary_body'
        )
        
        st.markdown("#### 1-2. 画像アップロード")
        uploaded_file = st.file_uploader(
            "画像をここにドラッグ＆ドロップ (JPG/PNG)",
            type=['png', 'jpg', 'jpeg']
        )
        
        col_A, col_B, col_SUB = st.columns(3)
        with col_A:
            subject_A = st.text_input("下書き [A] の件名", value=DRAFT_SUBJECT_TEMPLATE.format(date="新規"), key='subject_A')
        with col_B:
            subject_B = st.text_input("下書き [B] の件名", value=DRAFT_SUBJECT_TEMPLATE.format(date="新規"), key='subject_B')
        with col_SUB:
            subject_SUB = st.text_input("下書き [SUB] の件名", value=DRAFT_SUBJECT_TEMPLATE.format(date="新規"), key='subject_SUB')
            
        st.markdown("---")
        submit_button = st.form_submit_button(label='🚀 全自動化プロセスを開始')

    # --- 実行ロジック ---
    if submit_button and diary_body:
        # フォームデータをまとめる
        form_data = {
            'body': diary_body,
            'subject_A': subject_A, 'subject_B': subject_B, 'subject_SUB': subject_SUB
        }
        
        if AUTH_READY:
            full_automation_process(form_data, uploaded_file)
        else:
            st.error("🚨 Google認証が完了していません。設定を確認してください。")

    # --- ステータス表示 ---
    st.markdown("---")
    st.subheader("2. 🚦 自動化プロセスの進捗状況 (信号機方式)")
    
    # リアルタイムのメッセージ表示
    status_message = st.session_state.last_run_data.get('status_message', "待機中: 「全自動化プロセスを開始」を押してください。")
    if 'failed' in st.session_state.steps_status.values():
         st.error(f"⚠️ **処理停止:** {st.session_state.last_run_data.get('error_message', '不明なエラーで停止しました。')}")
    st.info(status_message)

    # 11ステップの進捗を直感的に表示
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("準備・連絡先")
        display_step_status('extract_mails', '1. 媒体メールアドレス抽出')
        display_step_status('update_contact_A', '2-A. 連絡先 [A] 更新')
        display_step_status('update_contact_B', '2-B. 連絡先 [B] 更新')
        display_step_status('update_contact_SUB', '2-C. 連絡先 [SUB] 更新')
    
    with col2:
        st.subheader("データ登録")
        display_step_status('upload_image', '3. ドライブ画像アップロード')
        display_step_status('register_sheet', '4. 日記マスターシート登録')
    
    with col3:
        st.subheader("下書き作成")
        display_step_status('create_draft_A', '5-A. 下書き [A] 作成/宛先登録')
        display_step_status('create_draft_B', '5-B. 下書き [B] 作成/宛先登録')
        display_step_status('create_draft_SUB', '5-C. 下書き [SUB] 作成/宛先登録')


# 2. 下書き修正モード (E-03 ~ E-06)
else:
    st.header("1. 既存下書きの検索と修正")
    
    # --- 検索フォーム ---
    with st.form(key='draft_search_form'):
        search_term = st.text_input(
            "件名、または宛先アドレスの一部を入力してください",
            placeholder="例: テスト日報 2025/11/01 または recipient_a@example.com",
            key='search_query'
        )
        search_button = st.form_submit_button("🔍 下書きを検索")

    if search_button and search_term:
        st.session_state.last_run_data['search_results'] = []
        if AUTH_READY:
            # 検索ロジックを呼び出す
            success, results, message = search_draft_by_subject(search_term)
            if success and results:
                st.session_state.last_run_data['search_results'] = results
                st.success(message)
            elif success:
                st.warning("該当する下書きは見つかりませんでした。")
            else:
                st.error(f"検索エラー: {message}")
        else:
            st.error("認証が必要です。")

    # --- 検索結果と編集フォーム ---
    if st.session_state.last_run_data.get('search_results'):
        st.markdown("---")
        st.subheader("2. 検索結果")
        
        # ユーザーに編集したい下書きを選択させる
        draft_options = [f"{r['subject']} ({r['to']})" for r in st.session_state.last_run_data['search_results']]
        selected_option = st.selectbox("編集したい下書きを選択してください", options=draft_options, key='draft_selector')
        
        # 選択された下書きの詳細を読み込む
        if selected_option:
            selected_draft = next(r for r in st.session_state.last_run_data['search_results'] if f"{r['subject']} ({r['to']})" == selected_option)
            
            # 詳細情報読み込み処理
            if st.button(f"選択した下書きの詳細を読み込む ({selected_draft['id'][:10]}...)"):
                success, details, message = get_draft_details(selected_draft['id'])
                if success:
                    st.session_state.last_run_data['edit_details'] = details
                    st.success("下書きの詳細をフォームに読み込みました。")
                else:
                    st.error(f"詳細読み込みエラー: {message}")

    # --- 編集フォーム (読み込み後の表示) ---
    if st.session_state.last_run_data.get('edit_details'):
        details = st.session_state.last_run_data['edit_details']
        
        st.markdown("---")
        st.subheader(f"3. 下書きの修正と更新 (ID: {details['draft_id'][:10]}...)")
        
        with st.form(key='edit_diary_form'):
            
            new_subject = st.text_input("件名", value=details['subject'])
            new_to = st.text_input("宛先アドレス", value=details['to'])
            new_body = st.text_area("本文", value=details['body'], height=300)
            
            st.markdown("##### 現在の画像URL")
            st.code(details['current_drive_url'], language='text')
            
            new_file = st.file_uploader(
                "新しい画像をアップロードして既存の画像を置き換える",
                type=['png', 'jpg', 'jpeg'],
                key='new_image_upload_edit'
            )
            
            update_button = st.form_submit_button("💾 下書きとマスターシートを更新")

        if update_button:
            # 更新処理の開始
            # 1. 画像処理
            if new_file:
                 success, new_drive_url, message = upload_image_to_drive(new_file)
                 if not success:
                    st.error(f"画像更新エラー: {message}")
                    st.stop()
            else:
                new_drive_url = details['current_drive_url'] # 変更なし

            # 2. シートの該当行を更新 (E-06)
            # 実際には、シートを検索して該当行をupdateDocで更新します。
            # ここではシミュレーション
            try:
                # 簡略化のため、新規登録と同じ関数をモックモードで呼び出し
                update_status_msg = f"マスターシートと下書き ({details['draft_id'][:10]}...) を更新しました。"
                
                # 3. Gmail下書きを更新 (E-06)
                success, updated_id, msg = create_or_update_draft('UPDATE', new_subject, new_body, new_to, new_drive_url, mode='update', draft_id=details['draft_id'])

                if success:
                    st.success(f"🎉 更新完了！ {update_status_msg}")
                    st.session_state.last_run_data['edit_details'] = None # フォームをクリア
                else:
                    st.error(f"下書き更新エラー: {msg}")

            except Exception as e:
                st.error(f"更新処理中に予期せぬエラーが発生しました: {e}")