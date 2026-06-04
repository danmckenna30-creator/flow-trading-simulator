import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from gpt_layer import _get_client


def generate_story_mode():
    import os
    print("LOADING CSV FROM:", os.path.abspath("ai_news_output.csv"))

    # -------------------------
    # Load news data
    # -------------------------
    try:
        df = pd.read_csv("ai_news_output.csv")

        # Convert dates safely
        if "date" in df.columns:
            df["date"] = pd.to_datetime(
                df["date"],
                utc=True,
                errors="coerce"
            )

        # Remove garbage timestamps
        df = df[df["date"] > datetime(2000, 1, 1, tzinfo=timezone.utc)]

        # HARD CAP: prevent runaway file growth
        if len(df) > 500:
            df = df.tail(500)

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

        # If nothing recent, fallback to last 20
        if recent.empty:
            recent = df.tail(20)

        # CAP recent articles to avoid huge batches
        recent = recent.tail(50)

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
    headlines_text = "\n".join(
        recent["headline"].head(3).astype(str).tolist()
    )

    prompt = f"""
You are a senior macro strategist writing a professional morning note for institutional traders.

HEADLINES (last 24h):
{headlines_text}

MACRO ANALYSIS:
{json.dumps(gpt)}

You MUST output all of the following sections.
All headings MUST be on their own line. Never place text on the same line as a heading.

## Market Tone
Provide one concise paragraph.

## Key Macro Themes
Provide exactly 3 bullet points.

## What Drove Sentiment
Explain the main drivers of market sentiment today.

## Risk
Explain the risk regime and why in exactly 2 sentences.

## What To Watch Today
Provide exactly 3 bullet points covering:
- Economic data
- Central banks
- Commodities
- Rates
- Equities

## The Key Takeaway
Provide the key takeaway in 3 sentences.

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
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"DEBUG ERROR: {e}"
