import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from gpt_layer import _get_client


def generate_story_mode():
    # -------------------------
    # Load news data
    # -------------------------
    try:
        df = pd.read_csv("ai_news_output.csv")

        if "date" in df.columns:
            df["date"] = pd.to_datetime(
                df["date"],
                utc=True,
                errors="coerce"
            )

    except Exception as e:
        return f"Could not load ai_news_output.csv: {e}"

    # -------------------------
    # Filter recent headlines
    # -------------------------
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        if "date" in df.columns:
            recent = df[df["date"] >= cutoff]
        else:
            recent = df

        if recent.empty:
            recent = df.tail(20)

    except Exception as e:
        return f"News filtering error: {e}"

    # -------------------------
    # Load macro analysis
    # -------------------------
    try:
        with open("gpt_analysis.json", "r") as f:
            gpt = json.load(f)

    except Exception:
        gpt = {
            "macro_theme": "unknown",
            "summary": "No GPT macro analysis available.",
            "market_impact": "neutral",
            "confidence": 0,
            "key_points": []
        }

    # -------------------------
    # Build prompt
    # -------------------------
    cols = [
        c for c in ["headline", "sentiment", "topic"]
        if c in recent.columns
    ]

    headlines_text = "\n".join(recent["headline"].head(3).tolist())

    prompt = f"""
You are a senior macro strategist writing a professional morning note for institutional traders.

Format headings EXACTLY like this:

## Market Tone
<paragraph here>

MACRO ANALYSIS:
{json.dumps(gpt)}

You MUST output all of the following sections.

## Market Tone
Provide one concise paragraph.

## Key Macro Themes
Provide exactly 3 bullet points.

## What Drove Sentiment
Explain the main drivers of market sentiment today.

## Risk 
Explain Risk Regime and why in 2 sentences

## What To Watch Today
Provide exactly 3 bullet points covering:
- Economic data
- Central banks
- Commodities
- Rates
- Equities

## The Key Takeaway
Provide the key takeaway, 3 sentences 

Style:
- Bloomberg terminal
- Professional
- Concise   
- No fluff
- No markdown tables
"""
    # -------------------------
    # OpenAI call
    # -------------------------
    try:
        client = _get_client()

        if client is None:
            return "DEBUG: _get_client() returned None"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=350
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"DEBUG ERROR: {e}"