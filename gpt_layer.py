import requests
import json
from openai import OpenAI
import os
import streamlit as st
from openai import OpenAI

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])


def call_gpt(headlines):
    """
    Takes a list of relevant headlines and returns structured macro analysis.
    """

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

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.2
    )

    content = response.choices[0].message.content

    try:
        return json.loads(content)
    except:
        print("GPT output was not valid JSON.")
        return None
