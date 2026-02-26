"""Page 3: Risk Monitor — kill switch, SHIELD™ enforcement, drawdown tracking."""

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
import random

st.title("🛡️ Risk Monitor")

# ─── Kill Switch Status ─────────────────────────────────────────

st.subheader("Kill Switch & Circuit Breakers")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Kill Switch", "INACTIVE")
c2.metric("Crisis Level", "Normal")
c3.metric("Daily Loss", "-0.12%", help="Limit: 2.0%")
c4.metric("Heartbeat", "OK (2s ago)", help="Timeout: 65 min")

# SHIELD gauges
st.divider()
st.subheader("SHIELD™ Enforcement")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Daily Loss Limit**")
    daily_loss = 0.12
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=daily_loss,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "Daily Loss %"},
        gauge={
            "axis": {"range": [0, 2.5]},
            "bar": {"color": "#4CAF50"},
            "steps": [
                {"range": [0, 1.5], "color": "rgba(76,175,80,0.2)"},
                {"range": [1.5, 2.0], "color": "rgba(255,152,0,0.2)"},
                {"range": [2.0, 2.5], "color": "rgba(244,67,54,0.2)"},
            ],
            "threshold": {"line": {"color": "red", "width": 3}, "value": 2.0},
        },
    ))
    fig.update_layout(height=200, margin=dict(t=40, b=0), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="white"))
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.markdown("**Max Drawdown (per account)**")
    max_dd = 5.1
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=max_dd,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "Max DD %"},
        gauge={
            "axis": {"range": [0, 15]},
            "bar": {"color": "#FF9800"},
            "steps": [
                {"range": [0, 6], "color": "rgba(76,175,80,0.2)"},
                {"range": [6, 10], "color": "rgba(255,152,0,0.2)"},
                {"range": [10, 15], "color": "rgba(244,67,54,0.2)"},
            ],
            "threshold": {"line": {"color": "red", "width": 3}, "value": 12.0},
        },
    ))
    fig.update_layout(height=200, margin=dict(t=40, b=0), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="white"))
    st.plotly_chart(fig, use_container_width=True)

with col3:
    st.markdown("**Leverage**")
    leverage = 1.3
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=leverage,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "Leverage x"},
        gauge={
            "axis": {"range": [0, 3]},
            "bar": {"color": "#2196F3"},
            "steps": [
                {"range": [0, 1.5], "color": "rgba(33,150,243,0.2)"},
                {"range": [1.5, 2.0], "color": "rgba(255,152,0,0.2)"},
                {"range": [2.0, 3.0], "color": "rgba(244,67,54,0.2)"},
            ],
            "threshold": {"line": {"color": "red", "width": 3}, "value": 2.0},
        },
    ))
    fig.update_layout(height=200, margin=dict(t=40, b=0), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="white"))
    st.plotly_chart(fig, use_container_width=True)

# ─── Permission Vector ──────────────────────────────────────────

st.divider()
st.subheader("Permission Vector (Current)")

biases = {"Treasury": 0.85, "Curve": 1.00, "Prop": 1.15, "Tail": 0.90}
cols = st.columns(4)
for col, (name, bias) in zip(cols, biases.items()):
    color = "🟢" if bias > 1.0 else "🟡" if bias > 0 else "🔴"
    col.metric(f"{color} {name}", f"{bias:.2f}x")

# ─── Drawdown History ───────────────────────────────────────────

st.divider()
st.subheader("Rolling Drawdown")

random.seed(42)
dates = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(420)]
dd_values = []
peak = 50_000
val = 50_000
for i in range(len(dates)):
    val *= (1 + random.gauss(0.0004, 0.008))
    peak = max(peak, val)
    dd_values.append((val - peak) / peak * 100)

fig_dd = go.Figure()
fig_dd.add_trace(go.Scatter(
    x=dates, y=dd_values, mode="lines",
    fill="tozeroy", fillcolor="rgba(244,67,54,0.15)",
    line=dict(color="#F44336", width=1.5), name="Drawdown",
))
fig_dd.add_hline(y=-2, line_dash="dash", line_color="orange", annotation_text="Daily limit (-2%)")
fig_dd.add_hline(y=-12, line_dash="dash", line_color="red", annotation_text="Max DD limit (-12%)")
fig_dd.update_layout(
    height=250, margin=dict(t=10, b=30, l=50, r=20),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="white"), yaxis_title="Drawdown %",
    xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
)
st.plotly_chart(fig_dd, use_container_width=True)

# ─── Risk Events Log ────────────────────────────────────────────

st.divider()
st.subheader("Recent Risk Events")

events = [
    {"time": "14:32:15", "level": "INFO", "event": "Permission vector broadcast: regime=growth"},
    {"time": "14:30:00", "level": "INFO", "event": "Heartbeat OK — all sleeves responsive"},
    {"time": "13:45:22", "level": "WARN", "event": "EVAL-004 approaching breach threshold (DD: -5.1%)"},
    {"time": "11:20:10", "level": "INFO", "event": "Sleeve 5 collar activated (VIX < 15)"},
    {"time": "09:30:00", "level": "INFO", "event": "New trading day — daily P&L counters reset"},
]

for evt in events:
    icon = "ℹ️" if evt["level"] == "INFO" else "⚠️" if evt["level"] == "WARN" else "🚨"
    st.text(f"{icon} [{evt['time']}] {evt['event']}")
