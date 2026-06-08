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

# Lazy client
client = None

def _ensure_client():
    global client
    if client is None:
        client = _get_client()
    return client


def call_gpt(headlines):
    """
    Structured JSON analysis of headlines.
    Used by the main pipeline for macro analysis.
    """
    c = _ensure_client()
    if c is None:
        print("[GPT] No API key available, skipping.")
        return None

    # If a single long prompt string is passed, treat it as a prose request
    if isinstance(headlines, list) and len(headlines) == 1 and len(headlines[0]) > 200:
        return call_gpt_prose(headlines[0])

    prompt = f"""
You are a macro-finance analyst. You will receive a list of news headlines.
Your job is to produce a structured JSON analysis with:

1. macro_theme: The dominant macro theme (inflation, growth, geopolitics, energy, tech, credit, etc.)
2. summary: A 2-3 sentence analyst-style summary
3. market_impact: One of ["risk-on", "risk-off", "neutral"]
4. confidence: 0-100 score of how confident you are
5. key_points: 3-5 bullet points of the most important takeaways

Here are the headlines:
{json.dumps(headlines, indent=2)}

Return ONLY valid JSON. No commentary.
"""
    try:
        response = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.2
        )
        content = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            return json.loads(content)
        except Exception:
            print(f"GPT output was not valid JSON: {content[:100]}")
            return None
    except Exception as e:
        print(f"[GPT error] {e}")
        return None


def call_gpt_prose(prompt_text):
    """
    Free-form prose response — used for risk narratives, story mode, etc.
    Returns a plain string, not JSON.
    """
    c = _ensure_client()
    if c is None:
        return None
    try:
        response = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_text}],
            max_tokens=500,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GPT prose error] {e}")
        return None