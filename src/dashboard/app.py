"""
Quantum Protocol - Layer 2 Platform (Retail AI Dashboard)

FastAPI application providing CTA-exempt dashboards with coarsened signals,
heatmaps, latency metrics, and compliance views.

When a QuantumEngine is injected via set_engine(), endpoints pull live data.
Without an engine, endpoints serve simulated data (preserves standalone testing).

Endpoints:
  GET  /dashboard       — Coarsened market context (no Buy/Sell signals)
  GET  /heatmaps        — Volatility heatmap data
  GET  /latency         — Engine latency metrics
  GET  /compliance      — Compliance / audit log summary
  POST /update_config   — Update shared config (hedge ratio, thresholds, etc.)
  GET  /health          — Health check
  GET  /internal/state  — Full engine state (internal use by Streamlit dashboard)
"""

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Optional
import time
import json
import os

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

app = FastAPI(
    title="Quantum Protocol Platform",
    version="0.2.0",
    description="CTA-Exempt Retail AI Dashboard for Quantum Protocol",
)

# ---------------------------------------------------------------------------
# Engine injection — when set, endpoints pull live data
# ---------------------------------------------------------------------------

_engine = None


def set_engine(engine):
    """Inject a running QuantumEngine. Endpoints will pull live data."""
    global _engine
    _engine = engine


def get_engine():
    """Get the injected engine (or None)."""
    return _engine


# ---------------------------------------------------------------------------
# In-memory shared config (fallback when no engine is connected)
# ---------------------------------------------------------------------------

_shared_config = {
    "hedge_ratio": 0.8,
    "max_position": 1_000_000.0,
    "vol_regime_threshold_low": 15.0,
    "vol_regime_threshold_high": 30.0,
    "quantum_weights": [0.125] * 8,
    "circuit_breaker_enabled": True,
    "heartbeat_max_lag_us": 100,
}

# ---------------------------------------------------------------------------
# In-memory engine metrics (fallback when no engine is connected)
# ---------------------------------------------------------------------------

_engine_metrics = {
    "ticks_processed": 0,
    "last_tick_ns": 0,
    "crisis_state": "Normal",
    "p99_latency_us": 0.0,
    "median_latency_us": 0.0,
    "uptime_seconds": 0.0,
}

_audit_log = []

_start_time = time.time()

# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------

TICKS_TOTAL = Counter("qp_ticks_total", "Total engine ticks processed")
TICK_LATENCY = Histogram(
    "qp_tick_latency_seconds",
    "Tick processing latency",
    ["phase"],  # feed, orchestrator, total
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)
CRISIS_LEVEL = Gauge("qp_crisis_level", "Current crisis level (0=normal, 1=elevated, 2=severe, 3=surgical, 4=bunker)")
KILL_SWITCH = Gauge("qp_kill_switch_active", "Kill switch status (0=inactive, 1=active)")
SIGNALS_TOTAL = Counter("qp_signals_generated_total", "Signals generated per sleeve", ["sleeve_id"])

_CRISIS_LEVEL_MAP = {
    "Normal": 0, "Elevated": 1, "Severe": 2, "Surgical": 3, "Bunker": 4,
}


def update_prometheus_metrics(state: dict):
    """Push engine state into Prometheus gauges. Called externally after each tick."""
    crisis = state.get("crisis_level", "Normal")
    CRISIS_LEVEL.set(_CRISIS_LEVEL_MAP.get(crisis, 0))
    KILL_SWITCH.set(1 if state.get("kill_switch_active", False) else 0)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class ConfigUpdate(BaseModel):
    hedge_ratio: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_position: Optional[float] = Field(None, ge=0.0)
    vol_regime_threshold_low: Optional[float] = Field(None, ge=0.0)
    vol_regime_threshold_high: Optional[float] = Field(None, ge=0.0)
    circuit_breaker_enabled: Optional[bool] = None
    heartbeat_max_lag_us: Optional[int] = Field(None, ge=1)


class DashboardResponse(BaseModel):
    market_context: str
    crisis_state: str
    vol_regime: str
    ticks_processed: int
    uptime_seconds: float


class HeatmapResponse(BaseModel):
    vol_regime_threshold_low: float
    vol_regime_threshold_high: float
    current_regime: str
    heatmap_data: list


class LatencyResponse(BaseModel):
    p99_latency_us: float
    median_latency_us: float
    ticks_processed: int
    target_p99_us: float


class ComplianceResponse(BaseModel):
    total_audit_records: int
    crisis_events: int
    last_crisis_state: str
    finra_3110_compliant: bool
    worm_storage_active: bool


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_engine_state() -> Optional[dict]:
    """Get live engine state, or None if no engine is connected."""
    if _engine is None:
        return None
    try:
        return _engine.get_state()
    except Exception:
        return None


def _get_vol_regime(vix: Optional[float] = None) -> str:
    """Classify current vol regime."""
    low = _shared_config["vol_regime_threshold_low"]
    high = _shared_config["vol_regime_threshold_high"]

    if vix is None:
        # Try live engine
        state = _get_engine_state()
        if state and state.get("market", {}).get("vix") is not None:
            vix = state["market"]["vix"]
        else:
            vix = 20.0  # fallback placeholder

    if vix < low:
        return "Low (Risk-On)"
    elif vix > high:
        return "High (Risk-Off)"
    return "Neutral"


