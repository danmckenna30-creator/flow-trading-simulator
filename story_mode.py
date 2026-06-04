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

    headlines_text = recent[cols].to_string(index=False)

    prompt = f"""
You are a senior macro strategist writing a morning brief for traders.

Use the information below.

HEADLINES:
{headlines_text}

MACRO ANALYSIS:
{json.dumps(gpt, indent=2)}

Write:

1. Market Tone
2. Key Macro Themes
3. What Drove Sentiment
4. Risk Regime
5. What To Watch Today
6. Three Key Takeaways

Style:
- Bloomberg
- Professional
- Concise
- No markdown tables
- Maximum 500 words
"""

    # -------------------------
    # OpenAI call
    # -------------------------
    try:
        client = _get_client()

        if client is None:
            return (
                "OpenAI client not available. "
                "Check OPENAI_API_KEY."
            )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=500,
            temperature=0.3
        )

        story = response.choices[0].message.content

        if not story:
            return "OpenAI returned an empty response."

        try:
            with open(
                "story_mode.txt",
                "w",
                encoding="utf-8"
            ) as f:
                f.write(story)
        except Exception as e:
            print(f"[story_mode] save error: {e}")

        return story

    except Exception as e:
        return f"Story mode error: {e}"


if __name__ == "__main__":
    print(generate_story_mode())