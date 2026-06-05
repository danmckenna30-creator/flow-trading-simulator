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
    NEWSAPI_KEY = st.secrets.get("NEWSAPI_KEY") or st.secrets.get("NEWS_API_KEY") or ""
except Exception:
    NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
if not NEWSAPI_KEY:
    print("[Warning] NEWSAPI_KEY not found.")

# --- Deduplication (in-memory for 24h window) ---
def get_seen_ids(df: pd.DataFrame) -> set:
    """Get IDs already in the sheet to avoid duplicates."""
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
        "inflation", "rates", "fed", "ecb", "bank of england",
        "earnings", "growth", "recession", "oil", "energy",
        "geopolitics", "war", "jobs", "cpi", "gdp", "bond yields"
    ]
    return sum(k in text.lower() for k in keywords) / len(keywords)

def classify_topic(text):
    text = text.lower()
    if any(k in text for k in ["inflation", "cpi", "ppi"]):
        return "inflation"
    if any(k in text for k in ["fed", "ecb", "bank of england", "rates"]):
        return "policy"
    if any(k in text for k in ["earnings", "profit", "revenue"]):
        return "earnings"
    if any(k in text for k in ["war", "geopolitics", "conflict"]):
        return "geopolitics"
    if any(k in text for k in ["oil", "energy", "gas"]):
        return "energy"
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

# --- News Fetching (last 24h only) ---
def fetch_newsapi():
    try:
        url = (
            "https://newsapi.org/v2/top-headlines"
            f"?category=business&language=en&pageSize=100&apiKey={NEWSAPI_KEY}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Filter to articles published in the last 24 hours
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
                "source":   a["source"]["name"],
                "headline": a["title"],
                "date":     a["publishedAt"],
                "url":      a.get("url", "")
            })
        return articles
    except Exception as e:
        print(f"[NewsAPI error] {e}")
        return []

# --- Processing ---
def process_all_news(existing_df=None):
    articles = fetch_newsapi()
    seen_ids = get_seen_ids(existing_df)
    results = []
    for article in articles:
        aid = article_id(article)
        if aid in seen_ids:
            continue
        try:
            analysis = process_headline(article["headline"])
            analysis["source"] = article.get("source")
            analysis["date"]   = article.get("date")
            analysis["id"]     = aid
            results.append(analysis)
        except Exception as e:
            print(f"[Processing error] {e}")
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
            print(f"GPT analysis saved to session state.")
    except Exception as e:
        print(f"[GPT error] {e}")

# --- Pipeline ---
def run_pipeline():
    print("Fetching and processing news...")

    # Load existing data to check for duplicates
    existing_df = load_news_from_sheets()

    # Fetch and process only new articles
    new_results = process_all_news(existing_df)

    if new_results:
        # Save to Google Sheets
        save_news_to_sheets(new_results)
        print(f"Saved {len(new_results)} new articles.")

        # Run GPT analysis on most relevant
        run_gpt_analysis(new_results)

        # Generate story mode
        try:
            story = generate_story_mode()
            st.session_state["story_text"] = story
        except Exception as e:
            print(f"[Story mode error] {e}")
    else:
        print("No new articles.")

    print("Done.")