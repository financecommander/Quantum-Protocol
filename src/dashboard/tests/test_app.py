"""
Integration tests for the Quantum Protocol FastAPI Platform (Layer 2).

Tests all endpoints: /health, /dashboard, /heatmaps, /latency, /compliance,
/update_config, /internal/state
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add the dashboard source directory to the path
_dashboard_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_dashboard_dir))
from app import app, _shared_config, _audit_log, _engine_metrics, set_engine, get_engine


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset shared state before each test."""
    _shared_config.update(
        {
            "hedge_ratio": 0.8,
            "max_position": 1_000_000.0,
            "vol_regime_threshold_low": 15.0,
            "vol_regime_threshold_high": 30.0,
            "quantum_weights": [0.125] * 8,
            "circuit_breaker_enabled": True,
            "heartbeat_max_lag_us": 100,
        }
    )
    _audit_log.clear()
    _engine_metrics.update(
        {
            "ticks_processed": 0,
            "last_tick_ns": 0,
            "crisis_state": "Normal",
            "p99_latency_us": 0.0,
            "median_latency_us": 0.0,
            "uptime_seconds": 0.0,
        }
    )
    # Clear any injected engine
    set_engine(None)
    yield


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class TestDashboard:
    def test_dashboard_returns_coarsened_context(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "coarsened" in data["market_context"].lower() or "signal" in data["market_context"].lower()
        assert data["crisis_state"] == "Normal"
        assert data["ticks_processed"] == 0

    def test_dashboard_no_buy_sell_signals(self, client):
        resp = client.get("/dashboard")
        data = resp.json()
        ctx = data["market_context"].lower()
        assert "buy" not in ctx
        assert "sell" not in ctx


# ---------------------------------------------------------------------------
# Heatmaps
# ---------------------------------------------------------------------------


class TestHeatmaps:
    def test_heatmaps_structure(self, client):
        resp = client.get("/heatmaps")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vol_regime_threshold_low"] == 15.0
        assert data["vol_regime_threshold_high"] == 30.0
        assert len(data["heatmap_data"]) == 3

    def test_heatmaps_regime_labels(self, client):
        resp = client.get("/heatmaps")
        data = resp.json()
        labels = [h["label"] for h in data["heatmap_data"]]
        assert "Low Vol" in labels
        assert "Neutral" in labels
        assert "High Vol" in labels


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


class TestLatency:
    def test_latency_target(self, client):
        resp = client.get("/latency")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_p99_us"] == 120.0

    def test_latency_metrics_present(self, client):
        resp = client.get("/latency")
        data = resp.json()
        assert "p99_latency_us" in data
        assert "median_latency_us" in data
        assert "ticks_processed" in data


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


class TestCompliance:
    def test_compliance_finra_3110(self, client):
        resp = client.get("/compliance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["finra_3110_compliant"] is True
        assert data["worm_storage_active"] is True

    def test_compliance_crisis_count(self, client):
        _audit_log.append({"event_type": "CrisisProtocol"})
        _audit_log.append({"event_type": "CrisisProtocol"})
        _audit_log.append({"event_type": "SleeveSignal"})

        resp = client.get("/compliance")
        data = resp.json()
        assert data["crisis_events"] == 2
        assert data["total_audit_records"] == 3


# ---------------------------------------------------------------------------
# Update Config
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    def test_update_hedge_ratio(self, client):
        resp = client.post("/update_config", json={"hedge_ratio": 0.6})
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["hedge_ratio"] == 0.6

    def test_update_multiple_fields(self, client):
        resp = client.post(
            "/update_config",
            json={
                "hedge_ratio": 0.5,
                "vol_regime_threshold_low": 12.0,
                "circuit_breaker_enabled": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["hedge_ratio"] == 0.5
        assert data["config"]["vol_regime_threshold_low"] == 12.0
        assert data["config"]["circuit_breaker_enabled"] is False

    def test_update_config_logs_audit(self, client):
        client.post("/update_config", json={"hedge_ratio": 0.9})
        assert len(_audit_log) == 1
        assert _audit_log[0]["event_type"] == "ConfigUpdate"

    def test_update_config_empty_body(self, client):
        resp = client.post("/update_config", json={})
        assert resp.status_code == 400

    def test_update_config_validation(self, client):
        resp = client.post("/update_config", json={"hedge_ratio": 5.0})
        assert resp.status_code == 422  # validation error: max 2.0


# ---------------------------------------------------------------------------
# Internal State (new Phase 3 endpoint)
# ---------------------------------------------------------------------------


class _MockEngine:
    """Minimal mock of QuantumEngine for testing set_engine() wiring."""

    def __init__(self, state: dict):
        self._state = state

    def get_state(self) -> dict:
        return self._state


_MOCK_STATE = {
    "running": True,
    "ticks_processed": 42,
    "uptime_seconds": 120.5,
    "crisis_level": "Normal",
    "portfolio_value": 50_000.0,
    "signals": [
        {
            "sleeve_id": 1,
            "sleeve_name": "Treasury Yield",
            "signal": 0.8,
            "confidence": 0.85,
            "instruments": ["IEF", "ZN"],
            "rationale": "HOLD: 2s10s=72bps",
        }
    ],
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
        "timestamp": "2025-01-15T14:30:00+00:00",
    },
    "permission_vector": {
        "regime": "growth",
        "sleeve_biases": {1: 0.85, 2: 1.00, 3: 1.15, 5: 0.90},
        "requires_human_approval": False,
    },
    "kill_switch": False,
    "human_approval_pending": False,
    "audit_summary": {
        "total_entries": 5,
        "orders": 2,
        "risk_events": 1,
        "kill_switches": 0,
        "config_changes": 2,
        "finra_3110_compliant": True,
        "worm_storage": True,
    },
}


class TestInternalState:
    """Tests for /internal/state endpoint."""

    def test_no_engine_returns_503(self, client):
        """When no engine is connected, /internal/state returns 503."""
        resp = client.get("/internal/state")
        assert resp.status_code == 503

    def test_with_engine_returns_full_state(self, client):
        """When engine is connected, /internal/state returns full state dict."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/internal/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["ticks_processed"] == 42
        assert data["crisis_level"] == "Normal"
        assert data["portfolio_value"] == 50_000.0

    def test_state_includes_seraph(self, client):
        """Internal state includes SERAPH AI regime data."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/internal/state")
        data = resp.json()
        assert "seraph" in data
        assert data["seraph"]["regime"] == "growth"
        assert data["seraph"]["confidence"] == 0.87

    def test_state_includes_market(self, client):
        """Internal state includes live market data."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/internal/state")
        data = resp.json()
        assert "market" in data
        assert data["market"]["vix"] == 14.8
        assert data["market"]["spx"] == 5842.0

    def test_state_includes_permission_vector(self, client):
        """Internal state includes permission vector biases."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/internal/state")
        data = resp.json()
        assert "permission_vector" in data
        pv = data["permission_vector"]
        assert pv["regime"] == "growth"
        assert pv["requires_human_approval"] is False

    def test_state_includes_signals(self, client):
        """Internal state includes sleeve signals."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/internal/state")
        data = resp.json()
        assert len(data["signals"]) == 1
        assert data["signals"][0]["sleeve_name"] == "Treasury Yield"

    def test_state_includes_audit_summary(self, client):
        """Internal state includes audit compliance summary."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/internal/state")
        data = resp.json()
        assert data["audit_summary"]["finra_3110_compliant"] is True


