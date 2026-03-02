"""
MATRIX PROTOCOL™ v1.0 — Dashboard

5-page Streamlit dashboard:
  1. Portfolio Overview (this page)
  2. Sleeve Performance
  3. Risk Monitor
  4. Signal Feed
  5. SERAPH AI Regime

Run: streamlit run dashboard/app.py
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import json
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard.state import get_portfolio_state, get_sleeve_allocations, is_live

st.set_page_config(
    page_title="Matrix Protocol™",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Sidebar ────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/color/96/matrix.png", width=60)
    st.title("MATRIX PROTOCOL™")
    st.caption("v1.0 — Brain Layer Dashboard")

    if is_live():
        st.success("🟢 Engine Connected")
    else:
        st.info("⚪ Simulated Data")

    st.divider()

    state = get_portfolio_state()

    # Kill switch status
    if state["kill_switch"]:
        st.error("🚨 KILL SWITCH ACTIVE")
    else:
        st.success("✅ Systems Normal")

    if state["human_approval_pending"]:
        st.warning("⚠️ Human Approval Pending")

    st.metric("Portfolio Value", f"${state['portfolio_value']:,.0f}")
    st.metric("VIX", f"{state['vix']:.1f}")
    st.metric("S&P 500", f"{state['spx']:,.0f}")
    st.metric("Regime", state["regime"])
    st.metric("Crisis Level", state["crisis_level"])

    st.divider()
    st.caption(f"Last update: {state['timestamp'].strftime('%H:%M:%S UTC')}")
    if st.button("🔄 Refresh"):
        from dashboard.state import invalidate_cache
        invalidate_cache()
        st.rerun()


# ─── Main Page: Portfolio Overview ──────────────────────────────

st.title("📊 Portfolio Overview")

# Top KPI row
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Daily P&L", f"${state['daily_pnl']:+,.2f}", f"{state['daily_pnl_pct']:+.2f}%")
with col2:
    st.metric("Total P&L", f"${state['total_pnl']:+,.2f}", f"{state['total_pnl_pct']:+.2f}%")
with col3:
    st.metric("Cash", f"${state['cash']:,.0f}")
with col4:
    st.metric("Invested", f"${state['portfolio_value'] - state['cash']:,.0f}")

st.divider()

# Allocation chart + table
col_chart, col_table = st.columns([1, 1])

sleeves = get_sleeve_allocations()

with col_chart:
    st.subheader("Allocation")
    labels = [k.split(":")[0] if ":" in k else k for k in sleeves.keys()]
    values = [v["actual"] for v in sleeves.values()]
    colors = ["#2196F3", "#FF9800", "#4CAF50", "#9E9E9E", "#F44336", "#78909C"]

    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values,
        hole=0.45, marker_colors=colors,
        textinfo="label+percent",
        textposition="outside",
    )])
    fig.update_layout(
        showlegend=False, margin=dict(t=20, b=20, l=20, r=20),
        height=350, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
    )
    st.plotly_chart(fig, use_container_width=True)

with col_table:
    st.subheader("Sleeve Status")
    for name, data in sleeves.items():
        short_name = name.split(": ")[1] if ": " in name else name
        pnl_color = "green" if data["pnl"] >= 0 else "red"
        st.markdown(
            f"**{short_name}** — {data['status']}  \n"
            f"Target: {data['target']:.0%} | Actual: {data['actual']:.0%} | "
            f"P&L: :{pnl_color}[${data['pnl']:+,.2f}]"
        )

st.divider()

# Simulated equity curve
st.subheader("Equity Curve")
import random
random.seed(42)
dates = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(420)]
equity = [50_000]
for i in range(1, len(dates)):
    daily_return = random.gauss(0.0004, 0.008)  # ~10% annual, ~12% vol
    equity.append(equity[-1] * (1 + daily_return))

fig_eq = go.Figure()
fig_eq.add_trace(go.Scatter(
    x=dates, y=equity, mode="lines",
    line=dict(color="#4CAF50", width=2),
    fill="tozeroy", fillcolor="rgba(76,175,80,0.1)",
    name="Portfolio",
))
fig_eq.update_layout(
    height=300, margin=dict(t=10, b=30, l=50, r=20),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
    font=dict(color="white"),
    yaxis_title="Portfolio Value ($)",
)
st.plotly_chart(fig_eq, use_container_width=True)
