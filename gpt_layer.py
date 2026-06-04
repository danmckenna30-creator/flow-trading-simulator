import json
import os
import streamlit as st
from openai import OpenAI

def _get_client():
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("[Warning] OPENAI_API_KEY not found.")
        return None
    return OpenAI(api_key=api_key)

# Lazy client — only created when needed
client = None

def call_gpt(headlines):
    global client
    if client is None:
        client = _get_client()
    if client is None:
        print("[GPT] No API key available, skipping.")
        return None

    prompt = f"""
You are a macro-finance analyst. You will receive a list of news headlines.
Your job is to produce a structured JSON analysis with:

1. macro_theme: The dominant macro theme (inflation, growth, geopolitics, energy, tech, credit, etc.)
2. summary: A 2–3 sentence analyst-style summary
3. market_impact: One of ["risk-on", "risk-off", "neutral"]
4. confidence: 0–100 score of how confident you are
5. key_points: 3–5 bullet points of the most important takeaways

Here are the headlines:
{json.dumps(headlines, indent=2)}

Return ONLY valid JSON. No commentary.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.2
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except Exception:
            print("GPT output was not valid JSON.")
            return None
    except Exception as e:
        print(f"[GPT error] {e}")
        return None