"""
MATRIX PROTOCOL™ v1.0 — Dashboard State Provider

Shared state module for Streamlit pages. Fetches live data from
the QuantumEngine via /internal/state when available, falls back
to simulated data for standalone development.

Usage in any Streamlit page:
    from dashboard.state import get_state
    state = get_state()
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("matrix.dashboard.state")

# FastAPI base URL (configurable via env var)
_API_BASE = os.environ.get("MATRIX_API_URL", "http://localhost:8000")

# Cached state to avoid hammering the API on every Streamlit rerun
_cached_state: Optional[dict] = None
_cache_time: float = 0.0
_CACHE_TTL = 2.0  # seconds


def _fetch_live_state() -> Optional[dict]:
    """Try to fetch live state from the FastAPI /internal/state endpoint."""
    import time
    global _cached_state, _cache_time

    # Return cache if fresh
    now = time.time()
    if _cached_state is not None and (now - _cache_time) < _CACHE_TTL:
        return _cached_state

    try:
        import urllib.request
        import json
        url = f"{_API_BASE}/internal/state"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                _cached_state = json.loads(resp.read().decode())
                _cache_time = now
                return _cached_state
    except Exception:
        pass  # Fall through to simulated data

    return None


def _simulated_state() -> dict:
    """Simulated state for standalone development."""
    return {
        "running": False,
        "ticks_processed": 0,
        "uptime_seconds": 0.0,
        "crisis_level": "Normal",
        "portfolio_value": 50_000.0,
        "signals": [],
        "allocation": {
            "treasury_yield": 0.10,
            "compression_curve": 0.15,
            "prop_scaling": 0.45,
            "convexity_shield": 0.10,
            "cash": 0.20,
        },
        "seraph": {
            "regime": "growth",
            "confidence": 0.87,
            "days_in_regime": 14,
            "previous_regime": None,
            "vix": 14.8,
            "adx": 28.5,
            "spx_20d_return": 0.032,
        },
        "market": {
            "vix": 14.8,
            "spx": 5842.0,
            "tnx": 40.0,
            "dxy": 104.0,
            "depeg_pct": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "permission_vector": {
            "regime": "growth",
            "sleeve_biases": {1: 0.85, 2: 1.00, 3: 1.15, 5: 0.90},
            "requires_human_approval": False,
        },
        "kill_switch": False,
        "human_approval_pending": False,
        "audit_summary": {
            "total_entries": 0,
            "orders": 0,
            "risk_events": 0,
            "kill_switches": 0,
            "config_changes": 0,
            "finra_3110_compliant": True,
            "worm_storage": True,
        },
    }


def get_state() -> dict:
    """
    Get current engine state. Tries live API first, falls back to simulated.

    Returns a dict with keys:
        running, ticks_processed, uptime_seconds, crisis_level, portfolio_value,
        signals, allocation, seraph, market, permission_vector,
        kill_switch, human_approval_pending, audit_summary
    """
    live = _fetch_live_state()
    if live is not None:
        return live
    return _simulated_state()


def is_live() -> bool:
    """Check if we're connected to a live engine."""
    state = get_state()
    return state.get("running", False)


def get_portfolio_state() -> dict:
    """
    Portfolio state dict matching the format used by the original Streamlit dashboard.
    Drop-in replacement for the hardcoded get_portfolio_state() in app.py.
    """
    state = get_state()
    market = state.get("market", {})
    seraph = state.get("seraph", {})

    return {
        "portfolio_value": state.get("portfolio_value", 50_000.0),
        "daily_pnl": 0.0,  # v1.5: from IBKR execution tracking
        "daily_pnl_pct": 0.0,
        "total_pnl": 0.0,
        "total_pnl_pct": 0.0,
        "cash": state.get("portfolio_value", 50_000.0) * state.get("allocation", {}).get("cash", 0.20),
        "regime": seraph.get("regime", "growth").capitalize(),
        "crisis_level": state.get("crisis_level", "Normal"),
        "vix": market.get("vix", 14.8),
        "spx": market.get("spx", 5842.0),
        "timestamp": datetime.now(timezone.utc),
        "kill_switch": state.get("kill_switch", False),
        "human_approval_pending": state.get("human_approval_pending", False),
    }


def get_sleeve_allocations() -> dict:
    """
    Sleeve allocation dict matching the format used by the original Streamlit dashboard.
    Drop-in replacement for the hardcoded get_sleeve_allocations() in app.py.
    """
    state = get_state()
    alloc = state.get("allocation", {})

    return {
        "Sleeve 1: Treasury Yield": {
            "target": 0.10,
            "actual": alloc.get("treasury_yield", 0.10),
            "pnl": 0.0,  # v1.5: from IBKR
            "status": _get_sleeve_status(state, 1),
        },
        "Sleeve 2: Compression & Curve": {
            "target": 0.15,
            "actual": alloc.get("compression_curve", 0.15),
            "pnl": 0.0,
            "status": _get_sleeve_status(state, 2),
        },
        "Sleeve 3: Prop Scaling": {
            "target": 0.45,
            "actual": alloc.get("prop_scaling", 0.45),
            "pnl": 0.0,
            "status": _get_sleeve_status(state, 3),
        },
        "Sleeve 4: RWA/Crypto": {
            "target": 0.10,
            "actual": alloc.get("rwa_infrastructure", 0.10),
            "pnl": 0.0,
            "status": _get_sleeve_status(state, 4),
        },
        "Sleeve 5: Convexity Shield": {
            "target": 0.10,
            "actual": alloc.get("convexity_shield", 0.10),
            "pnl": 0.0,
            "status": _get_sleeve_status(state, 5),
        },
        "Cash Reserve": {
            "target": 0.10,
            "actual": alloc.get("cash", 0.10),
            "pnl": 0.0,
            "status": "—",
        },
    }


def get_signals() -> list[dict]:
    """Get current sleeve signals from engine state."""
    state = get_state()
    return state.get("signals", [])


def get_permission_vector() -> dict:
    """Get current permission vector biases."""
    state = get_state()
    pv = state.get("permission_vector", {})
    biases = pv.get("sleeve_biases", {})
    # Normalize keys to int (JSON may serialize as strings)
    return {
        "regime": pv.get("regime", "compression"),
        "biases": {int(k): v for k, v in biases.items()} if biases else {},
        "requires_human_approval": pv.get("requires_human_approval", False),
    }


def get_seraph_state() -> dict:
    """Get SERAPH AI regime classification state."""
    state = get_state()
    return state.get("seraph", {})


def _get_sleeve_status(state: dict, sleeve_id: int) -> str:
    """Extract status string for a sleeve from signal data."""
    for sig in state.get("signals", []):
        if sig.get("sleeve_id") == sleeve_id:
            rationale = sig.get("rationale", "")
            # Extract action from rationale (format: "... | action=xxx")
            if "action=" in rationale:
                action = rationale.split("action=")[-1].strip()
                return action.upper()
            # Fallback: direction from signal value
            s = sig.get("signal", 0)
            if s > 0.5:
                return "LONG"
            elif s < -0.5:
                return "SHORT"
            elif s > 0:
                return "HOLD"
            return "FLAT"
    return "—"


def invalidate_cache():
    """Force a fresh fetch on next get_state() call."""
    global _cached_state, _cache_time
    _cached_state = None
    _cache_time = 0.0
