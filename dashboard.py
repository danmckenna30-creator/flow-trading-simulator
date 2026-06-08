import json
import pandas as pd
import streamlit as st
from datetime import datetime
import os
from market_data import get_market_data
from news_reader import run_pipeline
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
from market_data import get_yield_curve
import pytz
from market_data import get_advance_decline_line, get_rsp_spy_ratio, compute_sp500_breadth, render_sp500_tab, get_spot_price
import yfinance as yf
import plotly.express as px
import math
import random
from story_mode import generate_story_mode

# ---------- CONFIG ----------
st.set_page_config(
    page_title="Macro News Terminal",
    layout="wide",
    initial_sidebar_state="collapsed"
)
st.markdown("""
<style>
[data-testid="stMetricValue"] {
    color: white !important;
}

[data-testid="stMetricLabel"] {
    color: white !important;
}

[data-testid="stMetricDelta"] {
    color: white !important;
}
</style>
""", unsafe_allow_html=True)


# ---------- DARK THEME / BLOOMBERG VIBE ----------
BLOOMBERG_CSS = """
<style>
body {
    background-color: #000000;
}
[data-testid="stAppViewContainer"] {
    background-color: #000000;
    color: #E5E5E5;
}
[data-testid="stHeader"] {
    background-color: #000000;
}
.block-container {
    padding-top: 1rem;
    padding-bottom: 1rem;
}
.big-number {
    font-size: 32px;
    font-weight: 700;
    color: #F5F5F5;
}
.label {
    font-size: 12px;
    text-transform: uppercase;
    color: #888888;
    letter-spacing: 1px;
}
.card {
    background-color: #111111;
    padding: 12px 16px;
    border-radius: 4px;
    border: 1px solid #333333;
}
.risk-on {
    color: #00FF41;
}
.risk-off {
    color: #FF4136;
}
.neutral {
    color: #FFDC00;
}
</style>
"""
st.markdown(BLOOMBERG_CSS, unsafe_allow_html=True)

# ---------- LOAD DATA ----------
def load_news():
    try:
        from sheets_db import load_news_from_sheets
        return load_news_from_sheets()
    except Exception:
        return None

def load_gpt():
    if "gpt_analysis" in st.session_state:
        return st.session_state["gpt_analysis"]
    try:
        with open("gpt_analysis.json", "r") as f:
            return json.load(f)
    except Exception:
        return None

# ---------- LOAD AI HYPE HISTORY ----------
def load_ai_hype_history():
    try:
        df = pd.read_csv("ai_hype_history.csv", names=["date", "count"])
        df["date"] = pd.to_datetime(df["date"])
        return df
    except:
        return pd.DataFrame(columns=["date", "count"])

ai_hype_df = load_ai_hype_history()
news_df = load_news()
gpt = load_gpt()

# ---------- HEADER ----------
st.markdown("<h2 style='color:#F5F5F5;'>MACRO NEWS TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<span class='label'>Mode: Bloomberg-style • Source: NewsAPI + FinBERT + GPT</span>", unsafe_allow_html=True)
st.markdown("---")


# ══════════════════════════════════════════════
# FLOW TRADING — CONSTANTS & HELPER FUNCTIONS (MOVED UP)
# ══════════════════════════════════════════════

FLOW_ASSETS = {
    "S&P 500 (SPY)":    {"ticker": "SPY",   "spread_bps": 0.5,  "hedge_ticker": "SPY"},
    "Gold (GC=F)":      {"ticker": "GC=F",  "spread_bps": 1.0,  "hedge_ticker": "GLD"},
    "Brent Crude (BZ=F)":{"ticker": "BZ=F", "spread_bps": 2.0,  "hedge_ticker": "USO"},
    "EUR/USD":          {"ticker": "EURUSD=X","spread_bps": 0.3, "hedge_ticker": "FXE"},
    "US 10Y (IEF)":     {"ticker": "IEF",   "spread_bps": 0.5,  "hedge_ticker": "IEF"},
}

HEDGE_THRESHOLD_USD = 500_000   # hedge when net inventory exceeds this


