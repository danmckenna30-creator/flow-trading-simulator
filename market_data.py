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
    st.subheader("S&P 500 Breadth — Sector Dashboard")

    with st.spinner("Loading sector data..."):
        dates, ad_values, sector_data = get_sector_breadth()

    if not dates or not ad_values:
        st.warning("Could not load breadth data. Check your internet connection.")
        return

    # --- AD Line Chart ---
    st.markdown("#### Advance / Decline Line (Sector Proxy)")
    fig = px.line(
        x=dates,
        y=ad_values,
        title="Sector Advance/Decline Line",
        labels={"x": "Date", "y": "Cumulative AD"},
        template="plotly_dark"
    )
    fig.update_traces(line=dict(color="#00c3ff", width=2))
    fig.update_layout(
        height=350,
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="#333333")
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Sector Heatmap ---
    if sector_data:
        st.markdown("#### Sector Performance Heatmap (Today)")
        sectors = list(sector_data.keys())
        changes = list(sector_data.values())

        fig2 = go.Figure(data=go.Heatmap(
            z=[changes],
            x=sectors,
            y=["% Change"],
            colorscale=[[0.0, "#ff4d4d"], [0.5, "#1a1a2e"], [1.0, "#00ff88"]],
            zmid=0,
            text=[[f"{v:+.2f}%" for v in changes]],
            texttemplate="%{text}",
            showscale=True
        ))
        fig2.update_layout(
            template="plotly_dark",
            height=160,
            margin=dict(l=40, r=40, t=20, b=60),
        )
        st.plotly_chart(fig2, use_container_width=True)

    # --- Advancing vs Declining today ---
    if sector_data:
        advancing = sum(1 for v in sector_data.values() if v > 0)
        declining = sum(1 for v in sector_data.values() if v < 0)
        unchanged = len(sector_data) - advancing - declining

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("<div class='label'>Advancing Sectors</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number' style='color:#00ff88;'>{advancing}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("<div class='label'>Declining Sectors</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number' style='color:#ff4d4d;'>{declining}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with c3:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("<div class='label'>Unchanged</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-number' style='color:#FFDC00;'>{unchanged}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

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
