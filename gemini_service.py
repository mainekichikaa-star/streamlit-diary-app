import os
import json
import base64
import streamlit as st
from groq import AsyncGroq

class GroqService:
    def __init__(self):
        self.client = None
        self.model = "llama3-70b-8192"

    async def initialize(self):
        # Streamlit Cloudの「Secrets」設定からキーを読み込む
        api_key = st.secrets.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
        if not api_key:
            st.error("APIキーが見つかりません。Secretsを確認してください。")
        self.client = AsyncGroq(api_key=api_key)

    async def analyze_cast_image(self, image_bytes, tags, profile_data):
        if not self.client:
            await self.initialize()

        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        name = profile_data.get('name', '彼女')
        
        # --- システムプロンプト (以前のものを継承) ---
        system_prompt = """
        あなたは夜の街の魅力を引き出す伝説の紹介文ライターです。
        提供された画像とスペックから、読者の期待感を最大化させる紹介文を作成してください。
        JSON形式で返してください。 {"catchphrase": "...", "description": "..."}
        """

        user_content = [
            {"type": "text", "text": f"名前: {name}\nタグ: {tags}\nスペック: {profile_data}"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]

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