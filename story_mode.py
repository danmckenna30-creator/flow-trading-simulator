import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from gpt_layer import _get_client


def generate_story_mode(news_df=None, gpt_analysis=None):
    """
    Generate a Bloomberg-style morning brief.
    Accepts data directly so it works without any files on disk.
    """
    # --- Load news from Sheets if not passed in ---
    if news_df is None:
        try:
            from sheets_db import load_news_from_sheets
            news_df = load_news_from_sheets()
        except Exception as e:
            return f"Could not load news data: {e}"

    if news_df is None or (hasattr(news_df, 'empty') and news_df.empty):
        return "No news data available yet — pipeline may still be running."

    # --- Filter to last 24h ---
    try:
        if "date" in news_df.columns:
            news_df["date"] = pd.to_datetime(news_df["date"], utc=True, errors="coerce")
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            recent = news_df[news_df["date"] >= cutoff]
            if recent.empty:
                recent = news_df.tail(20)
        else:
            recent = news_df.tail(20)
        recent = recent.tail(50)
    except Exception:
        recent = news_df.tail(20)

    # --- Load GPT analysis ---
    if gpt_analysis is None:
        try:
            import streamlit as st
            gpt_analysis = st.session_state.get("gpt_analysis", {})
        except Exception:
            gpt_analysis = {}

    if not gpt_analysis:
        gpt_analysis = {
            "macro_theme": "unknown",
            "summary": "No GPT macro analysis available.",
            "market_impact": "neutral",
            "confidence": 0,
            "key_points": []
        }

    # --- Build prompt ---
    headlines_text = "\n".join(
        recent["headline"].head(10).astype(str).tolist()
    ) if "headline" in recent.columns else "No headlines available."

    prompt = f"""
You are a senior macro strategist writing a professional morning note for institutional traders.

HEADLINES (last 24h):
{headlines_text}

MACRO ANALYSIS:
{json.dumps(gpt_analysis)}

You MUST output all of the following sections.
All headings MUST be on their own line.

## Market Tone
One concise paragraph.

## Key Macro Themes
Exactly 3 bullet points.

## What Drove Sentiment
Main drivers in 2-3 sentences.

## Risk
Risk regime and why in 2 sentences.

## What To Watch Today
3 bullet points covering economic data, central banks, and markets.

## The Key Takeaway
3 sentences max.

Style: Bloomberg terminal, professional, concise, no fluff, no markdown tables.
"""

    try:
        client = _get_client()
        if client is None:
            return "OpenAI key not available — check Streamlit secrets."

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.3
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"Story mode error: {e}"


if __name__ == "__main__":
    print(generate_story_mode())