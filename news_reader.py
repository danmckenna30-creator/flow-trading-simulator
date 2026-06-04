import json
import hashlib
import os
import torch
import numpy as np
import pandas as pd
import requests
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from apscheduler.schedulers.blocking import BlockingScheduler
from gpt_layer import call_gpt
from story_mode import generate_story_mode

# --- FinBERT Setup ---
tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")

NEWSAPI_KEY = "9e771673d1b54ded8968a567705e3fda"

# --- Memory (deduplication) ---
def load_memory():
    try:
        with open("news_memory.json", "r") as f:
            return set(json.load(f)["seen"])
    except:
        return set()

def save_memory(memory):
    with open("news_memory.json", "w") as f:
        json.dump({"seen": list(memory)}, f, indent=2)

def article_id(article):
    if "url" in article and article["url"]:
        return article["url"]
    return hashlib.md5(article["headline"].encode()).hexdigest()

# --- Sentiment & Analysis ---
def finbert_sentiment(text):
    inputs = tokenizer(text, return_tensors="pt", truncation=True)
    outputs = model(**inputs)
    logits = outputs.logits.detach().numpy()[0]
    probs = np.exp(logits) / np.exp(logits).sum()
    return float(probs[2] - probs[0])  # positive minus negative

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
    sentiment = finbert_sentiment(headline)
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
        url  = f"https://newsapi.org/v2/top-headlines?category=business&language=en&apiKey={NEWSAPI_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return [
            {"source": a["source"]["name"], "headline": a["title"], "date": a["publishedAt"]}
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
    results  = []
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
        return

    # Filter to only new articles using memory
    memory = load_memory()
    new_results = [r for r in results if r["id"] not in memory]

    if not new_results:
        print("No new articles to save.")
        return

    # Append to existing CSV or create new one
    new_df = pd.DataFrame(new_results)
    if os.path.exists("ai_news_output.csv"):
        old_df = pd.read_csv("ai_news_output.csv")
        df = pd.concat([old_df, new_df], ignore_index=True)
    else:
        df = new_df

    df.to_csv("ai_news_output.csv", index=False)

    # Update memory with newly seen IDs
    for r in new_results:
        memory.add(r["id"])
    save_memory(memory)

    print(f"Saved {len(new_results)} new articles to ai_news_output.csv")
    return new_results

# --- GPT Analysis ---
def run_gpt_analysis(results):
    """Take top 3 most relevant headlines and run GPT analysis."""
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
    print("Done.")

if __name__ == "__main__":
    run_pipeline()  # run once immediately on start
    scheduler = BlockingScheduler()
    scheduler.add_job(run_pipeline, "interval", minutes=60)
    scheduler.add_job(generate_story_mode, "cron", hour=8, minute=0)
    print("Scheduler started — updating every 60 minutes, story mode at 8am daily.")
    scheduler.start()

# Save rolling AI hype count
ai_today = sum(
    1 for a in new_articles
    if any(k in a["headline"].lower() for k in ["ai", "artificial intelligence", "chip", "semiconductor", "gpu", "nvidia", "openai"])
)

# Append to ai_hype_history.csv
import csv
with open("ai_hype_history.csv", "a", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([datetime.now().strftime("%Y-%m-%d"), ai_today])
