import json
import hashlib
import os
import csv
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from gpt_layer import call_gpt
from story_mode import generate_story_mode
from sheets_db import load_news_from_sheets, save_news_to_sheets

# --- VADER Sentiment ---
_vader = SentimentIntensityAnalyzer()

def vader_sentiment(text):
    return _vader.polarity_scores(str(text))["compound"]

# --- Secrets ---
try:
    GNEWS_KEY = st.secrets.get("GNEWS_API_KEY") or os.environ.get("GNEWS_API_KEY", "")
except Exception:
    GNEWS_KEY = os.environ.get("GNEWS_API_KEY", "")
if not GNEWS_KEY:
    print("[Warning] GNEWS_API_KEY not found.")

# --- Deduplication ---
def get_seen_ids(df):
    if df is None or "id" not in df.columns:
        return set()
    return set(df["id"].dropna().astype(str).tolist())

def article_id(article):
    if article.get("url"):
        return article["url"]
    return hashlib.md5(article["headline"].encode()).hexdigest()

# --- Analysis ---
def classify_relevance(text):
    keywords = [
        # US macro
        "inflation", "rates", "fed", "federal reserve", "fomc",
        "earnings", "growth", "recession", "jobs", "cpi", "gdp",
        "bond yields", "treasury", "nfp", "payrolls", "retail sales",
        # UK macro
        "bank of england", "boe", "mpc", "gilt", "ftse", "sterling",
        "pound", "uk inflation", "uk gdp", "uk jobs", "ons",
        # European macro
        "ecb", "eurozone", "draghi", "lagarde", "bund", "dax",
        "german", "france", "italy", "euro", "eur",
        # Commodities / markets
        "oil", "energy", "opec", "gold", "copper",
        "geopolitics", "war", "sanctions", "supply chain",
    ]
    return sum(k in text.lower() for k in keywords) / len(keywords)

def classify_topic(text):
    text = text.lower()
    if any(k in text for k in ["inflation", "cpi", "ppi", "rpi"]):
        return "inflation"
    if any(k in text for k in ["fed", "fomc", "ecb", "bank of england", "boe", "mpc", "rates", "rate decision", "rate cut", "rate hike"]):
        return "policy"
    if any(k in text for k in ["earnings", "profit", "revenue", "results", "outlook"]):
        return "earnings"
    if any(k in text for k in ["war", "geopolitics", "conflict", "sanctions", "ukraine", "middle east", "nato"]):
        return "geopolitics"
    if any(k in text for k in ["oil", "energy", "gas", "opec", "brent", "wti"]):
        return "energy"
    if any(k in text for k in ["uk", "ftse", "sterling", "pound", "gilt", "chancellor", "budget"]):
        return "uk"
    if any(k in text for k in ["euro", "eurozone", "ecb", "bund", "dax", "german", "france"]):
        return "europe"
    if any(k in text for k in ["china", "pmi", "manufacturing", "trade", "tariff"]):
        return "growth"
    return "other"

def should_escalate(sentiment, relevance):
    return abs(sentiment) > 0.2 or relevance > 0.2

def process_headline(headline):
    sentiment = vader_sentiment(headline)
    relevance = classify_relevance(headline)
    return {
        "headline": headline,
        "sentiment": sentiment,
        "relevance": relevance,
        "topic":     classify_topic(headline),
        "escalate":  should_escalate(sentiment, relevance)
    }

# --- News Fetching via GNews ---
# We fetch from three regions to give good UK morning coverage:
# GB (UK), US (global business), and EU (European macro)
# GNews free tier = 100 requests/day, so 3 requests per pipeline run
# At 55-minute intervals that is ~80 requests/day — within limit.

GNEWS_SOURCES = [
    {"country": "gb", "label": "UK",     "max": 5},   # UK news — fresh at 7am London
    {"country": "us", "label": "US",     "max": 5},   # US business headlines
    {"country": "de", "label": "Europe", "max": 3},   # German/European macro proxy
]

