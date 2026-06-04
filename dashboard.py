import json
import pandas as pd
import streamlit as st
from datetime import datetime
import os
from market_data import get_market_data
import plotly.graph_objects as go
from market_data import get_yield_curve
import pandas as pd
import pytz
from market_data import get_advance_decline_line, get_rsp_spy_ratio, compute_sp500_breadth, render_sp500_tab, get_spot_price
import yfinance as yf
import plotly.express as px
import math
import random
from datetime import datetime


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
        df = pd.read_csv("ai_news_output.csv")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df
    except Exception:
        return None

def load_gpt():
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

# ---------- TABS ----------
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
        "ai_hype": False   # <-- ADD THIS HERE
    }

    for item in news:
        h = item["headline"].lower()

        # Oil supply / OPEC
        if any(k in h for k in ["opec", "production cut", "supply cut", "oil output"]):
            themes["oil_supply"] = True

        # Geopolitics affecting oil
        if any(k in h for k in ["middle east", "iran", "israel", "houthi", "red sea", "attack", "strike"]):
            themes["oil_geopolitics"] = True

        # Oil demand
        if any(k in h for k in ["demand", "travel", "consumption", "jet fuel"]):
            themes["oil_demand"] = True

        # General energy headlines
        if "energy" in h:
            themes["energy_prices"] = True

        # China / copper driver
        if any(k in h for k in ["china", "pmi", "manufacturing", "factory"]):
            themes["china_growth"] = True
            themes["manufacturing"] = True

        # Inflation → gold driver
        if any(k in h for k in ["inflation", "cpi", "ppi", "yields", "rates"]):
            themes["inflation"] = True

        # Agriculture
        if any(k in h for k in ["drought", "harvest", "crop", "weather", "heatwave"]):
            themes["weather"] = True

        if any(k in h for k in ["grain", "wheat", "corn", "export ban", "ukraine"]):
            themes["grain_supply"] = True

        # ⭐ AI hype detection (NEW)
        if any(k in h for k in [
            "ai", "artificial intelligence", "chip", "semiconductor",
            "gpu", "nvidia", "openai"
        ]):
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

        # Oil supply
        if any(k in h for k in ["opec", "production cut", "supply cut", "oil output"]):
            themes["oil_supply"] = True

        # Oil geopolitics
        if any(k in h for k in ["middle east", "iran", "israel", "houthi", "red sea", "attack"]):
            themes["oil_geopolitics"] = True

        # Oil demand
        if any(k in h for k in ["demand", "travel", "consumption", "jet fuel"]):
            themes["oil_demand"] = True

        # Energy sector
        if topic == "energy":
            themes["energy"] = True

        # China / copper
        if any(k in h for k in ["china", "pmi", "manufacturing", "factory"]):
            themes["china"] = True

        # Inflation / gold
        if any(k in h for k in ["inflation", "cpi", "ppi", "yields", "rates"]):
            themes["inflation"] = True

        # Weather / agriculture
        if any(k in h for k in ["drought", "weather", "heatwave"]):
            themes["weather"] = True

        if any(k in h for k in ["grain", "wheat", "corn", "export ban", "ukraine"]):
            themes["ag_supply"] = True

    themes["sentiment"] = total_sent / count if count > 0 else 0
    return themes

def render_sp500_tab():
    st.header("📊 S&P 500 Deep Dive")

    # --- SPX Price ---
    spx = yf.Ticker("^GSPC").history(period="5d")
    price = spx["Close"].iloc[-1]
    prev = spx["Close"].iloc[-2]
    change = (price - prev) / prev * 100

    st.subheader("S&P 500 Overview")
    st.metric("S&P 500", f"{price:,.0f}", f"{change:.2f}%")
    

    # --- Breadth ---
    st.subheader("Market Breadth")
    breadth = compute_sp500_breadth()

    col1, col2, col3 = st.columns(3)
    col1.metric("Above 20‑day MA", f"{breadth['20dma']}%")
    col2.metric("Above 50‑day MA", f"{breadth['50dma']}%")
    col3.metric("Above 200‑day MA", f"{breadth['200dma']}%")

    # --- RSP vs SPY ---
    st.subheader("Equal‑Weight vs Cap‑Weight")
    ratio = get_rsp_spy_ratio()
    st.metric("RSP / SPY Ratio", ratio)

    # --- Advance/Decline Line ---
    st.subheader("Advance / Decline Line")
    adv = (spx["Close"].diff() > 0).rolling(50).sum()
    fig = px.line(adv, title="Advance/Decline (50‑day Rolling)")
    st.plotly_chart(fig, use_container_width=True)

