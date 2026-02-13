"""
Quantum Protocol - Layer 2 Platform (Retail AI Dashboard)

FastAPI application providing CTA-exempt dashboards with coarsened signals,
heatmaps, latency metrics, and compliance views. Communicates with the
Rust engine via shared memory config blocks.

Endpoints:
  GET  /dashboard      — Coarsened market context (no Buy/Sell signals)
  GET  /heatmaps       — Volatility heatmap data
  GET  /latency        — Engine latency metrics
  GET  /compliance     — Compliance / audit log summary
  POST /update_config  — Update shared config (hedge ratio, thresholds, etc.)
  GET  /health         — Health check
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import time
import json
import os

app = FastAPI(
    title="Quantum Protocol Platform",
    version="0.1.0",
    description="CTA-Exempt Retail AI Dashboard for Quantum Protocol",
)

# ---------------------------------------------------------------------------
# In-memory shared config (simulates shared memory config block with Rust)
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
# In-memory engine metrics (simulates reading from engine shared memory)
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


def _get_vol_regime() -> str:
    """Classify current vol regime based on a simulated VIX."""
    low = _shared_config["vol_regime_threshold_low"]
    high = _shared_config["vol_regime_threshold_high"]
    # In production, this reads from shared memory with the engine
    simulated_vix = 20.0  # placeholder
    if simulated_vix < low:
        return "Low (Risk-On)"
    elif simulated_vix > high:
        return "High (Risk-Off)"
    return "Neutral"


def _get_uptime() -> float:
    return round(time.time() - _start_time, 2)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "uptime_seconds": _get_uptime()}


@app.get("/dashboard", response_model=DashboardResponse)
async def dashboard():
    """
    CTA-Exempt dashboard: coarsened market context.
    Does NOT provide Buy/Sell signals to retail users.
    """
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
    return LatencyResponse(
        p99_latency_us=_engine_metrics["p99_latency_us"],
        median_latency_us=_engine_metrics["median_latency_us"],
        ticks_processed=_engine_metrics["ticks_processed"],
        target_p99_us=120.0,
    )


@app.get("/compliance", response_model=ComplianceResponse)
async def compliance():
    """Compliance summary for FINRA 3110 audit."""
    crisis_count = sum(1 for r in _audit_log if r.get("event_type") == "CrisisProtocol")
    # FINRA 3110 requires active audit logging and heartbeat monitoring.
    # Assess dynamically: compliant only when audit trail is operational
    # and heartbeat lag is within configured threshold.
    has_recent_activity = len(_audit_log) > 0 or _engine_metrics["ticks_processed"] == 0
    heartbeat_ok = _engine_metrics.get("p99_latency_us", 0.0) <= _shared_config["heartbeat_max_lag_us"]
    finra_compliant = has_recent_activity and heartbeat_ok
    return ComplianceResponse(
        total_audit_records=len(_audit_log),
        crisis_events=crisis_count,
        last_crisis_state=_engine_metrics["crisis_state"],
        finra_3110_compliant=finra_compliant,
        worm_storage_active=True,
    )


@app.post("/update_config")
async def update_config(config: ConfigUpdate):
    """
    Update shared config block. In production, this writes to shared memory
    that the Rust engine reads on the next tick.
    """
    updates = config.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No config fields provided")

    # Validate threshold ordering: low must be <= high
    new_low = updates.get("vol_regime_threshold_low", _shared_config["vol_regime_threshold_low"])
    new_high = updates.get("vol_regime_threshold_high", _shared_config["vol_regime_threshold_high"])
    if new_low > new_high:
        raise HTTPException(
            status_code=400,
            detail="vol_regime_threshold_low must be <= vol_regime_threshold_high",
        )

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
