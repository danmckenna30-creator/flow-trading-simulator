import json
import os
import pandas as pd
from datetime import datetime, timedelta, timezone
from gpt_layer import call_gpt

def generate_story_mode():
    # Load news
    try:
        df = pd.read_csv("ai_news_output.csv")
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    except Exception:
        return "No news data available."

    # Filter last 24 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = df[df["date"] >= cutoff]

    if recent.empty:
        recent = df.tail(20)  # fallback to latest 20 if nothing in last 24h

    # Load GPT macro analysis
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

    # Build prompt
    cols = [c for c in ["headline", "sentiment", "topic"] if c in recent.columns]
    prompt = f"""
You are a macro analyst writing a morning brief for traders.

Use the following data:

1. Last 24h headlines:
{recent[cols].to_string(index=False)}

2. Macro analysis:
{json.dumps(gpt, indent=2)}

Write a concise, trader-ready morning note with:
- Market tone (1 paragraph)
- Key macro themes (3-5 bullets)
- What drove sentiment
- Risk regime (risk-on/off/neutral)
- What to watch today
- A final 3-bullet summary

Keep it sharp, professional, and Bloomberg-style.
"""

    try:
        story = call_gpt([prompt])
        if isinstance(story, dict):
            story = json.dumps(story, indent=2)
        if not story:
            return "Story mode generation failed."

        # Use direct client call for story (not structured JSON)
        from gpt_layer import _get_client
        c = _get_client()
        if c is None:
            return "No OpenAI key available for story mode."

        response = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.3
        )
        story = response.choices[0].message.content

        try:
            with open("story_mode.txt", "w") as f:
                f.write(story)
        except Exception as e:
            print(f"[story_mode] Could not save file: {e}")

        return story

    except Exception as e:
        print(f"[story_mode error] {e}")
        return f"Story mode error: {e}"

if __name__ == "__main__":
    print(generate_story_mode())