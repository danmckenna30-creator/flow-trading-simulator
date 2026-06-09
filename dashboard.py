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
    "S&P 500 (SPY)":       {"ticker":"SPY",      "spread_bps":0.5,  "hedge_ticker":"SPY",  "category":"Equities",    "description":"US large-cap equity index",    "liquidity":50_000_000, "base_vol":0.012},
    "NASDAQ (QQQ)":        {"ticker":"QQQ",      "spread_bps":0.5,  "hedge_ticker":"QQQ",  "category":"Equities",    "description":"US tech-heavy equity index",   "liquidity":30_000_000, "base_vol":0.016},
    "FTSE 100 (ISF)":      {"ticker":"ISF.L",    "spread_bps":1.0,  "hedge_ticker":"EWU",  "category":"Equities",    "description":"UK large-cap equity index",    "liquidity":10_000_000, "base_vol":0.011},
    "EUR/USD":             {"ticker":"EURUSD=X", "spread_bps":0.3,  "hedge_ticker":"FXE",  "category":"FX",          "description":"Euro vs US Dollar",            "liquidity":100_000_000,"base_vol":0.006},
    "GBP/USD":             {"ticker":"GBPUSD=X", "spread_bps":0.5,  "hedge_ticker":"FXB",  "category":"FX",          "description":"British Pound vs US Dollar",   "liquidity":60_000_000, "base_vol":0.008},
    "USD/JPY":             {"ticker":"JPY=X",    "spread_bps":0.3,  "hedge_ticker":"FXY",  "category":"FX",          "description":"US Dollar vs Japanese Yen",    "liquidity":80_000_000, "base_vol":0.007},
    "USD/CHF":             {"ticker":"CHF=X",    "spread_bps":0.5,  "hedge_ticker":"FXF",  "category":"FX",          "description":"US Dollar vs Swiss Franc",     "liquidity":40_000_000, "base_vol":0.007},
    "US 2Y (SHY)":         {"ticker":"SHY",      "spread_bps":0.3,  "hedge_ticker":"SHY",  "category":"Rates",       "description":"US 2-year Treasury",           "liquidity":80_000_000, "base_vol":0.003},
    "US 10Y (IEF)":        {"ticker":"IEF",      "spread_bps":0.5,  "hedge_ticker":"IEF",  "category":"Rates",       "description":"US 10-year Treasury",          "liquidity":50_000_000, "base_vol":0.007},
    "US 30Y (TLT)":        {"ticker":"TLT",      "spread_bps":0.8,  "hedge_ticker":"TLT",  "category":"Rates",       "description":"US 30-year Treasury",          "liquidity":30_000_000, "base_vol":0.012},
    "Brent Crude (BZ=F)":  {"ticker":"BZ=F",     "spread_bps":2.0,  "hedge_ticker":"USO",  "category":"Commodities", "description":"Brent crude oil futures",      "liquidity":20_000_000, "base_vol":0.020},
    "Gold (GC=F)":         {"ticker":"GC=F",     "spread_bps":1.0,  "hedge_ticker":"GLD",  "category":"Commodities", "description":"Gold futures",                 "liquidity":25_000_000, "base_vol":0.010},
    "Copper (HG=F)":       {"ticker":"HG=F",     "spread_bps":2.0,  "hedge_ticker":"CPER", "category":"Commodities", "description":"Copper futures",               "liquidity":10_000_000, "base_vol":0.018},
    "Natural Gas (NG=F)":  {"ticker":"NG=F",     "spread_bps":3.0,  "hedge_ticker":"UNG",  "category":"Commodities", "description":"Natural gas futures",          "liquidity":8_000_000,  "base_vol":0.035},
}

HEDGE_THRESHOLD_USD = 500_000
MAX_INVENTORY_USD   = 5_000_000

DEFAULT_RISK_PARAMS = {
    "slippage_min_bps":    1.0,
    "slippage_max_bps":    8.0,
    "latency_ms_min":      100,
    "latency_ms_max":      2000,
    "vol_multiplier":      1.0,
    "impact_factor":       0.10,
    "toxic_flow_prob":     0.20,
    "toxic_jump_bps":      15.0,
    "overnight_vol_scale": 1.5,
}

CLIENT_ORDER_SCENARIOS = [
    {"asset":"S&P 500 (SPY)",      "side":"Buy",  "notional":2_000_000,"reason":"Pension fund rebalancing into equities end of quarter",       "toxic":False},
    {"asset":"S&P 500 (SPY)",      "side":"Sell", "notional":5_000_000,"reason":"Hedge fund reducing equity exposure on macro uncertainty",     "toxic":True},
    {"asset":"Gold (GC=F)",        "side":"Buy",  "notional":1_000_000,"reason":"Safe-haven demand — geopolitical headline risk rising",        "toxic":False},
    {"asset":"Gold (GC=F)",        "side":"Sell", "notional":750_000,  "reason":"Risk-on rotation — client selling gold to buy equities",       "toxic":False},
    {"asset":"EUR/USD",            "side":"Buy",  "notional":3_000_000,"reason":"Corporate FX hedge — European exporter selling USD receipts",  "toxic":False},
    {"asset":"EUR/USD",            "side":"Sell", "notional":2_500_000,"reason":"Speculative short EUR on ECB dovish expectations",             "toxic":True},
    {"asset":"GBP/USD",            "side":"Buy",  "notional":1_500_000,"reason":"UK institutional buying GBP ahead of BoE meeting",            "toxic":False},
    {"asset":"USD/JPY",            "side":"Sell", "notional":2_000_000,"reason":"Risk-off flow — selling USD/JPY (buying Yen safe haven)",      "toxic":True},
    {"asset":"Brent Crude (BZ=F)", "side":"Buy",  "notional":1_000_000,"reason":"Energy company hedging future production",                    "toxic":False},
    {"asset":"Brent Crude (BZ=F)", "side":"Sell", "notional":800_000,  "reason":"Airline hedging fuel costs — selling crude futures",           "toxic":False},
    {"asset":"US 10Y (IEF)",       "side":"Buy",  "notional":4_000_000,"reason":"Flight to safety — institutional buying Treasuries",           "toxic":False},
    {"asset":"US 10Y (IEF)",       "side":"Sell", "notional":2_000_000,"reason":"Duration reduction — cutting bond exposure on inflation fears","toxic":True},
    {"asset":"NASDAQ (QQQ)",       "side":"Buy",  "notional":1_500_000,"reason":"Tech sector rotation — client adding tech exposure",           "toxic":False},
    {"asset":"NASDAQ (QQQ)",       "side":"Sell", "notional":3_000_000,"reason":"AI bubble concern — reducing concentrated tech position",      "toxic":True},
    {"asset":"Copper (HG=F)",      "side":"Buy",  "notional":600_000,  "reason":"China stimulus optimism — buying copper as growth proxy",      "toxic":False},
    {"asset":"US 30Y (TLT)",       "side":"Buy",  "notional":5_000_000,"reason":"Pension buying long duration to match liabilities",            "toxic":False},
]


def _get_risk_params():
    return st.session_state.get("risk_params", DEFAULT_RISK_PARAMS.copy())


def init_flow_state():
    defaults = {
        "inventory":    {},
        "flow_trades":  [],
        "hedge_trades": [],
        "risk_params":  DEFAULT_RISK_PARAMS.copy(),
        "pnl": {
            "spread_pnl":    0.0,
            "slippage_pnl":  0.0,
            "impact_pnl":    0.0,
            "inventory_pnl": 0.0,
            "toxic_pnl":     0.0,
            "overnight_pnl": 0.0,
        },
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _get_spot(ticker):
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="2d")
        if hist is not None and len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _compute_vol_adjusted_spread(asset_info, rp):
    """Risk 6: Widen spread when vol is high."""
    base_vol      = asset_info.get("base_vol", 0.01) * rp["vol_multiplier"]
    daily_vol_bps = base_vol / (252 ** 0.5) * 10_000
    return max(asset_info["spread_bps"], daily_vol_bps * 0.20)


def _compute_hedge_cost(asset_label, hedge_side, hedge_notional, rp):
    """
    Risk 1-3, 5: Compute realistic all-in hedge cost.
    Includes slippage, latency drift, bid/ask, and market impact.
    """
    import random, math
    asset     = FLOW_ASSETS[asset_label]
    liquidity = asset.get("liquidity", 20_000_000)
    base_vol  = asset.get("base_vol", 0.01) * rp["vol_multiplier"]

    slippage_bps     = random.uniform(rp["slippage_min_bps"], rp["slippage_max_bps"])
    latency_ms       = random.uniform(rp["latency_ms_min"], rp["latency_ms_max"])
    vol_per_sec      = base_vol / math.sqrt(252 * 6.5 * 3600)
    drift_bps        = abs(random.gauss(0, vol_per_sec * math.sqrt(latency_ms / 1000))) * 10_000
    hedge_spread_bps = asset["spread_bps"] * 0.5
    impact_bps       = rp["impact_factor"] * (hedge_notional / liquidity) * 10_000
    total_bps        = slippage_bps + drift_bps + hedge_spread_bps + impact_bps

    return {
        "latency_ms":      round(latency_ms),
        "slippage_bps":    round(slippage_bps, 2),
        "drift_bps":       round(drift_bps, 2),
        "impact_bps":      round(impact_bps, 2),
        "total_cost_bps":  round(total_bps, 2),
        "total_cost_usd":  round(hedge_notional * total_bps / 10_000, 2),
        "slippage_usd":    round(hedge_notional * slippage_bps / 10_000, 2),
        "impact_usd":      round(hedge_notional * impact_bps / 10_000, 2),
    }


def add_client_trade(asset_label, side, notional, is_toxic=False):
    """Record trade with all risk mechanics applied."""
    import random
    rp    = _get_risk_params()
    asset = FLOW_ASSETS[asset_label]

    eff_spread      = _compute_vol_adjusted_spread(asset, rp)
    spread_earned   = notional * (eff_spread / 10_000)
    st.session_state["pnl"]["spread_pnl"] += spread_earned

    direction = -1 if side == "Buy" else 1
    inv = st.session_state["inventory"]
    inv[asset_label] = inv.get(asset_label, 0.0) + direction * notional

    forced_cost = 0.0
    if abs(inv[asset_label]) > MAX_INVENTORY_USD:
        excess      = abs(inv[asset_label]) - MAX_INVENTORY_USD
        penalty_bps = rp["slippage_max_bps"] * 3
        forced_cost = excess * (penalty_bps / 10_000)
        st.session_state["pnl"]["slippage_pnl"] -= forced_cost
        sign = 1 if inv[asset_label] > 0 else -1
        inv[asset_label] = sign * MAX_INVENTORY_USD

    toxic_loss  = 0.0
    actual_toxic = is_toxic and random.random() < rp["toxic_flow_prob"]
    if actual_toxic:
        jump_bps   = rp["toxic_jump_bps"] * random.uniform(0.5, 1.5)
        toxic_loss = notional * (jump_bps / 10_000)
        st.session_state["pnl"]["toxic_pnl"] -= toxic_loss

    st.session_state["flow_trades"].append({
        "asset": asset_label, "client_side": side, "notional": notional,
        "spread_earned": round(spread_earned, 2), "effective_spread": round(eff_spread, 2),
        "toxic": actual_toxic, "toxic_loss": round(toxic_loss, 2),
        "forced_cost": round(forced_cost, 2),
    })

    return {"spread_earned": round(spread_earned,2), "toxic": actual_toxic,
            "toxic_loss": round(toxic_loss,2), "forced_hedge": forced_cost>0,
            "forced_cost": round(forced_cost,2)}


def compute_hedge_for_inventory():
    """Hedge with realistic slippage, latency, impact costs."""
    rp = _get_risk_params()
    hedges = []
    inv = st.session_state["inventory"]
    for asset_label, net_notional in list(inv.items()):
        if abs(net_notional) < HEDGE_THRESHOLD_USD:
            continue
        hedge_side     = "Sell" if net_notional > 0 else "Buy"
        hedge_notional = abs(net_notional)
        cost = _compute_hedge_cost(asset_label, hedge_side, hedge_notional, rp)
        st.session_state["pnl"]["slippage_pnl"] -= cost["slippage_usd"]
        st.session_state["pnl"]["impact_pnl"]   -= cost["impact_usd"]
        inv[asset_label] = 0.0
        hedge = {"asset": asset_label, "hedge_side": hedge_side,
                 "hedge_notional": round(hedge_notional,2), **cost}
        st.session_state["hedge_trades"].append(hedge)
        hedges.append(hedge)
    return hedges


def apply_overnight_risk():
    """Risk 8: Random gap move on open inventory."""
    import random
    rp  = _get_risk_params()
    inv = st.session_state["inventory"]
    total = 0.0
    for asset_label, net_notional in inv.items():
        if net_notional == 0:
            continue
        base_vol = FLOW_ASSETS[asset_label].get("base_vol", 0.01) * rp["vol_multiplier"]
        gap_pct  = random.gauss(0, base_vol * rp["overnight_vol_scale"])
        pnl      = net_notional * gap_pct * random.choice([-1, 1])
        total   += pnl
    st.session_state["pnl"]["overnight_pnl"] += total
    return total


def mark_to_market_inventory():
    """MTM using realistic vol-based random walk."""
    import random, math
    rp  = _get_risk_params()
    inv = st.session_state["inventory"]
    mtm = 0.0
    for asset_label, net_notional in inv.items():
        if net_notional == 0:
            continue
        base_vol = FLOW_ASSETS[asset_label].get("base_vol", 0.01) * rp["vol_multiplier"]
        move     = random.gauss(0, base_vol / math.sqrt(252 * 6.5 * 60))
        mtm     += net_notional * move
    st.session_state["pnl"]["inventory_pnl"] += mtm
    return mtm


def _total_pnl():
    return sum(st.session_state.get("pnl", {}).values())