def _fetch_gnews_region(country: str, max_articles: int, label: str) -> list:
    """Fetch top business headlines for a specific country/region."""
    try:
        url = (
            "https://gnews.io/api/v4/top-headlines"
            f"?category=business&lang=en&country={country}"
            f"&max={max_articles}&apikey={GNEWS_KEY}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        articles = []
        for a in data.get("articles", []):
            if not a.get("title"):
                continue
            try:
                pub = pd.to_datetime(a["publishedAt"], utc=True)
                if pub < cutoff:
                    continue
            except Exception:
                pass
            articles.append({
                "source":   f"[{label}] {a.get('source', {}).get('name', 'Unknown')}",
                "headline": a["title"],
                "date":     a["publishedAt"],
                "url":      a.get("url", ""),
                "region":   label,
            })
        print(f"[GNews/{label}] Fetched {len(articles)} articles.")
        return articles
    except Exception as e:
        print(f"[GNews/{label} error] {e}")
        return []


def fetch_gnews():
    """Fetch from UK, US, and European sources and deduplicate by headline."""
    all_articles = []
    seen_headlines = set()

    for source in GNEWS_SOURCES:
        articles = _fetch_gnews_region(
            country=source["country"],
            max_articles=source["max"],
            label=source["label"]
        )
        for a in articles:
            # Deduplicate on headline text across regions
            key = a["headline"].strip().lower()[:80]
            if key not in seen_headlines:
                seen_headlines.add(key)
                all_articles.append(a)

    print(f"[GNews] Total unique articles: {len(all_articles)}")
    return all_articles


def fetch_all_sources():
    return fetch_gnews()

# --- Processing ---
def process_all_news(existing_df=None):
    articles = fetch_all_sources()
    # Only deduplicate against real news rows (must have a headline)
    if existing_df is not None and "headline" in existing_df.columns:
        real_rows = existing_df[existing_df["headline"].str.strip() != "Test headline"]
        seen_ids = get_seen_ids(real_rows)
    else:
        seen_ids = set()
    print(f"[Pipeline] {len(articles)} fetched, {len(seen_ids)} already seen.")
    results = []
    for article in articles:
        aid = article_id(article)
        if aid in seen_ids:
            continue
        try:
            analysis = process_headline(article["headline"])
            analysis["source"] = article.get("source")
            analysis["date"]   = article.get("date")
            analysis["url"]    = article.get("url", "")
            analysis["id"]     = aid
            results.append(analysis)
        except Exception as e:
            print(f"[Processing error] {e}")
    print(f"[Pipeline] {len(results)} new articles to save.")
    return results

# --- GPT Analysis ---
def run_gpt_analysis(results):
    sorted_results = sorted(results, key=lambda x: x["relevance"], reverse=True)
    relevant = [r["headline"] for r in sorted_results[:3]]
    if not relevant:
        return
    try:
        gpt_output = call_gpt(relevant)
        if gpt_output:
            st.session_state["gpt_analysis"] = gpt_output
            print("GPT analysis saved to session state.")
    except Exception as e:
        print(f"[GPT error] {e}")

# --- Pipeline ---
def run_pipeline():
    print("Fetching and processing news...")

    existing_df = load_news_from_sheets()

    if existing_df is None or len(existing_df) == 0:
        print("[Pipeline] Sheet is empty — forcing full fetch.")
        existing_df = None

    new_results = process_all_news(existing_df)

    if new_results:
        save_news_to_sheets(new_results)
        print(f"Saved {len(new_results)} new articles.")
        run_gpt_analysis(new_results)
        try:
            fresh_df = load_news_from_sheets()
            gpt_data = st.session_state.get("gpt_analysis", None)
            story = generate_story_mode(news_df=fresh_df, gpt_analysis=gpt_data)
            st.session_state["story_text"] = story
        except Exception as e:
            print(f"[Story mode error] {e}")
    else:
        print("No new articles.")

    print("Done.")