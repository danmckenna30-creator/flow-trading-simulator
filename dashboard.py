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
    st_autorefresh(interval=60 * 60 * 1000, key="macro_refresh")

    with st.spinner("Fetching latest news and sentiment..."):
        try:
            run_pipeline()
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
            mtime = os.path.getmtime("ai_news_output.csv")
            utc_dt = datetime.fromtimestamp(mtime, tz=pytz.UTC)
            uk_dt = utc_dt.astimezone(pytz.timezone("Europe/London"))
            ts = uk_dt.strftime("%Y-%m-%d %H:%M")
        except:
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
    left, right = st.columns()

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
            st.session_state["story_text"] = generate_story_mode()
        except Exception as e:
            st.session_state["story_text"] = f"Story mode error: {e}"

    story_text = st.session_state.get("story_text", "No story mode brief generated yet.")
    st.markdown(story_text)

    if st.button("🔄 Regenerate Morning Brief"):
        try:
            st.session_state["story_text"] = generate_story_mode()
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
    st.markdown("## 🛡️ Desk Risk & Inventory Monitor")
    
    # -----------------------------------------------------------------
    # SECTION 1: MARKET REGIME GAUGES
    # -----------------------------------------------------------------
    st.markdown("### 1. Market Risk & Volatility Backdrop")
    
    st.markdown(
        "> **How to read this:** Before taking client flows, a trader must check the market climate. "
        "High volatility means prices move violently, making it riskier to hold inventory. "
        "Low volatility suggests stable markets where the desk can safely hold larger positions."
    )
    
    vix_level = prices.get("VIX", {}).get("price", 15.0)
    vix_change = prices.get("VIX", {}).get("change") or 0
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Volatility Regime Gauge</div>", unsafe_allow_html=True)
        if vix_level < 15:
            st.markdown("<div class='big-number' style='color:#00ff88;'>LOW VOLATILITY</div>", unsafe_allow_html=True)
        elif vix_level <= 25:
            st.markdown("<div class='big-number' style='color:#FFDC00;'>NORMAL VOLATILITY</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='big-number' style='color:#ff4d4d;'>HIGH VOLATILITY</div>", unsafe_allow_html=True)
        st.markdown(f"<p style='color:#AAAAAA;'>VIX Index Level: {vix_level:.2f} ({vix_change:+.2f}%)</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
    with col2:
        heat_assets = ["VIX", "S&P 500", "USDJPY", "Brent Crude", "Copper"]
        heat_values = [prices.get(asset, {}).get("change", 0) or 0 for asset in heat_assets]
        
        heatmap_fig = go.Figure(
            data=go.Heatmap(
                z=[heat_values], x=heat_assets, y=["Daily Move"],
                text=[[f"{v:+.2f}%" for v in heat_values]], texttemplate="%{text}",
                colorscale="RdYlGn", showscale=False
            )
        )
        heatmap_fig.update_layout(template="plotly_dark", height=110, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(heatmap_fig, use_container_width=True, key="risk_tab_heatmap")

    st.markdown("---")

    # -----------------------------------------------------------------
    # SECTION 2: INVENTORY & FLOW DESK RISK
    # -----------------------------------------------------------------
    st.markdown("### 2. Live Inventory Risk & Limits")
    
    st.markdown(
        "> **How to read this:** This is the flow trading simulator's nervous system. "
        "When clients trade with us, we inherit their risk; if a bar goes too far positive (Long) or negative (Short), "
        "we breach our **$500k Desk Limit** and must use the Hedge buttons to neutralize our exposure."
    )
    
    init_flow_state()
    current_inventory = st.session_state.get("inventory", {})
    
    if current_inventory and any(v != 0 for v in current_inventory.values()):
        inv_data = pd.DataFrame([
            {"Asset": asset, "Net Position ($)": amount} 
            for asset, amount in current_inventory.items()
        ])
        
        fig_inv = px.bar(
            inv_data, x="Net Position ($)", y="Asset", orientation="h",
            title="Desk Net Exposure vs. $500,000 Risk Limit",
            color="Net Position ($)", color_continuous_scale="RdbU_r",
            range_x=[-1500000, 1500000]
        )
        fig_inv.add_vline(x=500000, line_dash="dash", line_color="red", annotation_text="Max Long Limit")
        fig_inv.add_vline(x=-500000, line_dash="dash", line_color="red", annotation_text="Max Short Limit")
        fig_inv.update_layout(template="plotly_dark", height=250, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig_inv, use_container_width=True)
    else:
        st.info("💡 **Desk Inventory is Flat.** No active risk. Go to the Flow Trading tab to add client flows!")

    st.markdown("#### FX Liquidity Risk Pairs")
    fx_pairs = ["USDJPY", "GBPUSD", "EURUSD"]
    fx_cols = st.columns(3)
    
    for i, pair in enumerate(fx_pairs):
        with fx_cols[i]:
            item = prices.get(pair, {})
            price = item.get("price", 0.0)
            change = item.get("change", 0.0)
            
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{pair}</div>", unsafe_allow_html=True)
            if price:
                color = "#00ff88" if change >= 0 else "#ff4d4d"
                st.markdown(f"<div class='big-number'>{price:.4f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='color:{color};'>{'▲' if change >= 0 else '▼'} {abs(change):.2f}%</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)


# =========================================================
# =================== COMMODITIES TAB =====================
# =========================================================

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
        news_df = pd.read_csv("ai_news_output.csv")
        news_list = news_df.to_dict(orient="records")
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