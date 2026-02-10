"""
Integration tests for the Quantum Protocol FastAPI Platform (Layer 2).

Tests all endpoints: /health, /dashboard, /heatmaps, /latency, /compliance, /update_config
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add the dashboard source directory to the path
_dashboard_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_dashboard_dir))
from app import app, _shared_config, _audit_log, _engine_metrics


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
    yield


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
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