def init_flow_state():
    """Initialise Streamlit session state for the flow trading simulator."""
    defaults = {
        "inventory":   {},   # {asset_label: net_notional_usd}
        "flow_trades": [],   # list of trade dicts
        "pnl": {
            "spread_pnl":    0.0,
            "hedge_pnl":     0.0,
            "inventory_pnl": 0.0,
        },
        "hedge_trades": [],  # list of hedge dicts
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _get_spot(ticker: str) -> float | None:
    """Fetch latest price for a ticker via yfinance."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="2d")
        if hist is not None and len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def add_client_trade(asset_label: str, side: str, notional: float):
    """
    Record a client trade, update inventory, and book spread P&L.
    side: "Buy" (client buys, we sell) or "Sell" (client sells, we buy).
    """
    asset = FLOW_ASSETS[asset_label]
    spread_bps = asset["spread_bps"]

    # Spread P&L: we earn the spread on every client trade
    spread_earned = notional * (spread_bps / 10_000)
    st.session_state["pnl"]["spread_pnl"] += spread_earned

    # Inventory: client Buy → we are short (negative); client Sell → we are long (positive)
    direction = -1 if side == "Buy" else 1
    inv = st.session_state["inventory"]
    inv[asset_label] = inv.get(asset_label, 0.0) + direction * notional

    # Log the trade
    st.session_state["flow_trades"].append({
        "asset":       asset_label,
        "client_side": side,
        "notional":    notional,
        "spread_earned": round(spread_earned, 2),
    })


def compute_hedge_for_inventory() -> list:
    """
    For any position exceeding HEDGE_THRESHOLD_USD, execute a hedge trade
    and return a list of hedge descriptions.
    """
    hedges = []
    inv = st.session_state["inventory"]

    for asset_label, net_notional in list(inv.items()):
        if abs(net_notional) < HEDGE_THRESHOLD_USD:
            continue

        asset = FLOW_ASSETS[asset_label]
        hedge_ticker = asset["hedge_ticker"]
        spot = _get_spot(hedge_ticker) or 100.0   # fallback price

        # Hedge direction is opposite to our inventory
        hedge_side = "Sell" if net_notional > 0 else "Buy"
        hedge_notional = abs(net_notional)
        units = hedge_notional / spot

        # Mark inventory as hedged (zero it out)
        inv[asset_label] = 0.0

        hedge = {
            "asset":          asset_label,
            "hedge_ticker":   hedge_ticker,
            "hedge_side":     hedge_side,
            "hedge_notional": round(hedge_notional, 2),
            "units":          round(units, 4),
            "spot_price":     round(spot, 4),
        }
        st.session_state["hedge_trades"].append(hedge)
        hedges.append(hedge)

    return hedges


def mark_to_market_inventory() -> float:
    """
    MTM remaining (unhedged) inventory against current market prices.
    Returns the incremental P&L for this MTM step.
    """
    mtm_pnl = 0.0
    inv = st.session_state["inventory"]

    for asset_label, net_notional in inv.items():
        if net_notional == 0:
            continue
        asset = FLOW_ASSETS[asset_label]
        spot = _get_spot(asset["ticker"])
        if spot is None:
            continue
        # Simplified MTM: assume entry was at yesterday's close (1-tick move = 0.01%)
        pnl_estimate = net_notional * 0.0001
        mtm_pnl += pnl_estimate

    st.session_state["pnl"]["inventory_pnl"] += mtm_pnl
    return mtm_pnl

def render_flow_trading_tab():
    init_flow_state()

    st.header("Flow Trading Simulator")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("New Client Flow")

        asset_label = st.selectbox("Asset", list(FLOW_ASSETS.keys()))
        side = st.radio("Client side", ["Buy", "Sell"], horizontal=True)
        notional = st.number_input("Notional (USD)", min_value=100_000.0, value=1_000_000.0, step=100_000.0)

        if st.button("Add Client Trade"):
            add_client_trade(asset_label, side, notional)
            st.success("Client trade added to book.")

        if st.button("Hedge Inventory"):
            hedges = compute_hedge_for_inventory()
            if hedges:
                st.info("Hedges executed:")
                for h in hedges:
                    st.write(
                        f"{h['hedge_side']} {h['hedge_ticker']} for ~${h['hedge_notional']:,.0f} "
                        f"({h['units']:,.0f} units)"
                    )
            else:
                st.info("No inventory to hedge.")

        if st.button("Mark-to-Market Inventory"):
            mtm = mark_to_market_inventory()
            st.write(f"Inventory MTM P&L this step: ${mtm:,.0f}")

    with col2:
        st.subheader("Current Inventory")
        if st.session_state["inventory"]:
            inv_df = pd.DataFrame(
                [
                    {"Underlying": k, "Net Notional (USD)": v}
                    for k, v in st.session_state["inventory"].items()
                ]
            )
            st.dataframe(inv_df, use_container_width=True)
        else:
            st.write("No inventory yet.")

        st.subheader("P&L Breakdown")
        pnl = st.session_state["pnl"]
        pnl_df = pd.DataFrame(
            [
                {"Type": "Spread P&L", "Value": pnl["spread_pnl"]},
                {"Type": "Hedge P&L", "Value": pnl["hedge_pnl"]},
                {"Type": "Inventory P&L", "Value": pnl["inventory_pnl"]},
                {"Type": "Total P&L", "Value": pnl["spread_pnl"] + pnl["hedge_pnl"] + pnl["inventory_pnl"]},
            ]
        )
        st.dataframe(pnl_df, use_container_width=True)

        st.subheader("Client Flow Log")
        if st.session_state["flow_trades"]:
            flow_df = pd.DataFrame(st.session_state["flow_trades"])
            st.dataframe(flow_df, use_container_width=True)
        else:
            st.write("No client trades yet.")


# ---------- TABS INITIALIZATION ----------
tabs = st.tabs(["Macro", "Risk", "Commodities", "S&P500", "Flow Trading"])

# ---------- LOAD MARKET DATA ----------
prices = get_market_data()

# ---------- THEME EXTRACTION ----------
def extract_news_themes(news):
    themes = {
        "oil_supply": False,
        "oil_geopolitics": False,
        "oil_demand": False,
        "energy_prices": False,
        "china_growth": False,
        "manufacturing": False,
        "inflation": False,
        "weather": False,
        "grain_supply": False,
        "ai_hype": False
    }

    for item in news:
        h = item["headline"].lower()

        if any(k in h for k in ["opec", "production cut", "supply cut", "oil output"]):
            themes["oil_supply"] = True

        if any(k in h for k in ["middle east", "iran", "israel", "houthi", "red sea", "attack", "strike"]):
            themes["oil_geopolitics"] = True

        if any(k in h for k in ["demand", "travel", "consumption", "jet fuel"]):
            themes["oil_demand"] = True

        if "energy" in h:
            themes["energy_prices"] = True

        if any(k in h for k in ["china", "pmi", "manufacturing", "factory"]):
            themes["china_growth"] = True
            themes["manufacturing"] = True

        if any(k in h for k in ["inflation", "cpi", "ppi", "yields", "rates"]):
            themes["inflation"] = True

        if any(k in h for k in ["drought", "harvest", "crop", "weather", "heatwave"]):
            themes["weather"] = True

        if any(k in h for k in ["grain", "wheat", "corn", "export ban", "ukraine"]):
            themes["grain_supply"] = True

        if any(k in h for k in ["ai", "artificial intelligence", "chip", "semiconductor", "gpu", "nvidia", "openai"]):
            themes["ai_hype"] = True

    return themes

# ---------- COMMODITY THEMES ----------
def extract_commodity_themes(news):
    themes = {
        "oil_supply": False,
        "oil_geopolitics": False,
        "oil_demand": False,
        "energy": False,
        "china": False,
        "inflation": False,
        "weather": False,
        "ag_supply": False,
        "sentiment": 0
    }

    total_sent = 0
    count = 0

    for item in news:
        h = item["headline"].lower()
        topic = item.get("topic", "").lower()
        sent = item.get("sentiment", 0)

        total_sent += sent
        count += 1

        if any(k in h for k in ["opec", "production cut", "supply cut", "oil output"]):
            themes["oil_supply"] = True

        if any(k in h for k in ["middle east", "iran", "israel", "houthi", "red sea", "attack"]):
            themes["oil_geopolitics"] = True

        if any(k in h for k in ["demand", "travel", "consumption", "jet fuel"]):
            themes["oil_demand"] = True

        if topic == "energy":
            themes["energy"] = True

        if any(k in h for k in ["china", "pmi", "manufacturing", "factory"]):
            themes["china"] = True

        if any(k in h for k in ["inflation", "cpi", "ppi", "yields", "rates"]):
            themes["inflation"] = True

        if any(k in h for k in ["drought", "weather", "heatwave"]):
            themes["weather"] = True

        if any(k in h for k in ["grain", "wheat", "corn", "export ban", "ukraine"]):
            themes["ag_supply"] = True

    themes["sentiment"] = total_sent / count if count > 0 else 0
    return themes


# =========================================================
# ====================== MACRO TAB ========================
# =========================================================

with tabs[0]:
    # Auto-refresh trigger every 60 mins
    st_autorefresh(interval=60 * 60 * 1000, key="macro_refresh")

    # Only run pipeline if data is stale or missing
    last_run = st.session_state.get("last_pipeline_run")
    now = datetime.now(pytz.UTC)
    should_run = (
        last_run is None or
        (now - last_run).total_seconds() > 3300  # 55 minutes
    )

    if should_run:
        with st.spinner("Fetching latest news and sentiment..."):
            try:
                run_pipeline()
                st.session_state["last_pipeline_run"] = now
            except Exception as e:
                st.warning(f"Pipeline error: {e}")

    news_df = load_news()
    gpt = load_gpt()
    ai_hype_df = load_ai_hype_history()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Last Update</div>", unsafe_allow_html=True)

        try:
            last_run = st.session_state.get("last_pipeline_run")
            if last_run:
                uk_dt = last_run.astimezone(pytz.timezone("Europe/London"))
                ts = uk_dt.strftime("%Y-%m-%d %H:%M")
            elif news_df is not None and "date" in news_df.columns:
                latest = pd.to_datetime(news_df["date"], utc=True, errors="coerce").max()
                if pd.notna(latest):
                    ts = latest.astimezone(pytz.timezone("Europe/London")).strftime("%Y-%m-%d %H:%M")
                else:
                    ts = "No data"
            else:
                ts = "No data"
        except Exception:
            ts = "No data"

        st.markdown(f"<div class='big-number'>{ts}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Articles (latest batch)</div>", unsafe_allow_html=True)
        count = len(news_df) if news_df is not None else 0
        st.markdown(f"<div class='big-number'>{count}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col3:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Average Sentiment</div>", unsafe_allow_html=True)

        if news_df is not None and "sentiment" in news_df.columns and len(news_df) > 0:
            avg_sent = news_df["sentiment"].mean()
            avg_str = f"{avg_sent:+.2f}"
        else:
            avg_str = "N/A"

        st.markdown(f"<div class='big-number'>{avg_str}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col4:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Risk Regime</div>", unsafe_allow_html=True)

        if gpt and "market_impact" in gpt:
            regime = gpt["market_impact"]
            cls = "neutral"
            if regime == "risk-on":
                cls = "risk-on"
            elif regime == "risk-off":
                cls = "risk-off"
            st.markdown(f"<div class='big-number {cls}'>{regime.upper()}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='big-number neutral'>N/A</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("")

    st.markdown("### Macro Analyst View")
    left, right = st.columns(2)

    with left:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        if gpt:
            theme = gpt.get("macro_theme", "N/A")
            summary = gpt.get("summary", "No summary available.")
            st.markdown("<div class='label'>Macro Theme</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number'>{theme}</div>", unsafe_allow_html=True)
            st.markdown("<div class='label' style='margin-top:8px;'>Summary</div>", unsafe_allow_html=True)
            st.markdown(f"<p style='color:#DDDDDD;'>{summary}</p>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='color:#AAAAAA;'>No GPT analysis available yet.</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        if gpt:
            conf = gpt.get("confidence", None)
            kp = gpt.get("key_points", [])
            st.markdown("<div class='label'>Confidence</div>", unsafe_allow_html=True)
            if conf is not None:
                st.markdown(f"<div class='big-number'>{conf}/100</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)
            st.markdown("<div class='label' style='margin-top:8px;'>Key Points</div>", unsafe_allow_html=True)
            if isinstance(kp, list) and kp:
                for point in kp:
                    st.markdown(f"- {point}")
            else:
                st.markdown("<p style='color:#AAAAAA;'>No key points available.</p>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='color:#AAAAAA;'>No GPT analysis available yet.</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    bottom_left, bottom_right = st.columns(2)

    with bottom_left:
        st.markdown("### Latest Headlines")
        if news_df is not None and len(news_df) > 0:
            show_cols = ["date", "source", "headline", "sentiment", "topic", "relevance"]
            existing = [c for c in show_cols if c in news_df.columns]
            table = news_df.sort_values("date", ascending=False)[existing].head(25)
            st.dataframe(table, use_container_width=True, hide_index=True)
        else:
            st.markdown("<p style='color:#AAAAAA;'>No news data available yet.</p>", unsafe_allow_html=True)

    with bottom_right:
        st.markdown("### Sentiment Over Time")
        if news_df is not None and "date" in news_df.columns and "sentiment" in news_df.columns:
            chart_df = news_df.sort_values("date").set_index("date")[["sentiment"]]
            st.line_chart(chart_df, height=260)
        else:
            st.markdown("<p style='color:#AAAAAA;'>Not enough data to plot sentiment.</p>", unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("### Morning Macro Brief")
    if "story_text" not in st.session_state:
        try:
            st.session_state["story_text"] = generate_story_mode(
                news_df=news_df,
                gpt_analysis=st.session_state.get("gpt_analysis")
            )
        except Exception as e:
            st.session_state["story_text"] = f"Story mode error: {e}"

    story_text = st.session_state.get("story_text", "No story mode brief generated yet.")
    st.markdown(story_text)

    if st.button("🔄 Regenerate Morning Brief"):
        try:
            st.session_state["story_text"] = generate_story_mode(
                news_df=news_df,
                gpt_analysis=st.session_state.get("gpt_analysis")
            )
            st.rerun()
        except Exception as e:
            st.error(f"Story mode error: {e}")

    st.markdown("### Market Snapshot")
    cols = st.columns(5)

    for i, (name, item) in enumerate(prices.items()):
        with cols[i % 5]:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{name}</div>", unsafe_allow_html=True)

            if item and item["price"] is not None:
                price = item["price"]
                change = item["change"]

                if "Yield" in name or change is None:
                    change_str = ""
                    color = "#ffffff"
                else:
                    if change > 0:
                        change_str = f"▲ {change}%"
                        color = "#00ff88"
                    elif change < 0:
                        change_str = f"▼ {abs(change)}%"
                        color = "#ff4d4d"
                    else:
                        change_str = "0.00%"
                        color = "#ffffff"

                st.markdown(f"<div class='big-number'>{price}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:16px; font-weight:bold; color:{color};'>{change_str}</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)
                st.markdown("<div style='font-size:16px;'>N/A</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### Yield Curve")
    curve = get_yield_curve()
    maturities = ["2Y", "5Y", "10Y", "30Y"]
    yields = [curve[m] for m in maturities]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=maturities, y=yields, mode="lines+markers",
            line=dict(color="#00c3ff", width=3),
            marker=dict(size=10, color="#ffffff", line=dict(width=2, color="#00c3ff")),
        )
    )
    fig.update_layout(
        template="plotly_dark", height=350, margin=dict(l=40, r=40, t=40, b=40),
        xaxis_title="Maturity", yaxis_title="Yield (%)",
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#333333"),
    )
    st.plotly_chart(fig, use_container_width=True)

    slope_2s10s = curve["10Y"] - curve["2Y"]
    slope_5s30s = curve["30Y"] - curve["5Y"]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>2s10s Spread</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number'>{slope_2s10s:.2f} bps</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>5s30s Spread</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number'>{slope_5s30s:.2f} bps</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    if slope_2s10s < 0:
        st.markdown("<p style='color:#ff4d4d; font-weight:bold; font-size:18px;'>⚠️ Yield curve inverted (10-year Treasury yield < 2-year Treasury yield)</p>", unsafe_allow_html=True)


# =========================================================
# ======================= RISK TAB ========================
# =========================================================

with tabs[1]:
    st.markdown("## Risk Monitor")
    st.markdown("---")

    # ── Live data ───────────────────────────────────────────────
    vix_price     = (prices.get("VIX",        {}) or {}).get("price") or 20
    spx_change    = (prices.get("S&P 500",     {}) or {}).get("change") or 0
    usdjpy_change = (prices.get("USDJPY",      {}) or {}).get("change") or 0
    oil_change    = (prices.get("Brent Crude", {}) or {}).get("change") or 0
    copper_change = (prices.get("Copper",      {}) or {}).get("change") or 0
    gold_change   = (prices.get("Gold",        {}) or {}).get("change") or 0
    avg_sentiment = news_df["sentiment"].mean() if news_df is not None and "sentiment" in news_df.columns else 0

    risk_score = (
        spx_change    * 0.30 +
        copper_change * 0.20 +
        oil_change    * 0.15 +
        usdjpy_change * 0.15 +
        avg_sentiment * 20  * 0.10 +
        (-1 if vix_price > 25 else 1 if vix_price < 15 else 0) * 0.10
    )

    if   risk_score >  0.3: risk_label, risk_cls, risk_emoji = "RISK-ON",  "risk-on",  "🟢"
    elif risk_score < -0.3: risk_label, risk_cls, risk_emoji = "RISK-OFF", "risk-off", "🔴"
    else:                   risk_label, risk_cls, risk_emoji = "NEUTRAL",  "neutral",  "🟡"

    if   vix_price < 15:  vol_regime, vol_color = "LOW VOL",    "#00ff88"
    elif vix_price <= 25: vol_regime, vol_color = "NORMAL VOL", "#FFDC00"
    else:                 vol_regime, vol_color = "HIGH VOL",   "#ff4d4d"

    # ════════════════════════════════════════════════════════════
    # SECTION 1 — MARKET RISK REGIME
    # ════════════════════════════════════════════════════════════
    st.markdown("### 📊 Section 1 — Market Risk Regime")
    st.caption("A real-time snapshot of where markets sit on the risk spectrum. As a flow trader, this is your morning orientation — it tells you the likely direction of client flows before the phone even rings.")

    # Score cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Risk Regime</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number {risk_cls}'>{risk_emoji} {risk_label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='label'>Score: {risk_score:+.2f}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>VIX — Fear Index</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number'>{vix_price:.1f}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='color:{vol_color}; font-weight:bold;'>{vol_regime}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c3:
        sc = "#00ff88" if spx_change > 0 else "#ff4d4d" if spx_change < 0 else "#fff"
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>S&P 500 % Change</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number' style='color:{sc};'>{spx_change:+.2f}%</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c4:
        sc2 = "#00ff88" if avg_sentiment > 0.1 else "#ff4d4d" if avg_sentiment < -0.1 else "#FFDC00"
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>News Sentiment</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number' style='color:{sc2};'>{avg_sentiment:+.2f}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.caption("**Risk Score** blends equity, copper, oil, FX and news sentiment. Above +0.3 = risk-on. Below -0.3 = risk-off. **VIX** below 15 = calm, above 25 = fear. Neutral means markets are waiting for a catalyst.")
    st.markdown("")

    # Regime Gauge
    col_gauge, col_fx = st.columns([1, 1])
    with col_gauge:
        st.markdown("#### Regime Gauge")
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=risk_score,
            delta={"reference": 0},
            gauge={
                "axis": {"range": [-2, 2], "tickcolor": "#888"},
                "bar":  {"color": "#00c3ff"},
                "steps": [
                    {"range": [-2,   -0.3], "color": "#ff4d4d"},
                    {"range": [-0.3,  0.3], "color": "#333333"},
                    {"range": [0.3,   2.0], "color": "#00ff88"},
                ],
                "threshold": {"line": {"color": "white", "width": 3}, "value": risk_score}
            },
            title={"text": "Risk Score", "font": {"color": "#ccc"}}
        ))
        fig_gauge.update_layout(
            template="plotly_dark", height=260,
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor="rgba(0,0,0,0)", font={"color": "#ccc"}
        )
        st.plotly_chart(fig_gauge, use_container_width=True)
        st.caption("Red = risk-off, Green = risk-on. The needle moves with live market data. In risk-on, expect clients to buy equities and commodities. In risk-off, expect flows into gold, bonds, and USD.")

    with col_fx:
        st.markdown("#### FX Risk Pairs")
        st.markdown("")
        for pair in ["USDJPY", "GBPUSD", "EURUSD"]:
            item   = (prices.get(pair, {}) or {})
            price  = item.get("price")
            change = item.get("change") or 0
            color  = "#00ff88" if change > 0 else "#ff4d4d" if change < 0 else "#fff"
            arrow  = "▲" if change > 0 else "▼" if change < 0 else "–"
            st.markdown(
                f"<div class='card' style='margin-bottom:8px; display:flex; justify-content:space-between;'>"
                f"<span class='label' style='font-size:14px;'>{pair}</span>"
                f"<span style='font-size:18px; font-weight:bold;'>{price if price else 'N/A'}</span>"
                f"<span style='color:{color}; font-weight:bold;'>{arrow} {abs(change)}%</span>"
                f"</div>",
                unsafe_allow_html=True
            )
        st.markdown("")
        st.caption("USD/JPY rising = risk-on. GBP and EUR rising vs USD = dollar weakening, positive for global risk appetite. Large moves signal institutional positioning shifts.")

    st.markdown("---")

    # Cross-asset heatmap
    st.markdown("#### Cross-Asset Heatmap")
    heatmap_assets  = ["VIX", "S&P 500", "USDJPY", "Brent Crude", "Copper", "Gold", "FTSE 100"]
    heatmap_changes = [(prices.get(a, {}) or {}).get("change") or 0 for a in heatmap_assets]
    fig_heat = go.Figure(go.Heatmap(
        z=[heatmap_changes], x=heatmap_assets, y=["% Change"],
        colorscale=[[0.0,"#ff4d4d"],[0.5,"#111111"],[1.0,"#00ff88"]],
        zmid=0,
        text=[[f"{v:+.2f}%" for v in heatmap_changes]],
        texttemplate="%{text}", showscale=True
    ))
    fig_heat.update_layout(template="plotly_dark", height=150, margin=dict(l=40,r=40,t=10,b=40))
    st.plotly_chart(fig_heat, use_container_width=True)
    st.caption("A snapshot of every major asset class today. Red = falling, Green = rising. Look for confirmation signals — if equities, copper AND oil are all green, that's a strong risk-on day. If VIX is red and everything else green, markets are calm and bullish.")
    st.markdown("---")

    # ════════════════════════════════════════════════════════════
    # SECTION 2 — DEEP RISK INTELLIGENCE
    # ════════════════════════════════════════════════════════════
    st.markdown("### 🧠 Section 2 — Deep Risk Intelligence")
    st.caption("This section uses live market data and AI to monitor three specific structural risks in today's market. These are the kind of risks a senior trader or risk manager would flag in a morning meeting — longer-term themes that don't show up in daily price moves but can cause sudden dislocations.")
    st.markdown("")

    # Pull data for deep risk analysis
    mega_caps = {
        "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA",
        "GOOGL": "Alphabet", "META": "Meta", "AMZN": "Amazon", "TSLA": "Tesla"
    }

    @st.cache_data(ttl=1800)
    def get_mega_cap_data():
        import yfinance as yf
        results = {}
        try:
            spx = yf.Ticker("^GSPC").history(period="5d")
            results["spx_5d"] = float(((spx["Close"].iloc[-1] / spx["Close"].iloc[0]) - 1) * 100) if len(spx) >= 2 else 0
        except Exception:
            results["spx_5d"] = 0

        changes = {}
        for ticker, name in mega_caps.items():
            try:
                hist = yf.Ticker(ticker).history(period="5d")
                if len(hist) >= 2:
                    changes[name] = float(((hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1) * 100)
            except Exception:
                changes[name] = 0
        results["mega_changes"] = changes
        return results

    mega_data = get_mega_cap_data()
    mega_changes = mega_data.get("mega_changes", {})
    spx_5d = mega_data.get("spx_5d", 0)

    # Concentration score: how much are mega caps outperforming broader market?
    if mega_changes:
        avg_mega = sum(mega_changes.values()) / len(mega_changes)
        concentration_gap = avg_mega - spx_5d
    else:
        avg_mega = 0
        concentration_gap = 0

    if concentration_gap > 2:   conc_level, conc_color = "HIGH",   "#ff4d4d"
    elif concentration_gap > 0: conc_level, conc_color = "MEDIUM", "#FFDC00"
    else:                       conc_level, conc_color = "LOW",    "#00ff88"

    # AI bubble score from headlines
    ai_headlines = []
    ai_sentiment_scores = []
    if news_df is not None and "headline" in news_df.columns:
        ai_keywords = ["ai", "artificial intelligence", "nvidia", "chip", "semiconductor", "openai", "llm", "gpu"]
        for _, row in news_df.iterrows():
            if any(k in str(row.get("headline","")).lower() for k in ai_keywords):
                ai_headlines.append(row.get("headline",""))
                try:
                    ai_sentiment_scores.append(float(row.get("sentiment", 0)))
                except Exception:
                    pass

    ai_sentiment_avg = sum(ai_sentiment_scores) / len(ai_sentiment_scores) if ai_sentiment_scores else 0
    ai_count = len(ai_headlines)

    if ai_count >= 3 and ai_sentiment_avg > 0.3:   ai_level, ai_color = "HIGH — Euphoric", "#ff4d4d"
    elif ai_count >= 2 or ai_sentiment_avg > 0.1:  ai_level, ai_color = "MEDIUM — Active", "#FFDC00"
    else:                                           ai_level, ai_color = "LOW — Cooling",  "#00ff88"

    # IPO / issuance risk from headlines
    ipo_headlines = []
    ipo_keywords = ["ipo", "listing", "public offering", "spac", "debut", "fundraise", "raise capital", "issuance"]
    if news_df is not None and "headline" in news_df.columns:
        for _, row in news_df.iterrows():
            if any(k in str(row.get("headline","")).lower() for k in ipo_keywords):
                ipo_headlines.append(row.get("headline",""))

    ipo_count = len(ipo_headlines)
    if ipo_count >= 3:   ipo_level, ipo_color = "HIGH",   "#ff4d4d"
    elif ipo_count >= 1: ipo_level, ipo_color = "MEDIUM", "#FFDC00"
    else:                ipo_level, ipo_color = "LOW",     "#00ff88"

    # ── RISK 1: S&P Concentration ───────────────────────────────
    st.markdown("#### 🏦 Risk 1 — S&P 500 Concentration")

    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Concentration Risk</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number' style='color:{conc_color};'>{conc_level}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with r1c2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Mega-Cap Avg (5d)</div>", unsafe_allow_html=True)
        c = "#00ff88" if avg_mega > 0 else "#ff4d4d"
        st.markdown(f"<div class='big-number' style='color:{c};'>{avg_mega:+.2f}%</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with r1c3:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>vs S&P 500 (5d)</div>", unsafe_allow_html=True)
        c = "#00ff88" if spx_5d > 0 else "#ff4d4d"
        st.markdown(f"<div class='big-number' style='color:{c};'>{spx_5d:+.2f}%</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.caption(f"The top 7 mega-cap stocks are {'outperforming' if concentration_gap > 0 else 'underperforming'} the broader S&P 500 by **{abs(concentration_gap):.1f}%** over the last 5 days. When a small number of stocks drive most of the index return, the market is fragile — if just one or two stumble, the whole index can fall sharply even if most stocks are fine.")

    if mega_changes:
        sorted_mega = sorted(mega_changes.items(), key=lambda x: x[1], reverse=True)
        names  = [x[0] for x in sorted_mega]
        values = [x[1] for x in sorted_mega]
        colors = ["#00ff88" if v >= spx_5d else "#ff4d4d" for v in values]

        fig_conc = go.Figure()
        fig_conc.add_trace(go.Bar(
            x=names, y=values, marker_color=colors,
            text=[f"{v:+.1f}%" for v in values], textposition="outside",
            name="Mega-caps"
        ))
        fig_conc.add_hline(
            y=spx_5d, line_dash="dash", line_color="#FFDC00",
            annotation_text=f"S&P 500: {spx_5d:+.1f}%",
            annotation_position="right"
        )
        fig_conc.update_layout(
            template="plotly_dark", height=300,
            title="Mega-Cap 5-Day Returns vs S&P 500",
            yaxis_title="5-Day Return %",
            margin=dict(l=40, r=80, t=40, b=40),
            yaxis=dict(gridcolor="#333"), xaxis=dict(showgrid=False),
            showlegend=False
        )
        st.plotly_chart(fig_conc, use_container_width=True)
        st.caption("Yellow dashed line = S&P 500 return. Green bars = stocks outperforming the index (pulling it up). Red bars = underperforming (a drag on the index). If most bars are green but the S&P is barely moving, it means smaller stocks are falling and hiding the weakness.")
    st.markdown("---")

    # ── RISK 2: AI Bubble Monitor ───────────────────────────────
    st.markdown("#### 🤖 Risk 2 — AI Bubble Monitor")

    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>AI Hype Level</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number' style='color:{ai_color};'>{ai_level}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with r2c2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>AI Headlines Today</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number'>{ai_count}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with r2c3:
        sc3 = "#00ff88" if ai_sentiment_avg > 0.1 else "#ff4d4d" if ai_sentiment_avg < -0.1 else "#FFDC00"
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>AI Sentiment Score</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number' style='color:{sc3};'>{ai_sentiment_avg:+.2f}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.caption("AI stocks like NVIDIA have seen enormous gains driven by enthusiasm rather than earnings alone. When AI headlines are frequent and sentiment is very positive, it often signals the hype is peaking — which historically precedes sharp corrections. A bubble doesn't mean prices fall immediately, but it means the risk of a sudden reversal is elevated.")

    if ai_headlines:
        st.markdown("**AI-related headlines detected today:**")
        for h in ai_headlines[:5]:
            st.markdown(f"- {h}")

        # Mini sentiment bar chart
        if len(ai_sentiment_scores) > 1:
            fig_ai = go.Figure(go.Bar(
                x=[f"Headline {i+1}" for i in range(len(ai_sentiment_scores))],
                y=ai_sentiment_scores,
                marker_color=["#00ff88" if s > 0 else "#ff4d4d" for s in ai_sentiment_scores],
                text=[f"{s:+.2f}" for s in ai_sentiment_scores],
                textposition="outside"
            ))
            fig_ai.update_layout(
                template="plotly_dark", height=250,
                title="AI Headline Sentiment Scores",
                yaxis=dict(range=[-1, 1], gridcolor="#333"),
                xaxis=dict(showgrid=False),
                margin=dict(l=40, r=40, t=40, b=40)
            )
            st.plotly_chart(fig_ai, use_container_width=True)
            st.caption("Each bar is one AI-related headline from today's news. Green = positive sentiment, Red = negative. Consistently green bars with high scores suggest euphoria. Mixed or negative bars suggest the narrative is shifting — a potential early warning signal.")
    else:
        st.info("No AI-related headlines in today's feed. This could mean the hype is cooling or the news cycle has moved on — both worth noting.")
    st.markdown("---")

    # ── RISK 3: IPO / Capital Flow Risk ─────────────────────────
    st.markdown("#### 📋 Risk 3 — IPO & Capital Flow Risk")

    r3c1, r3c2, r3c3 = st.columns(3)
    with r3c1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>IPO Activity</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number' style='color:{ipo_color};'>{ipo_level}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with r3c2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>IPO Headlines Today</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number'>{ipo_count}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with r3c3:
        # Use Russell 2000 proxy (IWM) as small-cap barometer
        iwm = (prices.get("IWM", {}) or {}).get("change") or 0
        iwm_color = "#00ff88" if iwm > 0 else "#ff4d4d"
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Small-Cap Breadth</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number' style='color:{iwm_color};'>{spx_change:+.2f}% SPX</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.caption("When many companies list at once (IPOs, SPACs), they pull money out of existing stocks as investors sell holdings to fund new purchases. High IPO activity alongside a falling broader market is a classic warning sign — it drains liquidity from existing positions and can cause normally-stable stocks to underperform.")

    if ipo_headlines:
        st.markdown("**IPO/issuance headlines detected today:**")
        for h in ipo_headlines[:5]:
            st.markdown(f"- {h}")

        # Visual: IPO count vs market direction
        fig_ipo = go.Figure()
        fig_ipo.add_trace(go.Bar(
            x=["IPO Headlines", "S&P 500 Change", "Copper Change"],
            y=[ipo_count, spx_change, copper_change],
            marker_color=["#FFDC00",
                          "#00ff88" if spx_change > 0 else "#ff4d4d",
                          "#00ff88" if copper_change > 0 else "#ff4d4d"],
            text=[str(ipo_count), f"{spx_change:+.2f}%", f"{copper_change:+.2f}%"],
            textposition="outside"
        ))
        fig_ipo.update_layout(
            template="plotly_dark", height=280,
            title="IPO Activity vs Market Indicators",
            margin=dict(l=40, r=40, t=40, b=40),
            yaxis=dict(gridcolor="#333"), xaxis=dict(showgrid=False)
        )
        st.plotly_chart(fig_ipo, use_container_width=True)
        st.caption("Yellow = number of IPO-related headlines (scale is count, not %). If IPO activity is high while S&P and Copper are red, capital is moving into new listings and away from existing markets — a liquidity drain signal.")
    else:
        st.info("No IPO or capital issuance headlines detected today. Low issuance is generally supportive for existing stocks — less competition for investor capital.")
    st.markdown("---")

    # ── GPT RISK NARRATIVE ──────────────────────────────────────
    st.markdown("#### 🤖 AI Risk Narrative")
    st.caption("Claude synthesises the three risk themes above with today's live market data into a single trader-ready paragraph, updated every time new headlines arrive.")

    if st.button("🔄 Generate Risk Narrative", key="risk_narrative_btn"):
        with st.spinner("Analysing risk themes..."):
            try:
                from gpt_layer import call_gpt
                risk_prompt = f"""
You are a senior risk manager at a major investment bank writing a morning risk briefing.

LIVE MARKET DATA:
- Risk Regime: {risk_label} (score: {risk_score:+.2f})
- VIX: {vix_price:.1f} ({vol_regime})
- S&P 500: {spx_change:+.2f}% today
- Copper: {copper_change:+.2f}% (global growth proxy)
- Gold: {gold_change:+.2f}% (safe haven)
- News Sentiment: {avg_sentiment:+.2f}

CONCENTRATION RISK:
- Top 7 mega-caps averaged {avg_mega:+.2f}% over 5 days vs S&P 500 at {spx_5d:+.2f}%
- Concentration gap: {concentration_gap:+.2f}% — rated {conc_level}

AI BUBBLE MONITOR:
- {ai_count} AI-related headlines today
- AI headline sentiment: {ai_sentiment_avg:+.2f}
- Level: {ai_level}
- Headlines: {"; ".join(ai_headlines[:3]) if ai_headlines else "None"}

IPO & CAPITAL FLOW:
- {ipo_count} IPO/issuance headlines today — rated {ipo_level}
- Headlines: {"; ".join(ipo_headlines[:3]) if ipo_headlines else "None"}

Write a concise 3-4 sentence risk narrative that:
1. States the overall risk regime and what it means for flow traders today
2. Highlights the most important of the three structural risks and why it matters
3. Gives one actionable observation for a flow trader (e.g. watch for rotation, hedge concentration, etc.)

Be direct, professional, and Bloomberg-style. No bullet points. Plain prose only.
"""
                narrative = call_gpt([risk_prompt])
                if isinstance(narrative, dict):
                    narrative = narrative.get("summary", str(narrative))
                if narrative:
                    st.session_state["risk_narrative"] = narrative
                else:
                    st.session_state["risk_narrative"] = "Could not generate narrative — check OpenAI key."
            except Exception as e:
                st.session_state["risk_narrative"] = f"Error: {e}"

    narrative = st.session_state.get("risk_narrative", "Click 'Generate Risk Narrative' above to get an AI-powered summary of today's key risks.")
    st.markdown(
        f"<div class='card' style='line-height:1.7; color:#DDDDDD;'>{narrative}</div>",
        unsafe_allow_html=True
    )

    st.markdown("---")

    # ── FLOW TRADING RISK (condensed) ───────────────────────────
    st.markdown("### 🏦 Section 3 — Your Flow Trading Risk")
    st.caption("Live view of your simulated trading book from the Flow Trading tab. Go there to add client trades — your inventory and P&L will update here.")

    inv = st.session_state.get("inventory", {})
    pnl = st.session_state.get("pnl", {"spread_pnl": 0, "hedge_pnl": 0, "inventory_pnl": 0})
    total_pnl = sum(pnl.values())

    p1, p2, p3, p4 = st.columns(4)
    for col, label, key, tip in [
        (p1, "Spread P&L",    "spread_pnl",    "Earned from bid/offer"),
        (p2, "Hedge P&L",     "hedge_pnl",     "From hedges placed"),
        (p3, "Inventory P&L", "inventory_pnl", "Mark-to-market"),
        (p4, "Total P&L",     None,            "Overall book P&L"),
    ]:
        val = total_pnl if key is None else pnl.get(key, 0)
        cc  = "#00ff88" if val >= 0 else "#ff4d4d"
        with col:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{label}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number' style='color:{cc};'>${val:,.0f}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='label' style='font-size:10px;'>{tip}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    if inv and any(v != 0 for v in inv.values()):
        assets  = list(inv.keys())
        values  = [inv[a] for a in assets]
        colours = ["#00ff88" if v > 0 else "#ff4d4d" for v in values]
        fig_inv = go.Figure(go.Bar(
            x=assets, y=values, marker_color=colours,
            text=[f"${abs(v):,.0f}" for v in values], textposition="outside"
        ))
        fig_inv.update_layout(
            template="plotly_dark", height=280,
            title="Net Inventory (USD)",
            margin=dict(l=40, r=40, t=40, b=40),
            yaxis=dict(gridcolor="#333"), xaxis=dict(showgrid=False)
        )
        st.plotly_chart(fig_inv, use_container_width=True)

        needs_hedge = {a: v for a, v in inv.items() if abs(v) >= 500_000}
        if needs_hedge:
            for asset, notional in needs_hedge.items():
                direction = "LONG" if notional > 0 else "SHORT"
                st.warning(f"⚠️ **{asset}** — {direction} ${abs(notional):,.0f}. Hedge signal active.")
        else:
            st.success("✅ All positions within risk limits.")
    else:
        st.info("No open positions. Head to the Flow Trading tab to simulate client trades.")


with tabs[2]:
    st.markdown("### Commodities")
    commodity_names = ["Brent Crude", "WTI Crude", "Natural Gas", "Gold", "Silver", "Copper", "Corn", "Wheat"]
    cols = st.columns(4)

    for i, name in enumerate(commodity_names):
        with cols[i % 4]:
            item = prices.get(name, None)
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{name}</div>", unsafe_allow_html=True)

            if item and item["price"] is not None:
                price = item["price"]
                change = item["change"]

                if change is None:
                    change_str = "N/A"
                    color = "#ffffff"
                elif change > 0:
                    change_str = f"▲ {change}%"
                    color = "#00ff88"
                elif change < 0:
                    change_str = f"▼ {abs(change)}%"
                    color = "#ff4d4d"
                else:
                    change_str = "0.00%"
                    color = "#ffffff"

                st.markdown(f"<div class='big-number'>{price}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:16px; font-weight:bold; color:{color};'>{change_str}</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)
                st.markdown("<div style='font-size:16px;'>N/A</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### Commodity Commentary")
    try:
        news_list = news_df.to_dict(orient="records") if news_df is not None else []
    except:
        news_list = []

    themes = extract_commodity_themes(news_list)
    sent = themes["sentiment"]
    commentary = []

    oil = prices["Brent Crude"]["change"]
    if oil is not None:
        if oil > 1:
            if themes["oil_supply"]:
                commentary.append("Oil is climbing as supply-side headlines — including OPEC+ discipline and production constraints — support prices.")
            elif themes["oil_geopolitics"]:
                commentary.append("Oil is higher as geopolitical tensions in key producing regions add a risk premium.")
            elif themes["oil_demand"]:
                commentary.append("Oil is gaining on stronger demand expectations reflected in travel and consumption-related headlines.")
            else:
                commentary.append("Oil is moving higher despite limited headline catalysts, suggesting technical or positioning-driven flows.")
        elif oil < -1:
            if themes["oil_supply"]:
                commentary.append("Oil is falling even as supply headlines remain tight, indicating demand concerns are dominating.")
            elif themes["oil_demand"]:
                commentary.append("Oil is under pressure as headlines point to softer demand expectations.")
            else:
                commentary.append("Oil is weakening with little headline support, likely reflecting easing supply constraints or a broader macro risk-off tone.")
        else:
            commentary.append("Oil is relatively stable, with no dominant supply or demand headlines driving direction.")

    copper = prices["Copper"]["change"]
    if copper is not None:
        if themes["china"]:
            commentary.append("Copper is reacting to China-related headlines, with industrial activity remaining a key demand driver.")
        elif copper > 1:
            commentary.append("Copper is firm, potentially reflecting improved global manufacturing sentiment.")
        elif copper < -1:
            commentary.append("Copper is softer, hinting at weaker industrial demand or cautious macro sentiment.")

    gold = prices["Gold"]["change"]
    if gold is not None:
        if themes["inflation"]:
            commentary.append("Gold is responding to inflation and rate-related headlines, which continue to shape safe-haven demand.")
        elif gold > 1:
            commentary.append("Gold is gaining as investors seek safety amid broader macro uncertainty.")
        elif gold < -1:
            commentary.append("Gold is easing, suggesting reduced safe-haven demand or firmer yields.")

    if themes["weather"]:
        commentary.append("Weather-related headlines are affecting agricultural markets, raising concerns over crop yields.")
    if themes["ag_supply"]:
        commentary.append("Grain supply headlines are impacting wheat and corn, reflecting geopolitical or export-related risks.")

    if sent > 0.25:
        commentary.append("Overall news sentiment is constructive, offering support across cyclical commodities.")
    elif sent < -0.25:
        commentary.append("Negative news sentiment is weighing on risk-sensitive commodities.")

    if not commentary:
        commentary.append("Commodity markets are steady, with no major headline-driven themes dominating today.")

    for line in commentary:
        st.markdown(f"- {line}")


# =========================================================
# ======================= S&P500 TAB =======================
# =========================================================

with tabs[3]:
    render_sp500_tab()


# =========================================================
# =================== FLOW TRADING TAB ====================
# =========================================================

with tabs[4]:
    render_flow_trading_tab()