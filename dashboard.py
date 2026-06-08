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
# Sanitise all price values — ensure change is always float or 0, never None
for _k in list(prices.keys()):
    if prices[_k] is None:
        prices[_k] = {"price": None, "change": 0}
    else:
        if prices[_k].get("change") is None:
            prices[_k]["change"] = 0
        else:
            try:
                prices[_k]["change"] = float(prices[_k]["change"])
            except Exception:
                prices[_k]["change"] = 0

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

    vix_price     = (prices.get("VIX",          {}) or {}).get("price") or 20
    spx_change    = (prices.get("S&P 500",       {}) or {}).get("change") or 0
    usdjpy_change = (prices.get("USDJPY",        {}) or {}).get("change") or 0
    oil_change    = (prices.get("Brent Crude",   {}) or {}).get("change") or 0
    copper_change = (prices.get("Copper",        {}) or {}).get("change") or 0
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

    # ── SECTION 1: MARKET RISK ──────────────────────────────────
    st.markdown("### 📊 Section 1 — Market Risk Overview")
    st.caption("This section shows the overall market environment. As a flow trader, this tells you whether clients are likely buying risk assets (stocks, oil, copper) or selling them for safety (gold, USD, bonds).")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Risk Regime</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number {risk_cls}'>{risk_emoji} {risk_label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='label'>Score: {risk_score:+.2f}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>VIX (Fear Index)</div>", unsafe_allow_html=True)
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

    st.caption("**Risk Score** blends equity moves, copper, oil, FX and news sentiment into a single number. Above +0.3 = risk-on. Below -0.3 = risk-off. **VIX** below 15 is calm, above 25 means traders are scared.")
    st.markdown("---")

    # Regime Gauge
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
        template="plotly_dark", height=280,
        margin=dict(l=40, r=40, t=40, b=20),
        paper_bgcolor="rgba(0,0,0,0)", font={"color": "#ccc"}
    )
    st.plotly_chart(fig_gauge, use_container_width=True)
    st.caption("The gauge shows where markets sit between full risk-off (red) and risk-on (green). As a flow trader this predicts which way client orders will skew — in risk-on environments expect more equity and commodity buying.")
    st.markdown("---")

    # Heatmap
    st.markdown("#### Cross-Asset Heatmap")
    heatmap_assets  = ["VIX", "S&P 500", "USDJPY", "Brent Crude", "Copper", "Gold"]
    heatmap_changes = [(prices.get(a, {}) or {}).get("change") or 0 for a in heatmap_assets]
    fig_heat = go.Figure(go.Heatmap(
        z=[heatmap_changes], x=heatmap_assets, y=["% Change"],
        colorscale=[[0.0,"#ff4d4d"],[0.5,"#111111"],[1.0,"#00ff88"]],
        zmid=0,
        text=[[f"{v:+.2f}%" for v in heatmap_changes]],
        texttemplate="%{text}", showscale=True
    ))
    fig_heat.update_layout(template="plotly_dark", height=160, margin=dict(l=40,r=40,t=20,b=40))
    st.plotly_chart(fig_heat, use_container_width=True)
    st.caption("Red = falling today, Green = rising. VIX rising (red) is bad — fear is up. Copper and S&P 500 rising together = strong risk-on signal. Gold rising while equities fall = classic flight to safety.")
    st.markdown("---")

    # FX Pairs
    st.markdown("#### FX Risk Pairs")
    fx_cols = st.columns(3)
    for i, pair in enumerate(["USDJPY", "GBPUSD", "EURUSD"]):
        item   = (prices.get(pair, {}) or {})
        price  = item.get("price")
        change = item.get("change") or 0
        color  = "#00ff88" if change > 0 else "#ff4d4d" if change < 0 else "#fff"
        chstr  = f"▲ {change}%" if change > 0 else f"▼ {abs(change)}%" if change < 0 else "0.00%"
        with fx_cols[i]:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{pair}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number'>{price if price else 'N/A'}</div>", unsafe_allow_html=True)
            st.markdown(f"<div style='color:{color}; font-weight:bold;'>{chstr}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
    st.caption("USD/JPY rising = risk-on (investors selling safe-haven Yen). GBP/USD and EUR/USD rising = dollar weakening, positive for global risk. Large FX moves signal big institutional flows that flow traders need to be aware of.")
    st.markdown("---")

    # News Risk Themes
    st.markdown("#### News-Driven Risk Themes")
    if news_df is not None and len(news_df) > 0:
        news_list   = news_df.to_dict(orient="records")
        risk_themes = extract_news_themes(news_list)
        theme_labels = {
            "oil_supply":     "⛽ Oil Supply Risk",
            "oil_geopolitics":"🌍 Geopolitical Risk",
            "oil_demand":     "📉 Demand Concern",
            "energy_prices":  "⚡ Energy Price Pressure",
            "china_growth":   "🇨🇳 China Growth Risk",
            "manufacturing":  "🏭 Manufacturing Weakness",
            "inflation":      "📈 Inflation / Rate Risk",
            "weather":        "🌦 Weather / Crop Risk",
            "grain_supply":   "🌾 Grain Supply Risk",
        }
        active = [label for key, label in theme_labels.items() if risk_themes.get(key)]
        if active:
            tcols = st.columns(3)
            for i, label in enumerate(active):
                with tcols[i % 3]:
                    st.markdown(f"<div class='card' style='color:#FFDC00;'>{label}</div>", unsafe_allow_html=True)
        else:
            st.info("No elevated risk themes in current headlines.")
    else:
        st.info("No news data available yet.")
    st.caption("These themes are extracted from today's headlines. Each active theme is a macro risk that could drive client flow — e.g. geopolitical risk pushes clients into gold and out of equities.")
    st.markdown("---")

    # ── SECTION 2: FLOW TRADING RISK ───────────────────────────
    st.markdown("### 🏦 Section 2 — Flow Trading Risk")
    st.caption("This mirrors what a junior flow trader at a bank sees. When a client trades, you take the other side and manage the resulting risk. Your inventory shows what you're holding, and the bar chart shows your market exposure.")

    st.markdown("#### Current Inventory Exposure")
    inv = st.session_state.get("inventory", {})

    if inv and any(v != 0 for v in inv.values()):
        assets  = list(inv.keys())
        values  = [inv[a] for a in assets]
        colours = ["#00ff88" if v > 0 else "#ff4d4d" for v in values]
        fig_inv = go.Figure(go.Bar(
            x=assets, y=values, marker_color=colours,
            text=[f"${abs(v):,.0f}" for v in values], textposition="outside"
        ))
        fig_inv.update_layout(
            template="plotly_dark", height=320,
            title="Net Inventory (USD)", yaxis_title="Net Position (USD)",
            margin=dict(l=40,r=40,t=40,b=40),
            yaxis=dict(gridcolor="#333"), xaxis=dict(showgrid=False)
        )
        st.plotly_chart(fig_inv, use_container_width=True)
        st.caption("Green = long (you profit if price rises). Red = short (you profit if price falls). Good flow traders keep bars close to zero — large bars mean significant market risk if prices move against you.")
    else:
        st.info("No open inventory positions. Go to the Flow Trading tab to simulate some client trades — they will appear here.")
        st.caption("When you accept a client trade in the Flow Trading tab, your inventory updates here in real time. A flow trader's goal is to keep inventory balanced while collecting the bid/offer spread.")

    st.markdown("")

    # P&L Summary
    st.markdown("#### P&L Summary")
    pnl       = st.session_state.get("pnl", {"spread_pnl": 0, "hedge_pnl": 0, "inventory_pnl": 0})
    total_pnl = sum(pnl.values())
    p1, p2, p3, p4 = st.columns(4)
    for col, label, key, tip in [
        (p1, "Spread P&L",    "spread_pnl",    "Earned from bid/offer on every client trade"),
        (p2, "Hedge P&L",     "hedge_pnl",     "P&L from hedges placed to offset inventory risk"),
        (p3, "Inventory P&L", "inventory_pnl", "Mark-to-market gain/loss on open positions"),
        (p4, "Total P&L",     None,            "Your overall trading P&L"),
    ]:
        val = total_pnl if key is None else pnl.get(key, 0)
        cc  = "#00ff88" if val >= 0 else "#ff4d4d"
        with col:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{label}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number' style='color:{cc};'>${val:,.0f}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='label' style='font-size:10px;'>{tip}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
    st.caption("**Spread P&L** is guaranteed income you earn on every trade. **Inventory P&L** moves with the market and is risky. Great flow traders maximise spread income while keeping inventory P&L close to zero through hedging.")

    st.markdown("")

    # Hedge signals
    st.markdown("#### Hedge Signals")
    needs_hedge = {a: v for a, v in inv.items() if abs(v) >= 500_000}
    if needs_hedge:
        for asset, notional in needs_hedge.items():
            direction = "LONG" if notional > 0 else "SHORT"
            st.warning(f"⚠️ **{asset}** — You are {direction} ${abs(notional):,.0f}. Consider hedging in the Flow Trading tab.")
        st.caption("A hedge signal fires when a position exceeds $500,000. A 1% adverse move = $5,000 loss. Go to Flow Trading → Compute Hedge to reduce this exposure.")
    else:
        st.success("✅ No hedge signals — all positions within risk limits.")
        st.caption("Hedge signals appear when any single position exceeds $500,000 notional. Currently all positions are within acceptable limits.")


with tabs[2]:
    st.markdown("## Commodities")
    st.caption("Live prices, trends, risk themes, and flow signals across energy, metals, and agriculture.")
    st.markdown("---")

    commodity_names = ["Brent Crude", "WTI Crude", "Natural Gas", "Gold", "Silver", "Copper", "Corn", "Wheat"]

    # ── SECTION 1: PRICE CARDS ──────────────────────────────────
    st.markdown("### 📊 Live Prices")
    cols = st.columns(4)
    for i, name in enumerate(commodity_names):
        with cols[i % 4]:
            item = prices.get(name, None)
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{name}</div>", unsafe_allow_html=True)
            if item and item["price"] is not None:
                price  = item["price"]
                change = item["change"]
                if change is None:
                    change_str, color = "N/A", "#ffffff"
                elif change > 0:
                    change_str, color = f"▲ {change}%", "#00ff88"
                elif change < 0:
                    change_str, color = f"▼ {abs(change)}%", "#ff4d4d"
                else:
                    change_str, color = "0.00%", "#ffffff"
                st.markdown(f"<div class='big-number'>{price}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:16px; font-weight:bold; color:{color};'>{change_str}</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)
                st.markdown("<div style='font-size:16px;'>N/A</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── SECTION 2: HEATMAP ──────────────────────────────────────
    st.markdown("### 🌡️ Commodity Heatmap")
    st.caption("Today's % change across all commodities at a glance. Red = falling, Green = rising.")

    comm_changes = [(prices.get(n, {}) or {}).get("change") or 0 for n in commodity_names]
    fig_comm_heat = go.Figure(go.Heatmap(
        z=[comm_changes],
        x=commodity_names,
        y=["% Change"],
        colorscale=[[0.0,"#ff4d4d"],[0.5,"#111111"],[1.0,"#00ff88"]],
        zmid=0,
        text=[[f"{v:+.2f}%" for v in comm_changes]],
        texttemplate="%{text}",
        showscale=True
    ))
    fig_comm_heat.update_layout(
        template="plotly_dark", height=160,
        margin=dict(l=40, r=40, t=10, b=60)
    )
    st.plotly_chart(fig_comm_heat, use_container_width=True)
    st.caption("Energy (Brent, WTI, Gas) moving together = supply/demand story. Gold and Silver rising while equities fall = risk-off. Copper rising = global growth optimism. Corn and Wheat moving = weather or geopolitical supply disruption.")
    st.markdown("---")

    # ── SECTION 3: PRICE HISTORY SPARKLINES ─────────────────────
    st.markdown("### 📈 30-Day Price History")
    st.caption("Trend context for each commodity — one day's move means little without knowing the recent direction.")

    COMMODITY_TICKERS = {
        "Brent Crude": "BZ=F", "WTI Crude": "CL=F", "Natural Gas": "NG=F",
        "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F",
        "Corn": "ZC=F", "Wheat": "ZW=F"
    }

    @st.cache_data(ttl=3600)
    def get_commodity_history():
        import yfinance as yf
        history = {}
        for name, ticker in COMMODITY_TICKERS.items():
            try:
                hist = yf.Ticker(ticker).history(period="1mo")
                if hist is not None and len(hist) > 5:
                    history[name] = {
                        "dates":  [str(d.date()) for d in hist.index],
                        "closes": [round(float(v), 4) for v in hist["Close"]]
                    }
            except Exception:
                pass
        return history

    with st.spinner("Loading 30-day history..."):
        comm_history = get_commodity_history()

    spark_cols = st.columns(4)
    for i, name in enumerate(commodity_names):
        with spark_cols[i % 4]:
            if name in comm_history and comm_history[name]["closes"]:
                closes = comm_history[name]["closes"]
                dates  = comm_history[name]["dates"]
                start_price = closes[0]
                end_price   = closes[-1]
                pct_30d = ((end_price - start_price) / start_price) * 100
                trend_color = "#00ff88" if pct_30d > 0 else "#ff4d4d"

                fig_spark = go.Figure(go.Scatter(
                    x=dates, y=closes,
                    mode="lines",
                    line=dict(color=trend_color, width=2),
                    fill="tozeroy",
                    fillcolor=f"rgba({'0,255,136' if pct_30d > 0 else '255,77,77'},0.08)"
                ))
                fig_spark.update_layout(
                    template="plotly_dark",
                    height=120,
                    margin=dict(l=0, r=0, t=25, b=0),
                    title=dict(text=f"{name} ({pct_30d:+.1f}% 30d)", font=dict(size=11, color=trend_color), x=0),
                    xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                    yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig_spark, use_container_width=True, config={"displayModeBar": False})
            else:
                st.markdown(f"<div class='card'><div class='label'>{name}</div><div>No history</div></div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── SECTION 4: CORRELATION MATRIX ───────────────────────────
    st.markdown("### 🔗 Commodity Correlation Matrix")
    st.caption("Shows which commodities are moving together over the last 30 days. Dark green = moving in sync. Dark red = moving in opposite directions. Grey = no relationship.")

    @st.cache_data(ttl=3600)
    def get_commodity_correlations():
        import yfinance as yf
        import pandas as pd
        closes_dict = {}
        for name, ticker in COMMODITY_TICKERS.items():
            try:
                hist = yf.Ticker(ticker).history(period="1mo")
                if hist is not None and len(hist) > 5:
                    closes_dict[name] = hist["Close"].values[-20:]
            except Exception:
                pass
        if len(closes_dict) < 2:
            return None
        import numpy as np
        names = list(closes_dict.keys())
        matrix = []
        for n1 in names:
            row = []
            for n2 in names:
                a, b = closes_dict[n1], closes_dict[n2]
                min_len = min(len(a), len(b))
                if min_len < 5:
                    row.append(0)
                else:
                    corr = float(np.corrcoef(a[-min_len:], b[-min_len:])[0,1])
                    row.append(round(corr, 2))
            matrix.append(row)
        return names, matrix

    corr_result = get_commodity_correlations()
    if corr_result:
        corr_names, corr_matrix = corr_result
        fig_corr = go.Figure(go.Heatmap(
            z=corr_matrix,
            x=corr_names, y=corr_names,
            colorscale=[[0.0,"#ff4d4d"],[0.5,"#222222"],[1.0,"#00ff88"]],
            zmin=-1, zmax=1,
            text=[[f"{v:.2f}" for v in row] for row in corr_matrix],
            texttemplate="%{text}", showscale=True,
            colorbar=dict(title="Correlation")
        ))
        fig_corr.update_layout(
            template="plotly_dark", height=380,
            margin=dict(l=40, r=40, t=20, b=40)
        )
        st.plotly_chart(fig_corr, use_container_width=True)
        st.caption("**Reading the matrix:** Each cell shows how correlated two commodities are over the past 20 trading days. +1.0 = they move perfectly together. -1.0 = they move in opposite directions. 0 = no relationship. As a flow trader, high correlation between two assets means hedging one with the other is less effective.")
    else:
        st.info("Not enough data to compute correlations yet.")
    st.markdown("---")

    # ── SECTION 5: PER-COMMODITY RISK CARDS ─────────────────────
    st.markdown("### ⚡ Commodity Risk Themes")
    st.caption("Each commodity's risk status based on today's headlines and price action. These are the themes a commodity desk would flag in their morning meeting.")

    try:
        news_list = news_df.to_dict(orient="records") if news_df is not None else []
    except Exception:
        news_list = []

    themes = extract_commodity_themes(news_list)

    commodity_risks = {
        "Brent Crude": {
            "drivers": [],
            "risk": "LOW",
            "color": "#00ff88"
        },
        "WTI Crude": {"drivers": [], "risk": "LOW", "color": "#00ff88"},
        "Natural Gas": {"drivers": [], "risk": "LOW", "color": "#00ff88"},
        "Gold": {"drivers": [], "risk": "LOW", "color": "#00ff88"},
        "Copper": {"drivers": [], "risk": "LOW", "color": "#00ff88"},
        "Corn": {"drivers": [], "risk": "LOW", "color": "#00ff88"},
        "Wheat": {"drivers": [], "risk": "LOW", "color": "#00ff88"},
    }

    if themes.get("oil_supply"):
        commodity_risks["Brent Crude"]["drivers"].append("Supply headlines active")
        commodity_risks["WTI Crude"]["drivers"].append("Supply headlines active")
    if themes.get("oil_geopolitics"):
        commodity_risks["Brent Crude"]["drivers"].append("⚠️ Geopolitical risk")
        commodity_risks["WTI Crude"]["drivers"].append("⚠️ Geopolitical risk")
        commodity_risks["Brent Crude"]["risk"] = "HIGH"
        commodity_risks["Brent Crude"]["color"] = "#ff4d4d"
    if themes.get("oil_demand"):
        commodity_risks["Brent Crude"]["drivers"].append("Demand signal")
        commodity_risks["WTI Crude"]["drivers"].append("Demand signal")
    if themes.get("energy"):
        commodity_risks["Natural Gas"]["drivers"].append("Energy headlines active")
        commodity_risks["Natural Gas"]["risk"] = "MEDIUM"
        commodity_risks["Natural Gas"]["color"] = "#FFDC00"
    if themes.get("inflation"):
        commodity_risks["Gold"]["drivers"].append("Inflation/rates driver")
        commodity_risks["Gold"]["risk"] = "MEDIUM"
        commodity_risks["Gold"]["color"] = "#FFDC00"
    if themes.get("china"):
        commodity_risks["Copper"]["drivers"].append("China demand signal")
        commodity_risks["Copper"]["risk"] = "MEDIUM"
        commodity_risks["Copper"]["color"] = "#FFDC00"
    if themes.get("weather"):
        commodity_risks["Corn"]["drivers"].append("⚠️ Weather risk")
        commodity_risks["Wheat"]["drivers"].append("⚠️ Weather risk")
        commodity_risks["Corn"]["risk"] = "HIGH"
        commodity_risks["Corn"]["color"] = "#ff4d4d"
    if themes.get("ag_supply"):
        commodity_risks["Wheat"]["drivers"].append("Supply disruption signal")
        commodity_risks["Wheat"]["risk"] = "HIGH"
        commodity_risks["Wheat"]["color"] = "#ff4d4d"

    # Apply price-based risk adjustments
    for name in ["Brent Crude", "WTI Crude", "Natural Gas", "Gold", "Silver", "Copper", "Corn", "Wheat"]:
        change = (prices.get(name, {}) or {}).get("change") or 0
        if abs(change) > 2 and name in commodity_risks:
            if commodity_risks[name]["risk"] == "LOW":
                commodity_risks[name]["risk"] = "MEDIUM"
                commodity_risks[name]["color"] = "#FFDC00"
            commodity_risks[name]["drivers"].append(f"Large price move: {change:+.1f}%")

    risk_cols = st.columns(4)
    for i, (name, info) in enumerate(commodity_risks.items()):
        with risk_cols[i % 4]:
            drivers_text = "<br>".join(info["drivers"]) if info["drivers"] else "No active themes"
            st.markdown(
                f"<div class='card'>"
                f"<div class='label'>{name}</div>"
                f"<div class='big-number' style='color:{info["color"]};'>{info["risk"]}</div>"
                f"<div style='font-size:11px; color:#AAAAAA; margin-top:4px;'>{drivers_text}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ── SECTION 6: FLOW SIGNALS ──────────────────────────────────
    st.markdown("### 🏦 Flow Trading Signals")
    st.caption("Based on today's price moves, news themes, and the overall risk regime — what are clients likely buying and selling? This is how a commodity flow trader thinks about the day ahead.")

    # Build flow signals
    flow_signals = []
    vix_flow = (prices.get("VIX", {}) or {}).get("price") or 20
    risk_regime_flow = "risk-on" if (prices.get("S&P 500", {}) or {}).get("change", 0) > 0 else "risk-off"

    brent_chg  = (prices.get("Brent Crude", {}) or {}).get("change") or 0
    gold_chg   = (prices.get("Gold",        {}) or {}).get("change") or 0
    copper_chg = (prices.get("Copper",      {}) or {}).get("change") or 0
    gas_chg    = (prices.get("Natural Gas", {}) or {}).get("change") or 0
    silver_chg = (prices.get("Silver",      {}) or {}).get("change") or 0
    corn_chg   = (prices.get("Corn",        {}) or {}).get("change") or 0
    wheat_chg  = (prices.get("Wheat",       {}) or {}).get("change") or 0

    if brent_chg > 1:
        flow_signals.append(("🟢 BUY FLOW", "Brent Crude", f"Up {brent_chg:+.1f}% — expect client buying. Likely driven by {'geopolitical risk premium' if themes.get('oil_geopolitics') else 'supply constraints' if themes.get('oil_supply') else 'broad risk-on positioning'}."))
    elif brent_chg < -1:
        flow_signals.append(("🔴 SELL FLOW", "Brent Crude", f"Down {brent_chg:+.1f}% — expect client selling or hedging. {'Demand concerns dominant.' if themes.get('oil_demand') else 'Broad risk-off tone.'}"))

    if gold_chg > 0.5 and vix_flow > 18:
        flow_signals.append(("🟢 BUY FLOW", "Gold", f"Up {gold_chg:+.1f}% with VIX at {vix_flow:.0f} — safe-haven demand. Clients likely adding gold as portfolio hedge."))
    elif gold_chg < -0.5 and risk_regime_flow == "risk-on":
        flow_signals.append(("🔴 SELL FLOW", "Gold", f"Down {gold_chg:+.1f}% — risk-on environment. Clients rotating out of safe havens into equities and cyclicals."))

    if copper_chg > 1:
        flow_signals.append(("🟢 BUY FLOW", "Copper", f"Up {copper_chg:+.1f}% — industrial demand signal. {'China growth story supporting copper.' if themes.get('china') else 'Global growth optimism driving base metals.'} "))
    elif copper_chg < -1:
        flow_signals.append(("🔴 SELL FLOW", "Copper", f"Down {copper_chg:+.1f}% — growth concern signal. Watch for broader risk-off rotation."))

    if gas_chg > 2:
        flow_signals.append(("🟢 BUY FLOW", "Natural Gas", f"Up {gas_chg:+.1f}% — energy supply or seasonal demand driving prices. Utility and energy sector clients likely active."))
    elif gas_chg < -2:
        flow_signals.append(("🔴 SELL FLOW", "Natural Gas", f"Down {gas_chg:+.1f}% — oversupply or demand miss. Energy producers may be hedging."))

    if themes.get("weather") and (corn_chg > 1 or wheat_chg > 1):
        flow_signals.append(("🟢 BUY FLOW", "Grains", f"Weather headlines active with Corn {corn_chg:+.1f}% and Wheat {wheat_chg:+.1f}%. Agricultural traders and food producers likely buying protection."))

    if not flow_signals:
        flow_signals.append(("🟡 NEUTRAL", "All Commodities", "No strong directional signals today. Commodity moves are modest and headline themes are limited. Expect two-way flow with no clear dominant direction."))

    for signal, asset, reasoning in flow_signals:
        color = "#00ff88" if "BUY" in signal else "#ff4d4d" if "SELL" in signal else "#FFDC00"
        st.markdown(
            f"<div class='card' style='margin-bottom:8px; border-left: 3px solid {color};'>"
            f"<div style='color:{color}; font-weight:bold; font-size:14px;'>{signal} — {asset}</div>"
            f"<div style='color:#DDDDDD; font-size:13px; margin-top:4px;'>{reasoning}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    st.markdown("")

    # Position sizing guide
    st.markdown("#### Position Sizing Guide")
    st.caption("Based on current VIX and commodity volatility, how large a position would a flow trader typically take? Lower VIX = more comfortable taking larger positions. Higher VIX = tighter risk limits.")

    if vix_flow < 15:
        size_regime, size_color, size_pct = "LOW VOL — Normal sizing", "#00ff88", 100
    elif vix_flow < 20:
        size_regime, size_color, size_pct = "MODERATE VOL — Slightly reduced", "#FFDC00", 75
    elif vix_flow < 25:
        size_regime, size_color, size_pct = "ELEVATED VOL — Reduced sizing", "#FF8C00", 50
    else:
        size_regime, size_color, size_pct = "HIGH VOL — Minimum sizing", "#ff4d4d", 25

    sz1, sz2, sz3 = st.columns(3)
    with sz1:
        st.markdown(f"<div class='card'><div class='label'>Vol Regime</div><div style='color:{size_color}; font-weight:bold; font-size:15px;'>{size_regime}</div></div>", unsafe_allow_html=True)
    with sz2:
        st.markdown(f"<div class='card'><div class='label'>VIX Level</div><div class='big-number'>{vix_flow:.1f}</div></div>", unsafe_allow_html=True)
    with sz3:
        st.markdown(f"<div class='card'><div class='label'>Suggested Position Size</div><div class='big-number' style='color:{size_color};'>{size_pct}% of normal</div></div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── SECTION 7: GPT COMMODITY BRIEF ──────────────────────────
    st.markdown("### 🤖 AI Commodity Brief")
    st.caption("GPT synthesises today's commodity price moves, news themes, and correlations into a trader-ready morning note for the commodity desk.")

    if st.button("🔄 Generate Commodity Brief", key="commodity_brief_btn"):
        with st.spinner("Generating commodity brief..."):
            try:
                from gpt_layer import call_gpt_prose
                comm_prompt = f"""You are a senior commodity strategist writing a morning brief for a commodity flow trading desk.

LIVE COMMODITY DATA:
- Brent Crude: {brent_chg:+.2f}% today
- WTI Crude: {(prices.get("WTI Crude",{}) or {}).get("change",0) or 0:+.2f}% today
- Natural Gas: {gas_chg:+.2f}% today
- Gold: {gold_chg:+.2f}% today
- Silver: {silver_chg:+.2f}% today
- Copper: {copper_chg:+.2f}% today
- Corn: {corn_chg:+.2f}% today
- Wheat: {wheat_chg:+.2f}% today

ACTIVE NEWS THEMES:
- Oil supply headlines: {themes.get("oil_supply", False)}
- Geopolitical risk: {themes.get("oil_geopolitics", False)}
- China/manufacturing: {themes.get("china", False)}
- Inflation/rates: {themes.get("inflation", False)}
- Weather/crop risk: {themes.get("weather", False)}
- Agricultural supply: {themes.get("ag_supply", False)}

MACRO CONTEXT:
- VIX: {vix_flow:.1f}
- Risk regime: {risk_regime_flow}
- Overall news sentiment: {themes.get("sentiment", 0):.2f}

Write a concise 4-5 sentence commodity morning brief covering:
1. The dominant theme driving commodity markets today
2. The most important individual commodity move and why
3. What the energy/metals/agriculture split tells us about the macro environment
4. One specific flow trading observation — what are clients likely buying or selling?

Bloomberg terminal style. Professional and direct. Plain prose only. No bullet points."""

                comm_brief = call_gpt_prose(comm_prompt)
                st.session_state["commodity_brief"] = comm_brief or "Could not generate brief — check OpenAI key."
            except Exception as e:
                st.session_state["commodity_brief"] = f"Error: {e}"

    comm_text = st.session_state.get("commodity_brief", "Click above to generate an AI commodity brief.")
    st.markdown(f"<div class='card' style='line-height:1.7; color:#DDDDDD;'>{comm_text}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── SECTION 8: ORIGINAL COMMENTARY ──────────────────────────
    st.markdown("### 📝 Commodity Commentary")

    sent = themes.get("sentiment", 0)
    commentary = []

    oil = (prices.get("Brent Crude", {}) or {}).get("change")
    if oil is not None:
        if oil > 1:
            if themes.get("oil_supply"): commentary.append("Oil is climbing as supply-side headlines — including OPEC+ discipline and production constraints — support prices.")
            elif themes.get("oil_geopolitics"): commentary.append("Oil is higher as geopolitical tensions in key producing regions add a risk premium.")
            elif themes.get("oil_demand"): commentary.append("Oil is gaining on stronger demand expectations reflected in travel and consumption-related headlines.")
            else: commentary.append("Oil is moving higher despite limited headline catalysts, suggesting technical or positioning-driven flows.")
        elif oil < -1:
            if themes.get("oil_supply"): commentary.append("Oil is falling even as supply headlines remain tight, indicating demand concerns are dominating.")
            elif themes.get("oil_demand"): commentary.append("Oil is under pressure as headlines point to softer demand expectations.")
            else: commentary.append("Oil is weakening with little headline support, likely reflecting easing supply constraints or a broader macro risk-off tone.")
        else:
            commentary.append("Oil is relatively stable, with no dominant supply or demand headlines driving direction.")

    copper_c = (prices.get("Copper", {}) or {}).get("change")
    if copper_c is not None:
        if themes.get("china"): commentary.append("Copper is reacting to China-related headlines, with industrial activity remaining a key demand driver.")
        elif copper_c > 1: commentary.append("Copper is firm, potentially reflecting improved global manufacturing sentiment.")
        elif copper_c < -1: commentary.append("Copper is softer, hinting at weaker industrial demand or cautious macro sentiment.")

    gold_c = (prices.get("Gold", {}) or {}).get("change")
    if gold_c is not None:
        if themes.get("inflation"): commentary.append("Gold is responding to inflation and rate-related headlines, which continue to shape safe-haven demand.")
        elif gold_c > 1: commentary.append("Gold is gaining as investors seek safety amid broader macro uncertainty.")
        elif gold_c < -1: commentary.append("Gold is easing, suggesting reduced safe-haven demand or firmer yields.")

    if themes.get("weather"): commentary.append("Weather-related headlines are affecting agricultural markets, raising concerns over crop yields.")
    if themes.get("ag_supply"): commentary.append("Grain supply headlines are impacting wheat and corn, reflecting geopolitical or export-related risks.")
    if sent > 0.25: commentary.append("Overall news sentiment is constructive, offering support across cyclical commodities.")
    elif sent < -0.25: commentary.append("Negative news sentiment is weighing on risk-sensitive commodities.")
    if not commentary: commentary.append("Commodity markets are steady, with no major headline-driven themes dominating today.")

    for line in commentary:
        st.markdown(f"- {line}")


with tabs[3]:
    render_sp500_tab()


# =========================================================
# =================== FLOW TRADING TAB ====================
# =========================================================

with tabs[4]:
    render_flow_trading_tab()