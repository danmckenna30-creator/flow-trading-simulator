import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from gpt_layer import client

def generate_story_mode():
    # Load news
    try:
        df = pd.read_csv("ai_news_output.csv")
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    except:
        return "No news data available."

    # Filter last 24 hours (timezone-aware)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = df[df["date"] >= cutoff]

    # Load GPT macro analysis
    try:
        with open("gpt_analysis.json", "r") as f:
            gpt = json.load(f)
    except:
        gpt = {
            "macro_theme": "unknown",
            "summary": "No GPT macro analysis available.",
            "market_impact": "neutral",
            "confidence": 0,
            "key_points": []
        }

    # Build prompt
    prompt = f"""
You are a macro analyst writing a morning brief for traders.

Use the following data:

1. Last 24h headlines:
{recent[['headline','sentiment','topic']].to_string(index=False)}

2. Macro analysis:
{json.dumps(gpt, indent=2)}

Write a concise, trader-ready morning note with:

- Market tone (1 paragraph)
- Key macro themes (3–5 bullets)
- What drove sentiment
- Risk regime (risk-on/off/neutral)
- What to watch today (macro events or themes)
- A final 3-bullet summary

Keep it sharp, professional, and Bloomberg-style.
"""

    # Call GPT (fixed: use .content)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.3
    )

    story = response.choices[0].message.content

    # Save output
    with open("story_mode.txt", "w") as f:
        f.write(story)

    return story

if __name__ == "__main__":
    print(generate_story_mode())