# =========================================================
# ====================== MACRO TAB ========================
# =========================================================

with tabs[0]:

    # ---------- TOP ROW: MACRO SNAPSHOT ----------
    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])

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

            st.markdown(
                f"<div class='big-number {cls}'>{regime.upper()}</div>",
                unsafe_allow_html=True
            )
        else:
            st.markdown("<div class='big-number neutral'>N/A</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("")

    # ---------- GPT MACRO ANALYSIS ----------
    st.markdown("### Macro Analyst View")

    left, right = st.columns([3, 2])

    with left:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        if gpt:
            theme = gpt.get("macro_theme", "N/A")
            summary = gpt.get("summary", "No summary available.")

            st.markdown("<div class='label'>Macro Theme</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number'>{theme}</div>", unsafe_allow_html=True)

            st.markdown(
                "<div class='label' style='margin-top:8px;'>Summary</div>",
                unsafe_allow_html=True
            )

            st.markdown(
                f"<p style='color:#DDDDDD;'>{summary}</p>",
                unsafe_allow_html=True
            )

        else:
            st.markdown(
                "<p style='color:#AAAAAA;'>No GPT analysis available yet.</p>",
                unsafe_allow_html=True
            )

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        if gpt:
            conf = gpt.get("confidence", None)
            kp = gpt.get("key_points", [])

            st.markdown("<div class='label'>Confidence</div>", unsafe_allow_html=True)

            if conf is not None:
                st.markdown(
                    f"<div class='big-number'>{conf}/100</div>",
                    unsafe_allow_html=True
                )
            else:
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)

            st.markdown(
                "<div class='label' style='margin-top:8px;'>Key Points</div>",
                unsafe_allow_html=True
            )

            if isinstance(kp, list) and kp:
                for point in kp:
                    st.markdown(f"- {point}")
            else:
                st.markdown(
                    "<p style='color:#AAAAAA;'>No key points available.</p>",
                    unsafe_allow_html=True
                )

        else:
            st.markdown(
                "<p style='color:#AAAAAA;'>No GPT analysis available yet.</p>",
                unsafe_allow_html=True
            )

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ---------- HEADLINES + SENTIMENT ----------
    bottom_left, bottom_right = st.columns([3, 2])

    with bottom_left:
        st.markdown("### Latest Headlines")

        if news_df is not None and len(news_df) > 0:
            show_cols = [
                "date",
                "source",
                "headline",
                "sentiment",
                "topic",
                "relevance"
            ]

            existing = [c for c in show_cols if c in news_df.columns]

            table = news_df.sort_values(
                "date",
                ascending=False
            )[existing].head(25)

            st.dataframe(
                table,
                use_container_width=True,
                hide_index=True
            )

        else:
            st.markdown(
                "<p style='color:#AAAAAA;'>No news data available yet.</p>",
                unsafe_allow_html=True
            )

    with bottom_right:
        st.markdown("### Sentiment Over Time")

        if (
            news_df is not None
            and "date" in news_df.columns
            and "sentiment" in news_df.columns
        ):
            chart_df = news_df.sort_values("date").set_index("date")[["sentiment"]]
            st.line_chart(chart_df, height=260)

        else:
            st.markdown(
                "<p style='color:#AAAAAA;'>Not enough data to plot sentiment.</p>",
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ---------- STORY MODE ----------
    st.markdown("### Morning Macro Brief")

    try:
        with open("story_mode.txt", "r") as f:
            story_text = f.read()
    except:
        story_text = "No story mode brief generated yet."

    st.markdown(
        """
        <div class='card' style='white-space: pre-wrap; line-height: 1.4;'>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        f"<p style='color:#DDDDDD;'>{story_text}</p>",
        unsafe_allow_html=True
    )

    st.markdown("</div>", unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("## Story Mode")

        if st.button("Regenerate Morning Brief"):
            os.system("python story_mode.py")
            st.experimental_rerun()

    # ---------- MARKET SNAPSHOT ----------
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

                st.markdown(
                    f"<div class='big-number'>{price}</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    f"<div style='font-size:16px; font-weight:bold; color:{color};'>{change_str}</div>",
                    unsafe_allow_html=True
                )

            else:
                st.markdown(
                    "<div class='big-number'>N/A</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    "<div style='font-size:16px;'>N/A</div>",
                    unsafe_allow_html=True
                )

            st.markdown("</div>", unsafe_allow_html=True)

    # ---------- YIELD CURVE ----------
    st.markdown("### Yield Curve")

    curve = get_yield_curve()

    maturities = ["2Y", "5Y", "10Y", "30Y"]
    yields = [curve[m] for m in maturities]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=maturities,
            y=yields,
            mode="lines+markers",
            line=dict(color="#00c3ff", width=3),
            marker=dict(
                size=10,
                color="#ffffff",
                line=dict(width=2, color="#00c3ff")
            ),
        )
    )

    fig.update_layout(
        template="plotly_dark",
        height=350,
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis_title="Maturity",
        yaxis_title="Yield (%)",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#333333"),
    )

    st.plotly_chart(fig, use_container_width=True)

    # ---------- SPREADS ----------
    slope_2s10s = curve["10Y"] - curve["2Y"]
    slope_5s30s = curve["30Y"] - curve["5Y"]

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>2s10s Spread</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='big-number'>{slope_2s10s:.2f} bps</div>",
            unsafe_allow_html=True
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>5s30s Spread</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='big-number'>{slope_5s30s:.2f} bps</div>",
            unsafe_allow_html=True
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if slope_2s10s < 0:
        st.markdown(
            "<p style='color:#ff4d4d; font-weight:bold; font-size:18px;'>⚠️ Yield curve inverted (10-year Treasury yield < 2-year Treasury yield)</p>",
            unsafe_allow_html=True
        )

# =========================================================
# ======================= RISK TAB ========================
# =========================================================

with tabs[1]:

    st.markdown("### Cross-Asset Risk Monitor")

    # ---------- RISK DATA ----------
    vix_change = prices.get("VIX", {}).get("change", 0) or 0
    spx_change = prices.get("S&P 500", {}).get("change", 0) or 0
    usdjpy_change = prices.get("USDJPY", {}).get("change", 0) or 0
    oil_change = prices.get("Brent Crude", {}).get("change", 0) or 0
    copper_change = prices.get("Copper", {}).get("change", 0) or 0

    news_sentiment = 0
    if news_df is not None and "sentiment" in news_df.columns and len(news_df) > 0:
        news_sentiment = news_df["sentiment"].mean()

    # ---------- RISK SCORE ----------
    risk_score = 0
    risk_score += spx_change * 2
    risk_score += copper_change
    risk_score += oil_change * 0.5
    risk_score += usdjpy_change
    risk_score += news_sentiment * 10
    risk_score -= vix_change * 2

    if risk_score > 2:
        risk_label = "RISK-ON"
        risk_class = "risk-on"
    elif risk_score < -2:
        risk_label = "RISK-OFF"
        risk_class = "risk-off"
    else:
        risk_label = "NEUTRAL"
        risk_class = "neutral"

    score_col1, score_col2 = st.columns([2, 1])

    # ---------- RISK REGIME CARD ----------
    with score_col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Cross-Asset Risk Regime</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='big-number {risk_class}'>{risk_label}</div>", unsafe_allow_html=True)
        st.markdown(f"<p style='color:#AAAAAA;'>Composite Risk Score: {risk_score:.2f}</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ---------- VOLATILITY REGIME ----------
    with score_col2:
        vix_level = prices.get("VIX", {}).get("price", None)

        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>Volatility Regime</div>", unsafe_allow_html=True)

        if vix_level is not None:
            if vix_level < 15:
                vol_regime = "LOW VOL"
                vol_color = "#00ff88"
            elif vix_level <= 25:
                vol_regime = "NORMAL VOL"
                vol_color = "#FFDC00"
            else:
                vol_regime = "HIGH VOL"
                vol_color = "#ff4d4d"

            st.markdown(f"<div class='big-number' style='color:{vol_color};'>{vol_regime}</div>", unsafe_allow_html=True)
            st.markdown(f"<p style='color:#AAAAAA;'>VIX: {vix_level}</p>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ---------- HEATMAP ----------
    st.markdown("### Cross-Asset Heatmap")

    heat_assets = ["VIX", "S&P 500", "USDJPY", "Brent Crude", "Copper"]
    heat_values = []

    for asset in heat_assets:
        val = prices.get(asset, {}).get("change", 0)
        heat_values.append(val if val is not None else 0)

    heatmap_fig = go.Figure(
        data=go.Heatmap(
            z=[heat_values],
            x=heat_assets,
            y=["Daily Move"],
            text=[[f"{v:.2f}%" for v in heat_values]],
            texttemplate="%{text}",
            colorscale="RdYlGn",
        )
    )

    heatmap_fig.update_layout(
        template="plotly_dark",
        height=250,
        margin=dict(l=20, r=20, t=40, b=20)
    )

    st.plotly_chart(heatmap_fig, use_container_width=True, key="risk_heatmap")

    st.markdown("---")

       # ---------- FX RISK ----------
    st.markdown("### FX Risk Pairs")

    fx_pairs = ["USDJPY", "GBPUSD", "EURUSD"]
    fx_cols = st.columns(3)

    for i, pair in enumerate(fx_pairs):
        with fx_cols[i]:

            item = prices.get(pair, {})

            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{pair}</div>", unsafe_allow_html=True)

            price = item.get("price")
            change = item.get("change")

            if price is not None and change is not None:

                # Format price nicely
                if pair == "USDJPY":
                    price_str = f"{price:.2f}"
                else:
                    price_str = f"{price:.4f}"

                # Colour + arrow
                if change > 0:
                    color = "#00ff88"
                    arrow = "▲"
                elif change < 0:
                    color = "#ff4d4d"
                    arrow = "▼"
                else:
                    color = "#ffffff"
                    arrow = ""

                st.markdown(
                    f"<div class='big-number'>{price_str}</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    f"<div style='font-size:18px; color:{color};'>{arrow} {abs(change):.2f}%</div>",
                    unsafe_allow_html=True
                )

            else:
                # If missing data
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

        # ---------- AI BUBBLE RISK INDICATOR ----------
    st.markdown("### AI Bubble Risk")

    # --- 1. Price action & volatility ---
    nvda = prices.get("NVDA", {}).get("change", 0)
    soxx = prices.get("SOXX", {}).get("change", 0)

    vol_risk = 0
    if abs(nvda) > 4 or abs(soxx) > 3:
        vol_risk = 2
    elif abs(nvda) > 2 or abs(soxx) > 1.5:
        vol_risk = 1

    # --- 2. Breadth ---
    spx = prices.get("S&P 500", {}).get("change", 0)
    rsp = prices.get("RSP", {}).get("change", 0)
    breadth_gap = spx - rsp

    breadth_risk = 0
    if breadth_gap > 1.5:
        breadth_risk = 2
    elif breadth_gap > 0.7:
        breadth_risk = 1

    # --- 3. SOXX/SPX ratio ---
    soxx_spx_ratio = soxx - spx
    ratio_risk = 0
    if soxx_spx_ratio > 2:
        ratio_risk = 2
    elif soxx_spx_ratio > 1:
        ratio_risk = 1

    # --- 4. AI sentiment ---
    ai_news = news_df[
        news_df["headline"].str.contains(
            "AI|artificial intelligence|chip|GPU|Nvidia|semiconductor|OpenAI",
            case=False, na=False
        )
    ]

    ai_sent = ai_news["sentiment"].mean() if len(ai_news) > 0 else 0

    sentiment_risk = 0
    if ai_sent > 0.35:
        sentiment_risk = 2
    elif ai_sent > 0.15:
        sentiment_risk = 1

    # --- 5. AI hype trend (7-day) ---
    trend_risk = 0
    if len(ai_hype_df) >= 7:
        last7 = ai_hype_df.tail(7)["count"].sum()
        prev7 = ai_hype_df.tail(14).head(7)["count"].sum() if len(ai_hype_df) >= 14 else 0

        if last7 > prev7 * 1.5:
            trend_risk = 2
        elif last7 > prev7 * 1.2:
            trend_risk = 1

    # --- Final score ---
    ai_bubble_score = vol_risk + breadth_risk + ratio_risk + sentiment_risk + trend_risk
    ai_bubble_score = min(ai_bubble_score, 5)

    # --- Label & color ---
    if ai_bubble_score >= 4:
        label = "HIGH"
        color = "#FF4136"
    elif ai_bubble_score >= 2:
        label = "MEDIUM"
        color = "#FFDC00"
    else:
        label = "LOW"
        color = "#00FF41"

    # --- Visual hype meter ---
    meter_blocks = int(ai_bubble_score)
    meter = "█" * meter_blocks + "░" * (5 - meter_blocks)

    st.markdown(
        f"<h4 style='color:{color};'>AI Bubble Risk: {label} ({ai_bubble_score}/5)</h4>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"<pre style='color:{color}; font-size:18px;'>[{meter}]</pre>",
        unsafe_allow_html=True
    )

    # --- Narrative ---
    if label == "HIGH":
        st.markdown(
            "AI‑linked markets show signs of overheating. Semiconductor momentum, narrow breadth, "
            "and rising AI‑themed sentiment point to bubble‑like conditions."
        )
    elif label == "MEDIUM":
        st.markdown(
            "AI enthusiasm is elevated. Semiconductor strength and increasing AI‑related headlines "
            "suggest growing optimism, but not yet extreme froth."
        )
    else:
        st.markdown(
            "AI‑related market activity appears healthy, with balanced sentiment and no major signs "
            "of speculative excess."
        )

   

    # ---------- GPT COMMENTARY ----------
    st.markdown("### GPT Risk Commentary")

    st.markdown("<div class='card'>", unsafe_allow_html=True)

    if gpt and "summary" in gpt:
        st.markdown(
            f"""
            <p style='color:#DDDDDD;'>
            Markets are currently exhibiting a <b>{risk_label}</b> tone across
            equities, volatility, FX, and commodities. Current macro positioning
            suggests investors remain focused on cross-asset risk transmission,
            volatility dynamics, and geopolitical headlines.
            </p>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<p style='color:#AAAAAA;'>No GPT risk commentary available.</p>",
            unsafe_allow_html=True
        )

    st.markdown("</div>", unsafe_allow_html=True)
# =========================================================
# =================== COMMODITIES TAB =====================
# =========================================================

with tabs[2]:

    # ---------- COMMODITIES PANEL ----------
    st.markdown("### Commodities")

    commodity_names = [
        "Brent Crude",
        "WTI Crude",
        "Natural Gas",
        "Gold",
        "Silver",
        "Copper",
        "Corn",
        "Wheat"
    ]

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

                st.markdown(
                    f"<div class='big-number'>{price}</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    f"<div style='font-size:16px; font-weight:bold; color:{color};'>{change_str}</div>",
                    unsafe_allow_html=True
                )

            else:
                st.markdown(
                    "<div class='big-number'>N/A</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    "<div style='font-size:16px;'>N/A</div>",
                    unsafe_allow_html=True
                )

            st.markdown("</div>", unsafe_allow_html=True)

    # ---------- COMMODITY COMMENTARY ----------
    st.markdown("### Commodity Commentary")

    try:
        news_df = pd.read_csv("ai_news_output.csv")
        news_list = news_df.to_dict(orient="records")
    except:
        news_list = []

    themes = extract_commodity_themes(news_list)
    sent = themes["sentiment"]

    commentary = []

    # ---------- OIL ----------
    oil = prices["Brent Crude"]["change"]

    if oil is not None:

        if oil > 1:

            if themes["oil_supply"]:
                commentary.append(
                    "Oil is climbing as supply-side headlines — including OPEC+ discipline and production constraints — support prices."
                )

            elif themes["oil_geopolitics"]:
                commentary.append(
                    "Oil is higher as geopolitical tensions in key producing regions add a risk premium."
                )

            elif themes["oil_demand"]:
                commentary.append(
                    "Oil is gaining on stronger demand expectations reflected in travel and consumption-related headlines."
                )

            else:
                commentary.append(
                    "Oil is moving higher despite limited headline catalysts, suggesting technical or positioning-driven flows."
                )

        elif oil < -1:

            if themes["oil_supply"]:
                commentary.append(
                    "Oil is falling even as supply headlines remain tight, indicating demand concerns are dominating."
                )

            elif themes["oil_demand"]:
                commentary.append(
                    "Oil is under pressure as headlines point to softer demand expectations."
                )

            else:
                commentary.append(
                    "Oil is weakening with little headline support, likely reflecting easing supply constraints or a broader macro risk-off tone."
                )

        else:
            commentary.append(
                "Oil is relatively stable, with no dominant supply or demand headlines driving direction."
            )

    # ---------- COPPER ----------
    copper = prices["Copper"]["change"]

    if copper is not None:

        if themes["china"]:
            commentary.append(
                "Copper is reacting to China-related headlines, with industrial activity remaining a key demand driver."
            )

        elif copper > 1:
            commentary.append(
                "Copper is firm, potentially reflecting improved global manufacturing sentiment."
            )

        elif copper < -1:
            commentary.append(
                "Copper is softer, hinting at weaker industrial demand or cautious macro sentiment."
            )

    # ---------- GOLD ----------
    gold = prices["Gold"]["change"]

    if gold is not None:

        if themes["inflation"]:
            commentary.append(
                "Gold is responding to inflation and rate-related headlines, which continue to shape safe-haven demand."
            )

        elif gold > 1:
            commentary.append(
                "Gold is gaining as investors seek safety amid broader macro uncertainty."
            )

        elif gold < -1:
            commentary.append(
                "Gold is easing, suggesting reduced safe-haven demand or firmer yields."
            )

    # ---------- AGRICULTURE ----------
    if themes["weather"]:
        commentary.append(
            "Weather-related headlines are affecting agricultural markets, raising concerns over crop yields."
        )

    if themes["ag_supply"]:
        commentary.append(
            "Grain supply headlines are impacting wheat and corn, reflecting geopolitical or export-related risks."
        )

    # ---------- SENTIMENT ----------
    if sent > 0.25:
        commentary.append(
            "Overall news sentiment is constructive, offering support across cyclical commodities."
        )

    elif sent < -0.25:
        commentary.append(
            "Negative news sentiment is weighing on risk-sensitive commodities."
        )

    # ---------- FALLBACK ----------
    if not commentary:
        commentary.append(
            "Commodity markets are steady, with no major headline-driven themes dominating today."
        )

    # ---------- DISPLAY ----------
    for line in commentary:
        st.markdown(f"- {line}")

with tabs[3]:
    render_sp500_tab()
    

# ══════════════════════════════════════════════
# FLOW TRADING — CONSTANTS & HELPER FUNCTIONS
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

@st.cache_data(ttl=300)
def get_vix():
    """Fetch the VIX index level. Fallback to 20 if unavailable."""
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(period="2d")
        if hist is not None and len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 20.0  # normal volatility fallback
def get_dynamic_spread_bps(base_spread_bps: float) -> float:
    """
    Volatility-linked spread model:
    Spread widens linearly with VIX.
    VIX = 20 → normal spreads
    VIX = 40 → spreads double
    """
    vix = get_vix()
    multiplier = 1 + (vix / 20)
    return base_spread_bps * multiplier


def add_client_trade(asset_label: str, side: str, notional: float):
    asset = FLOW_ASSETS[asset_label]

    # --- Volatility-linked spread ---
    base_spread_bps = asset["spread_bps"]
    spread_bps = get_dynamic_spread_bps(base_spread_bps)

    spread_earned = notional * (spread_bps / 10_000)
    st.session_state["pnl"]["spread_pnl"] += spread_earned

    # Inventory update
    direction = -1 if side == "Buy" else 1
    inv = st.session_state["inventory"]
    inv[asset_label] = inv.get(asset_label, 0.0) + direction * notional

    # Log the trade
    st.session_state["flow_trades"].append({
        "asset": asset_label,
        "client_side": side,
        "notional": notional,
        "spread_earned": round(spread_earned, 2),
        "spread_bps_used": round(spread_bps, 2),
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

    # --- Volatility-linked spread display ---
        current_vix = get_vix()
        st.metric("VIX (Volatility Index)", f"{current_vix:.2f}")

        base_spread = FLOW_ASSETS[asset_label]["spread_bps"]
        dyn_spread = get_dynamic_spread_bps(base_spread)
        st.metric("Current Spread (bps)", f"{dyn_spread:.2f}")

    # --- Buttons ---
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

    st.markdown("---")

    if st.button("🔄 Reset Simulation", type="secondary"):
        st.session_state["inventory"]   = {}
        st.session_state["flow_trades"] = []
        st.session_state["hedge_trades"]= []
        st.session_state["pnl"] = {
            "spread_pnl":    0.0,
            "hedge_pnl":     0.0,
            "inventory_pnl": 0.0,
        }
        st.success("Simulation reset.")
        st.rerun()

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

        


with tabs[4]:
    render_flow_trading_tab()