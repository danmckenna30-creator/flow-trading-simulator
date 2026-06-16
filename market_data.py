import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

TICKERS = {
    "S&P 500": "^GSPC",
    "FTSE 100": "^FTSE",

    # Yields (ETF proxies)
    "US 2Y Yield": "SHY",
    "US 10Y Yield": "IEF",
    "US 30Y Yield": "TLT",

    # FX
    "GBPUSD": "GBPUSD=X",
    "EURUSD": "EURUSD=X",
    "USDJPY": "JPY=X",


    # Commodities
    "Brent Crude": "BZ=F",
    "WTI Crude": "CL=F",
    "Natural Gas": "NG=F",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Copper": "HG=F",
    "Corn": "ZC=F",
    "Wheat": "ZW=F",

    # Volatility
    "VIX": "^VIX"
}


@st.cache_data(ttl=30)
def get_market_data():
    data = {}

    for name, ticker in TICKERS.items():
        try:
            # Get price + % change
            price, change = get_price_and_change(ticker)

            # Store price + change for all normal tickers
            data[name] = {"price": price, "change": change}

            # Override yields with fixed estimates
            if "Yield" in name:
                if name == "US 2Y Yield":
                    yield_est = 4.5
                elif name == "US 10Y Yield":
                    yield_est = 4.3
                elif name == "US 30Y Yield":
                    yield_est = 4.5

                data[name] = {"price": yield_est, "change": None}

        except Exception:
            data[name] = {"price": None, "change": None}

    return data


def get_yield_curve():
    """
    Returns approximate yields for 2Y, 5Y, 10Y, 30Y.
    Uses ETF proxies for stability.
    """
    curve = {
        "2Y": 4.50,
        "5Y": 4.35,
        "10Y": 4.30,
        "30Y": 4.45
    }
    return curve


def get_price_and_change(ticker):
    """
    Robust price fetcher for equities, FX, and futures.
    Tries multiple periods and handles empty Yahoo responses.
    """
    try:
        tk = yf.Ticker(ticker)

        # Try multiple periods (Yahoo often returns empty for futures/FX)
        for period in ["2d", "5d", "1mo"]:
            hist = tk.history(period=period)

            if hist is not None and len(hist) >= 2:
                prev_close = hist["Close"].iloc[-2]
                last_close = hist["Close"].iloc[-1]

                pct_change = ((last_close - prev_close) / prev_close) * 100
                return round(float(last_close), 4), round(float(pct_change), 2)

        # If still empty, try "Close" from fast_info
        try:
            last_price = tk.fast_info["last_price"]
            prev_close = tk.fast_info["previous_close"]
            pct_change = ((last_price - prev_close) / prev_close) * 100
            return round(float(last_price), 4), round(float(pct_change), 2)
        except:
            pass

        return None, None

    except Exception:
        return None, None

def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    tables = pd.read_html(response.text)
    return tables[0]["Symbol"].tolist()

@st.cache_data(ttl=3600)
def get_advance_decline_line():
    """
    Fetches a representative sample of S&P 500 stocks individually (most reliable),
    computes daily advances/declines, and returns the cumulative AD line.
    """
    sample_tickers = [
        "AAPL","MSFT","AMZN","NVDA","GOOGL","META","TSLA","BRK-B","UNH","JPM",
        "V","XOM","LLY","JNJ","MA","AVGO","PG","HD","MRK","CVX",
        "ABBV","PEP","KO","COST","WMT","BAC","MCD","CRM","ACN","TMO",
        "CSCO","ABT","LIN","DHR","NFLX","AMD","TXN","NEE","PM","ORCL",
        "QCOM","HON","UPS","MS","GS","AMGN","INTU","RTX","CAT","ELV",
        "SBUX","ISRG","GE","AMAT","AXP","BLK","DE","ADI","MDLZ","SYK",
        "GILD","VRTX","CB","PLD","CI","MO","REGN","SCHW","ZTS","SO",
        "DUK","CME","BSX","BMY","TGT","LRCX","AON","ITW","WM","SHW",
        "PNC","NOC","MMM","USB","EOG","OXY","APD","EMR","FDX","MCK",
        "HCA","ICE","EW","NSC","AIG","CL","DXCM","IDXX","KLAC","HUM"
    ]

    all_series = []
    for ticker in sample_tickers:
        try:
            hist = yf.Ticker(ticker).history(period="6mo", auto_adjust=True)
            if hist is not None and len(hist) >= 10:
                s = hist["Close"].dropna()
                s.name = ticker
                all_series.append(s)
        except Exception:
            continue

    if not all_series:
        return [], []

    combined = pd.concat(all_series, axis=1).dropna(how="all")
    combined = combined.dropna(axis=1, how="all")

    if combined.shape[1] < 5:
        return [], []

    daily_diff = combined.diff().iloc[1:]
    advances = (daily_diff > 0).sum(axis=1)
    declines = (daily_diff < 0).sum(axis=1)
    ad_line = (advances - declines).cumsum()

    return list(ad_line.index), list(ad_line.values)

