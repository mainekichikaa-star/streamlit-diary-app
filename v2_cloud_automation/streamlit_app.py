import streamlit as st
import json
import asyncio
from gemini_service import GroqService

# 管理用画面（基本は見ない）
st.set_page_config(page_title="AI Worker Backend")
st.title("Cloud Automation Node")

# サービスの初期化
if 'groq_service' not in st.session_state:
    st.session_state.groq_service = GroqService()

# --- GASからのデータ受け取りロジック ---
# StreamlitのURLにパラメータをつけて叩かれた際の処理
query_params = st.query_params

if "action" in query_params:
    st.success("GASからのリクエストを受信しました")
    
    # 本来はPOSTで受け取るのが理想ですが、Streamlit Cloudの仕様上、
    # シンプルに動作させるためにセッションやURLを利用する設計にします。
    # ここに投稿処理の関数を呼び出すコードを書きます。

# ダミーの実行ボタン（動作テスト用）
if st.button("テスト実行"):
    st.write("テスト動作中...")
