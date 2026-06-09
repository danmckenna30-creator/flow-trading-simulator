"""
sheets_db.py — Google Sheets as a persistent news database.
Reads/writes the last 24 hours of news articles.
"""
import os
import json
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_NAME = "MacroNewsData"   # name of the Google Sheet
TAB_NAME   = "news"            # worksheet tab name

COLUMNS = ["id", "date", "source", "headline", "sentiment",
           "relevance", "topic", "escalate", "url"]


def get_sheet():
    """Connect to Google Sheets using service account credentials from Streamlit secrets."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open(SHEET_NAME)
        try:
            ws = sh.worksheet(TAB_NAME)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=TAB_NAME, rows=5000, cols=len(COLUMNS))
            ws.append_row(COLUMNS)  # add header
        return ws
    except Exception as e:
        print(f"[Sheets] Connection error: {e}")
        return None


def load_news_from_sheets() -> pd.DataFrame | None:
    """Load last 24 hours of news from Google Sheets."""
    ws = get_sheet()
    if ws is None:
        return None
    try:
        records = ws.get_all_records()
        if not records:
            return None
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        df = df[df["date"] >= cutoff]
        return df if not df.empty else None
    except Exception as e:
        print(f"[Sheets] Load error: {e}")
        return None


def save_news_to_sheets(new_results: list) -> None:
    """
    Append new articles to the sheet.
    Removes articles older than 24 hours to keep the sheet lean.
    """
    if not new_results:
        return

    ws = get_sheet()
    if ws is None:
        return

    try:
        # Load existing data
        records = ws.get_all_records()
        existing_ids = {r["id"] for r in records if r.get("id")}

        # Filter to truly new articles
        to_add = [r for r in new_results if r.get("id") not in existing_ids]
        if not to_add:
            print("[Sheets] No new articles to add.")
            return

        # Append new rows
        rows = [
            [
                str(r.get("id", "")),
                str(r.get("date", "")),
                str(r.get("source", "")),
                str(r.get("headline", "")),
                float(r.get("sentiment", 0)),
                float(r.get("relevance", 0)),
                str(r.get("topic", "")),
                str(r.get("escalate", False)),
                str(r.get("url", "")),
            ]
            for r in to_add
        ]
        ws.append_rows(rows, value_input_option="RAW")

        # Prune rows older than 24 hours to keep sheet clean
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        all_records = ws.get_all_records()
        rows_to_keep = []
        for rec in all_records:
            try:
                dt = pd.to_datetime(rec["date"], utc=True, errors="coerce")
                if pd.isna(dt) or dt >= cutoff:
                    rows_to_keep.append(rec)
            except Exception:
                rows_to_keep.append(rec)

        # Rewrite sheet if we pruned anything
        if len(rows_to_keep) < len(all_records):
            ws.clear()
            ws.append_row(COLUMNS)
            keep_rows = [
                [str(r.get(c, "")) for c in COLUMNS]
                for r in rows_to_keep
            ]
            ws.append_rows(keep_rows, value_input_option="RAW")

        print(f"[Sheets] Added {len(to_add)} articles.")

    except Exception as e:
        print(f"[Sheets] Save error: {e}")

# ══════════════════════════════════════════════════════════════
# GPT ANALYSIS PERSISTENCE — stored in a second sheet tab
# so it survives app restarts and redeploys
# ══════════════════════════════════════════════════════════════
GPT_TAB_NAME = "gpt_analysis"


def _get_gpt_sheet():
    """Get or create the gpt_analysis worksheet."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open(SHEET_NAME)
        try:
            return sh.worksheet(GPT_TAB_NAME)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=GPT_TAB_NAME, rows=10, cols=2)
            ws.append_row(["key", "value"])
            return ws
    except Exception as e:
        print(f"[GPT Sheet] Connection error: {e}")
        return None


def save_gpt_analysis(gpt_data: dict) -> None:
    """Persist GPT analysis dict to Google Sheets."""
    if not gpt_data:
        return
    try:
        import json
        ws = _get_gpt_sheet()
        if ws is None:
            return
        ws.clear()
        ws.append_row(["key", "value"])
        ws.append_row(["gpt_analysis", json.dumps(gpt_data)])
        ws.append_row(["saved_at", str(pd.Timestamp.now(tz="UTC"))])
        print("[GPT Sheet] GPT analysis saved.")
    except Exception as e:
        print(f"[GPT Sheet] Save error: {e}")


def load_gpt_analysis() -> dict | None:
    """Load GPT analysis from Google Sheets."""
    try:
        import json
        ws = _get_gpt_sheet()
        if ws is None:
            return None
        records = ws.get_all_records()
        for row in records:
            if row.get("key") == "gpt_analysis":
                return json.loads(row["value"])
        return None
    except Exception as e:
        print(f"[GPT Sheet] Load error: {e}")
        return None