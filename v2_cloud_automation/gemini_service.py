import os
import json
import base64
import re
import requests
import streamlit as st
from groq import AsyncGroq

class GroqService:
    def __init__(self):
        self.client = None
        self.model = "llama3-70b-8192"

    async def initialize(self):
        api_key = st.secrets.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
        if not api_key:
            st.error("APIキーが見つかりません。")
        self.client = AsyncGroq(api_key=api_key)

    def _get_image_base64_from_url(self, url):
        """GoogleドライブのURLから画像をダウンロードしBase64に変換する"""
        try:
            # ドライブURLを直リンクに変換
            match = re.search(r'd/([a-zA-Z0-9_-]+)', url)
            if not match:
                return None
            file_id = match.group(1)
            direct_url = f'https://drive.google.com/uc?export=download&id={file_id}'
            
            response = requests.get(direct_url, timeout=15)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
            return None
        except Exception as e:
            print(f"画像変換エラー: {e}")
            return None

    async def analyze_cast_data(self, image_url, selected_tags, related_tags, profile_data):
        """画像とタグリストを元に『お店目線』の紹介文を生成する"""
        if not self.client:
            await self.initialize()

        # 画像の処理
        image_base64 = self._get_image_base64_from_url(image_url)
        name = profile_data.get('name', '彼女')

        # --- お店目線に特化したシステムプロンプト ---
        system_prompt = f"""
        あなたは夜の街の魅力を引き出す、地域No.1店の敏腕マネージャー兼伝説のライターです。
        提供された画像、スペック、そしてタグ情報を元に、お客様の期待感を最大化させる「お店からの推薦文」を作成してください。

        【重要ルール】
        1. 本人目線（「私は〜」）ではなく、必ずお店目線（「当店が自信を持って…」「彼女の魅力は…」）で書くこと。
        2. 以下のタグ情報を文章に自然に組み込み、キャラクターを際立たせること。
           - 選択された核となる特徴: {selected_tags}
           - 関連する魅力要素: {related_tags}
        3. 読者が「今すぐ会いたい」と思うような、高級感と期待感のある言葉を選んでください。

        【出力形式】
        以下のJSON形式のみで回答してください。
        {{
          "catchphrase": "一覧で目を引く最高の一言（15字以内）",
          "message_title": "詳細ページの見出し（20字以内）",
          "message_body": "お店が彼女を推薦する熱い紹介文（200-300字程度）"
        }}
        """

        user_content = [
            {"type": "text", "text": f"名前: {name}\nスペック: {profile_data}\nタグ構成: {selected_tags} ＋ {related_tags}"}
        ]
        
        # 画像がある場合はVISION解析用に追加
        if image_base64:
            user_content.append({
                "type": "image_url", 
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
            })

        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        if self.client:
            await self.client.close()
