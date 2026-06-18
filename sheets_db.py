"""
sheets_db.py — Google Sheets as persistent storage for the Macro Terminal.
Handles: news articles, GPT analysis, and per-user data.
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

SHEET_NAME = "MacroNewsData"
TAB_NAME   = "news"
COLUMNS    = ["id", "date", "source", "headline", "sentiment",
              "relevance", "topic", "escalate", "url"]


def _get_client():
    """Return an authorised gspread client.

    Looks for credentials in this order:
    1. GCP_SERVICE_ACCOUNT_JSON env variable (used on Render, where there
       is no st.secrets), expected to be a JSON string of the full
       service-account object.
    2. st.secrets["gcp_service_account"] (used on Streamlit Cloud).

    This lets the same file run unchanged on either platform.
    """
    env_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if env_json:
        creds_dict = json.loads(env_json)
    else:
        creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _open_or_create_tab(tab_name: str, headers: list) -> gspread.Worksheet:
    """Open a worksheet tab, creating it with headers if it doesn't exist."""
    gc = _get_client()
    sh = gc.open(SHEET_NAME)
    try:
        return sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=5000, cols=max(len(headers), 3))
        ws.append_row(headers)
        return ws


# ══════════════════════════════════════════════════════════════
# NEWS — read/write last 24h of headlines
# ══════════════════════════════════════════════════════════════

def get_sheet():
    try:
        return _open_or_create_tab(TAB_NAME, COLUMNS)
    except Exception as e:
        print(f"[Sheets] Connection error: {e}")
        return None


@st.cache_data(ttl=60)
def load_news_from_sheets() -> pd.DataFrame | None:
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
    if not new_results:
        return
    ws = get_sheet()
    if ws is None:
        return
    try:
        records = ws.get_all_records()
        existing_ids = {r["id"] for r in records if r.get("id")}
        to_add = [r for r in new_results if r.get("id") not in existing_ids]
        if not to_add:
            print("[Sheets] No new articles to add.")
            return

        rows = [[
            str(r.get("id", "")),
            str(r.get("date", "")),
            str(r.get("source", "")),
            str(r.get("headline", "")),
            float(r.get("sentiment", 0)),
            float(r.get("relevance", 0)),
            str(r.get("topic", "")),
            str(r.get("escalate", False)),
            str(r.get("url", "")),
        ] for r in to_add]
        ws.append_rows(rows, value_input_option="RAW")

        # Prune rows older than 24h
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

        if len(rows_to_keep) < len(all_records):
            ws.clear()
            ws.append_row(COLUMNS)
            keep_rows = [[str(r.get(c, "")) for c in COLUMNS] for r in rows_to_keep]
            ws.append_rows(keep_rows, value_input_option="RAW")

        print(f"[Sheets] Added {len(to_add)} articles.")
        load_news_from_sheets.clear()  # so new articles show up immediately, not after the 60s cache window
    except Exception as e:
        print(f"[Sheets] Save error: {e}")


# ══════════════════════════════════════════════════════════════
# GPT ANALYSIS — persists the latest macro analysis
# ══════════════════════════════════════════════════════════════
GPT_TAB_NAME = "gpt_analysis"
STATUS_TAB_NAME = "app_status"


def save_gpt_analysis(gpt_data: dict) -> None:
    """Persist GPT analysis dict to Google Sheets."""
    if not gpt_data:
        return
    try:
        ws = _open_or_create_tab(GPT_TAB_NAME, ["key", "value"])
        ws.clear()
        ws.append_row(["key", "value"])
        ws.append_row(["gpt_analysis", json.dumps(gpt_data)])
        ws.append_row(["saved_at", str(pd.Timestamp.now(tz="UTC"))])
        print("[GPT Sheet] Saved.")
        load_gpt_analysis.clear()
    except Exception as e:
        print(f"[GPT Sheet] Save error: {e}")


@st.cache_data(ttl=60)
def load_gpt_analysis() -> dict | None:
    """Load GPT analysis from Google Sheets."""
    try:
        ws = _open_or_create_tab(GPT_TAB_NAME, ["key", "value"])
        records = ws.get_all_records()
        for row in records:
            if row.get("key") == "gpt_analysis":
                return json.loads(row["value"])
        return None
    except Exception as e:
        print(f"[GPT Sheet] Load error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# APP STATUS — when the pipeline last actually ran, regardless of
# whether it found new articles. Kept in its own tab since
# save_gpt_analysis() clears its tab on every write.
# ══════════════════════════════════════════════════════════════

def save_last_checked() -> None:
    """Record the timestamp of the last time the pipeline actually ran."""
    try:
        ws = _open_or_create_tab(STATUS_TAB_NAME, ["key", "value"])
        records = ws.get_all_records()
        now_str = str(pd.Timestamp.now(tz="UTC"))
        for idx, row in enumerate(records, start=2):  # row 1 is header
            if row.get("key") == "last_checked":
                ws.update_cell(idx, 2, now_str)
                load_last_checked.clear()
                return
        ws.append_row(["last_checked", now_str])
        load_last_checked.clear()
    except Exception as e:
        print(f"[Status Sheet] Save error: {e}")


@st.cache_data(ttl=60)
def load_last_checked():
    """Load the timestamp of the last time the pipeline actually ran."""
    try:
        ws = _open_or_create_tab(STATUS_TAB_NAME, ["key", "value"])
        records = ws.get_all_records()
        for row in records:
            if row.get("key") == "last_checked":
                return pd.to_datetime(row["value"], utc=True, errors="coerce")
        return None
    except Exception as e:
        print(f"[Status Sheet] Load error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# USER DATA — per-user persistent storage (scores, trade ideas)
# ══════════════════════════════════════════════════════════════
USER_TAB_NAME = "user_data"


def _get_user_sheet():
    try:
        return _open_or_create_tab(USER_TAB_NAME, ["username", "key", "value"])
    except Exception as e:
        print(f"[User Sheet] Connection error: {e}")
        return None


def save_user_data(username: str, key: str, value) -> None:
    """Save a JSON-serialisable value for a user."""
    try:
        ws = _get_user_sheet()
        if ws is None:
            return
        records = ws.get_all_records()
        for idx, row in enumerate(records, start=2):  # row 1 is header
            if row.get("username") == username and row.get("key") == key:
                ws.update_cell(idx, 3, json.dumps(value))
                return
        ws.append_row([username, key, json.dumps(value)])
    except Exception as e:
        print(f"[User Sheet] Save error: {e}")


def load_user_data(username: str, key: str):
    """Load a value for a user. Returns None if not found."""
    try:
        ws = _get_user_sheet()
        if ws is None:
            return None
        records = ws.get_all_records()
        for row in records:
            if row.get("username") == username and row.get("key") == key:
                return json.loads(row["value"])
        return None
    except Exception as e:
        print(f"[User Sheet] Load error: {e}")
        return None


def load_all_user_data(username: str) -> dict:
    """Load all saved data for a user as a dict."""
    try:
        ws = _get_user_sheet()
        if ws is None:
            return {}
        records = ws.get_all_records()
        return {
            row["key"]: json.loads(row["value"])
            for row in records
            if row.get("username") == username and row.get("key") and row.get("value")
        }
    except Exception as e:
        print(f"[User Sheet] Load all error: {e}")
        return {}