def get_rsp_spy_ratio():
    rsp = yf.Ticker("RSP").history(period="6mo")["Close"]
    spy = yf.Ticker("SPY").history(period="6mo")["Close"]

    # Avoid division errors if data missing
    if len(rsp) == 0 or len(spy) == 0:
        return None

    ratio = (rsp.iloc[-1] / spy.iloc[-1])
    return round(float(ratio), 4)
@st.cache_data(ttl=3600)
def compute_sp500_breadth():
    # Load tickers from GitHub (stable)
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
    df = pd.read_csv(url)
    tickers = df["Symbol"].tolist()

    # Batch download
    hist = yf.download(tickers, period="1y", group_by="ticker", threads=True)

    above20 = above50 = above200 = 0
    total = len(tickers)

    for t in tickers:
        try:
            prices = hist[t]["Close"].dropna()
            if len(prices) < 200:
                continue

            price = prices.iloc[-1]
            ma20 = prices.rolling(20).mean().iloc[-1]
            ma50 = prices.rolling(50).mean().iloc[-1]
            ma200 = prices.rolling(200).mean().iloc[-1]

            if price > ma20: above20 += 1
            if price > ma50: above50 += 1
            if price > ma200: above200 += 1

        except:
            continue

    return {
        "20dma": round(above20 / total * 100, 1),
        "50dma": round(above50 / total * 100, 1),
        "200dma": round(above200 / total * 100, 1)
    }

@st.cache_data(ttl=1800)
def get_sector_breadth():
    """
    Uses the 11 S&P 500 sector ETFs to compute a breadth/AD proxy.
    Fast and reliable — no rate limiting issues.
    """
    sector_etfs = {
        "XLK": "Technology",
        "XLF": "Financials",
        "XLV": "Health Care",
        "XLY": "Consumer Disc.",
        "XLP": "Consumer Staples",
        "XLE": "Energy",
        "XLI": "Industrials",
        "XLB": "Materials",
        "XLRE": "Real Estate",
        "XLU": "Utilities",
        "XLC": "Comm. Services"
    }

    all_series = []
    sector_data = {}

    for ticker, name in sector_etfs.items():
        try:
            hist = yf.Ticker(ticker).history(period="6mo", auto_adjust=True)
            if hist is not None and len(hist) >= 10:
                s = hist["Close"].dropna()
                s.name = ticker
                all_series.append(s)
                # Store latest change for heatmap
                if len(s) >= 2:
                    change = ((s.iloc[-1] - s.iloc[-2]) / s.iloc[-2]) * 100
                    sector_data[name] = round(float(change), 2)
        except Exception:
            continue

    if not all_series:
        return [], [], {}

    combined = pd.concat(all_series, axis=1).dropna(how="all")
    daily_diff = combined.diff().iloc[1:]
    advances = (daily_diff > 0).sum(axis=1)
    declines = (daily_diff < 0).sum(axis=1)
    ad_line = (advances - declines).cumsum()

    return list(ad_line.index), list(ad_line.values), sector_data


