import os
import json
import base64
import streamlit as st
import requests
import re
from groq import AsyncGroq

class GroqService:
    def __init__(self):
        self.client = None
        self.model = "llama-3.2-11b-vision-preview" # Vision対応モデルに変更

    async def initialize(self):
        api_key = st.secrets.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
        if not api_key:
            st.error("APIキーが見つかりません。")
        self.client = AsyncGroq(api_key=api_key)

    def _get_image_base64_from_drive(self, drive_url):
        """GoogleドライブのURLから画像をダウンロードし、Base64に変換する"""
        try:
            match = re.search(r'd/([a-zA-Z0-9_-]+)', drive_url)
            if not match: return None
            file_id = match.group(1)
            direct_url = f'https://drive.google.com/uc?export=download&id={file_id}'
            response = requests.get(direct_url, timeout=10)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            st.error(f"画像取得エラー: {e}")
        return None

    async def generate_store_content(self, profile_data, shop_type="店舗型"):
        """
        お店目線でキャッチコピー、タイトル、本文を生成する
        """
        if not self.client:
            await self.initialize()

        # ドライブURLから画像データを取得
        image_base64 = self._get_image_base64_from_drive(profile_data.get('image_url', ''))
        
        # ユーザーが選択したタグ（例: ['清楚', '美肌', '潮吹き']）
        user_tags = profile_data.get('selected_tags', [])
        
        # システムプロンプト：お店目線 & タグパターン意識
        system_prompt = f"""
        あなたは夜の街で数々の人気キャストをプロデュースしてきた伝説の店長です。
        提供された画像とスペックから、**「お店からの推薦文」**として、読者の期待感を最大化させる紹介文を作成してください。

        【重要ルール】
        1. **視点**: 常に「当店スタッフが太鼓判を押す」「マネージャー目線」の三人称視点であること。
        2. **文体**: {shop_type}に合わせたトーン（例：出張なら高級感、店舗なら親しみやすさ）。
        3. **タグの活用**: ユーザーが選んだタグ {user_tags} を核とし、提供された「タグパターンリスト」の傾向（関連タグなど）を参考に、矛盾のない魅力的な文章にすること。
        4. **禁止事項**: 「nano banana」等のワード、画像生成に関する言及は一切禁止。

        【出力形式】
        JSON形式で以下の3点を出力してください。
        {{
          "catchphrase": "（15字以内の強烈なキャッチ）",
          "message_title": "（20字以内の詳細ページ用タイトル）",
          "message_body": "（200〜300字程度のお店からの熱い推薦文）"
        }}
        """

        user_content = [
            {"type": "text", "text": f"名前: {profile_data.get('name')}\nスペック: {profile_data}\n選択タグ: {user_tags}"}
        ]

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