def _get_uptime() -> float:
    state = _get_engine_state()
    if state is not None:
        return state.get("uptime_seconds", 0.0)
    return round(time.time() - _start_time, 2)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint for Docker/Prometheus scraping."""
    state = _get_engine_state()
    if state is not None:
        return {
            "status": "healthy",
            "engine": "connected",
            "uptime_seconds": state.get("uptime_seconds", 0.0),
            "ticks_processed": state.get("ticks_processed", 0),
            "crisis_level": state.get("crisis_level", "Normal"),
            "kill_switch_active": state.get("kill_switch_active", False),
            "tick_latency": state.get("tick_latency", {
                "feed_ms": 0.0, "orchestrator_ms": 0.0, "total_ms": 0.0,
            }),
        }
    return {
        "status": "healthy",
        "engine": "disconnected",
        "uptime_seconds": _get_uptime(),
        "ticks_processed": _engine_metrics["ticks_processed"],
        "crisis_level": _engine_metrics["crisis_state"],
        "kill_switch_active": False,
        "tick_latency": {"feed_ms": 0.0, "orchestrator_ms": 0.0, "total_ms": 0.0},
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    state = _get_engine_state()
    if state is not None:
        update_prometheus_metrics(state)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/dashboard", response_model=DashboardResponse)
async def dashboard():
    """
    CTA-Exempt dashboard: coarsened market context.
    Does NOT provide Buy/Sell signals to retail users.
    """
    state = _get_engine_state()
    if state is not None:
        vix = state.get("market", {}).get("vix")
        return DashboardResponse(
            market_context="Coarsened institutional signal — no direct execution",
            crisis_state=state.get("crisis_level", "Normal"),
            vol_regime=_get_vol_regime(vix),
            ticks_processed=state.get("ticks_processed", 0),
            uptime_seconds=state.get("uptime_seconds", 0.0),
        )

    return DashboardResponse(
        market_context="Coarsened institutional signal — no direct execution",
        crisis_state=_engine_metrics["crisis_state"],
        vol_regime=_get_vol_regime(),
        ticks_processed=_engine_metrics["ticks_processed"],
        uptime_seconds=_get_uptime(),
    )


@app.get("/heatmaps", response_model=HeatmapResponse)
async def heatmaps():
    """Volatility heatmap data for dashboard visualization."""
    return HeatmapResponse(
        vol_regime_threshold_low=_shared_config["vol_regime_threshold_low"],
        vol_regime_threshold_high=_shared_config["vol_regime_threshold_high"],
        current_regime=_get_vol_regime(),
        heatmap_data=[
            {"label": "Low Vol", "range": f"VIX < {_shared_config['vol_regime_threshold_low']}"},
            {
                "label": "Neutral",
                "range": f"{_shared_config['vol_regime_threshold_low']} <= VIX <= {_shared_config['vol_regime_threshold_high']}",
            },
            {
                "label": "High Vol",
                "range": f"VIX > {_shared_config['vol_regime_threshold_high']}",
            },
        ],
    )


@app.get("/latency", response_model=LatencyResponse)
async def latency():
    """Engine latency metrics. Target: p99 < 120µs."""
    state = _get_engine_state()
    if state is not None:
        return LatencyResponse(
            p99_latency_us=_engine_metrics.get("p99_latency_us", 0.0),
            median_latency_us=_engine_metrics.get("median_latency_us", 0.0),
            ticks_processed=state.get("ticks_processed", 0),
            target_p99_us=120.0,
        )

    return LatencyResponse(
        p99_latency_us=_engine_metrics["p99_latency_us"],
        median_latency_us=_engine_metrics["median_latency_us"],
        ticks_processed=_engine_metrics["ticks_processed"],
        target_p99_us=120.0,
    )


@app.get("/compliance", response_model=ComplianceResponse)
async def compliance():
    """Compliance summary for FINRA 3110 audit."""
    state = _get_engine_state()
    if state is not None:
        audit = state.get("audit_summary", {})
        return ComplianceResponse(
            total_audit_records=audit.get("total_entries", 0),
            crisis_events=audit.get("risk_events", 0),
            last_crisis_state=state.get("crisis_level", "Normal"),
            finra_3110_compliant=audit.get("finra_3110_compliant", True),
            worm_storage_active=audit.get("worm_storage", True),
        )

    crisis_count = sum(1 for r in _audit_log if r.get("event_type") == "CrisisProtocol")
    return ComplianceResponse(
        total_audit_records=len(_audit_log),
        crisis_events=crisis_count,
        last_crisis_state=_engine_metrics["crisis_state"],
        finra_3110_compliant=True,
        worm_storage_active=True,
    )


@app.get("/internal/state")
async def internal_state():
    """
    Full engine state for internal dashboards (Streamlit).
    NOT CTA-exempt — contains full signal detail.
    Returns 503 if no engine is connected.
    """
    state = _get_engine_state()
    if state is None:
        raise HTTPException(
            status_code=503,
            detail="No engine connected. Start the QuantumEngine and call set_engine().",
        )
    return state


@app.post("/update_config")
async def update_config(config: ConfigUpdate):
    """
    Update shared config block. In production, this writes to shared memory
    that the engine reads on the next tick.
    """
    updates = config.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No config fields provided")

    for key, value in updates.items():
        if key in _shared_config:
            _shared_config[key] = value

    _audit_log.append(
        {
            "timestamp": time.time(),
            "event_type": "ConfigUpdate",
            "details": updates,
        }
    )

    return {"status": "updated", "config": _shared_config}