def render_sp500_tab():
    """S&P 500 Health Dashboard — Breadth, Sector Rotation, Valuation & AI Summary."""
    st.markdown("## S&P 500 Health Dashboard")
    st.caption("A full picture of S&P 500 market internals — breadth, sector rotation, and valuation. These indicators tell you how healthy the rally really is beneath the headline number.")

    with st.spinner("Loading S&P 500 data..."):
        dates, ad_values, sector_data = get_sector_breadth()

    # ── SECTION 1: BREADTH ──────────────────────────────────────
    st.markdown("### 📊 Section 1 — Market Breadth")
    st.caption("Breadth measures how many stocks are participating in the market move. A rising index driven by only a few stocks is fragile. Broad participation is healthy and sustainable.")
    st.markdown("")

    # RSP/SPY ratio — equal weight vs market cap weight
    try:
        rsp_hist = yf.Ticker("RSP").history(period="3mo")["Close"].dropna()
        spy_hist = yf.Ticker("SPY").history(period="3mo")["Close"].dropna()
        if len(rsp_hist) >= 2 and len(spy_hist) >= 2:
            rsp_spy_current = rsp_hist.iloc[-1] / spy_hist.iloc[-1]
            rsp_spy_start   = rsp_hist.iloc[0]  / spy_hist.iloc[0]
            rsp_spy_change  = ((rsp_spy_current - rsp_spy_start) / rsp_spy_start) * 100
            rsp_spy_today   = ((rsp_hist.iloc[-1] - rsp_hist.iloc[-2]) / rsp_hist.iloc[-2]) * 100
            spy_today       = ((spy_hist.iloc[-1] - spy_hist.iloc[-2]) / spy_hist.iloc[-2]) * 100
            breadth_gap     = rsp_spy_today - spy_today
        else:
            rsp_spy_change = breadth_gap = rsp_spy_today = spy_today = 0
    except Exception:
        rsp_spy_change = breadth_gap = rsp_spy_today = spy_today = 0

    # Advancing/declining count from sector data
    advancing = sum(1 for v in sector_data.values() if v > 0) if sector_data else 0
    declining = sum(1 for v in sector_data.values() if v < 0) if sector_data else 0
    unchanged = (len(sector_data) - advancing - declining) if sector_data else 0
    breadth_pct = round(advancing / len(sector_data) * 100) if sector_data else 0

    if breadth_pct >= 70:   breadth_health, breadth_color = "HEALTHY",  "#00ff88"
    elif breadth_pct >= 50: breadth_health, breadth_color = "MODERATE", "#FFDC00"
    else:                   breadth_health, breadth_color = "NARROW",   "#ff4d4d"

    rsp_color = "#00ff88" if rsp_spy_change > 0 else "#ff4d4d"

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        st.markdown(f"<div class='card'><div class='label'>Breadth Health</div><div class='big-number' style='color:{breadth_color};'>{breadth_health}</div><div class='label' style='font-size:10px;'>{breadth_pct}% sectors advancing</div></div>", unsafe_allow_html=True)
    with b2:
        st.markdown(f"<div class='card'><div class='label'>Advancing Sectors</div><div class='big-number' style='color:#00ff88;'>{advancing}</div></div>", unsafe_allow_html=True)
    with b3:
        st.markdown(f"<div class='card'><div class='label'>Declining Sectors</div><div class='big-number' style='color:#ff4d4d;'>{declining}</div></div>", unsafe_allow_html=True)
    with b4:
        st.markdown(f"<div class='card'><div class='label'>RSP/SPY (3mo)</div><div class='big-number' style='color:{rsp_color};'>{rsp_spy_change:+.2f}%</div><div class='label' style='font-size:10px;'>Equal vs market cap wt</div></div>", unsafe_allow_html=True)

    st.caption("**Breadth Health** = % of sectors advancing today. **RSP/SPY ratio** compares the equal-weight S&P 500 (RSP) to the market-cap-weighted S&P 500 (SPY). If RSP is underperforming SPY, it means large-cap mega stocks are carrying the index — a concentration warning.")
    st.markdown("")

    # AD Line chart
    st.markdown("#### Advance / Decline Line (6 months)")
    if dates and ad_values:
        fig_ad = px.line(
            x=dates, y=ad_values,
            labels={"x": "Date", "y": "Cumulative AD"},
            template="plotly_dark"
        )
        fig_ad.update_traces(line=dict(color="#00c3ff", width=2))
        fig_ad.add_hline(y=0, line_dash="dash", line_color="#555555")
        fig_ad.update_layout(
            height=300, margin=dict(l=40, r=40, t=20, b=40),
            xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#333333"),
            title="Sector Advance/Decline Line — Rising = Broad Participation"
        )
        st.plotly_chart(fig_ad, use_container_width=True)
        st.caption("A rising AD line = more sectors advancing than declining over time — healthy, broad-based rally. A falling AD line while the index rises = only a few stocks driving the move, the rest are lagging. This divergence often precedes a correction.")
    else:
        st.warning("Could not load AD line data.")

    st.markdown("---")

    # ── SECTION 2: SECTOR ROTATION ──────────────────────────────
    st.markdown("### 🔄 Section 2 — Sector Rotation")
    st.caption("Sector rotation shows where money is flowing within the S&P 500. Different sectors lead at different points in the economic cycle — identifying rotation early is one of the most valuable skills in flow trading.")
    st.markdown("")

    if sector_data:
        sectors  = list(sector_data.keys())
        changes  = list(sector_data.values())
        sorted_sectors = sorted(zip(sectors, changes), key=lambda x: x[1], reverse=True)

        # Sector performance bar chart
        s_names  = [x[0] for x in sorted_sectors]
        s_vals   = [x[1] for x in sorted_sectors]
        s_colors = ["#00ff88" if v > 0 else "#ff4d4d" for v in s_vals]

        fig_sec = go.Figure(go.Bar(
            x=s_names, y=s_vals,
            marker_color=s_colors,
            text=[f"{v:+.2f}%" for v in s_vals],
            textposition="outside"
        ))
        fig_sec.update_layout(
            template="plotly_dark", height=320,
            title="Sector Performance Today (Best to Worst)",
            yaxis_title="% Change",
            margin=dict(l=40, r=40, t=50, b=60),
            yaxis=dict(gridcolor="#333"),
            xaxis=dict(showgrid=False, tickangle=-30)
        )
        st.plotly_chart(fig_sec, use_container_width=True)

        # Rotation signal
        top_sector    = sorted_sectors[0]
        bottom_sector = sorted_sectors[-1]

        defensive = ["Consumer Staples", "Utilities", "Health Care"]
        cyclical  = ["Technology", "Consumer Disc.", "Financials", "Industrials", "Materials"]

        top_is_defensive = top_sector[0] in defensive
        top_is_cyclical  = top_sector[0] in cyclical

        if top_is_cyclical and top_sector[1] > 0.5:
            rotation_signal, rot_color = "RISK-ON ROTATION — Cyclicals leading", "#00ff88"
            rotation_meaning = "Money is flowing into growth-sensitive sectors. Clients are adding risk. Expect buying in tech, financials, and industrials."
        elif top_is_defensive and top_sector[1] > 0:
            rotation_signal, rot_color = "DEFENSIVE ROTATION — Risk-off shift", "#ff4d4d"
            rotation_meaning = "Money is rotating into safe sectors. This often signals institutional concern about the outlook — watch for broader selling."
        else:
            rotation_signal, rot_color = "MIXED — No clear rotation signal", "#FFDC00"
            rotation_meaning = "No dominant rotation theme today. Markets are in a wait-and-see mode with mixed signals across sectors."

        st.markdown(f"<div class='card' style='border-left: 3px solid {rot_color}; margin-bottom:8px;'><div style='color:{rot_color}; font-weight:bold;'>🔄 {rotation_signal}</div><div style='color:#DDDDDD; font-size:13px; margin-top:4px;'>{rotation_meaning}</div></div>", unsafe_allow_html=True)

        # Sector heatmap
        st.markdown("#### Sector Heatmap")
        fig_heat = go.Figure(go.Heatmap(
            z=[changes], x=sectors, y=["% Change"],
            colorscale=[[0.0,"#ff4d4d"],[0.5,"#1a1a2e"],[1.0,"#00ff88"]],
            zmid=0,
            text=[[f"{v:+.2f}%" for v in changes]],
            texttemplate="%{text}", showscale=True
        ))
        fig_heat.update_layout(
            template="plotly_dark", height=150,
            margin=dict(l=40, r=40, t=10, b=60)
        )
        st.plotly_chart(fig_heat, use_container_width=True)
        st.caption("**Cyclical sectors** (Tech, Financials, Consumer Disc, Industrials) leading = risk-on, growth expectations rising. **Defensive sectors** (Utilities, Staples, Health Care) leading = risk-off, investors seeking safety. **Energy** leading alone = oil-specific story, not a broad market signal.")

    st.markdown("---")

    # ── SECTION 3: VALUATION ────────────────────────────────────
    st.markdown("### 💰 Section 3 — Valuation Pulse")
    st.caption("Valuation shows whether the S&P 500 is cheap or expensive relative to history. An expensive market isn't necessarily about to fall — but it leaves less margin for error if earnings disappoint.")
    st.markdown("")

    @st.cache_data(ttl=3600)
    def get_valuation_data():
        try:
            spy = yf.Ticker("SPY")
            spy_hist = spy.history(period="1y")["Close"].dropna()
            if len(spy_hist) < 2:
                return None

            spy_price    = float(spy_hist.iloc[-1])
            spy_52w_high = float(spy_hist.max())
            spy_52w_low  = float(spy_hist.min())
            spy_ytd      = float(((spy_hist.iloc[-1] - spy_hist.iloc[0]) / spy_hist.iloc[0]) * 100)
            spy_from_high= float(((spy_price - spy_52w_high) / spy_52w_high) * 100)

            # 50d and 200d moving averages
            ma50  = float(spy_hist.rolling(50).mean().iloc[-1])  if len(spy_hist) >= 50  else None
            ma200 = float(spy_hist.rolling(200).mean().iloc[-1]) if len(spy_hist) >= 200 else None

            return {
                "price":      round(spy_price, 2),
                "52w_high":   round(spy_52w_high, 2),
                "52w_low":    round(spy_52w_low, 2),
                "ytd":        round(spy_ytd, 2),
                "from_high":  round(spy_from_high, 2),
                "ma50":       round(ma50, 2) if ma50 else None,
                "ma200":      round(ma200, 2) if ma200 else None,
                "above_50d":  spy_price > ma50 if ma50 else None,
                "above_200d": spy_price > ma200 if ma200 else None,
            }
        except Exception:
            return None

    val = get_valuation_data()

    if val:
        v1, v2, v3, v4 = st.columns(4)
        with v1:
            ytd_color = "#00ff88" if val["ytd"] > 0 else "#ff4d4d"
            st.markdown(f"<div class='card'><div class='label'>SPY YTD Return</div><div class='big-number' style='color:{ytd_color};'>{val['ytd']:+.1f}%</div></div>", unsafe_allow_html=True)
        with v2:
            fh_color = "#FFDC00" if val["from_high"] > -5 else "#ff4d4d"
            st.markdown(f"<div class='card'><div class='label'>From 52W High</div><div class='big-number' style='color:{fh_color};'>{val['from_high']:+.1f}%</div></div>", unsafe_allow_html=True)
        with v3:
            ma50_color = "#00ff88" if val["above_50d"] else "#ff4d4d"
            ma50_label = "✅ Above 50D MA" if val["above_50d"] else "❌ Below 50D MA"
            st.markdown(f"<div class='card'><div class='label'>50-Day MA</div><div style='color:{ma50_color}; font-weight:bold; font-size:14px;'>{ma50_label}</div><div class='label'>{val['ma50']}</div></div>", unsafe_allow_html=True)
        with v4:
            ma200_color = "#00ff88" if val["above_200d"] else "#ff4d4d"
            ma200_label = "✅ Above 200D MA" if val["above_200d"] else "❌ Below 200D MA"
            st.markdown(f"<div class='card'><div class='label'>200-Day MA</div><div style='color:{ma200_color}; font-weight:bold; font-size:14px;'>{ma200_label}</div><div class='label'>{val['ma200']}</div></div>", unsafe_allow_html=True)

        # SPY 1-year price chart with MAs
        @st.cache_data(ttl=3600)
        def get_spy_chart():
            try:
                hist = yf.Ticker("SPY").history(period="1y")["Close"].dropna()
                return hist
            except Exception:
                return None

        spy_hist_chart = get_spy_chart()
        if spy_hist_chart is not None and len(spy_hist_chart) >= 50:
            dates_chart = [str(d.date()) for d in spy_hist_chart.index]
            closes      = list(spy_hist_chart.values)
            ma50_line   = list(spy_hist_chart.rolling(50).mean().values)
            ma200_line  = list(spy_hist_chart.rolling(200).mean().values) if len(spy_hist_chart) >= 200 else None

            fig_spy = go.Figure()
            fig_spy.add_trace(go.Scatter(
                x=dates_chart, y=closes, mode="lines",
                name="SPY", line=dict(color="#00c3ff", width=2)
            ))
            fig_spy.add_trace(go.Scatter(
                x=dates_chart, y=ma50_line, mode="lines",
                name="50D MA", line=dict(color="#FFDC00", width=1.5, dash="dash")
            ))
            if ma200_line:
                fig_spy.add_trace(go.Scatter(
                    x=dates_chart, y=ma200_line, mode="lines",
                    name="200D MA", line=dict(color="#ff4d4d", width=1.5, dash="dot")
                ))
            fig_spy.update_layout(
                template="plotly_dark", height=320,
                title="SPY — 1 Year Price with 50D & 200D Moving Averages",
                margin=dict(l=40, r=40, t=50, b=40),
                xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="#333"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_spy, use_container_width=True)
            st.caption("**Blue** = SPY price. **Yellow dashed** = 50-day moving average (short-term trend). **Red dotted** = 200-day moving average (long-term trend). Price above both MAs = bullish. Price crossing below the 200D MA is a major warning signal — often triggers significant institutional selling.")

        # 52-week range bar
        if val["52w_low"] and val["52w_high"]:
            pct_in_range = (val["price"] - val["52w_low"]) / (val["52w_high"] - val["52w_low"]) * 100
            st.markdown(f"**52-Week Range:** ${val['52w_low']:,.0f} ← SPY at ${val['price']:,.0f} ({pct_in_range:.0f}% of range) → ${val['52w_high']:,.0f}")
            st.progress(min(pct_in_range / 100, 1.0))
            st.caption("The progress bar shows where SPY sits within its 52-week range. Near the top (right) = strong momentum but potentially extended. Near the bottom (left) = either a buying opportunity or a deteriorating trend.")
    else:
        st.warning("Could not load valuation data.")

    st.markdown("---")

    # ── SECTION 4: AI HEALTH SUMMARY ────────────────────────────
    st.markdown("### 🤖 Section 4 — AI Market Health Summary")
    st.caption("GPT synthesises breadth, rotation, and valuation into a single trader-ready assessment of S&P 500 market health.")

    if st.button("🔄 Generate S&P 500 Health Summary", key="sp500_health_btn"):
        with st.spinner("Analysing S&P 500 health..."):
            try:
                from gpt_layer import call_gpt_prose

                val_str = f"SPY YTD: {val['ytd']:+.1f}%, From 52W High: {val['from_high']:+.1f}%, Above 50D MA: {val['above_50d']}, Above 200D MA: {val['above_200d']}" if val else "Valuation data unavailable"
                top_3   = [f"{s[0]}: {s[1]:+.2f}%" for s in sorted_sectors[:3]] if sector_data else []
                bot_3   = [f"{s[0]}: {s[1]:+.2f}%" for s in sorted_sectors[-3:]] if sector_data else []

                prompt = f"""You are a senior equity strategist writing a morning health check on the S&P 500.

BREADTH DATA:
- Sectors advancing today: {advancing} of {len(sector_data) if sector_data else 11}
- Breadth health: {breadth_health}
- RSP/SPY 3-month change: {rsp_spy_change:+.2f}% (equal weight vs market cap)
- AD line trend: {"Rising" if ad_values and len(ad_values) > 1 and ad_values[-1] > ad_values[-10] else "Falling"}

SECTOR ROTATION:
- Top sectors today: {", ".join(top_3)}
- Bottom sectors today: {", ".join(bot_3)}
- Rotation signal: {rotation_signal if sector_data else "Unknown"}

VALUATION:
- {val_str}

Write a concise 4-5 sentence S&P 500 health assessment covering:
1. Whether market breadth is healthy or concerning and why
2. What the sector rotation tells us about investor sentiment
3. What the valuation/technical picture tells us
4. One specific actionable observation for a flow trader

Bloomberg style. Professional and direct. Plain prose only."""

                summary = call_gpt_prose(prompt)
                st.session_state["sp500_summary"] = summary or "Could not generate summary — check OpenAI key."
            except Exception as e:
                st.session_state["sp500_summary"] = f"Error: {e}"

    summary_text = st.session_state.get("sp500_summary", "Click above to generate an AI assessment of S&P 500 market health.")
    st.markdown(f"<div class='card' style='line-height:1.7; color:#DDDDDD;'>{summary_text}</div>", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def get_spot_price(ticker: str):
    tk = yf.Ticker(ticker)
    hist = tk.history(period="2d")
    if hist is None or len(hist) == 0:
        return None
    return float(hist["Close"].iloc[-1])

@st.cache_data(ttl=300)
def get_vix():
    tk = yf.Ticker("^VIX")
    hist = tk.history(period="2d")
    if hist is None or len(hist) == 0:
        return 20  # fallback normal vol
    return float(hist["Close"].iloc[-1])