# ---------------------------------------------------------------------------
# Engine-wired endpoints
# ---------------------------------------------------------------------------


class TestEngineWiring:
    """Test that existing endpoints pull from engine when connected."""

    def test_dashboard_with_engine(self, client):
        """Dashboard uses engine state when available."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["crisis_state"] == "Normal"
        assert data["ticks_processed"] == 42

    def test_health_with_engine(self, client):
        """Health endpoint shows engine connection status."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/health")
        data = resp.json()
        assert data["engine"] == "connected"
        assert data["ticks_processed"] == 42

    def test_compliance_with_engine(self, client):
        """Compliance pulls from engine audit logger."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/compliance")
        data = resp.json()
        assert data["total_audit_records"] == 5
        assert data["finra_3110_compliant"] is True

    def test_dashboard_cta_compliance_with_engine(self, client):
        """Even with engine, dashboard must NOT expose Buy/Sell signals."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/dashboard")
        data = resp.json()
        ctx = data["market_context"].lower()
        assert "buy" not in ctx
        assert "sell" not in ctx

    def test_latency_with_engine_ticks(self, client):
        """Latency endpoint uses engine tick count."""
        set_engine(_MockEngine(_MOCK_STATE))
        resp = client.get("/latency")
        data = resp.json()
        assert data["ticks_processed"] == 42
