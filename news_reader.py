import json
import hashlib
import os
import csv
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from gpt_layer import call_gpt
from story_mode import generate_story_mode

# --- VADER Sentiment (lightweight, no GPU needed) ---
analyzer = SentimentIntensityAnalyzer()

def vader_sentiment(text):
    """Returns compound sentiment score from -1 to +1."""
    return analyzer.polarity_scores(str(text))["compound"]

# --- Secrets ---
try:
    NEWSAPI_KEY = st.secrets["NEWS_API_KEY"]
except Exception:
    NEWSAPI_KEY = os.environ.get("NEWS_API_KEY", "")
    if not NEWSAPI_KEY:
        print("[Warning] NEWS_API_KEY not found in secrets or environment.")

# --- Memory (deduplication) ---
def load_memory():
    try:
        with open("news_memory.json", "r") as f:
            return set(json.load(f)["seen"])
    except Exception:
        return set()

def save_memory(memory):
    try:
        with open("news_memory.json", "w") as f:
            json.dump({"seen": list(memory)}, f, indent=2)
    except Exception as e:
        print(f"[Memory save error] {e}")

def article_id(article):
    if "url" in article and article["url"]:
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

# --- News Fetching ---
def fetch_newsapi():
    try:
        url = (
            "https://newsapi.org/v2/top-headlines"
            f"?category=business&language=en&apiKey={NEWSAPI_KEY}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "source":   a["source"]["name"],
                "headline": a["title"],
                "date":     a["publishedAt"],
                "url":      a.get("url")
            }
            for a in data.get("articles", [])
            if a.get("title")
        ]
    except Exception as e:
        print(f"[NewsAPI error] {e}")
        return []

def fetch_all_sources():
    return fetch_newsapi()

# --- Processing ---
def process_all_news():
    articles = fetch_all_sources()
    results = []
    for article in articles:
        try:
            analysis = process_headline(article["headline"])
            analysis["source"] = article.get("source")
            analysis["date"]   = article.get("date")
            analysis["id"]     = article_id(article)
            results.append(analysis)
        except Exception as e:
            print(f"[Processing error] {e}")
    return results

# --- Saving (with deduplication) ---
def save_results(results):
    if not results:
        print("No results to save.")
        return []

    memory = load_memory()
    new_results = [r for r in results if r["id"] not in memory]

    if not new_results:
        print("No new articles to save.")
        return []

    try:
        new_df = pd.DataFrame(new_results)
        if os.path.exists("ai_news_output.csv"):
            old_df = pd.read_csv("ai_news_output.csv")
            df = pd.concat([old_df, new_df], ignore_index=True)
        else:
            df = new_df
        df.to_csv("ai_news_output.csv", index=False)

        for r in new_results:
            memory.add(r["id"])
        save_memory(memory)

        print(f"Saved {len(new_results)} new articles to ai_news_output.csv")
    except Exception as e:
        print(f"[Save error] {e}")
        return []

    return new_results

# --- GPT Analysis ---
def run_gpt_analysis(results):
    sorted_results = sorted(results, key=lambda x: x["relevance"], reverse=True)
    relevant = [r["headline"] for r in sorted_results[:3]]

    if not relevant:
        print("No relevant headlines for GPT analysis.")
        return

    try:
        gpt_output = call_gpt(relevant)
        if gpt_output:
            with open("gpt_analysis.json", "w") as f:
                json.dump(gpt_output, f, indent=2)
            print(f"GPT analysis saved — {len(relevant)} headlines analysed.")
    except Exception as e:
        print(f"[GPT error] {e}")

# --- Pipeline ---
def run_pipeline():
    print("Fetching and processing news...")
    results = process_all_news()
    new_results = save_results(results)

    if new_results:
        run_gpt_analysis(new_results)

        # Save rolling AI hype count
        try:
            ai_today = sum(
                1 for a in new_results
                if any(k in a["headline"].lower() for k in
                       ["ai", "artificial intelligence", "chip", "semiconductor", "gpu", "nvidia", "openai"])
            )
            with open("ai_hype_history.csv", "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([datetime.now().strftime("%Y-%m-%d"), ai_today])
        except Exception as e:
            print(f"[AI hype tracking error] {e}")

    print("Done.")