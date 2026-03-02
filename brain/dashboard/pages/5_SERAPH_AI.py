"""Page 5: SERAPH AI™ — regime detection, allocation adjustments, v1.0 vs thesis."""

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
import random
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dashboard.state import get_seraph_state, get_state, is_live

st.title("🧠 SERAPH AI™ Regime Monitor")

# ─── Current Regime ─────────────────────────────────────────────

seraph = get_seraph_state()
engine_state = get_state()

st.subheader("Current Regime Classification")

regime = seraph.get("regime", "growth").upper()
confidence = seraph.get("confidence", 0.87)
days_in = seraph.get("days_in_regime", 14)
# Estimate next rebalance: 90 - days_in_regime (quarterly)
next_rebal = max(0, 90 - days_in)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Active Regime", regime, help="Based on VIX + SPX trend analysis")
c2.metric("Confidence", f"{confidence:.0%}")
c3.metric("Duration", f"{days_in} days")
c4.metric("Next Rebalance", f"{next_rebal} days")

if is_live():
    vix = seraph.get("vix", 0)
    adx = seraph.get("adx", 0)
    spx_ret = seraph.get("spx_20d_return", 0)
    st.caption(f"🟢 Live | VIX: {vix:.1f} | ADX: {adx:.0f} | SPX 20d Return: {spx_ret:+.2%}")

# Regime indicator
regimes = {
    "Growth": {"color": "#4CAF50", "desc": "+15% Prop/RWA allocation, reduced hedging"},
    "Stress": {"color": "#F44336", "desc": "+12% Tail/Yield allocation, reduced risk"},
    "Transition": {"color": "#FF9800", "desc": "+5-10% Curve allocation, monitoring"},
    "Compression": {"color": "#2196F3", "desc": "Neutral — base allocations apply"},
    "Crisis": {"color": "#9C27B0", "desc": "Emergency — Prop/Curve blocked, max hedge"},
}

# Map engine regime names to display names
regime_display_map = {
    "GROWTH": "Growth", "COMPRESSION": "Compression",
    "VOLATILE": "Transition", "CRISIS": "Crisis",
}
current = regime_display_map.get(regime, "Growth")

st.markdown("---")
cols = st.columns(5)
for col, (name, info) in zip(cols, regimes.items()):
    if name == current:
        col.markdown(f"### ⬤ {name}")
        col.caption(info["desc"])
    else:
        col.markdown(f"○ {name}")
        col.caption(info["desc"])

# ─── Current Allocation (live) ──────────────────────────────────

alloc = engine_state.get("allocation", {})
if alloc:
    st.divider()
    st.subheader("Current Allocation (Regime-Adjusted)")
    acols = st.columns(5)
    alloc_labels = [
        ("Treasury", alloc.get("treasury_yield", 0.10)),
        ("Curve", alloc.get("compression_curve", 0.15)),
        ("Prop", alloc.get("prop_scaling", 0.45)),
        ("Hedge", alloc.get("convexity_shield", 0.10)),
        ("Cash", alloc.get("cash", 0.20)),
    ]
    for col, (label, val) in zip(acols, alloc_labels):
        col.metric(label, f"{val:.0%}")

# ─── Permission Vector Map ──────────────────────────────────────

st.divider()
st.subheader("Permission Vector — Regime Bias Map")

regime_data = {
    "Growth":      {"Treasury": 0.85, "Curve": 1.00, "Prop": 1.15, "RWA": 0.00, "Tail": 0.90},
    "Stress":      {"Treasury": 1.12, "Curve": 0.80, "Prop": 0.70, "RWA": 0.00, "Tail": 1.12},
    "Transition":  {"Treasury": 1.00, "Curve": 1.10, "Prop": 0.95, "RWA": 0.00, "Tail": 1.05},
    "Compression": {"Treasury": 1.00, "Curve": 1.05, "Prop": 1.10, "RWA": 0.00, "Tail": 0.80},
    "Crisis":      {"Treasury": 1.20, "Curve": 0.00, "Prop": 0.00, "RWA": 0.00, "Tail": 1.30},
}

sleeves = ["Treasury", "Curve", "Prop", "RWA", "Tail"]
fig = go.Figure()
for reg_name, biases in regime_data.items():
    fig.add_trace(go.Bar(
        name=reg_name,
        x=sleeves,
        y=[biases[s] for s in sleeves],
        opacity=0.85,
    ))
fig.add_hline(y=1.0, line_dash="dash", line_color="white", opacity=0.4)
fig.update_layout(
    barmode="group", height=300,
    margin=dict(t=10, b=30, l=50, r=20),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="white"), yaxis_title="Bias Multiplier",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
)
st.plotly_chart(fig, use_container_width=True)

# ─── Regime History ─────────────────────────────────────────────

st.divider()
st.subheader("Regime History (12 months)")

random.seed(99)
dates = [datetime(2025, 3, 1) + timedelta(days=i) for i in range(365)]
regime_map = {"Growth": 0, "Compression": 1, "Transition": 2, "Stress": 3, "Crisis": 4}
colors = ["#4CAF50", "#2196F3", "#FF9800", "#F44336", "#9C27B0"]

# Simulate regime transitions
regime_history = []
current_r = 0
for d in dates:
    if random.random() < 0.02:
        current_r = random.choice([0, 0, 0, 1, 1, 2, 3])  # Growth-biased
    regime_history.append(current_r)

fig_hist = go.Figure()
fig_hist.add_trace(go.Scatter(
    x=dates, y=regime_history, mode="lines",
    line=dict(width=2, color="#4CAF50"),
    fill="tozeroy", fillcolor="rgba(76,175,80,0.1)",
))
fig_hist.update_layout(
    height=200, margin=dict(t=10, b=30, l=50, r=20),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="white"),
    yaxis=dict(
        tickvals=[0, 1, 2, 3, 4],
        ticktext=["Growth", "Compression", "Transition", "Stress", "Crisis"],
        showgrid=True, gridcolor="rgba(255,255,255,0.1)",
    ),
    xaxis=dict(showgrid=False),
)
st.plotly_chart(fig_hist, use_container_width=True)

# ─── v1.0 vs Thesis Reconciliation ─────────────────────────────

st.divider()
st.subheader("v1.0 vs Thesis — Implementation Status")

features = [
    ("Master-Slave gating", "Single tick loop", "Dual timeframe (hourly→1min)", "LARGE", "v1.5"),
    ("Weight optimizer", "Fixed allocation table", "PuLP per cycle", "MEDIUM", "v2.0"),
    ("Regime classifier", "VIX threshold (4 features)", "RF 91% (128 features)", "MEDIUM", "v2.0"),
    ("KPI Guard", "Kill switch 2% daily", "DD >5% veto + rolling 20-day", "PARTIAL", "✅ v1.0"),
    ("Permission vector", "Regime→bias broadcast", "Full MARL hierarchy", "PARTIAL", "✅ v1.0"),
    ("Human approval", ">20% shift gate (logged)", ">20% shift gate (dashboard)", "EASY", "✅ v1.0"),
    ("Watcher Agent", "None", "1,000 Monte Carlo paths", "LARGE", "v1.5"),
    ("ARIMA Oracle", "VIX threshold", "Vol forecast + pre-emptive boost", "MEDIUM", "v1.5"),
    ("RAG integration", "None", "Pinecone tax/rulebook", "LARGE", "v2.0"),
]

for name, v1, thesis, gap, status in features:
    icon = "✅" if "v1.0" in status else "🔶" if "v1.5" in status else "⬜"
    st.markdown(f"{icon} **{name}** — Gap: {gap}  \n  v1.0: {v1} → Thesis: {thesis}")
