"""Page 4: Signal Feed — live signal history with source tracking."""

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dashboard.state import get_signals, is_live

st.title("📡 Signal Feed")

# ─── Active Signals ─────────────────────────────────────────────

st.subheader("Active Signals")

live_signals = get_signals()

if live_signals:
    # Live signals from engine
    for sig in live_signals:
        direction = "LONG" if sig.get("signal", 0) > 0 else "SHORT" if sig.get("signal", 0) < 0 else "FLAT"
        dir_color = "🟢" if direction in ("LONG",) else "🔴" if direction == "SHORT" else "⚪"
        instruments = ", ".join(sig.get("instruments", []))

        with st.container():
            c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
            c1.write(f"{dir_color} **{sig.get('sleeve_name', 'Unknown')}**")
            c2.write(f"{direction} — {instruments}")
            c3.write(sig.get("rationale", ""))
            c4.write(f"Conf: {sig.get('confidence', 0):.0%} | Signal: {sig.get('signal', 0):+.2f}")
        st.divider()

    if is_live():
        st.success(f"🟢 Live — {len(live_signals)} active signals from engine")
else:
    # Simulated signals (fallback)
    signals = [
        {"time": "14:32:15", "sleeve": "Sleeve 3", "direction": "LONG", "source": "LLM", "confidence": 0.88, "ticker": "MU", "rationale": "AI capex cycle + HBM3E ramp, conviction 0.88"},
        {"time": "14:30:00", "sleeve": "Sleeve 1", "direction": "HOLD", "source": "—", "confidence": 0.80, "ticker": "IEF", "rationale": "2s10s=72bps, roll-down position active"},
        {"time": "14:28:45", "sleeve": "Sleeve 5", "direction": "BUY HEDGE", "source": "—", "confidence": 0.75, "ticker": "SPX puts", "rationale": "ACCUMULATE: VIX=14.8, cheap premium window + collar active"},
        {"time": "14:25:10", "sleeve": "Sleeve 2", "direction": "SHORT", "source": "RSI", "confidence": 0.72, "ticker": "ZN-ZF", "rationale": "Flattener: 2s10s=112bps > 100bps threshold"},
        {"time": "14:20:00", "sleeve": "Sleeve 3", "direction": "LONG", "source": "Momentum", "confidence": 0.65, "ticker": "ES", "rationale": "Trend strength 0.74, fast EMA > slow EMA"},
    ]

    for sig in signals:
        dir_color = "🟢" if sig["direction"] in ("LONG", "BUY HEDGE", "HOLD") else "🔴"
        source_badge = f"🤖 {sig['source']}" if sig["source"] in ("LLM", "RSI", "Momentum") else sig["source"]

        with st.container():
            c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
            c1.write(f"{dir_color} **{sig['sleeve']}**")
            c2.write(f"{sig['direction']} — {sig['ticker']}")
            c3.write(f"{source_badge} | {sig['rationale']}")
            c4.write(f"Conf: {sig['confidence']:.0%} | {sig['time']}")
        st.divider()

    st.info("⚪ Showing simulated signals (engine not connected)")

# ─── Pending LLM Signals ────────────────────────────────────────

st.subheader("Pending LLM Signals (Queue)")

llm_queue = [
    {"ticker": "NOW", "direction": "LONG", "conviction": 0.72, "source": "grok", "thesis": "Enterprise AI spend acceleration, ServiceNow platform stickiness"},
    {"ticker": "FSLR", "direction": "LONG", "conviction": 0.55, "source": "grok", "thesis": "Solar IRA tailwinds, domestic manufacturing advantage"},
]

if llm_queue:
    for sig in llm_queue:
        conv_color = "🟢" if sig["conviction"] >= 0.7 else "🟡"
        priority = "HIGH (overrides technicals)" if sig["conviction"] >= 0.7 else "MEDIUM (fallback when technicals silent)"
        st.markdown(
            f"{conv_color} **{sig['ticker']}** — {sig['direction']} | "
            f"Conviction: {sig['conviction']:.0%} ({priority}) | "
            f"Source: {sig['source']}  \n"
            f"_{sig['thesis']}_"
        )
else:
    st.info("No pending LLM signals.")

# ─── Signal History Chart ────────────────────────────────────────

st.divider()
st.subheader("Signal History (24h)")

hours = [datetime.utcnow() - timedelta(hours=i) for i in range(24, 0, -1)]
rsi_signals = [0, 0, 1, 0, 0, -1, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 1, 0]
mom_signals = [0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0]
llm_signals = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]

fig = go.Figure()
fig.add_trace(go.Bar(x=hours, y=rsi_signals, name="RSI", marker_color="#2196F3", opacity=0.8))
fig.add_trace(go.Bar(x=hours, y=mom_signals, name="Momentum", marker_color="#FF9800", opacity=0.8))
fig.add_trace(go.Bar(x=hours, y=llm_signals, name="LLM Conviction", marker_color="#4CAF50", opacity=0.8))
fig.update_layout(
    barmode="group", height=250,
    margin=dict(t=10, b=30, l=50, r=20),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="white"), yaxis_title="Signal (+1=Long, -1=Short)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
)
st.plotly_chart(fig, use_container_width=True)