def render_flow_trading_tab():
    import random
    from datetime import datetime as _dt
    init_flow_state()

    st.markdown("## 🏦 Flow Trading Simulator")
    st.caption("You are a junior flow trader at a major investment bank. Every hedge costs real money — slippage, market impact, latency drift, and toxic flow all eat into your P&L. Your goal: earn more in spread than you lose in hedging costs.")

    # ── RISK PARAMETERS SIDEBAR ─────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚙️ Risk Parameters")
        st.caption("Tune the simulation to reflect different market conditions.")
        rp = st.session_state.get("risk_params", DEFAULT_RISK_PARAMS.copy())
        rp["slippage_min_bps"]    = st.slider("Min Slippage (bps)",       0.5,  5.0,  float(rp["slippage_min_bps"]),   0.5)
        rp["slippage_max_bps"]    = st.slider("Max Slippage (bps)",       1.0,  20.0, float(rp["slippage_max_bps"]),   0.5)
        rp["latency_ms_min"]      = st.slider("Min Latency (ms)",         50,   500,  int(rp["latency_ms_min"]),       50)
        rp["latency_ms_max"]      = st.slider("Max Latency (ms)",         500,  5000, int(rp["latency_ms_max"]),       100)
        rp["vol_multiplier"]      = st.slider("Vol Multiplier",           0.5,  3.0,  float(rp["vol_multiplier"]),     0.1)
        rp["impact_factor"]       = st.slider("Market Impact Factor",     0.01, 0.5,  float(rp["impact_factor"]),      0.01)
        rp["toxic_flow_prob"]     = st.slider("Toxic Flow Probability",   0.0,  0.5,  float(rp["toxic_flow_prob"]),    0.05)
        rp["toxic_jump_bps"]      = st.slider("Toxic Jump (bps)",         5.0,  50.0, float(rp["toxic_jump_bps"]),     1.0)
        rp["overnight_vol_scale"] = st.slider("Overnight Vol Scale",      0.5,  3.0,  float(rp["overnight_vol_scale"]),0.1)
        st.session_state["risk_params"] = rp
        st.markdown("---")
        st.caption(f"**Max inventory:** ${MAX_INVENTORY_USD:,.0f} | **Hedge threshold:** ${HEDGE_THRESHOLD_USD:,.0f}")
    st.markdown("---")

    # ── AUTO-GENERATE CLIENT ORDER ───────────────────────────────
    st.markdown("### 📞 Incoming Client Order")
    st.caption("A client order has arrived. Read the context, decide whether to accept it, and if so at what size. In real life you have seconds to decide — the market is moving.")

    # Generate or retrieve current order
    if "current_order" not in st.session_state or st.session_state.get("order_accepted", False) or st.session_state.get("order_rejected", False):
        # Pick a scenario weighted by current market conditions
        scenario = random.choice(CLIENT_ORDER_SCENARIOS)
        st.session_state["current_order"] = scenario
        st.session_state["order_accepted"] = False
        st.session_state["order_rejected"] = False

    order = st.session_state["current_order"]
    asset_info = FLOW_ASSETS.get(order["asset"], {})

    # Order card
    side_color = "#00ff88" if order["side"] == "Buy" else "#ff4d4d"
    st.markdown(
        f"<div class='card' style='border-left: 4px solid {side_color}; padding: 16px;'>"
        f"<div style='font-size:13px; color:#888; margin-bottom:6px;'>INCOMING CLIENT ORDER — {_dt.now().strftime('%H:%M:%S')}</div>"
        f"<div style='font-size:22px; font-weight:bold; color:{side_color};'>{order['side'].upper()} {order['asset']}</div>"
        f"<div style='font-size:18px; color:#FFFFFF; margin-top:4px;'>${order['notional']:,.0f} notional</div>"
        f"<div style='font-size:13px; color:#AAAAAA; margin-top:8px;'>📋 {order['reason']}</div>"
        f"<div style='font-size:12px; color:#666; margin-top:6px;'>Category: {asset_info.get('category','—')} | Spread: {asset_info.get('spread_bps', 0):.1f} bps | {asset_info.get('description','')}</div>"
        f"</div>",
        unsafe_allow_html=True
    )

    # Spread earned if accepted
    spread_earned = order["notional"] * (asset_info.get("spread_bps", 1) / 10_000)
    current_inv   = st.session_state["inventory"].get(order["asset"], 0)
    direction     = -1 if order["side"] == "Buy" else 1
    new_inv       = current_inv + direction * order["notional"]

    st.markdown("")
    rp = _get_risk_params()
    eff_spread_bps = _compute_vol_adjusted_spread(asset_info, rp) if asset_info else asset_info.get("spread_bps", 1)
    spread_earned  = order["notional"] * (eff_spread_bps / 10_000)
    est_cost       = _compute_hedge_cost(order["asset"], "Buy" if direction < 0 else "Sell", order["notional"], rp) if asset_info else {}
    est_net        = spread_earned - est_cost.get("total_cost_usd", 0)

    ic1, ic2, ic3, ic4 = st.columns(4)
    with ic1:
        st.markdown(f"<div class='card'><div class='label'>Spread Earned</div><div class='big-number' style='color:#00ff88;'>${spread_earned:,.0f}</div><div class='label' style='font-size:10px;'>{eff_spread_bps:.1f}bps (vol-adjusted)</div></div>", unsafe_allow_html=True)
    with ic2:
        st.markdown(f"<div class='card'><div class='label'>Est. Hedge Cost</div><div class='big-number' style='color:#FFDC00;'>${est_cost.get('total_cost_usd',0):,.0f}</div><div class='label' style='font-size:10px;'>{est_cost.get('total_cost_bps',0):.1f}bps all-in</div></div>", unsafe_allow_html=True)
    with ic3:
        nc = "#00ff88" if est_net > 0 else "#ff4d4d"
        st.markdown(f"<div class='card'><div class='label'>Est. Net P&L</div><div class='big-number' style='color:{nc};'>${est_net:,.0f}</div><div class='label' style='font-size:10px;'>Spread minus hedge cost</div></div>", unsafe_allow_html=True)
    with ic4:
        new_color = "#00ff88" if abs(new_inv) < HEDGE_THRESHOLD_USD else "#FFDC00" if abs(new_inv) < MAX_INVENTORY_USD else "#ff4d4d"
        st.markdown(f"<div class='card'><div class='label'>Inventory After</div><div class='big-number' style='color:{new_color};'>${new_inv:,.0f}</div></div>", unsafe_allow_html=True)

    if abs(new_inv) >= HEDGE_THRESHOLD_USD:
        st.warning(f"⚠️ Accepting this trade will push your {order['asset']} position to ${abs(new_inv):,.0f} — above the $500k hedge threshold. You'll need to hedge after accepting.")

    st.markdown("")

    # Allow size adjustment
    accept_notional = st.slider(
        "Adjust trade size (USD)",
        min_value=100_000,
        max_value=int(order["notional"] * 1.5),
        value=int(order["notional"]),
        step=100_000,
        format="$%d"
    )

    col_acc, col_rej, col_new = st.columns(3)
    with col_acc:
        if st.button("✅ Accept Trade", type="primary"):
            add_client_trade(order["asset"], order["side"], accept_notional)
            st.session_state["order_accepted"] = True
            st.session_state["trade_log"] = st.session_state.get("trade_log", [])
            st.session_state["trade_log"].append({
                "time":     _dt.now().strftime("%H:%M:%S"),
                "action":   "ACCEPTED",
                "asset":    order["asset"],
                "side":     order["side"],
                "notional": accept_notional,
                "spread":   round(accept_notional * asset_info.get("spread_bps", 1) / 10_000, 2),
                "reason":   order["reason"]
            })
            st.success(f"✅ Trade accepted! Spread earned: ${accept_notional * asset_info.get('spread_bps',1) / 10_000:,.0f}")
            st.rerun()
    with col_rej:
        if st.button("❌ Reject Trade"):
            st.session_state["order_rejected"] = True
            st.session_state["trade_log"] = st.session_state.get("trade_log", [])
            st.session_state["trade_log"].append({
                "time":     _dt.now().strftime("%H:%M:%S"),
                "action":   "REJECTED",
                "asset":    order["asset"],
                "side":     order["side"],
                "notional": order["notional"],
                "spread":   0,
                "reason":   order["reason"]
            })
            st.info("Order rejected. Next client order incoming...")
            st.rerun()
    with col_new:
        if st.button("🔄 New Order"):
            del st.session_state["current_order"]
            st.rerun()

    st.markdown("---")

    # ── MANUAL TRADE ENTRY ───────────────────────────────────────
    with st.expander("➕ Enter Manual Trade", expanded=False):
        st.caption("Enter your own trade manually — useful for testing specific scenarios.")
        categories = sorted(set(v["category"] for v in FLOW_ASSETS.values()))
        cat_filter = st.selectbox("Filter by asset class", ["All"] + categories)
        filtered_assets = [k for k, v in FLOW_ASSETS.items() if cat_filter == "All" or v["category"] == cat_filter]
        m_asset    = st.selectbox("Asset", filtered_assets, key="manual_asset")
        m_side     = st.radio("Client side", ["Buy", "Sell"], horizontal=True, key="manual_side")
        m_notional = st.number_input("Notional (USD)", min_value=100_000.0, value=1_000_000.0, step=100_000.0, key="manual_notional")
        if st.button("Add Manual Trade"):
            add_client_trade(m_asset, m_side, m_notional)
            st.success(f"Manual trade added: {m_side} {m_asset} ${m_notional:,.0f}")
            st.rerun()

    st.markdown("---")

    # ── INVENTORY & RISK MANAGEMENT ─────────────────────────────
    st.markdown("### 📊 Your Trading Book")
    inv = st.session_state["inventory"]
    pnl = st.session_state["pnl"]
    total_pnl = sum(pnl.values())

    # Full P&L breakdown
    st.markdown("#### P&L Breakdown")
    pnl_items = [
        ("Spread P&L",    "spread_pnl",    "Earned from bid/offer on every trade",   True),
        ("Hedge Slippage","slippage_pnl",  "Lost to slippage + latency + bid/ask",   False),
        ("Market Impact", "impact_pnl",    "Lost moving the market with large hedges",False),
        ("Inventory MTM", "inventory_pnl", "Mark-to-market on open positions",        None),
        ("Toxic Flow",    "toxic_pnl",     "Losses from informed client flow",         False),
        ("Overnight",     "overnight_pnl", "Gap risk from holding inventory overnight",None),
    ]
    cols6 = st.columns(6)
    for col, (label, key, tip, good) in zip(cols6, pnl_items):
        val = pnl.get(key, 0)
        cc  = "#00ff88" if (good is True and val >= 0) or (good is False and val >= 0) else "#ff4d4d" if val < 0 else "#FFDC00"
        if good is None:
            cc = "#00ff88" if val >= 0 else "#ff4d4d"
        with col:
            st.markdown(f"<div class='card'><div class='label' style='font-size:10px;'>{label}</div><div style='font-size:18px;font-weight:bold;color:{cc};'>${val:,.0f}</div><div class='label' style='font-size:9px;'>{tip}</div></div>", unsafe_allow_html=True)

    total_color = "#00ff88" if total_pnl >= 0 else "#ff4d4d"
    st.markdown(f"<div class='card' style='text-align:center; margin-top:4px;'><div class='label'>TOTAL P&L</div><div class='big-number' style='color:{total_color};'>${total_pnl:,.0f}</div></div>", unsafe_allow_html=True)

    st.markdown("")

    if inv and any(v != 0 for v in inv.values()):
        # Inventory bar chart grouped by category
        assets_list  = [k for k, v in inv.items() if v != 0]
        values_list  = [inv[k] for k in assets_list]
        cats_list    = [FLOW_ASSETS.get(k, {}).get("category", "Other") for k in assets_list]
        colors_list  = ["#00ff88" if v > 0 else "#ff4d4d" for v in values_list]

        fig_inv = go.Figure(go.Bar(
            x=assets_list, y=values_list,
            marker_color=colors_list,
            text=[f"${abs(v):,.0f}" for v in values_list],
            textposition="outside",
            customdata=cats_list,
            hovertemplate="%{x}<br>%{customdata}<br>${%{y:,.0f}}<extra></extra>"
        ))
        fig_inv.add_hline(y=HEDGE_THRESHOLD_USD,  line_dash="dash", line_color="#FFDC00",
                          annotation_text="Hedge threshold (+)", annotation_position="right")
        fig_inv.add_hline(y=-HEDGE_THRESHOLD_USD, line_dash="dash", line_color="#FFDC00",
                          annotation_text="Hedge threshold (−)", annotation_position="right")
        fig_inv.update_layout(
            template="plotly_dark", height=340,
            title="Net Inventory by Asset (USD) — Yellow lines = hedge triggers",
            margin=dict(l=40, r=100, t=50, b=60),
            yaxis=dict(gridcolor="#333"),
            xaxis=dict(showgrid=False, tickangle=-30)
        )
        st.plotly_chart(fig_inv, use_container_width=True)
        st.caption("Green = long position (profit if price rises). Red = short position (profit if price falls). Yellow dashed lines = $500k hedge threshold. Bars crossing the threshold signal you need to hedge.")

        # Hedge signals
        needs_hedge = {a: v for a, v in inv.items() if abs(v) >= HEDGE_THRESHOLD_USD}
        if needs_hedge:
            st.markdown("#### ⚠️ Hedge Signals")
            for asset, notional in needs_hedge.items():
                direction = "LONG" if notional > 0 else "SHORT"
                loss_1pct = abs(notional) * 0.01
                st.warning(f"**{asset}** — {direction} ${abs(notional):,.0f} | 1% move against you = **${loss_1pct:,.0f} loss**")

    else:
        st.info("No open positions. Accept a client order above to build your book.")

    st.markdown("")

    # Hedge and MTM buttons
    hb1, hb2, hb3, hb4 = st.columns(4)
    with hb1:
        if st.button("🛡️ Hedge All Positions"):
            hedges = compute_hedge_for_inventory()
            if hedges:
                for h in hedges:
                    st.warning(f"Hedged {h['asset']}: {h['hedge_side']} ${h['hedge_notional']:,.0f} | Cost: ${h['total_cost_usd']:,.0f} ({h['total_cost_bps']:.1f}bps) | Latency: {h['latency_ms']}ms")
            else:
                st.info("No positions above threshold to hedge.")
            st.rerun()
    with hb2:
        if st.button("📊 Mark to Market"):
            mtm = mark_to_market_inventory()
            color = "success" if mtm >= 0 else "error"
            getattr(st, color)(f"MTM P&L this step: ${mtm:,.0f}")
    with hb3:
        if st.button("🌙 Apply Overnight Risk"):
            gap_pnl = apply_overnight_risk()
            color = "success" if gap_pnl >= 0 else "error"
            getattr(st, color)(f"Overnight gap P&L: ${gap_pnl:,.0f}")
            st.rerun()
    with hb4:
        if st.button("🔄 Reset Simulation"):
            for key in ["inventory","flow_trades","hedge_trades","pnl","trade_log","current_order","sp500_summary","risk_narrative","trader_feedback"]:
                st.session_state.pop(key, None)
            st.success("Simulation reset.")
            st.rerun()

    st.markdown("---")

    # ── TRADE LOG ────────────────────────────────────────────────
    st.markdown("### 📋 Decision Log")
    trade_log = st.session_state.get("trade_log", [])
    if trade_log:
        log_df = pd.DataFrame(trade_log)
        # Colour accepted vs rejected
        def highlight_row(row):
            color = "background-color: rgba(0,255,136,0.08)" if row["action"] == "ACCEPTED" else "background-color: rgba(255,77,77,0.08)"
            return [color] * len(row)
        st.dataframe(log_df.style.apply(highlight_row, axis=1), use_container_width=True, hide_index=True)
        accepted = sum(1 for t in trade_log if t["action"] == "ACCEPTED")
        rejected = sum(1 for t in trade_log if t["action"] == "REJECTED")
        total_spread = sum(t.get("spread", 0) for t in trade_log)
        dl1, dl2, dl3 = st.columns(3)
        with dl1:
            st.markdown(f"<div class='card'><div class='label'>Orders Accepted</div><div class='big-number' style='color:#00ff88;'>{accepted}</div></div>", unsafe_allow_html=True)
        with dl2:
            st.markdown(f"<div class='card'><div class='label'>Orders Rejected</div><div class='big-number' style='color:#ff4d4d;'>{rejected}</div></div>", unsafe_allow_html=True)
        with dl3:
            st.markdown(f"<div class='card'><div class='label'>Total Spread Earned</div><div class='big-number' style='color:#00ff88;'>${total_spread:,.0f}</div></div>", unsafe_allow_html=True)
    else:
        st.info("No trades yet — accept or reject the incoming client order above.")

    st.markdown("---")

    # ── AI PERFORMANCE FEEDBACK ──────────────────────────────────
    st.markdown("### 🤖 AI Trading Coach")
    st.caption("Once you have made some decisions, get scored and coached by GPT on your risk management, decision quality, and what a real flow trader would have done differently.")

    if st.button("📈 Get Performance Feedback", key="perf_feedback_btn"):
        if not trade_log:
            st.warning("Make some trading decisions first before requesting feedback.")
        else:
            with st.spinner("Analysing your trading decisions..."):
                try:
                    from gpt_layer import call_gpt_prose
                    accepted_trades = [t for t in trade_log if t["action"] == "ACCEPTED"]
                    rejected_trades = [t for t in trade_log if t["action"] == "REJECTED"]
                    inv_summary = {k: v for k, v in st.session_state.get("inventory", {}).items() if v != 0}

                    feedback_prompt = f"""You are a senior flow trading mentor at a major investment bank, reviewing a junior trader's simulation session.

TRADING SESSION SUMMARY:
- Orders accepted: {len(accepted_trades)}
- Orders rejected: {len(rejected_trades)}
- Total spread earned: ${sum(t.get('spread',0) for t in trade_log):,.0f}
- Total P&L: ${total_pnl:,.0f}
- Current open inventory: {inv_summary if inv_summary else "Flat (no open positions)"}

ACCEPTED TRADES:
{chr(10).join(f"- {t['side']} {t['asset']} ${t['notional']:,.0f} | {t['reason']}" for t in accepted_trades) if accepted_trades else "None"}

REJECTED TRADES:
{chr(10).join(f"- {t['side']} {t['asset']} ${t['notional']:,.0f} | {t['reason']}" for t in rejected_trades) if rejected_trades else "None"}

Please provide:
1. A SCORE out of 100 for overall risk management (format: "Risk Management Score: XX/100")
2. A SCORE out of 100 for decision quality (format: "Decision Quality Score: XX/100")
3. What the trader did well (2-3 sentences)
4. What a real senior flow trader would have done differently (2-3 sentences)
5. One specific lesson to take away from this session

Be direct, constructive, and realistic. Use a mentor tone — tough but fair."""

                    feedback = call_gpt_prose(feedback_prompt)
                    st.session_state["trader_feedback"] = feedback or "Could not generate feedback."
                except Exception as e:
                    st.session_state["trader_feedback"] = f"Error: {e}"

    feedback_text = st.session_state.get("trader_feedback", "Click above after making some trading decisions to get AI coaching feedback.")
    st.markdown(f"<div class='card' style='line-height:1.8; color:#DDDDDD; white-space:pre-wrap;'>{feedback_text}</div>", unsafe_allow_html=True)

    # Trader tip of the session
    st.markdown("---")
    with st.expander("📚 Flow Trading Guide — Key Concepts", expanded=False):
        st.markdown("""
**What is flow trading?**
Flow traders (also called market makers) sit between clients and the market. When a client wants to buy or sell, you take the other side — immediately. You profit from the bid/offer spread on every trade. Your job is then to manage the resulting inventory risk.

**The bid/offer spread**
Every asset has a price you'll buy at (bid) and a price you'll sell at (offer). The difference is the spread — your guaranteed profit on every trade. Tighter spreads = more competitive but less profit per trade.

**Inventory risk**
When you take the other side of a client trade, you build up inventory. If a client buys $5m of S&P 500 from you, you're now short $5m of S&P 500. If the market rises, you lose money. This is inventory risk — and managing it is the core skill of flow trading.

**Hedging**
To reduce inventory risk, you hedge — placing an offsetting trade in the market. If you're short $5m S&P 500, you buy $5m SPY to hedge. The hedge costs money (you cross the spread yourself) but removes the market risk.

**The flow trader's dilemma**
- Accept every trade → maximise spread income but accumulate risk
- Reject trades → no risk but no income either
- The skill is knowing WHEN to accept, WHEN to reduce size, and WHEN to hedge immediately

**Asset class nuances**
- **FX**: Very liquid, tight spreads, but large notionals. Corporate hedgers are predictable; speculators are not.
- **Rates**: Sensitive to macro news. Flight-to-safety flows can be very large and one-directional.
- **Equities**: Index flows often tied to rebalancing. Large directional flows from hedge funds are dangerous to hold.
- **Commodities**: Seasonal patterns matter. Producer hedging (airlines, energy companies) is regular and predictable.
        """)


# ---------- TABS INITIALIZATION ----------
tabs = st.tabs(["Macro", "Risk", "Commodities", "S&P500", "Flow Trading", "Trade Ideas", "Econ Calendar", "Interview Prep"])

