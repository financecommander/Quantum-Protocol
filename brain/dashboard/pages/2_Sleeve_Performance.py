"""Page 2: Sleeve Performance — per-sleeve deep dive with eval accounts."""

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

st.title("🎯 Sleeve Performance")

# Sleeve selector
sleeve = st.selectbox("Select Sleeve", [
    "Sleeve 1: Treasury Yield",
    "Sleeve 2: Compression & Curve",
    "Sleeve 3: Prop Scaling",
    "Sleeve 5: Convexity Shield",
])

st.divider()

if sleeve == "Sleeve 3: Prop Scaling":
    st.subheader("Eval Account Dashboard")

    # Simulated eval accounts
    accounts = [
        {"id": "EVAL-001", "phase": "SCALING", "capital": 20_000, "mult": "2x", "return": "+12.4%", "dd": "-2.1%", "wr": "82%", "trades": 14, "days": 8},
        {"id": "EVAL-002", "phase": "SCALING", "capital": 40_000, "mult": "4x", "return": "+8.7%", "dd": "-1.8%", "wr": "75%", "trades": 22, "days": 15},
        {"id": "EVAL-003", "phase": "EVAL", "capital": 10_800, "mult": "1x", "return": "+8.0%", "dd": "-3.2%", "wr": "80%", "trades": 5, "days": 12},
        {"id": "EVAL-004", "phase": "EVAL", "capital": 9_200, "mult": "1x", "return": "-8.0%", "dd": "-5.1%", "wr": "60%", "trades": 5, "days": 20},
        {"id": "EVAL-005", "phase": "EVAL", "capital": 10_500, "mult": "1x", "return": "+5.0%", "dd": "-1.5%", "wr": "71%", "trades": 7, "days": 18},
    ]

    # KPIs
    total_capital = sum(a["capital"] for a in accounts)
    active = [a for a in accounts if a["phase"] != "BREACHED"]
    scaling = [a for a in accounts if a["phase"] == "SCALING"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Capital", f"${total_capital:,.0f}")
    c2.metric("Active Accounts", len(active))
    c3.metric("Scaling", len(scaling))
    c4.metric("Avg Win Rate", f"{sum(int(a['wr'].strip('%')) for a in accounts) / len(accounts):.0f}%")

    # Account table
    for acct in accounts:
        phase_color = "🟢" if acct["phase"] == "SCALING" else "🔵" if acct["phase"] == "EVAL" else "🔴"
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
        col1.write(f"{phase_color} **{acct['id']}** ({acct['phase']})")
        col2.write(f"Capital: ${acct['capital']:,.0f} ({acct['mult']})")
        col3.write(f"Return: {acct['return']}")
        col4.write(f"DD: {acct['dd']} | WR: {acct['wr']}")
        col5.write(f"Trades: {acct['trades']} | Day {acct['days']}/30")

    st.divider()

    # Signal source scorecard
    st.subheader("Signal Source Scorecard")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("RSI Signals", "18 trades")
        st.caption("Win rate: 72% | P&L: +$1,240")
    with c2:
        st.metric("Momentum Signals", "11 trades")
        st.caption("Win rate: 64% | P&L: +$380")
    with c3:
        st.metric("LLM Conviction", "6 trades")
        st.caption("Win rate: 83% | P&L: +$2,105")

    # Source comparison chart
    fig = go.Figure(data=[
        go.Bar(name="Win Rate", x=["RSI", "Momentum", "LLM"], y=[72, 64, 83], marker_color=["#2196F3", "#FF9800", "#4CAF50"]),
    ])
    fig.update_layout(
        height=250, margin=dict(t=30, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"), yaxis_title="Win Rate %",
        title="Signal Source Win Rate Comparison",
    )
    st.plotly_chart(fig, use_container_width=True)

elif sleeve == "Sleeve 1: Treasury Yield":
    st.subheader("Yield Curve Roll-Down")
    c1, c2, c3 = st.columns(3)
    c1.metric("Regime", "NORMAL")
    c2.metric("2s10s Spread", "72 bps")
    c3.metric("Position", "Long IEF/ZN")

    st.info("Quarterly rebalance in 34 days. Current monthly pickup: +0.24%")

elif sleeve == "Sleeve 2: Compression & Curve":
    st.subheader("Curve Trade Status")
    c1, c2, c3 = st.columns(3)
    c1.metric("Active Trade", "FLATTENER")
    c2.metric("Entry Spread", "112 bps")
    c3.metric("Current P&L", "-$42.00", "-0.6%")

    st.warning("Approaching stop loss (entry ± 20bps). Current: entry + 18bps.")

elif sleeve == "Sleeve 5: Convexity Shield":
    st.subheader("Hedge Status")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Regime", "ACCUMULATE")
    c2.metric("VIX", "14.8")
    c3.metric("Annual Budget Used", "0.4% / 2.0%")
    c4.metric("Collar Active", "Yes")

    st.success("VIX < 15 — cheap premium window. Collars active to offset drag.")