# ---------- LOAD MARKET DATA ----------
prices = get_market_data()
# Sanitise — guarantee change is always float or 0, never None
for _k in list(prices.keys()):
    if prices[_k] is None:
        prices[_k] = {"price": None, "change": 0}
    elif prices[_k].get("change") is None:
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

    # If no GPT analysis exists but we have headlines, generate it now from existing data
    if gpt is None and news_df is not None and len(news_df) > 0:
        try:
            from gpt_layer import call_gpt
            from sheets_db import save_gpt_analysis
            headlines = news_df.sort_values("relevance", ascending=False)["headline"].head(5).tolist() if "relevance" in news_df.columns else news_df["headline"].head(5).tolist()
            gpt_output = call_gpt([str(h) for h in headlines if h])
            if gpt_output:
                st.session_state["gpt_analysis"] = gpt_output
                save_gpt_analysis(gpt_output)
                gpt = gpt_output
        except Exception as e:
            print(f"[GPT fallback] {e}")

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
            all_headlines = news_df.sort_values("date", ascending=False).head(25)

            # Show top 5 by default, expand on button click
            if "show_all_headlines" not in st.session_state:
                st.session_state["show_all_headlines"] = False

            table = all_headlines if st.session_state["show_all_headlines"] else all_headlines.head(5)

            def _render_headline(row):
                headline = str(row.get("headline", ""))
                source   = str(row.get("source", ""))
                raw_url  = row.get("url", "")
                topic    = str(row.get("topic", "other"))
                try:
                    sentiment_val = float(row.get("sentiment", 0))
                except Exception:
                    sentiment_val = 0.0
                sent_color = "#00ff88" if sentiment_val > 0.05 else "#ff4d4d" if sentiment_val < -0.05 else "#FFDC00"
                sent_str = f"{sentiment_val:+.2f}"
                try:
                    date_str = pd.to_datetime(row.get("date")).strftime("%d %b %H:%M")
                except Exception:
                    date_str = str(row.get("date", ""))[:16]

                # Clean URL — handle NaN, None, empty
                url = str(raw_url).strip() if raw_url and str(raw_url) not in ["nan", "None", ""] else ""

                # Use article URL if available, otherwise fall back to Google News search
                import urllib.parse as _up
                if url.startswith("http"):
                    final_url = url
                else:
                    final_url = "https://news.google.com/search?q=" + _up.quote(headline)

                link_start = f'<a href="{final_url}" target="_blank" style="color:#00c3ff; font-weight:500; text-decoration:none;">'
                link_end   = " ↗</a>"

                html = (
                    '<div style="padding:7px 0; border-bottom:1px solid #222;">' +
                    '<div>' + link_start + headline + link_end + '</div>' +
                    '<div style="font-size:11px; color:#888; margin-top:2px;">' +
                    date_str + " &nbsp;|&nbsp; " + source + " &nbsp;|&nbsp; " +
                    f'<span style="color:{sent_color};">{sent_str}</span> sentiment &nbsp;|&nbsp; ' + topic +
                    '</div></div>'
                )
                st.markdown(html, unsafe_allow_html=True)

            for _, row in table.iterrows():
                _render_headline(row)

            # Show more / show less toggle
            total = len(all_headlines)
            if total > 5:
                if st.session_state["show_all_headlines"]:
                    if st.button(f"▲ Show less", key="headlines_toggle"):
                        st.session_state["show_all_headlines"] = False
                        st.rerun()
                else:
                    if st.button(f"▼ Show all {total} headlines", key="headlines_toggle"):
                        st.session_state["show_all_headlines"] = True
                        st.rerun()
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
    st.caption("Click any asset to view its full price history.")

    # Asset ticker map for charting
    SNAPSHOT_TICKERS = {
        "S&P 500": "^GSPC", "FTSE 100": "^FTSE",
        "US 2Y Yield": "SHY", "US 10Y Yield": "IEF", "US 30Y Yield": "TLT",
        "GBPUSD": "GBPUSD=X", "EURUSD": "EURUSD=X", "USDJPY": "JPY=X",
        "Brent Crude": "BZ=F", "WTI Crude": "CL=F", "Natural Gas": "NG=F",
        "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F",
        "Corn": "ZC=F", "Wheat": "ZW=F", "VIX": "^VIX",
    }

    cols = st.columns(5)
    for i, (name, item) in enumerate(prices.items()):
        with cols[i % 5]:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='label'>{name}</div>", unsafe_allow_html=True)
            if item and item["price"] is not None:
                price  = item["price"]
                change = item["change"]
                if "Yield" in name or change is None:
                    change_str, color = "", "#ffffff"
                elif change > 0:
                    change_str, color = f"▲ {change}%", "#00ff88"
                elif change < 0:
                    change_str, color = f"▼ {abs(change)}%", "#ff4d4d"
                else:
                    change_str, color = "0.00%", "#ffffff"
                st.markdown(f"<div class='big-number'>{price}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:16px;font-weight:bold;color:{color};'>{change_str}</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='big-number'>N/A</div>", unsafe_allow_html=True)
                st.markdown("<div style='font-size:16px;'>N/A</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # Click to expand chart
            if st.button(f"📈 Chart", key=f"chart_btn_{name}"):
                if st.session_state.get("selected_asset") == name:
                    st.session_state.pop("selected_asset", None)
                else:
                    st.session_state["selected_asset"] = name

    # Full-width asset chart — shows below the grid when an asset is selected
    selected = st.session_state.get("selected_asset")
    if selected and selected in SNAPSHOT_TICKERS:
        st.markdown("")
        st.markdown(f"### 📈 {selected} — Price History")

        period_options = {
            "1 Month":  "1mo",
            "3 Months": "3mo",
            "6 Months": "6mo",
            "1 Year":   "1y",
            "2 Years":  "2y",
            "5 Years":  "5y",
        }

        col_period, col_ma, col_close = st.columns([2, 2, 1])
        with col_period:
            selected_period_label = st.selectbox(
                "Time period",
                list(period_options.keys()),
                index=2,
                key="chart_period"
            )
        with col_ma:
            show_ma = st.multiselect(
                "Moving averages",
                ["20D", "50D", "200D"],
                default=["50D"],
                key="chart_ma"
            )
        with col_close:
            st.markdown("")
            if st.button("✕ Close chart"):
                st.session_state.pop("selected_asset", None)
                st.rerun()

        period = period_options[selected_period_label]
        ticker = SNAPSHOT_TICKERS[selected]

        @st.cache_data(ttl=900)
        def _get_asset_history(ticker, period):
            try:
                import yfinance as yf
                hist = yf.Ticker(ticker).history(period=period)
                if hist is not None and len(hist) > 1:
                    return hist["Close"].dropna()
            except Exception:
                pass
            return None

        with st.spinner(f"Loading {selected} history..."):
            hist = _get_asset_history(ticker, period)

        if hist is not None and len(hist) > 1:
            dates  = [str(d.date()) for d in hist.index]
            closes = list(hist.values)

            # Key stats
            start_price = closes[0]
            end_price   = closes[-1]
            pct_chg     = ((end_price - start_price) / start_price) * 100
            high        = max(closes)
            low         = min(closes)

            s1, s2, s3, s4 = st.columns(4)
            pct_color = "#00ff88" if pct_chg > 0 else "#ff4d4d"
            with s1:
                st.markdown(f"<div class='card'><div class='label'>Current</div><div class='big-number'>{end_price:.4f}</div></div>", unsafe_allow_html=True)
            with s2:
                st.markdown(f"<div class='card'><div class='label'>{selected_period_label} Return</div><div class='big-number' style='color:{pct_color};'>{pct_chg:+.2f}%</div></div>", unsafe_allow_html=True)
            with s3:
                st.markdown(f"<div class='card'><div class='label'>Period High</div><div class='big-number' style='color:#00ff88;'>{high:.4f}</div></div>", unsafe_allow_html=True)
            with s4:
                st.markdown(f"<div class='card'><div class='label'>Period Low</div><div class='big-number' style='color:#ff4d4d;'>{low:.4f}</div></div>", unsafe_allow_html=True)

            st.markdown("")

            # Build chart
            line_color = "#00ff88" if pct_chg >= 0 else "#ff4d4d"
            fig_asset = go.Figure()

            # Price line with fill
            fig_asset.add_trace(go.Scatter(
                x=dates, y=closes,
                mode="lines",
                name=selected,
                line=dict(color=line_color, width=2),
                fill="tozeroy",
                fillcolor=f"rgba({'0,255,136' if pct_chg >= 0 else '255,77,77'},0.05)"
            ))

            # Moving averages
            import pandas as pd
            series = pd.Series(closes, index=dates)
            ma_colors = {"20D": "#FFDC00", "50D": "#00c3ff", "200D": "#ff4d4d"}
            ma_windows = {"20D": 20, "50D": 50, "200D": 200}
            for ma in show_ma:
                window = ma_windows[ma]
                if len(closes) >= window:
                    ma_vals = series.rolling(window).mean()
                    fig_asset.add_trace(go.Scatter(
                        x=dates, y=list(ma_vals),
                        mode="lines",
                        name=f"{ma} MA",
                        line=dict(color=ma_colors[ma], width=1.5, dash="dash")
                    ))

            fig_asset.update_layout(
                template="plotly_dark",
                height=420,
                margin=dict(l=40, r=40, t=30, b=40),
                xaxis=dict(showgrid=False, rangeslider=dict(visible=True, thickness=0.05)),
                yaxis=dict(showgrid=True, gridcolor="#333333"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified"
            )
            st.plotly_chart(fig_asset, use_container_width=True)
            st.caption(f"**{selected}** | {selected_period_label} | Green fill = positive return, Red fill = negative. Drag the range bar at the bottom to zoom into a specific period.")
        else:
            st.warning(f"Could not load price history for {selected}. The asset may not be available from Yahoo Finance for this period.")
        st.markdown("---")

    st.markdown("### Yield Curve")
    st.caption("The yield curve shows what interest rate the US government pays to borrow money at different time horizons. Its shape is one of the most watched signals in finance — it tells us what the market expects for growth, inflation, and recession risk.")

    curve = get_yield_curve()
    maturities    = ["2Y", "5Y", "10Y", "30Y"]
    yields        = [curve[m] for m in maturities]
    normal_yields = [2.5, 2.8, 3.0, 3.2]

    slope_2s10s = curve["10Y"] - curve["2Y"]
    slope_5s30s = curve["30Y"] - curve["5Y"]
    is_inverted = slope_2s10s < 0

    if slope_2s10s > 0.5:
        curve_shape, shape_color = "STEEP",    "#00ff88"
        shape_meaning = "Strong growth expectations — long-term borrowing costs well above short-term. Historically positive for banks and risk assets."
    elif slope_2s10s > 0:
        curve_shape, shape_color = "NORMAL",   "#FFDC00"
        shape_meaning = "Slightly positive slope — markets broadly comfortable with the outlook, though not strongly bullish on growth."
    elif slope_2s10s > -0.25:
        curve_shape, shape_color = "FLAT",     "#FF8C00"
        shape_meaning = "Flat curve signals uncertainty — markets unsure whether growth or recession lies ahead. Often precedes inversion."
    else:
        curve_shape, shape_color = "INVERTED", "#ff4d4d"
        shape_meaning = "Inverted — short-term rates above long-term. Has preceded every US recession in the last 50 years."

    yc1, yc2, yc3, yc4 = st.columns(4)
    with yc1:
        st.markdown(f"<div class='card'><div class='label'>Curve Shape</div><div class='big-number' style='color:{shape_color};'>{curve_shape}</div></div>", unsafe_allow_html=True)
    with yc2:
        c = "#00ff88" if slope_2s10s > 0 else "#ff4d4d"
        st.markdown(f"<div class='card'><div class='label'>2s10s Spread</div><div class='big-number' style='color:{c};'>{slope_2s10s:+.2f}%</div><div class='label' style='font-size:10px;'>10Y minus 2Y</div></div>", unsafe_allow_html=True)
    with yc3:
        c = "#00ff88" if slope_5s30s > 0 else "#ff4d4d"
        st.markdown(f"<div class='card'><div class='label'>5s30s Spread</div><div class='big-number' style='color:{c};'>{slope_5s30s:+.2f}%</div><div class='label' style='font-size:10px;'>30Y minus 5Y</div></div>", unsafe_allow_html=True)
    with yc4:
        rec_signal = "⚠️ WARNING" if is_inverted else "✅ CLEAR"
        rec_color  = "#ff4d4d" if is_inverted else "#00ff88"
        st.markdown(f"<div class='card'><div class='label'>Recession Signal</div><div class='big-number' style='color:{rec_color};'>{rec_signal}</div></div>", unsafe_allow_html=True)

    st.markdown(f"<div class='card' style='color:#DDDDDD; margin-bottom:12px;'>📌 <strong>What this means:</strong> {shape_meaning}</div>", unsafe_allow_html=True)

    fig_yc = go.Figure()
    fig_yc.add_trace(go.Scatter(
        x=maturities, y=normal_yields, mode="lines+markers",
        name="Normal curve (pre-2022)",
        line=dict(color="#555555", width=2, dash="dash"),
        marker=dict(size=7, color="#555555"),
    ))
    fig_yc.add_trace(go.Scatter(
        x=maturities, y=yields, mode="lines+markers+text",
        name="Current curve",
        line=dict(color="#00c3ff", width=3),
        marker=dict(size=10, color="#ffffff", line=dict(width=2, color="#00c3ff")),
        text=[f"{y:.2f}%" for y in yields], textposition="top center"
    ))
    fig_yc.add_trace(go.Scatter(
        x=maturities + maturities[::-1],
        y=yields + normal_yields[::-1],
        fill="toself", fillcolor="rgba(0,195,255,0.07)",
        line=dict(color="rgba(0,0,0,0)"), showlegend=False, hoverinfo="skip"
    ))
    fig_yc.update_layout(
        template="plotly_dark", height=360,
        margin=dict(l=40, r=40, t=50, b=40),
        xaxis_title="Maturity", yaxis_title="Yield (%)",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#333333"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        title="US Treasury Yield Curve — Current vs Normal"
    )
    st.plotly_chart(fig_yc, use_container_width=True)
    st.caption("Blue line = today's curve. Grey dashed = typical pre-2022 normal. The shaded area shows deviation from normal. Blue dipping below grey at the short end = Fed has pushed short-term rates unusually high.")

    if is_inverted:
        st.error("⚠️ Yield curve inverted. 2-year yield above the 10-year. Has preceded every US recession in 50 years. Expect more demand for gold, USD and bonds, less for equities.")

    st.markdown("---")

    with st.expander("📚 What is the yield curve? (Beginner guide)", expanded=False):
        st.markdown("""
**The basics:** Governments borrow by issuing bonds. A 2-year bond = borrow for 2 years. The yield is the interest rate paid.

**Why the shape matters:** Normally longer bonds pay higher yields. This creates an upward-sloping normal curve.

**The four shapes:**
- 🟢 **Steep** — strong growth expected. Good for banks and risk assets.
- 🟡 **Normal** — standard, moderate growth expected.
- 🟠 **Flat** — uncertainty. Credit starts to tighten.
- 🔴 **Inverted** — recession signal. Every US recession since 1970 was preceded by inversion.

**For flow traders:** Inverted or flat curve = more client demand for gold, Treasuries and USD. Less for equities and high-yield bonds.
        """)

    st.markdown("---")
    st.markdown("#### 🤖 AI Yield Curve Commentary")
    st.caption("GPT analyses the current curve shape and what it signals for markets and flow traders.")

    if st.button("🔄 Generate Yield Curve Commentary", key="yield_commentary_btn"):
        with st.spinner("Analysing yield curve..."):
            try:
                from gpt_layer import call_gpt_prose
                yc_prompt = f"""You are a senior fixed income strategist at a major investment bank.

CURRENT US TREASURY YIELD CURVE:
- 2Y: {curve["2Y"]:.2f}%, 5Y: {curve["5Y"]:.2f}%, 10Y: {curve["10Y"]:.2f}%, 30Y: {curve["30Y"]:.2f}%
- 2s10s spread: {slope_2s10s:+.2f}% ({"INVERTED" if is_inverted else "positive"})
- 5s30s spread: {slope_5s30s:+.2f}%, Shape: {curve_shape}

Write a concise 3-4 sentence commentary covering:
1. What the current curve shape tells us about growth and inflation expectations
2. What this means for a flow trader today
3. The single most important thing to watch on the yield curve right now

Bloomberg style. Direct. Plain prose only."""

                yc_commentary = call_gpt_prose(yc_prompt)
                st.session_state["yield_commentary"] = yc_commentary or "Could not generate commentary."
            except Exception as e:
                st.session_state["yield_commentary"] = f"Error: {e}"

    yc_text = st.session_state.get("yield_commentary", "Click above to generate an AI commentary on what the current yield curve signals.")
    st.markdown(f"<div class='card' style='line-height:1.7; color:#DDDDDD;'>{yc_text}</div>", unsafe_allow_html=True)


# =========================================================
# ======================= RISK TAB ========================
# =========================================================


    st.markdown("---")
    st.markdown("### 💬 Ask the Trading Assistant")
    st.caption("Ask anything about markets, trading, or what you see on this tab. Powered by GPT.")

    tab_chat_key = f"chat_history_Macro"
    if tab_chat_key not in st.session_state:
        st.session_state[tab_chat_key] = []

    for msg in st.session_state[tab_chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _question := st.chat_input(f"Ask about Macro...", key=f"chat_input_Macro"):
        st.session_state[tab_chat_key].append({"role": "user", "content": _question})
        with st.chat_message("user"):
            st.markdown(_question)

        inv_ctx  = str({k: v for k, v in st.session_state.get("inventory", {}).items() if v != 0}) or "Flat"
        pnl_ctx  = sum(st.session_state.get("pnl", {}).values())
        news_ctx = ""
        if news_df is not None and "headline" in news_df.columns:
            news_ctx = "\n".join(news_df["headline"].head(5).tolist())

        _system = f"""You are an expert trading assistant in a macro finance dashboard helping someone learn flow trading.
TAB CONTEXT: User is on the {"Macro"} tab.
DASHBOARD DATA: VIX={((prices.get("VIX") or {{}}).get("price","N/A"))}, S&P 500={((prices.get("S&P 500") or {{}}).get("change","N/A"))}%, Inventory={inv_ctx}, P&L=${pnl_ctx:,.0f}
HEADLINES: {news_ctx if news_ctx else "None"}
Be concise (2-4 sentences), explain jargon for beginners, and use the dashboard context when relevant."""

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _resp = call_gpt_prose(f"{_system}\n\nQuestion: {_question}")
                    if _resp:
                        st.markdown(_resp)
                        st.session_state[tab_chat_key].append({"role": "assistant", "content": _resp})
                    else:
                        st.markdown("Could not generate a response — check your OpenAI key.")
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key):
        if st.button("🗑️ Clear chat", key=f"clear_chat_Macro"):
            st.session_state[tab_chat_key] = []
            st.rerun()

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
    st.markdown("---")
    st.markdown("#### 🤖 AI Risk Narrative")
    st.caption("Uses live market data and the risk monitors above to generate a single trader-ready risk summary.")

    if st.button("🔄 Generate Risk Narrative", key="risk_narrative_btn"):
        with st.spinner("Analysing risk themes..."):
            try:
                from gpt_layer import call_gpt_prose
                risk_prompt = f"""You are a senior risk manager at a major investment bank writing a morning risk briefing.

LIVE MARKET DATA:
- VIX: {vix_price:.1f} ({vol_regime})
- S&P 500: {spx_change:+.2f}% today
- Copper: {copper_change:+.2f}%
- Gold: {gold_change:+.2f}%
- News Sentiment: {avg_sentiment:+.2f}
- Risk Regime: {risk_label} (score: {risk_score:+.2f})

Write a concise 3-4 sentence risk narrative that:
1. States the overall risk regime and what it means for flow traders today
2. Highlights the most important risk and why it matters
3. Gives one actionable observation for a flow trader

Bloomberg style. Direct. Plain prose only."""
                narrative = call_gpt_prose(risk_prompt)
                st.session_state["risk_narrative"] = narrative or "Could not generate narrative — check OpenAI key."
            except Exception as e:
                st.session_state["risk_narrative"] = f"Error: {e}"

    narrative = st.session_state.get("risk_narrative", "Click above to get an AI-powered summary of today's key risks.")
    st.markdown(f"<div class='card' style='line-height:1.7; color:#DDDDDD;'>{narrative}</div>", unsafe_allow_html=True)



    st.markdown("---")
    st.markdown("### 💬 Ask the Trading Assistant")
    st.caption("Ask anything about markets, trading, or what you see on this tab. Powered by GPT.")

    tab_chat_key = f"chat_history_Risk"
    if tab_chat_key not in st.session_state:
        st.session_state[tab_chat_key] = []

    for msg in st.session_state[tab_chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _question := st.chat_input(f"Ask about Risk...", key=f"chat_input_Risk"):
        st.session_state[tab_chat_key].append({"role": "user", "content": _question})
        with st.chat_message("user"):
            st.markdown(_question)

        inv_ctx  = str({k: v for k, v in st.session_state.get("inventory", {}).items() if v != 0}) or "Flat"
        pnl_ctx  = sum(st.session_state.get("pnl", {}).values())
        news_ctx = ""
        if news_df is not None and "headline" in news_df.columns:
            news_ctx = "\n".join(news_df["headline"].head(5).tolist())

        _system = f"""You are an expert trading assistant in a macro finance dashboard helping someone learn flow trading.
TAB CONTEXT: User is on the {"Risk"} tab.
DASHBOARD DATA: VIX={((prices.get("VIX") or {{}}).get("price","N/A"))}, S&P 500={((prices.get("S&P 500") or {{}}).get("change","N/A"))}%, Inventory={inv_ctx}, P&L=${pnl_ctx:,.0f}
HEADLINES: {news_ctx if news_ctx else "None"}
Be concise (2-4 sentences), explain jargon for beginners, and use the dashboard context when relevant."""

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _resp = call_gpt_prose(f"{_system}\n\nQuestion: {_question}")
                    if _resp:
                        st.markdown(_resp)
                        st.session_state[tab_chat_key].append({"role": "assistant", "content": _resp})
                    else:
                        st.markdown("Could not generate a response — check your OpenAI key.")
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key):
        if st.button("🗑️ Clear chat", key=f"clear_chat_Risk"):
            st.session_state[tab_chat_key] = []
            st.rerun()

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
    st.markdown("### 📈 Price History")
    st.caption("Trend context for each commodity — one day's move means little without knowing the recent direction.")

    COMMODITY_TICKERS = {
        "Brent Crude": "BZ=F", "WTI Crude": "CL=F", "Natural Gas": "NG=F",
        "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F",
        "Corn": "ZC=F", "Wheat": "ZW=F"
    }

    # Period selector
    period_map = {
        "1 Week": "5d", "1 Month": "1mo", "3 Months": "3mo",
        "6 Months": "6mo", "1 Year": "1y", "2 Years": "2y"
    }
    selected_period_label = st.select_slider(
        "Time period",
        options=list(period_map.keys()),
        value="1 Month",
        key="comm_history_period"
    )
    selected_period = period_map[selected_period_label]

    @st.cache_data(ttl=3600)
    def get_commodity_history(period):
        import yfinance as yf
        history = {}
        for name, ticker in COMMODITY_TICKERS.items():
            try:
                hist = yf.Ticker(ticker).history(period=period)
                if hist is not None and len(hist) > 5:
                    history[name] = {
                        "dates":  [str(d.date()) for d in hist.index],
                        "closes": [round(float(v), 4) for v in hist["Close"]]
                    }
            except Exception:
                pass
        return history

    with st.spinner(f"Loading {selected_period_label} history..."):
        comm_history = get_commodity_history(selected_period)

    spark_cols = st.columns(4)
    for i, name in enumerate(commodity_names):
        with spark_cols[i % 4]:
            if name in comm_history and comm_history[name]["closes"]:
                closes = comm_history[name]["closes"]
                dates  = comm_history[name]["dates"]
                start_price = closes[0]
                end_price   = closes[-1]
                pct_chg     = ((end_price - start_price) / start_price) * 100
                trend_color = "#00ff88" if pct_chg > 0 else "#ff4d4d"

                fig_spark = go.Figure(go.Scatter(
                    x=dates, y=closes, mode="lines",
                    line=dict(color=trend_color, width=2),
                    fill="tozeroy",
                    fillcolor="rgba(0,255,136,0.08)" if pct_chg > 0 else "rgba(255,77,77,0.08)",
                ))
                fig_spark.update_layout(
                    template="plotly_dark", height=120,
                    margin=dict(l=0, r=0, t=25, b=0),
                    title=dict(text=f"{name} ({pct_chg:+.1f}% {selected_period_label})", font=dict(size=11, color=trend_color), x=0),
                    xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                    yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                    showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
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
    risk_regime_flow = "risk-on" if float((prices.get("S&P 500") or {}).get("change") or 0) > 0 else "risk-off"

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



    st.markdown("---")
    st.markdown("### 💬 Ask the Trading Assistant")
    st.caption("Ask anything about markets, trading, or what you see on this tab. Powered by GPT.")

    tab_chat_key = f"chat_history_Commodities"
    if tab_chat_key not in st.session_state:
        st.session_state[tab_chat_key] = []

    for msg in st.session_state[tab_chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _question := st.chat_input(f"Ask about Commodities...", key=f"chat_input_Commodities"):
        st.session_state[tab_chat_key].append({"role": "user", "content": _question})
        with st.chat_message("user"):
            st.markdown(_question)

        inv_ctx  = str({k: v for k, v in st.session_state.get("inventory", {}).items() if v != 0}) or "Flat"
        pnl_ctx  = sum(st.session_state.get("pnl", {}).values())
        news_ctx = ""
        if news_df is not None and "headline" in news_df.columns:
            news_ctx = "\n".join(news_df["headline"].head(5).tolist())

        _system = f"""You are an expert trading assistant in a macro finance dashboard helping someone learn flow trading.
TAB CONTEXT: User is on the {"Commodities"} tab.
DASHBOARD DATA: VIX={((prices.get("VIX") or {{}}).get("price","N/A"))}, S&P 500={((prices.get("S&P 500") or {{}}).get("change","N/A"))}%, Inventory={inv_ctx}, P&L=${pnl_ctx:,.0f}
HEADLINES: {news_ctx if news_ctx else "None"}
Be concise (2-4 sentences), explain jargon for beginners, and use the dashboard context when relevant."""

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _resp = call_gpt_prose(f"{_system}\n\nQuestion: {_question}")
                    if _resp:
                        st.markdown(_resp)
                        st.session_state[tab_chat_key].append({"role": "assistant", "content": _resp})
                    else:
                        st.markdown("Could not generate a response — check your OpenAI key.")
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key):
        if st.button("🗑️ Clear chat", key=f"clear_chat_Commodities"):
            st.session_state[tab_chat_key] = []
            st.rerun()

with tabs[3]:
    render_sp500_tab()


# =========================================================
# =================== FLOW TRADING TAB ====================
# =========================================================


    st.markdown("---")
    st.markdown("### 💬 Ask the Trading Assistant")
    st.caption("Ask anything about markets, trading, or what you see on this tab. Powered by GPT.")

    tab_chat_key = f"chat_history_S&P500"
    if tab_chat_key not in st.session_state:
        st.session_state[tab_chat_key] = []

    for msg in st.session_state[tab_chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _question := st.chat_input(f"Ask about S&P500...", key=f"chat_input_S&P500"):
        st.session_state[tab_chat_key].append({"role": "user", "content": _question})
        with st.chat_message("user"):
            st.markdown(_question)

        inv_ctx  = str({k: v for k, v in st.session_state.get("inventory", {}).items() if v != 0}) or "Flat"
        pnl_ctx  = sum(st.session_state.get("pnl", {}).values())
        news_ctx = ""
        if news_df is not None and "headline" in news_df.columns:
            news_ctx = "\n".join(news_df["headline"].head(5).tolist())

        _system = f"""You are an expert trading assistant in a macro finance dashboard helping someone learn flow trading.
TAB CONTEXT: User is on the {"S&P500"} tab.
DASHBOARD DATA: VIX={((prices.get("VIX") or {{}}).get("price","N/A"))}, S&P 500={((prices.get("S&P 500") or {{}}).get("change","N/A"))}%, Inventory={inv_ctx}, P&L=${pnl_ctx:,.0f}
HEADLINES: {news_ctx if news_ctx else "None"}
Be concise (2-4 sentences), explain jargon for beginners, and use the dashboard context when relevant."""

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _resp = call_gpt_prose(f"{_system}\n\nQuestion: {_question}")
                    if _resp:
                        st.markdown(_resp)
                        st.session_state[tab_chat_key].append({"role": "assistant", "content": _resp})
                    else:
                        st.markdown("Could not generate a response — check your OpenAI key.")
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key):
        if st.button("🗑️ Clear chat", key=f"clear_chat_S&P500"):
            st.session_state[tab_chat_key] = []
            st.rerun()

with tabs[4]:
    render_flow_trading_tab()

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


    st.markdown("---")
    st.markdown("### 💬 Ask the Trading Assistant")
    st.caption("Ask anything about markets, trading, or what you see on this tab. Powered by GPT.")

    tab_chat_key = f"chat_history_Flow Trading"
    if tab_chat_key not in st.session_state:
        st.session_state[tab_chat_key] = []

    for msg in st.session_state[tab_chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _question := st.chat_input(f"Ask about Flow Trading...", key=f"chat_input_Flow Trading"):
        st.session_state[tab_chat_key].append({"role": "user", "content": _question})
        with st.chat_message("user"):
            st.markdown(_question)

        inv_ctx  = str({k: v for k, v in st.session_state.get("inventory", {}).items() if v != 0}) or "Flat"
        pnl_ctx  = sum(st.session_state.get("pnl", {}).values())
        news_ctx = ""
        if news_df is not None and "headline" in news_df.columns:
            news_ctx = "\n".join(news_df["headline"].head(5).tolist())

        _system = f"""You are an expert trading assistant in a macro finance dashboard helping someone learn flow trading.
TAB CONTEXT: User is on the {"Flow Trading"} tab.
DASHBOARD DATA: VIX={((prices.get("VIX") or {{}}).get("price","N/A"))}, S&P 500={((prices.get("S&P 500") or {{}}).get("change","N/A"))}%, Inventory={inv_ctx}, P&L=${pnl_ctx:,.0f}
HEADLINES: {news_ctx if news_ctx else "None"}
Be concise (2-4 sentences), explain jargon for beginners, and use the dashboard context when relevant."""

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _resp = call_gpt_prose(f"{_system}\n\nQuestion: {_question}")
                    if _resp:
                        st.markdown(_resp)
                        st.session_state[tab_chat_key].append({"role": "assistant", "content": _resp})
                    else:
                        st.markdown("Could not generate a response — check your OpenAI key.")
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key):
        if st.button("🗑️ Clear chat", key=f"clear_chat_Flow Trading"):
            st.session_state[tab_chat_key] = []
            st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 5 — TRADE IDEAS
# ══════════════════════════════════════════════════════════════
with tabs[5]:
    import json as _json
    from datetime import datetime as _dt2

    st.markdown("## 💡 Trade Ideas")
    st.caption("Structure and track your own market calls. Every idea needs an entry, target, stop and rationale — just like a real S&T desk. This builds the habit of thinking in structured trade terms, which is exactly what interviewers test.")

    # ── Initialise trade ideas state ────────────────────────────
    if "trade_ideas" not in st.session_state:
        st.session_state["trade_ideas"] = []

    # ── ASSET UNIVERSE ───────────────────────────────────────────
    TRADE_ASSETS = {
        "S&P 500":       "^GSPC",   "NASDAQ":        "^IXIC",
        "FTSE 100":      "^FTSE",   "EUR/USD":       "EURUSD=X",
        "GBP/USD":       "GBPUSD=X","USD/JPY":       "JPY=X",
        "Brent Crude":   "BZ=F",    "Gold":          "GC=F",
        "Silver":        "SI=F",    "Copper":        "HG=F",
        "Natural Gas":   "NG=F",    "US 10Y (IEF)":  "IEF",
        "US 30Y (TLT)":  "TLT",     "VIX":           "^VIX",
        "NVIDIA (NVDA)": "NVDA",    "Apple (AAPL)":  "AAPL",
        "Microsoft":     "MSFT",    "Amazon":        "AMZN",
    }

    @st.cache_data(ttl=300)
    def _get_live_price(ticker):
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period="2d")
            if hist is not None and len(hist) > 0:
                return round(float(hist["Close"].iloc[-1]), 4)
        except Exception:
            pass
        return None

    def _update_idea_status(idea):
        """Check if idea has hit target or stop."""
        if idea["status"] != "Open":
            return idea
        ticker = TRADE_ASSETS.get(idea["asset"])
        if not ticker:
            return idea
        price = _get_live_price(ticker)
        if price is None:
            return idea
        idea["current_price"] = price
        entry = idea["entry_price"]
        target = idea["target"]
        stop   = idea["stop"]
        direction = 1 if idea["direction"] == "BUY" else -1
        pnl_pct = ((price - entry) / entry) * 100 * direction
        idea["pnl_pct"] = round(pnl_pct, 2)
        # Check hit levels
        if direction == 1:
            if price >= target:
                idea["status"] = "✅ Won"
            elif price <= stop:
                idea["status"] = "❌ Lost"
        else:
            if price <= target:
                idea["status"] = "✅ Won"
            elif price >= stop:
                idea["status"] = "❌ Lost"
        return idea

    # Update all open ideas
    st.session_state["trade_ideas"] = [
        _update_idea_status(i) for i in st.session_state["trade_ideas"]
    ]

    # ── SCORECARD ────────────────────────────────────────────────
    ideas = st.session_state["trade_ideas"]
    if ideas:
        won   = [i for i in ideas if i["status"] == "✅ Won"]
        lost  = [i for i in ideas if i["status"] == "❌ Lost"]
        open_ = [i for i in ideas if i["status"] == "Open"]
        hit_rate = round(len(won) / (len(won) + len(lost)) * 100) if (won or lost) else 0
        avg_rr   = round(sum(i.get("risk_reward",0) for i in ideas) / len(ideas), 2)
        total_pnl_ideas = sum(i.get("pnl_pct", 0) for i in ideas if i["status"] != "Open")

        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        with sc1:
            st.markdown(f"<div class='card'><div class='label'>Open Ideas</div><div class='big-number' style='color:#FFDC00;'>{len(open_)}</div></div>", unsafe_allow_html=True)
        with sc2:
            st.markdown(f"<div class='card'><div class='label'>Won</div><div class='big-number' style='color:#00ff88;'>{len(won)}</div></div>", unsafe_allow_html=True)
        with sc3:
            st.markdown(f"<div class='card'><div class='label'>Lost</div><div class='big-number' style='color:#ff4d4d;'>{len(lost)}</div></div>", unsafe_allow_html=True)
        with sc4:
            hr_color = "#00ff88" if hit_rate >= 50 else "#ff4d4d"
            st.markdown(f"<div class='card'><div class='label'>Hit Rate</div><div class='big-number' style='color:{hr_color};'>{hit_rate}%</div></div>", unsafe_allow_html=True)
        with sc5:
            rr_color = "#00ff88" if avg_rr >= 2 else "#FFDC00"
            st.markdown(f"<div class='card'><div class='label'>Avg Risk/Reward</div><div class='big-number' style='color:{rr_color};'>{avg_rr}:1</div></div>", unsafe_allow_html=True)
        st.markdown("")

    st.markdown("---")

    # ── NEW TRADE IDEA FORM ──────────────────────────────────────
    st.markdown("### ➕ New Trade Idea")

    with st.form("new_trade_idea", clear_on_submit=True):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            asset = st.selectbox("Asset", list(TRADE_ASSETS.keys()))
        with fc2:
            direction = st.radio("Direction", ["BUY", "SELL"], horizontal=True)
        with fc3:
            horizon = st.selectbox("Time Horizon", ["Intraday", "1-3 Days", "1-2 Weeks", "1 Month", "3+ Months"])

        # Get live price for reference
        live_ref = _get_live_price(TRADE_ASSETS.get(asset, ""))
        if live_ref:
            st.caption(f"📌 Current live price: **{live_ref}**")

        fp1, fp2, fp3 = st.columns(3)
        with fp1:
            entry  = st.number_input("Entry Price", value=float(live_ref) if live_ref else 100.0, format="%.4f")
        with fp2:
            target = st.number_input("Target Price", value=float(live_ref * 1.03) if live_ref else 103.0, format="%.4f")
        with fp3:
            stop   = st.number_input("Stop Price",   value=float(live_ref * 0.98) if live_ref else 98.0,  format="%.4f")

        rationale = st.text_area(
            "Trade Rationale",
            placeholder="e.g. Fed pivot expected — real yields falling, gold breaking out above $2000 resistance with strong momentum. Risk: stronger than expected NFP could push yields higher.",
            height=100
        )

        catalysts = st.text_input(
            "Key Catalysts / Events to Watch",
            placeholder="e.g. Fed meeting Jun 12, CPI Jun 15, OPEC+ meeting"
        )

        tag = st.selectbox("Theme Tag", ["Macro", "Technical", "Rates", "FX", "Equity", "Commodity", "Risk-On", "Risk-Off", "Event-Driven"])

        submitted = st.form_submit_button("📌 Add Trade Idea", type="primary")

        if submitted:
            if not rationale.strip():
                st.error("Please add a rationale — this is the most important part of any trade idea.")
            else:
                # Compute risk/reward
                if direction == "BUY":
                    reward = abs(target - entry)
                    risk   = abs(entry - stop)
                else:
                    reward = abs(entry - target)
                    risk   = abs(stop - entry)
                rr = round(reward / risk, 2) if risk > 0 else 0

                new_idea = {
                    "id":            len(ideas) + 1,
                    "date":          _dt2.now().strftime("%Y-%m-%d %H:%M"),
                    "asset":         asset,
                    "direction":     direction,
                    "horizon":       horizon,
                    "entry_price":   entry,
                    "target":        target,
                    "stop":          stop,
                    "current_price": live_ref or entry,
                    "rationale":     rationale,
                    "catalysts":     catalysts,
                    "tag":           tag,
                    "risk_reward":   rr,
                    "status":        "Open",
                    "pnl_pct":       0.0,
                }
                st.session_state["trade_ideas"].append(new_idea)
                st.success(f"✅ Trade idea added! Risk/Reward: {rr}:1 {'⚠️ Below 2:1 — consider adjusting target or stop' if rr < 2 else '👍 Good R/R'}")
                st.rerun()

    st.markdown("---")

    # ── OPEN IDEAS ───────────────────────────────────────────────
    open_ideas = [i for i in ideas if i["status"] == "Open"]
    if open_ideas:
        st.markdown("### 📊 Open Positions")

        for idea in open_ideas:
            dir_color = "#00ff88" if idea["direction"] == "BUY" else "#ff4d4d"
            pnl       = idea.get("pnl_pct", 0)
            pnl_color = "#00ff88" if pnl > 0 else "#ff4d4d" if pnl < 0 else "#fff"
            cur_price = idea.get("current_price", idea["entry_price"])

            # Progress to target
            entry, target, stop = idea["entry_price"], idea["target"], idea["stop"]
            direction_mult = 1 if idea["direction"] == "BUY" else -1
            total_move = abs(target - entry)
            current_move = (cur_price - entry) * direction_mult
            progress = max(0, min(1, current_move / total_move)) if total_move > 0 else 0

            with st.container():
                st.markdown(
                    f"<div class='card' style='border-left:4px solid {dir_color}; margin-bottom:12px;'>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
                    f"<div>"
                    f"<span style='color:{dir_color}; font-weight:bold; font-size:16px;'>{idea['direction']} {idea['asset']}</span>"
                    f"<span style='color:#888; font-size:12px; margin-left:10px;'>{idea['tag']} | {idea['horizon']} | Added {idea['date']}</span>"
                    f"</div>"
                    f"<div style='text-align:right;'>"
                    f"<span style='color:{pnl_color}; font-size:18px; font-weight:bold;'>{pnl:+.2f}%</span>"
                    f"</div>"
                    f"</div>"
                    f"<div style='margin-top:8px; font-size:13px; color:#888;'>"
                    f"Entry: <strong style='color:#fff;'>{entry}</strong> &nbsp;|&nbsp; "
                    f"Current: <strong style='color:{pnl_color};'>{cur_price}</strong> &nbsp;|&nbsp; "
                    f"Target: <strong style='color:#00ff88;'>{target}</strong> &nbsp;|&nbsp; "
                    f"Stop: <strong style='color:#ff4d4d;'>{stop}</strong> &nbsp;|&nbsp; "
                    f"R/R: <strong>{idea['risk_reward']}:1</strong>"
                    f"</div>"
                    f"<div style='margin-top:6px; font-size:12px; color:#AAAAAA;'>{idea['rationale'][:150]}{'...' if len(idea['rationale']) > 150 else ''}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
                # Progress bar toward target
                st.progress(progress, text=f"{progress*100:.0f}% of the way to target")

                # Close button
                if st.button(f"✕ Close idea #{idea['id']}", key=f"close_idea_{idea['id']}"):
                    for i2 in st.session_state["trade_ideas"]:
                        if i2["id"] == idea["id"]:
                            i2["status"] = "🔒 Closed"
                    st.rerun()

        st.markdown("---")

    # ── CLOSED IDEAS ─────────────────────────────────────────────
    closed = [i for i in ideas if i["status"] != "Open"]
    if closed:
        st.markdown("### 📋 Trade History")
        for idea in reversed(closed):
            status_color = "#00ff88" if "Won" in idea["status"] else "#ff4d4d" if "Lost" in idea["status"] else "#888"
            pnl          = idea.get("pnl_pct", 0)
            pnl_color    = "#00ff88" if pnl > 0 else "#ff4d4d" if pnl < 0 else "#fff"
            dir_color    = "#00ff88" if idea["direction"] == "BUY" else "#ff4d4d"
            st.markdown(
                f"<div class='card' style='margin-bottom:6px; opacity:0.85;'>"
                f"<div style='display:flex; justify-content:space-between;'>"
                f"<div>"
                f"<span style='color:{status_color}; font-weight:bold;'>{idea['status']}</span>"
                f"<span style='color:{dir_color}; margin-left:8px; font-weight:bold;'>{idea['direction']} {idea['asset']}</span>"
                f"<span style='color:#888; font-size:12px; margin-left:8px;'>{idea['tag']} | {idea['date']}</span>"
                f"</div>"
                f"<div style='color:{pnl_color}; font-weight:bold;'>{pnl:+.2f}% | R/R: {idea['risk_reward']}:1</div>"
                f"</div>"
                f"<div style='font-size:12px; color:#888; margin-top:4px;'>Entry: {idea['entry_price']} → Target: {idea['target']} | Stop: {idea['stop']}</div>"
                f"<div style='font-size:11px; color:#666; margin-top:2px;'>{idea['rationale'][:120]}{'...' if len(idea['rationale']) > 120 else ''}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
        st.markdown("---")

    if not ideas:
        st.info("No trade ideas yet. Use the form above to add your first structured trade idea.")
        st.markdown("""
**How to write a good trade idea:**
- **Be specific** — "Long Brent Crude at $82" not "oil looks good"
- **Define your levels** — entry, target, and stop before you put it on
- **State your catalyst** — what event or data will prove you right?
- **Know your risk/reward** — aim for at least 2:1 (risk \$1 to make \$2)
- **Set a time horizon** — when will you know if you're wrong?
        """)

    # ── AI TRADE IDEA REVIEW ──────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🤖 AI Trade Idea Coach")
    st.caption("Get GPT feedback on your trade ideas — quality of rationale, risk/reward assessment, and what a senior trader might challenge you on.")

    if ideas:
        idea_to_review = st.selectbox(
            "Select idea to review",
            [f"#{i['id']} {i['direction']} {i['asset']} ({i['status']})" for i in ideas],
            key="idea_review_select"
        )
        selected_id = int(idea_to_review.split("#")[1].split(" ")[0])
        selected_idea = next((i for i in ideas if i["id"] == selected_id), None)

        if st.button("🔍 Review This Trade Idea", key="review_idea_btn"):
            if selected_idea:
                with st.spinner("Reviewing your trade idea..."):
                    try:
                        from gpt_layer import call_gpt_prose
                        review_prompt = f"""You are a senior S&T trader reviewing a junior analyst's trade idea. Be direct and constructive.

TRADE IDEA:
- Asset: {selected_idea['asset']}
- Direction: {selected_idea['direction']}
- Entry: {selected_idea['entry_price']}
- Target: {selected_idea['target']}
- Stop: {selected_idea['stop']}
- Risk/Reward: {selected_idea['risk_reward']}:1
- Time Horizon: {selected_idea['horizon']}
- Theme: {selected_idea['tag']}
- Status: {selected_idea['status']} | P&L: {selected_idea.get('pnl_pct', 0):+.2f}%

RATIONALE:
{selected_idea['rationale']}

CATALYSTS:
{selected_idea.get('catalysts', 'None specified')}

Please provide:
1. STRENGTHS (1-2 sentences): What is good about this trade idea?
2. WEAKNESSES (1-2 sentences): What is missing or poorly thought through?
3. RISK/REWARD ASSESSMENT: Is {selected_idea['risk_reward']}:1 appropriate for this trade?
4. WHAT A SENIOR TRADER WOULD ASK: 2-3 challenging questions they'd fire at you in a morning meeting
5. OVERALL RATING: Score /10 and one line on how to improve it

Be honest and rigorous — this person is trying to break into S&T."""

                        review = call_gpt_prose(review_prompt)
                        st.session_state["idea_review"] = review or "Could not generate review."
                    except Exception as e:
                        st.session_state["idea_review"] = f"Error: {e}"

        review_text = st.session_state.get("idea_review", "Select an idea above and click Review to get AI feedback.")
        st.markdown(f"<div class='card' style='line-height:1.8; color:#DDDDDD; white-space:pre-wrap;'>{review_text}</div>", unsafe_allow_html=True)
    else:
        st.info("Add a trade idea above to get AI coaching feedback on it.")

    # ── TAB CHAT ─────────────────────────────────────────────────
    _tab_name = "Trade Ideas"
    tab_chat_key = f"chat_history_{_tab_name}"
    if tab_chat_key not in st.session_state:
        st.session_state[tab_chat_key] = []

    st.markdown("---")
    st.markdown("### 💬 Ask the Trading Assistant")
    st.caption("Ask anything about trade structuring, risk/reward, or how to pitch a trade idea in an interview.")

    for msg in st.session_state[tab_chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _question := st.chat_input("Ask about trade ideas, structuring, or interview prep...", key="chat_input_Trade Ideas"):
        st.session_state[tab_chat_key].append({"role": "user", "content": _question})
        with st.chat_message("user"):
            st.markdown(_question)

        open_summary = "; ".join([f"{i['direction']} {i['asset']} ({i.get('pnl_pct',0):+.1f}%)" for i in open_ideas[:3]]) if open_ideas else "None"
        _system = f"""You are an expert S&T trading mentor helping someone break into investment banking sales and trading.
OPEN IDEAS: {open_summary}
Help with trade structuring, rationale writing, risk/reward thinking, and interview preparation.
Be concise (2-4 sentences) and direct."""

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _resp = call_gpt_prose(f"{_system}\n\nQuestion: {_question}")
                    if _resp:
                        st.markdown(_resp)
                        st.session_state[tab_chat_key].append({"role": "assistant", "content": _resp})
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key):
        if st.button("🗑️ Clear chat", key="clear_chat_Trade Ideas"):
            st.session_state[tab_chat_key] = []
            st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 6 — ECONOMIC CALENDAR
# ══════════════════════════════════════════════════════════════
with tabs[6]:
    import json as _json2
    from datetime import datetime as _dt3, timedelta as _td

    st.markdown("## 📅 Economic Calendar")
    st.caption("Track upcoming macro events, form your own forecast before each release, and train the instinct of connecting data to market moves — the core skill tested in every S&T interview.")
    st.markdown("---")

    # ── UPCOMING EVENTS DATABASE ─────────────────────────────────
    # Key recurring events with typical market impact
    ECON_EVENTS = [
        # US
        {"name": "US Non-Farm Payrolls (NFP)",       "country": "🇺🇸", "frequency": "Monthly (1st Friday)",  "importance": "🔴 HIGH",  "typical_surprise_impact": "Big miss = risk-off, bonds rally, USD falls. Big beat = rates rise, USD rallies, equities mixed.",    "assets_affected": ["S&P 500","US 10Y (IEF)","USD/JPY","Gold"]},
        {"name": "US CPI (Inflation)",                "country": "🇺🇸", "frequency": "Monthly (mid-month)",   "importance": "🔴 HIGH",  "typical_surprise_impact": "Hot CPI = rates spike, equities fall, USD rallies. Cool CPI = rally everything, bonds up.",         "assets_affected": ["US 10Y (IEF)","S&P 500","Gold","EUR/USD"]},
        {"name": "Federal Reserve Meeting (FOMC)",    "country": "🇺🇸", "frequency": "8x per year",           "importance": "🔴 HIGH",  "typical_surprise_impact": "Hawkish surprise = rates up, equities down, USD up. Dovish pivot = equity rally, bonds rally.",      "assets_affected": ["US 10Y (IEF)","S&P 500","Gold","USD/JPY","EUR/USD"]},
        {"name": "US GDP (Advance)",                  "country": "🇺🇸", "frequency": "Quarterly",             "importance": "🟡 MEDIUM","typical_surprise_impact": "Strong GDP = risk-on, rates may rise. Weak GDP = recession fears, bonds rally, equities fall.",       "assets_affected": ["S&P 500","US 10Y (IEF)","USD/JPY"]},
        {"name": "US Jobless Claims",                 "country": "🇺🇸", "frequency": "Weekly (Thursday)",     "importance": "🟡 MEDIUM","typical_surprise_impact": "Rising claims = labour market softening, dovish expectations build. Falling = hawkish pressure.",      "assets_affected": ["US 10Y (IEF)","S&P 500","USD/JPY"]},
        {"name": "US ISM Manufacturing PMI",          "country": "🇺🇸", "frequency": "Monthly (1st day)",     "importance": "🟡 MEDIUM","typical_surprise_impact": "Above 50 = expansion, risk-on. Below 50 = contraction signal, risk-off.",                            "assets_affected": ["S&P 500","Copper","USD/JPY"]},
        {"name": "US Retail Sales",                   "country": "🇺🇸", "frequency": "Monthly (mid-month)",   "importance": "🟡 MEDIUM","typical_surprise_impact": "Strong = consumer resilient, hawkish. Weak = slowdown fears, dovish.",                               "assets_affected": ["S&P 500","EUR/USD"]},
        {"name": "US PPI (Producer Prices)",          "country": "🇺🇸", "frequency": "Monthly",               "importance": "🟢 LOW",   "typical_surprise_impact": "Leading indicator for CPI. Hot PPI warns inflation pipeline is building.",                           "assets_affected": ["US 10Y (IEF)","Gold"]},
        # Europe
        {"name": "ECB Interest Rate Decision",        "country": "🇪🇺", "frequency": "8x per year",           "importance": "🔴 HIGH",  "typical_surprise_impact": "Hawkish = EUR rallies, European bonds fall. Dovish = EUR falls, peripheral spreads tighten.",        "assets_affected": ["EUR/USD","US 10Y (IEF)","Gold"]},
        {"name": "Eurozone CPI (Flash)",              "country": "🇪🇺", "frequency": "Monthly (end of month)","importance": "🟡 MEDIUM","typical_surprise_impact": "Hot = ECB hawkish expectations, EUR up. Cool = ECB cut expectations, EUR falls.",                    "assets_affected": ["EUR/USD","GBP/USD"]},
        {"name": "Eurozone GDP (Flash)",              "country": "🇪🇺", "frequency": "Quarterly",             "importance": "🟡 MEDIUM","typical_surprise_impact": "Weak GDP increases ECB cut expectations, EUR falls. Strong = hawkish, EUR up.",                      "assets_affected": ["EUR/USD","GBP/USD"]},
        {"name": "German IFO Business Climate",       "country": "🇩🇪", "frequency": "Monthly",               "importance": "🟢 LOW",   "typical_surprise_impact": "Germany is Europe's largest economy. Weak IFO = European risk-off, EUR falls.",                     "assets_affected": ["EUR/USD"]},
        # UK
        {"name": "Bank of England Meeting (MPC)",     "country": "🇬🇧", "frequency": "8x per year",           "importance": "🔴 HIGH",  "typical_surprise_impact": "Hawkish = GBP rallies, gilts sell off. Dovish = GBP falls, gilts rally.",                          "assets_affected": ["GBP/USD","US 10Y (IEF)"]},
        {"name": "UK CPI",                            "country": "🇬🇧", "frequency": "Monthly",               "importance": "🟡 MEDIUM","typical_surprise_impact": "Hot UK CPI = BoE hawkish, GBP rallies. Cool = BoE cut expectations, GBP falls.",                   "assets_affected": ["GBP/USD"]},
        {"name": "UK GDP",                            "country": "🇬🇧", "frequency": "Monthly",               "importance": "🟢 LOW",   "typical_surprise_impact": "Weak GDP = recession fears, GBP falls. Strong = BoE stays hawkish, GBP up.",                       "assets_affected": ["GBP/USD"]},
        # China
        {"name": "China PMI (Caixin Manufacturing)",  "country": "🇨🇳", "frequency": "Monthly (1st day)",     "importance": "🟡 MEDIUM","typical_surprise_impact": "Strong China PMI = copper rallies, risk-on in Asia, global growth optimism.",                       "assets_affected": ["Copper","Brent Crude","S&P 500"]},
        {"name": "China GDP",                         "country": "🇨🇳", "frequency": "Quarterly",             "importance": "🔴 HIGH",  "typical_surprise_impact": "Weak China GDP = global growth fears, commodities sell off, EM currencies fall.",                    "assets_affected": ["Copper","Brent Crude","Gold"]},
        # Commodities/Other
        {"name": "OPEC+ Meeting",                     "country": "🌍",  "frequency": "Periodic",              "importance": "🔴 HIGH",  "typical_surprise_impact": "Production cut = oil rallies. Production increase = oil falls. Key for energy sector.",              "assets_affected": ["Brent Crude","Natural Gas"]},
        {"name": "EIA Crude Oil Inventories",         "country": "🇺🇸", "frequency": "Weekly (Wednesday)",    "importance": "🟢 LOW",   "typical_surprise_impact": "Large inventory build = oil falls (oversupply). Large draw = oil rallies (demand strong).",         "assets_affected": ["Brent Crude","Natural Gas"]},
        {"name": "US 10Y Treasury Auction",           "country": "🇺🇸", "frequency": "Monthly",               "importance": "🟡 MEDIUM","typical_surprise_impact": "Weak auction (low demand) = yields rise, bonds fall. Strong = yields fall, bonds rally.",            "assets_affected": ["US 10Y (IEF)","US 30Y (TLT)","Gold"]},
    ]

    # ── SECTION 1: MARKET IMPACT TRAINING ───────────────────────
    st.markdown("### 🎯 Market Impact Training")
    st.caption("Pick an economic event, enter your forecast vs the consensus, and GPT will walk you through exactly what would happen to each market — training the reflex that S&T interviewers test.")

    importance_filter = st.multiselect(
        "Filter by importance",
        ["🔴 HIGH", "🟡 MEDIUM", "🟢 LOW"],
        default=["🔴 HIGH", "🟡 MEDIUM"],
        key="econ_filter"
    )
    country_filter = st.multiselect(
        "Filter by country",
        ["🇺🇸", "🇪🇺", "🇬🇧", "🇨🇳", "🇩🇪", "🌍"],
        default=["🇺🇸", "🇪🇺", "🇬🇧"],
        key="econ_country_filter"
    )

    filtered_events = [e for e in ECON_EVENTS
                       if e["importance"] in importance_filter
                       and e["country"] in country_filter]

    selected_event_name = st.selectbox(
        "Select economic event",
        [f"{e['country']} {e['name']}" for e in filtered_events],
        key="econ_event_select"
    )
    selected_event = next((e for e in filtered_events
                           if f"{e['country']} {e['name']}" == selected_event_name), None)

    if selected_event:
        # Event info card
        st.markdown(
            f"<div class='card' style='margin-bottom:12px;'>"
            f"<div style='font-size:18px; font-weight:bold;'>{selected_event['country']} {selected_event['name']}</div>"
            f"<div style='color:#888; font-size:13px; margin-top:4px;'>{selected_event['importance']} &nbsp;|&nbsp; {selected_event['frequency']}</div>"
            f"<div style='color:#AAAAAA; font-size:13px; margin-top:6px;'>Assets affected: {', '.join(selected_event['assets_affected'])}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

        st.markdown("#### 📊 Typical Surprise Impact")
        st.info(selected_event["typical_surprise_impact"])

        st.markdown("---")
        st.markdown("#### 🧠 Scenario Training — What Would Happen If...")

        col_prev, col_cons, col_actual = st.columns(3)
        with col_prev:
            previous = st.text_input("Previous reading", placeholder="e.g. 150k / 2.3% / 52.1", key="econ_previous")
        with col_cons:
            consensus = st.text_input("Consensus forecast", placeholder="e.g. 180k / 2.5% / 51.0", key="econ_consensus")
        with col_actual:
            actual = st.text_input("Actual / Your forecast", placeholder="e.g. 250k / 3.1% / 48.5", key="econ_actual")

        scenario_type = st.radio(
            "Scenario",
            ["Big Beat (much better than expected)", "Small Beat", "In Line", "Small Miss", "Big Miss (much worse than expected)"],
            horizontal=True,
            key="econ_scenario"
        )

        if st.button("🔍 Analyse Market Impact", key="econ_analyse_btn", type="primary"):
            with st.spinner("Analysing market impact..."):
                try:
                    from gpt_layer import call_gpt_prose

                    # Get current market context
                    vix_ctx = (prices.get("VIX") or {}).get("price", "N/A")
                    spx_ctx = (prices.get("S&P 500") or {}).get("change", "N/A")

                    impact_prompt = f"""You are a senior S&T trader explaining the market impact of an economic data release to a junior analyst.

EVENT: {selected_event['name']} ({selected_event['country']})
Previous: {previous or 'Not specified'}
Consensus: {consensus or 'Not specified'}
Actual/Forecast: {actual or 'Not specified'}
Scenario: {scenario_type}

CURRENT MARKET CONTEXT:
VIX: {vix_ctx} | S&P 500: {spx_ctx}% today

PRIMARY ASSETS AFFECTED: {', '.join(selected_event['assets_affected'])}

Please provide a STRUCTURED market impact analysis covering:

**IMMEDIATE REACTION (0-5 minutes)**
What happens in the first few minutes across rates, FX, equities, and commodities? Be specific with direction and magnitude (e.g. "US 10Y yields spike 8-12bps", "EUR/USD drops 50-80 pips", "S&P futures fall 0.5-1%").

**FLOW IMPLICATIONS (What clients will do)**
What will institutional clients do in response? What orders will flow through the desk? Which assets will see buying/selling?

**SECOND-ORDER EFFECTS (30 mins - 1 day)**
What happens next as traders reassess positioning? Any sector rotation? Cross-asset themes?

**THE KEY TRADE**
If this scenario played out, what is the single best trade to express it? Be specific: direction, instrument, rationale, rough target.

**INTERVIEW ANSWER**
Write a 2-sentence answer that a sharp junior trader would give if asked "NFP just printed X — what do you do?" in a morning meeting.

Be specific with numbers. Use trading desk language. This person is trying to learn S&T."""

                    impact = call_gpt_prose(impact_prompt)
                    st.session_state["econ_impact"] = impact or "Could not generate analysis."
                except Exception as e:
                    st.session_state["econ_impact"] = f"Error: {e}"

        impact_text = st.session_state.get("econ_impact", "Fill in the fields above and click Analyse to see what would happen across markets.")
        if st.session_state.get("econ_impact"):
            st.markdown(f"<div class='card' style='line-height:1.8; color:#DDDDDD; white-space:pre-wrap;'>{impact_text}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── SECTION 2: EVENT REFERENCE GUIDE ────────────────────────
    st.markdown("### 📖 Event Reference Guide")
    st.caption("A quick reference for every major macro release — what it measures, why it matters, and the typical market reaction to a surprise.")

    for importance in ["🔴 HIGH", "🟡 MEDIUM", "🟢 LOW"]:
        events_in_group = [e for e in ECON_EVENTS if e["importance"] == importance]
        if not events_in_group:
            continue

        label = {"🔴 HIGH": "High Impact Events", "🟡 MEDIUM": "Medium Impact Events", "🟢 LOW": "Lower Impact Events"}[importance]
        with st.expander(f"{importance} — {label} ({len(events_in_group)} events)", expanded=(importance == "🔴 HIGH")):
            for event in events_in_group:
                st.markdown(
                    f"<div class='card' style='margin-bottom:8px;'>"
                    f"<div style='font-weight:bold; font-size:14px;'>{event['country']} {event['name']} <span style='color:#888; font-size:12px; font-weight:normal;'>— {event['frequency']}</span></div>"
                    f"<div style='color:#AAAAAA; font-size:12px; margin-top:4px;'>Assets: {', '.join(event['assets_affected'])}</div>"
                    f"<div style='color:#DDDDDD; font-size:12px; margin-top:4px;'>{event['typical_surprise_impact']}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

    st.markdown("---")

    # ── SECTION 3: MACRO CALENDAR CHEAT SHEET ───────────────────
    st.markdown("### 🗓️ Weekly Macro Calendar")
    st.caption("The typical weekly rhythm of macro data releases. Knowing this calendar by heart is expected of every S&T analyst.")

    week_data = {
        "Monday":    ["🇨🇳 China PMI (monthly, 1st Mon)", "🇪🇺 Eurozone PMI", "🇬🇧 UK PMI"],
        "Tuesday":   ["🇺🇸 ISM Manufacturing PMI (1st Tue)", "🇺🇸 JOLTS Job Openings", "🇬🇧 UK Employment"],
        "Wednesday": ["🇺🇸 ADP Employment (before NFP week)", "🇺🇸 EIA Oil Inventories", "🇺🇸 FOMC Minutes (periodic)"],
        "Thursday":  ["🇺🇸 Weekly Jobless Claims", "🇪🇺 ECB Meeting (periodic)", "🇬🇧 BoE Meeting (periodic)"],
        "Friday":    ["🇺🇸 Non-Farm Payrolls (1st Friday)", "🇺🇸 CPI (mid-month)", "🇺🇸 Retail Sales (mid-month)"],
    }

    day_cols = st.columns(5)
    day_colors = {"Monday": "#333", "Tuesday": "#333", "Wednesday": "#1a1a2e", "Thursday": "#333", "Friday": "#1a3a1a"}
    for col, (day, events_list) in zip(day_cols, week_data.items()):
        with col:
            st.markdown(f"<div class='card' style='background:{day_colors[day]};'><div class='label' style='color:#00c3ff;'>{day.upper()}</div>", unsafe_allow_html=True)
            for ev in events_list:
                st.markdown(f"<div style='font-size:11px; color:#DDDDDD; margin-top:4px;'>• {ev}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    st.caption("Friday is the most important day — NFP can move every asset class simultaneously. Wednesday is key for energy traders (EIA inventories). Thursday is crucial for rates traders in Europe (ECB/BoE meetings).")

    st.markdown("---")

    # ── SECTION 4: INTERVIEW QUICK FIRE ─────────────────────────
    st.markdown("### ⚡ Quick Fire: Data Release Interview Questions")
    st.caption("Common S&T interview questions about economic data. Click Generate to get a random one and practice your answer.")

    QUICK_FIRE_QS = [
        "NFP just came in at 280k vs 190k expected. Walk me through what happens to rates, equities, and the dollar.",
        "US CPI prints 3.8% vs 3.2% expected. What's your immediate trade?",
        "The Fed just hiked 25bps but signalled a pause. EUR/USD is up 80 pips. Is that the right move?",
        "China PMI comes in at 47.2 vs 50.5 expected. What happens to copper and why?",
        "UK CPI surprises to the upside at 5.2% vs 4.8%. Walk me through the GBP reaction.",
        "OPEC announces a surprise 1 million barrel/day production cut. What do you buy and what do you sell?",
        "US 10Y auction comes in with a tail — demand was much weaker than expected. What does this mean for markets?",
        "The ECB is dovish but the Fed is hawkish. What does that mean for EUR/USD over the next month?",
        "US GDP comes in at -0.3% for Q2 — two consecutive negative quarters. How does the market react?",
        "ISM Manufacturing PMI drops to 44.5 — its lowest in two years. What rotations do you expect in equities?",
        "German IFO drops sharply. You're long EUR/USD. Do you hold or cut?",
        "The Fed pauses but core CPI is still at 3.5%. What's the market's dilemma and how do you trade it?",
    ]

    if st.button("🎲 Generate Question", key="quickfire_btn"):
        import random as _rand
        st.session_state["quickfire_q"] = _rand.choice(QUICK_FIRE_QS)
        st.session_state.pop("quickfire_answer", None)

    if "quickfire_q" in st.session_state:
        st.markdown(f"<div class='card' style='border-left:4px solid #00c3ff; font-size:16px; font-weight:bold; color:#FFFFFF;'>❓ {st.session_state['quickfire_q']}</div>", unsafe_allow_html=True)
        st.markdown("")

        user_answer = st.text_area("Your answer:", height=100, key="quickfire_user_answer", placeholder="Type your answer as if you're in the interview...")

        if st.button("✅ Submit Answer for Feedback", key="quickfire_submit"):
            if not user_answer.strip():
                st.warning("Type your answer first.")
            else:
                with st.spinner("Evaluating your answer..."):
                    try:
                        from gpt_layer import call_gpt_prose
                        qa_prompt = f"""You are an S&T MD at a bulge bracket bank in London conducting a first-round interview. You are asking market knowledge questions to test whether this candidate can think on their feet about economic data and market reactions.

QUESTION: {st.session_state['quickfire_q']}
CANDIDATE'S ANSWER: {user_answer}

You are assessing:
- Did they get the direction of market moves right?
- Did they give specific magnitudes (bps, %, not just "up" or "down")?
- Did they cover multiple asset classes, not just one?
- Did they explain the mechanism, not just the conclusion?
- Would they sound credible saying this in a morning meeting?

Respond in this EXACT format:

SCORE: X/10

WHAT THEY GOT RIGHT:
[Specific correct points they made — quote their words if possible]

WHAT'S MISSING OR WRONG:
[Specific errors or gaps — be direct. Did they miss an asset class? Get a direction wrong? Skip the mechanism?]

THE IDEAL ANSWER:
[What a sharp junior trader would say — include specific numbers (e.g. "10Y yields spike 8-12bps", "EUR/USD drops 40-60 pips", "Gold rallies on real rate compression"). Explain the mechanism clearly.]

FOLLOW-UP QUESTION:
[The next question you'd ask to probe deeper — make it a hard one]

VERDICT: [Pass / Borderline / Fail — one sentence why]"""

                        feedback = call_gpt_prose(qa_prompt)
                        st.session_state["quickfire_answer"] = feedback or "Could not generate feedback."
                    except Exception as e:
                        st.session_state["quickfire_answer"] = f"Error: {e}"

        if "quickfire_answer" in st.session_state:
            st.markdown(f"<div class='card' style='line-height:1.8; color:#DDDDDD; white-space:pre-wrap;'>{st.session_state['quickfire_answer']}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── TAB CHAT ─────────────────────────────────────────────────
    _tab_name_ec = "Econ Calendar"
    tab_chat_key_ec = f"chat_history_{_tab_name_ec}"
    if tab_chat_key_ec not in st.session_state:
        st.session_state[tab_chat_key_ec] = []

    st.markdown("### 💬 Ask the Trading Assistant")
    st.caption("Ask anything about economic data, how to read releases, or how to answer data questions in interviews.")

    for msg in st.session_state[tab_chat_key_ec]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _qec := st.chat_input("Ask about economic data, market reactions, or interview prep...", key="chat_input_Econ Calendar"):
        st.session_state[tab_chat_key_ec].append({"role": "user", "content": _qec})
        with st.chat_message("user"):
            st.markdown(_qec)
        _sys_ec = """You are an expert macro trading mentor. Help with understanding economic data releases, market reactions, and S&T interview preparation. Be concise and use trading desk language."""
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _r = call_gpt_prose(f"{_sys_ec}\n\nQuestion: {_qec}")
                    if _r:
                        st.markdown(_r)
                        st.session_state[tab_chat_key_ec].append({"role": "assistant", "content": _r})
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key_ec):
        if st.button("🗑️ Clear chat", key="clear_chat_Econ Calendar"):
            st.session_state[tab_chat_key_ec] = []
            st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 7 — INTERVIEW PREP
# ══════════════════════════════════════════════════════════════
with tabs[7]:
    import random as _random

    st.markdown("## 🎓 Interview Prep")
    st.caption("Practice the questions that actually come up in S&T, IBD, and markets interviews. Choose your level, pick a mode, and get scored by GPT like a real interviewer would.")
    st.markdown("---")

    # ══════════════════════════════════════════════════════════
    # QUESTION BANK
    # ══════════════════════════════════════════════════════════
    QUESTION_BANK = {

        # ── S&T ──────────────────────────────────────────────
        "S&T": {
            "Beginner": [
                {"q": "What is a market maker and how do they make money?", "hint": "Think about bid/offer spreads and inventory risk."},
                {"q": "What is the difference between a broker and a dealer?", "hint": "One acts as agent, one acts as principal."},
                {"q": "What does 'going long' and 'going short' mean?", "hint": "Think about your expectation of price direction."},
                {"q": "What is the VIX and why do traders watch it?", "hint": "It measures implied volatility of S&P 500 options."},
                {"q": "Explain the difference between equities and bonds in one sentence.", "hint": "Think about ownership vs lending."},
                {"q": "What is a bid-offer spread and why does it exist?", "hint": "Compensation for providing liquidity and taking risk."},
                {"q": "Why would a company issue bonds instead of equity?", "hint": "Think about cost of capital and dilution."},
                {"q": "What does it mean to hedge a position?", "hint": "Reducing risk by taking an offsetting position."},
                {"q": "What is a futures contract?", "hint": "An agreement to buy or sell an asset at a future date and price."},
                {"q": "What is the difference between a primary and secondary market?", "hint": "Where securities are first issued vs where they are traded afterwards."},
            ],
            "Intermediate": [
                {"q": "Walk me through how a flow trader manages inventory risk after a large client trade.", "hint": "Think about hedging, timing, slippage, and market impact."},
                {"q": "What is the 2s10s spread and what does it tell you about the economy?", "hint": "Difference between 2Y and 10Y yields — shape of the curve matters."},
                {"q": "A client wants to buy $50m of S&P 500. You quote them. What risks are you taking on?", "hint": "Inventory, market impact, timing, delta risk."},
                {"q": "Explain how a repo transaction works.", "hint": "Short-term borrowing using securities as collateral."},
                {"q": "What is toxic flow and why does it cause losses for market makers?", "hint": "Informed clients who trade ahead of a price move."},
                {"q": "What happens to bond prices when interest rates rise?", "hint": "Inverse relationship — duration tells you how much."},
                {"q": "What is duration and why does it matter for a rates trader?", "hint": "Sensitivity of bond price to changes in yield."},
                {"q": "Explain the carry trade in FX markets.", "hint": "Borrow in low-rate currency, invest in high-rate currency."},
                {"q": "What is a credit default swap (CDS) and who uses them?", "hint": "Insurance against credit default — used to hedge or speculate."},
                {"q": "How does market impact affect a large hedge execution?", "hint": "Your own trade moves the market against you."},
            ],
            "Advanced": [
                {"q": "Explain delta-gamma hedging and when gamma becomes dangerous.", "hint": "Think about convexity and large moves near expiry."},
                {"q": "What is the vol surface and why isn't it flat?", "hint": "Implied vol varies by strike and expiry — skew and term structure."},
                {"q": "How would you price a variance swap and why would a client want one?", "hint": "Payoff based on realised vs implied variance."},
                {"q": "Walk me through the risks of being short gamma heading into a major data release.", "hint": "Large moves hurt you — think about vega, gamma, theta trade-offs."},
                {"q": "What is a synthetic CDO and how did it contribute to the 2008 crisis?", "hint": "Tranched exposure to credit risk via CDS — correlation assumptions broke down."},
                {"q": "Explain the difference between historical VaR and parametric VaR. Which do you prefer?", "hint": "Fat tails, normality assumptions, look-back periods."},
                {"q": "What is basis risk and give a real trading example where it caused a large loss.", "hint": "When your hedge doesn't perfectly offset your position — think Metallgesellschaft or LTCM."},
                {"q": "How would you structure a trade to profit from a steepening yield curve?", "hint": "Long the short end, short the long end — or use swaps."},
                {"q": "What is the difference between DV01 and duration?", "hint": "DV01 is dollar value of 1bp move — duration is percentage sensitivity."},
                {"q": "Explain how a central bank's quantitative easing programme affects FX markets.", "hint": "Money supply, real yields, capital flows, carry dynamics."},
            ],
        },

        # ── IBD ──────────────────────────────────────────────
        "IBD": {
            "Beginner": [
                {"q": "What is investment banking and how does it differ from commercial banking?", "hint": "Capital markets, advisory vs lending and deposits."},
                {"q": "What is an IPO and why would a company pursue one?", "hint": "First sale of shares to the public — access to capital, liquidity for founders."},
                {"q": "What are the three main valuation methodologies?", "hint": "DCF, comparable companies, precedent transactions."},
                {"q": "What does EBITDA stand for and why do bankers use it?", "hint": "Earnings before interest, tax, depreciation, amortisation — proxy for operating cash flow."},
                {"q": "What is the difference between enterprise value and equity value?", "hint": "EV includes debt; equity value is what shareholders own."},
                {"q": "What is a merger vs an acquisition?", "hint": "Merger = two companies combining as equals. Acquisition = one buys the other."},
                {"q": "What is leveraged buyout (LBO)?", "hint": "Acquisition using mostly debt — PE firms buy companies this way."},
                {"q": "What is a pitch book?", "hint": "A presentation bankers prepare to win mandates or present ideas to clients."},
                {"q": "What does 'accretive' mean in the context of M&A?", "hint": "The deal increases acquirer's EPS after completion."},
                {"q": "What is a fairness opinion?", "hint": "Independent assessment that the terms of a transaction are fair — typically required by a board."},
            ],
            "Intermediate": [
                {"q": "Walk me through a DCF valuation step by step.", "hint": "Project FCF, choose discount rate (WACC), terminal value, discount back to present."},
                {"q": "What is WACC and how do you calculate it?", "hint": "Weighted average of cost of equity and after-tax cost of debt."},
                {"q": "Why might two comparable companies trade at different EV/EBITDA multiples?", "hint": "Growth rate, margins, capex intensity, leverage, management quality."},
                {"q": "How does increasing leverage affect a company's WACC?", "hint": "Cheaper debt reduces WACC but increases equity risk — think Modigliani-Miller."},
                {"q": "What are synergies in M&A and how do you value them?", "hint": "Revenue synergies and cost synergies — be sceptical, they're often overstated."},
                {"q": "Walk me through how an LBO model works.", "hint": "Entry, financing structure, operating model, exit multiple, returns to PE sponsor."},
                {"q": "What is a convertible bond and why would a company issue one?", "hint": "Bond that converts to equity — lower coupon in exchange for upside optionality."},
                {"q": "What is the difference between a strategic buyer and a financial buyer in M&A?", "hint": "Strategic = industry player seeking synergies. Financial = PE firm seeking returns."},
                {"q": "How do you determine the appropriate discount rate for a DCF?", "hint": "WACC — cost of equity via CAPM plus after-tax cost of debt, weighted by capital structure."},
                {"q": "What happens to a company's share price if it announces an all-cash acquisition?", "hint": "Usually falls slightly on dilution fears / premium paid — unless market thinks it's transformative."},
            ],
            "Advanced": [
                {"q": "How does the treatment of deferred tax liabilities affect enterprise value in an acquisition?", "hint": "Acquirer inherits DTLs — they reduce equity value in a purchase price allocation."},
                {"q": "Explain how a cross-border M&A deal creates additional complexity vs a domestic deal.", "hint": "FX risk, regulatory approvals, cultural integration, tax structuring, repatriation issues."},
                {"q": "What is a poison pill and when would a board deploy one?", "hint": "Shareholder rights plan to dilute hostile acquirer — buys time for negotiation or white knight."},
                {"q": "Walk me through the tax implications of a stock deal vs a cash deal for the target's shareholders.", "hint": "Cash = immediate capital gains tax. Stock = tax-deferred until shares are sold."},
                {"q": "How would you advise a client on whether to pursue a hostile takeover vs a friendly approach?", "hint": "Cost, timeline, regulatory risk, board reaction, alternative uses of capital."},
                {"q": "What is NAV analysis and when is it more appropriate than a DCF or comps?", "hint": "Asset-heavy industries like real estate, mining — value the assets directly."},
                {"q": "Explain the concept of normalised earnings and when you would adjust EBITDA.", "hint": "Remove one-off items, restructuring charges, stock comp — to get sustainable earnings power."},
                {"q": "What is a reverse merger and what are its advantages for a private company?", "hint": "Private company merges with a listed shell — faster and cheaper than a full IPO."},
                {"q": "How does a rights issue affect existing shareholders and why might the market react negatively?", "hint": "Dilution — signals management thinks shares are overvalued or company needs cash urgently."},
                {"q": "What is the impact of goodwill impairment on financial statements?", "hint": "Non-cash charge — reduces net income and equity, but no cash flow or tax impact."},
            ],
        },

        # ── Markets ───────────────────────────────────────────
        "Markets": {
            "Beginner": [
                {"q": "What is inflation and why do central banks target 2%?", "hint": "Too high = purchasing power erodes. Too low = deflation risk. 2% gives room to cut rates."},
                {"q": "What is a central bank and what tools does it have?", "hint": "Sets interest rates, controls money supply, lender of last resort."},
                {"q": "Explain the relationship between interest rates and the economy.", "hint": "Higher rates = more expensive to borrow = slower growth = lower inflation."},
                {"q": "What is GDP and what does it measure?", "hint": "Total value of goods and services produced in an economy over a period."},
                {"q": "What is a recession?", "hint": "Two consecutive quarters of negative GDP growth — technically. But feels different in practice."},
                {"q": "Why does the dollar strengthen when risk-off sentiment increases?", "hint": "USD is the world's reserve currency — safe haven demand drives flows into USD assets."},
                {"q": "What is quantitative easing (QE)?", "hint": "Central bank buys bonds to inject money into the economy and push down long-term rates."},
                {"q": "What is the difference between fiscal policy and monetary policy?", "hint": "Fiscal = government spending/taxes. Monetary = central bank setting rates."},
                {"q": "Why do oil prices affect inflation?", "hint": "Energy is an input to almost everything — transport, manufacturing, heating."},
                {"q": "What is a yield and how is it different from a coupon?", "hint": "Coupon is fixed. Yield changes with price — they move inversely."},
            ],
            "Intermediate": [
                {"q": "How does the Fed's dual mandate create tension in policy decisions?", "hint": "Maximise employment AND stable prices — they often conflict, especially with supply shocks."},
                {"q": "Explain the transmission mechanism of monetary policy.", "hint": "Rate change → bank lending costs → corporate investment → consumer spending → inflation."},
                {"q": "What is the difference between headline CPI and core CPI and which matters more?", "hint": "Core strips out food and energy — less volatile, better indicator of underlying inflation."},
                {"q": "How do currency wars start and what are their consequences?", "hint": "Competitive devaluation — each country tries to weaken its currency to boost exports."},
                {"q": "What is the 'Greenspan put' and has it changed how markets behave?", "hint": "Belief the Fed will cut rates whenever markets fall — moral hazard, risk-taking encouraged."},
                {"q": "Why does copper sometimes act as a leading economic indicator?", "hint": "Used in construction, manufacturing, electronics — high demand signals growth. 'Dr Copper.'"},
                {"q": "What is the carry trade and what causes it to unwind violently?", "hint": "Borrow cheap, invest in high yield — unwinds when risk-off hits and funding dries up. Yen 2024."},
                {"q": "Explain how a strong dollar affects emerging markets.", "hint": "Dollar-denominated debt becomes more expensive, capital flows out, currencies weaken."},
                {"q": "What caused the 2023 UK gilt crisis and what does it tell us about fiscal credibility?", "hint": "Kwasi Kwarteng mini-budget — unfunded tax cuts spooked bond markets, LDI funds blow-up."},
                {"q": "What is the difference between a soft landing and a hard landing?", "hint": "Soft = inflation controlled without recession. Hard = recession required to break inflation."},
            ],
            "Advanced": [
                {"q": "Explain the mechanics of the 2008 financial crisis from mortgage origination to systemic collapse.", "hint": "Subprime → securitisation → CDO → AIG → interbank freeze → Lehman → government bailouts."},
                {"q": "What is the Fisher equation and how does it explain real vs nominal rates?", "hint": "Nominal rate = real rate + expected inflation. Real rates drive investment decisions."},
                {"q": "How does forward guidance work and what are its limitations?", "hint": "Central bank commits to future policy path — shapes expectations but credibility can be lost."},
                {"q": "What is secular stagnation and is it still a relevant concept post-COVID?", "hint": "Summers thesis — structurally low r* due to demographics and savings glut. COVID changed some assumptions."},
                {"q": "Explain the impossible trinity in international economics.", "hint": "Can't have fixed exchange rate, free capital flows, AND independent monetary policy simultaneously."},
                {"q": "How did the Bank of Japan's yield curve control policy affect global bond markets?", "hint": "Suppressed JGB yields globally, carry trade funding, eventual unwind caused yen squeeze."},
                {"q": "What is the neutral rate of interest (r*) and why does disagreement about it matter?", "hint": "The rate that neither stimulates nor restricts — if you don't know r* you don't know if policy is tight."},
                {"q": "Explain how a sovereign debt crisis develops and what the IMF's role is.", "hint": "Loss of market access → currency collapse → austerity demands → IMF conditionality → political instability."},
                {"q": "How does the repo market connect monetary policy to broader financial conditions?", "hint": "Overnight funding rate, collateral chains, Fed facilities — September 2019 repo spike as example."},
                {"q": "What is reflexivity in markets as described by George Soros and give a real example.", "hint": "Market prices affect fundamentals which affect prices — self-reinforcing loops. GBP 1992 or TMT bubble."},
            ],
        },
    }

    # Flatten all questions for quick fire
    ALL_QUESTIONS = []
    for category, levels in QUESTION_BANK.items():
        for level, qs in levels.items():
            for q in qs:
                ALL_QUESTIONS.append({**q, "category": category, "level": level})

    # ── PROGRESS TRACKER ─────────────────────────────────────
    if "prep_scores" not in st.session_state:
        st.session_state["prep_scores"] = []

    scores = st.session_state["prep_scores"]
    if scores:
        total  = len(scores)
        avg    = round(sum(s["score"] for s in scores) / total, 1)
        by_cat = {}
        by_level = {}
        for s in scores:
            by_cat.setdefault(s["category"], []).append(s["score"])
            by_level.setdefault(s.get("level",""), []).append(s["score"])

        # Identify weak spots — category + level combinations
        cat_avgs   = {c: round(sum(v)/len(v), 1) for c, v in by_cat.items()}
        level_avgs = {l: round(sum(v)/len(v), 1) for l, v in by_level.items() if l}
        best_cat   = max(cat_avgs, key=cat_avgs.get) if cat_avgs else "—"
        weak_cat   = min(cat_avgs, key=cat_avgs.get) if cat_avgs else "—"
        weak_level = min(level_avgs, key=level_avgs.get) if level_avgs else "—"

        # Last 3 questions for context
        recent_scores = scores[-3:]
        recent_avg    = round(sum(s["score"] for s in recent_scores) / len(recent_scores), 1)
        recent_trend  = "📈 Improving" if len(scores) >= 3 and recent_avg > avg else "📉 Declining" if len(scores) >= 3 and recent_avg < avg else "➡️ Steady"

        st.markdown("### 📊 Your Progress")
        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
        with pc1:
            st.markdown(f"<div class='card'><div class='label'>Questions Answered</div><div class='big-number'>{total}</div></div>", unsafe_allow_html=True)
        with pc2:
            avg_color = "#00ff88" if avg >= 7 else "#FFDC00" if avg >= 5 else "#ff4d4d"
            st.markdown(f"<div class='card'><div class='label'>Overall Average</div><div class='big-number' style='color:{avg_color};'>{avg}/10</div></div>", unsafe_allow_html=True)
        with pc3:
            trend_color = "#00ff88" if "Improving" in recent_trend else "#ff4d4d" if "Declining" in recent_trend else "#FFDC00"
            st.markdown(f"<div class='card'><div class='label'>Recent Trend</div><div class='big-number' style='color:{trend_color}; font-size:16px;'>{recent_trend}</div><div class='label'>{recent_avg}/10 last 3</div></div>", unsafe_allow_html=True)
        with pc4:
            st.markdown(f"<div class='card'><div class='label'>Strongest Area</div><div class='big-number' style='font-size:18px; color:#00ff88;'>{best_cat}</div><div class='label'>{cat_avgs.get(best_cat,'—')}/10 avg</div></div>", unsafe_allow_html=True)
        with pc5:
            weak_score = cat_avgs.get(weak_cat, "—")
            wc = "#ff4d4d" if isinstance(weak_score, float) and weak_score < 5 else "#FFDC00"
            st.markdown(f"<div class='card'><div class='label'>Weakest Area</div><div class='big-number' style='font-size:18px; color:{wc};'>{weak_cat}</div><div class='label'>{weak_score}/10 avg</div></div>", unsafe_allow_html=True)

        st.markdown("")

        # Per-category score breakdown bar
        if len(cat_avgs) > 1:
            fig_prog = go.Figure(go.Bar(
                x=list(cat_avgs.keys()),
                y=list(cat_avgs.values()),
                marker_color=["#00ff88" if v >= 7 else "#FFDC00" if v >= 5 else "#ff4d4d" for v in cat_avgs.values()],
                text=[f"{v}/10" for v in cat_avgs.values()],
                textposition="outside"
            ))
            fig_prog.update_layout(
                template="plotly_dark", height=220,
                margin=dict(l=20, r=20, t=20, b=20),
                yaxis=dict(range=[0,10], gridcolor="#333"),
                xaxis=dict(showgrid=False),
            )
            st.plotly_chart(fig_prog, use_container_width=True)

        # Recent question history
        with st.expander("📋 Question History", expanded=False):
            for s in reversed(scores[-10:]):
                sc = s["score"]
                sc_color = "#00ff88" if sc >= 7 else "#FFDC00" if sc >= 5 else "#ff4d4d"
                st.markdown(
                    f"<div style='padding:4px 0; border-bottom:1px solid #222; font-size:12px;'>"
                    f"<span style='color:{sc_color}; font-weight:bold;'>{sc}/10</span>"
                    f" &nbsp;|&nbsp; <span style='color:#888;'>{s.get('category','')} · {s.get('level','')}</span>"
                    f" &nbsp;|&nbsp; {s.get('question','')}"
                    f"</div>",
                    unsafe_allow_html=True
                )

        # ── ADAPTIVE LESSON GENERATOR ────────────────────────
        st.markdown("")
        st.markdown("#### 🎓 Adaptive Lesson")

        # Determine what to teach — prioritise the last low-scoring question
        last_weak = None
        for s in reversed(scores):
            if s["score"] <= 5:
                last_weak = s
                break

        if last_weak:
            if last_weak:
                weak_q = last_weak.get("question", "")
                weak_s = last_weak.get("score", 0)
                weak_l = last_weak.get("level", "")
                weak_c = last_weak.get("category", "")
                st.markdown(
                    f'<div class="card" style="border-left:3px solid #FFDC00;">'
                    f'<div style="color:#FFDC00; font-size:12px; font-weight:bold;">⚠️ WEAK SPOT DETECTED</div>'
                    f'<div style="color:#DDDDDD; font-size:13px; margin-top:4px;">'
                    f'You scored <strong>{weak_s}/10</strong> on a <strong>{weak_l} {weak_c}</strong> question: "{weak_q}..."'
                    '</div></div>',
                    unsafe_allow_html=True
                )
                lesson_context = f"Category: {weak_c} | Level: {weak_l} | Question: {weak_q}"
        else:
            # No low scores — teach the weakest category
            lesson_context = f"Category: {weak_cat} | Level: {weak_level} | Average score: {cat_avgs.get(weak_cat, 5)}/10"

        if st.button("📖 Generate Lesson for My Weak Spot", key="gen_lesson_btn", type="primary"):
            with st.spinner("Generating your personalised lesson..."):
                try:
                    from gpt_layer import call_gpt_prose

                    # Include last few wrong answers for extra context
                    wrong_qs = [s for s in scores if s["score"] <= 5][-3:]
                    wrong_context = "\n".join([
                        f"- {s.get('question','')} (scored {s['score']}/10)"
                        for s in wrong_qs
                    ]) if wrong_qs else "No specific wrong answers yet."

                    lesson_prompt = f"""You are a top-tier finance tutor who has trained graduates at Goldman Sachs, Morgan Stanley, and Barclays. A student is preparing for S&T and IBD interviews in London and has shown weakness in specific areas.

THEIR WEAK SPOT:
{lesson_context}

RECENT LOW-SCORING QUESTIONS:
{wrong_context}

OVERALL WEAK CATEGORY: {weak_cat} (avg {cat_avgs.get(weak_cat, 'N/A')}/10)

Write a focused, high-quality lesson that will directly improve their performance on these topics. Structure it as:

## THE CORE CONCEPT
[Explain the key concept they're struggling with in plain English — assume they have basic finance knowledge but are not expert. 3-4 sentences.]

## WHY IT MATTERS FOR INTERVIEWS
[Why does this come up? What are interviewers really testing when they ask about this? 2-3 sentences.]

## THE MENTAL MODEL
[Give them a simple framework or mental model they can use to structure their answer. Use an analogy if it helps. 3-4 sentences.]

## WORKED EXAMPLE
[Walk through a concrete, real-world example that illustrates the concept. Use real companies, real numbers, real events where possible. 4-5 sentences.]

## THE PERFECT INTERVIEW ANSWER
[Show them exactly how to answer a question on this topic in an interview. Write it as if they are speaking. 4-5 sentences that would genuinely impress an MD.]

## THREE THINGS TO REMEMBER
1. [Key fact or principle]
2. [Key fact or principle]
3. [Key fact or principle]

## PRACTICE QUESTION
[One follow-up question on this topic they should be able to answer after reading this lesson]

Write in a direct, teacher-to-student style. Be specific and practical — no generic finance textbook language."""

                    lesson = call_gpt_prose(lesson_prompt)
                    st.session_state["adaptive_lesson"] = lesson or "Could not generate lesson."
                except Exception as e:
                    st.session_state["adaptive_lesson"] = f"Error: {e}"

        if "adaptive_lesson" in st.session_state:
            st.markdown(
                f"<div class='card' style='line-height:1.9; color:#DDDDDD; white-space:pre-wrap;'>"
                f"{st.session_state['adaptive_lesson']}"
                f"</div>",
                unsafe_allow_html=True
            )

        if st.button("🗑️ Reset Progress", key="reset_prep"):
            for k in ["prep_scores", "adaptive_lesson", "qf_feedback", "drill_feedback"]:
                st.session_state.pop(k, None)
            st.rerun()
        st.markdown("---")

    # ── MODE SELECTOR ─────────────────────────────────────────
    st.markdown("### ⚙️ Settings")
    set1, set2, set3 = st.columns(3)
    with set1:
        prep_mode = st.radio("Mode", ["⚡ Quick Fire", "📚 Topic Drill"], horizontal=True, key="prep_mode")
    with set2:
        prep_level = st.selectbox("Difficulty", ["Beginner", "Intermediate", "Advanced", "Mixed"], key="prep_level")
    with set3:
        if prep_mode == "📚 Topic Drill":
            prep_category = st.selectbox("Category", ["S&T", "IBD", "Markets"], key="prep_category")
        else:
            prep_category = st.selectbox("Category", ["All", "S&T", "IBD", "Markets"], key="prep_category_qf")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════
    # MODE 1: QUICK FIRE
    # ══════════════════════════════════════════════════════════
    if prep_mode == "⚡ Quick Fire":
        st.markdown("### ⚡ Quick Fire")
        st.caption("One question at a time. Answer it, get scored, move on. Simulates the real interview pace.")

        if st.button("🎲 Get Question", key="qf_new_btn", type="primary"):
            # Filter by level and category
            pool = ALL_QUESTIONS.copy()
            if prep_level != "Mixed":
                pool = [q for q in pool if q["level"] == prep_level]
            if prep_category != "All":
                pool = [q for q in pool if q["category"] == prep_category]
            if pool:
                st.session_state["qf_question"] = _random.choice(pool)
                st.session_state.pop("qf_feedback", None)
                st.session_state.pop("qf_user_answer", None)
            else:
                st.warning("No questions match your filters.")

        if "qf_question" in st.session_state:
            q = st.session_state["qf_question"]
            level_colors = {"Beginner": "#00ff88", "Intermediate": "#FFDC00", "Advanced": "#ff4d4d"}
            lc = level_colors.get(q["level"], "#fff")

            st.markdown(
                f"<div class='card' style='border-left:4px solid {lc};'>"
                f"<div style='font-size:11px; color:#888; margin-bottom:6px;'>{q['category']} | "
                f"<span style='color:{lc};'>{q['level']}</span></div>"
                f"<div style='font-size:18px; font-weight:bold; color:#FFFFFF;'>❓ {q['q']}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            with st.expander("💡 Hint", expanded=False):
                st.markdown(f"*{q['hint']}*")

            answer = st.text_area("Your answer:", height=120, key=f"qf_ans_{q['q'][:20]}",
                                  placeholder="Answer as you would in an interview room — be specific and structured.")

            if st.button("✅ Submit for Feedback", key="qf_submit"):
                if not answer.strip():
                    st.warning("Write your answer first.")
                else:
                    with st.spinner("Scoring your answer..."):
                        try:
                            from gpt_layer import call_gpt_prose
                            prompt = f"""You are a senior {q['category']} professional at Goldman Sachs or Morgan Stanley conducting a first-round interview. You have 15 years of experience and you are assessing whether this candidate thinks like a banker or trader.

CONTEXT:
- Role: {q['category']} at a bulge bracket bank in London
- Question difficulty: {q['level']}
- Question: {q['q']}
- Candidate's answer: {answer}

WHAT YOU'RE ASSESSING:
- Technical accuracy (do they actually know the concept?)
- Structure (did they give a clear, organised answer or ramble?)
- Depth (did they go beyond the textbook definition?)
- Market awareness (did they connect it to the real world?)
- Confidence and precision (would you trust this person talking to a client?)

Respond in this EXACT format — no extra text before or after:

SCORE: X/10

WHAT YOU GOT RIGHT:
[2-3 specific things they did well — reference their actual words]

WHAT'S MISSING OR WRONG:
[2-3 specific gaps or errors — be direct, this is what loses them the job]

WHAT A TOP CANDIDATE WOULD SAY:
[4-5 sentences — the answer that would make you want to hire them. Include a specific real-world example or number if relevant]

FOLLOW-UP QUESTION:
[The one probing question you'd ask next to see if they really understand it]

VERDICT:
[One honest sentence: hire / strong maybe / weak maybe / no — and why]"""
                            feedback = call_gpt_prose(prompt)
                            st.session_state["qf_feedback"] = feedback
                            # Extract score
                            try:
                                score_line = [l for l in feedback.split("\n") if l.startswith("SCORE:")][0]
                                score = int(score_line.split(":")[1].strip().split("/")[0])
                            except Exception:
                                score = 5
                            st.session_state["prep_scores"].append({
                                "category": q["category"], "level": q["level"],
                                "question": q["q"][:60], "score": score
                            })
                        except Exception as e:
                            st.session_state["qf_feedback"] = f"Error: {e}"

            if "qf_feedback" in st.session_state:
                st.markdown(f"<div class='card' style='line-height:1.8; white-space:pre-wrap; color:#DDDDDD;'>{st.session_state['qf_feedback']}</div>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════
    # MODE 2: TOPIC DRILL
    # ══════════════════════════════════════════════════════════
    else:
        st.markdown(f"### 📚 Topic Drill — {prep_category}")
        st.caption("5 questions on your chosen topic and level, one after another. Builds depth and pattern recognition.")

        if st.button("🚀 Start Drill", key="drill_start", type="primary"):
            pool = QUESTION_BANK[prep_category].get(prep_level if prep_level != "Mixed" else "Intermediate", [])
            if prep_level == "Mixed":
                pool = []
                for lvl in ["Beginner", "Intermediate", "Advanced"]:
                    pool += QUESTION_BANK[prep_category].get(lvl, [])
                pool = [{**q, "level": lvl}
                        for lvl in ["Beginner", "Intermediate", "Advanced"]
                        for q in QUESTION_BANK[prep_category].get(lvl, [])]
            else:
                pool = [{**q, "level": prep_level} for q in pool]

            selected = _random.sample(pool, min(5, len(pool)))
            st.session_state["drill_questions"] = selected
            st.session_state["drill_index"]     = 0
            st.session_state["drill_answers"]   = []
            st.session_state.pop("drill_feedback", None)

        if "drill_questions" in st.session_state:
            questions  = st.session_state["drill_questions"]
            idx        = st.session_state.get("drill_index", 0)
            answers    = st.session_state.get("drill_answers", [])

            if idx < len(questions):
                q = questions[idx]
                level_colors = {"Beginner": "#00ff88", "Intermediate": "#FFDC00", "Advanced": "#ff4d4d"}
                lc = level_colors.get(q.get("level",""), "#fff")

                st.markdown(f"**Question {idx+1} of {len(questions)}**")
                st.progress((idx) / len(questions))

                st.markdown(
                    f"<div class='card' style='border-left:4px solid {lc};'>"
                    f"<div style='font-size:11px; color:#888;'>{prep_category} | <span style='color:{lc};'>{q.get('level','')}</span></div>"
                    f"<div style='font-size:18px; font-weight:bold; color:#FFFFFF; margin-top:4px;'>❓ {q['q']}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

                with st.expander("💡 Hint", expanded=False):
                    st.markdown(f"*{q['hint']}*")

                drill_ans = st.text_area("Your answer:", height=120, key=f"drill_ans_{idx}",
                                         placeholder="Be specific. Structure your answer: definition → mechanism → example.")

                if st.button("➡️ Submit & Next", key=f"drill_next_{idx}"):
                    if not drill_ans.strip():
                        st.warning("Please write an answer first.")
                    else:
                        answers.append({"q": q["q"], "a": drill_ans, "level": q.get("level",""), "hint": q["hint"]})
                        st.session_state["drill_answers"] = answers
                        st.session_state["drill_index"]   = idx + 1
                        st.rerun()

            else:
                # All questions answered — get full drill review
                st.success(f"✅ Drill complete! {len(answers)} questions answered.")
                st.markdown("---")

                if st.button("🤖 Get Full Drill Feedback", key="drill_feedback_btn", type="primary"):
                    with st.spinner("Reviewing all your answers..."):
                        try:
                            from gpt_layer import call_gpt_prose
                            qa_text = "\n\n".join([
                                f"Q{i+1}: {a['q']}\nLevel: {a['level']}\nAnswer: {a['a']}"
                                for i, a in enumerate(answers)
                            ])
                            drill_prompt = f"""You are a senior {prep_category} professional at a top investment bank in London, doing a post-interview debrief on a candidate who just answered 5 questions.

CANDIDATE'S ANSWERS:
{qa_text}

You are assessing: technical accuracy, depth of knowledge, real-world awareness, and communication clarity.

Give a thorough debrief in this format:

OVERALL SCORE: X/10

OVERALL ASSESSMENT:
[3-4 sentences — honest overall impression. Would you pass them to the next round?]

PER-QUESTION BREAKDOWN:
Q1 — SCORE: X/10 | [One sentence verdict] | [One specific thing to improve]
Q2 — SCORE: X/10 | [One sentence verdict] | [One specific thing to improve]
Q3 — SCORE: X/10 | [One sentence verdict] | [One specific thing to improve]
Q4 — SCORE: X/10 | [One sentence verdict] | [One specific thing to improve]
Q5 — SCORE: X/10 | [One sentence verdict] | [One specific thing to improve]

STRONGEST ANSWER: Q[N] — [Why this one stood out]

WEAKEST ANSWER: Q[N] — [What was missing and the ideal answer in 2-3 sentences]

KNOWLEDGE GAPS TO FIX:
1. [Specific topic/concept to study with a suggested resource or focus area]
2. [Specific topic/concept]
3. [Specific topic/concept]

INTERVIEW READINESS FOR {prep_category.upper()} AT A BULGE BRACKET:
[Honest verdict — are they ready now, nearly ready, or do they need significant work? What is the single most important thing to fix before their interview?]"""

                            feedback = call_gpt_prose(drill_prompt)
                            st.session_state["drill_feedback"] = feedback
                            try:
                                score_line = [l for l in feedback.split("\n") if "OVERALL SCORE:" in l][0]
                                score = int(score_line.split(":")[1].strip().split("/")[0])
                            except Exception:
                                score = 5
                            for a in answers:
                                st.session_state["prep_scores"].append({
                                    "category": prep_category, "level": a["level"],
                                    "question": a["q"][:60], "score": score
                                })
                        except Exception as e:
                            st.session_state["drill_feedback"] = f"Error: {e}"

                if "drill_feedback" in st.session_state:
                    st.markdown(f"<div class='card' style='line-height:1.8; white-space:pre-wrap; color:#DDDDDD;'>{st.session_state['drill_feedback']}</div>", unsafe_allow_html=True)

                if st.button("🔄 Start New Drill", key="drill_restart"):
                    for k in ["drill_questions","drill_index","drill_answers","drill_feedback"]:
                        st.session_state.pop(k, None)
                    st.rerun()

    st.markdown("---")

    # ── REFERENCE GUIDES ─────────────────────────────────────
    st.markdown("### 📖 Quick Reference Guides")
    st.caption("Key concepts you need to know cold before any S&T or IBD interview.")

    with st.expander("🏦 S&T — What Interviewers Always Ask", expanded=False):
        st.markdown("""
**The non-negotiables for S&T interviews:**
- **Your trade idea** — always have one ready. Asset, direction, entry, target, stop, catalyst, time horizon.
- **The yield curve** — know the 4 shapes, what each means, and the current shape.
- **Risk-on vs risk-off** — be able to name 3 assets that move in each regime and why.
- **A recent market event** — pick one from the last month and explain the cross-asset impact.
- **Flow trading mechanics** — bid/offer spread, inventory risk, hedging, toxic flow.
- **VIX** — what it is, what levels mean, and how traders use it.
- **One macro view** — "I think X because Y, and the trade is Z."

**Questions that trip people up:**
- "If the Fed cuts by 25bps, what happens to gold, the dollar, and 2-year yields — and in what order?"
- "Walk me through what happens to your book if a client sells you $100m of S&P 500."
- "What's the difference between vol and realised vol, and why does it matter?"
        """)

    with st.expander("📊 IBD — Technical Questions You Must Know", expanded=False):
        st.markdown("""
**The absolute minimum for IBD interviews:**
- **Walk me through a DCF** — know every step cold. Project FCF → WACC → terminal value → discount.
- **Three statements** — how do they link? Net income flows to retained earnings and cash flow statement.
- **What makes a good acquisition target?** — Strong FCF, fragmented market, synergy potential, reasonable price.
- **EV vs Equity Value** — know when to use each and how to bridge between them.
- **Dilution/accretion analysis** — can you work out if a deal is accretive in your head?

**Common technical traps:**
- "If depreciation increases by \$10, what happens to the three statements?"
- "Why can two companies with the same EBITDA trade at different multiples?"
- "What happens to EV if you issue new shares?"
        """)

    with st.expander("🌍 Markets — Macro Concepts You Need Cold", expanded=False):
        st.markdown("""
**What every markets candidate must know:**
- **Monetary policy transmission** — how does a rate hike actually slow inflation? Walk through the chain.
- **The Fed's dual mandate** — maximum employment AND price stability. Know the tension between them.
- **Safe haven assets** — gold, USD, JPY, US Treasuries. Know why each is a safe haven and when they diverge.
- **Oil and the economy** — why oil is an input to everything and how oil shocks cause recessions.
- **The carry trade** — borrow in JPY, invest in high-yield currencies. Know what causes violent unwinds.

**Always read before an interview:**
- What did the Fed/BoE/ECB say at their last meeting?
- What is the current state of inflation in the US and UK?
- What is the 2s10s spread today and is the curve inverted?
- What happened to markets last week and why?
        """)

    # ── TAB CHAT ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 💬 Ask the Interview Coach")
    st.caption("Ask anything about interview prep, finance concepts, or how to answer specific questions.")

    _tab_ip = "Interview Prep"
    tab_chat_key_ip = f"chat_history_{_tab_ip}"
    if tab_chat_key_ip not in st.session_state:
        st.session_state[tab_chat_key_ip] = []

    for msg in st.session_state[tab_chat_key_ip]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if _qip := st.chat_input("Ask about finance concepts, interview technique, or how to structure an answer...", key="chat_input_Interview Prep"):
        st.session_state[tab_chat_key_ip].append({"role": "user", "content": _qip})
        with st.chat_message("user"):
            st.markdown(_qip)
        _sys_ip = """You are an expert IB interview coach helping someone break into S&T and IBD at a top investment bank in London.
Answer finance and interview questions clearly and directly. Explain concepts like a senior banker would to a junior — precise, no fluff.
For interview technique questions, give specific, actionable advice."""
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from gpt_layer import call_gpt_prose
                    _r = call_gpt_prose(f"{_sys_ip}\n\nQuestion: {_qip}")
                    if _r:
                        st.markdown(_r)
                        st.session_state[tab_chat_key_ip].append({"role": "assistant", "content": _r})
                except Exception as e:
                    st.markdown(f"Error: {e}")

    if st.session_state.get(tab_chat_key_ip):
        if st.button("🗑️ Clear chat", key="clear_chat_Interview Prep"):
            st.session_state[tab_chat_key_ip] = []
            st.rerun()