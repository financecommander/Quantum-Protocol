"""
Tests for the async Python engine (brain/engine.py).
Verifies start/stop lifecycle, tick processing, and crisis logging.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain"))

import pytest
import pytest_asyncio
from engine import QuantumEngine
from feeds.market_data import MockMarketDataFeed


@pytest.fixture
def mock_feed():
    return MockMarketDataFeed(default_vix=18.0, default_spx=5000.0)


@pytest.fixture
def engine(mock_feed, tmp_path):
    e = QuantumEngine(portfolio_value=50_000.0, tick_interval=0.01)
    e.set_feed(mock_feed)
    e.audit.log_dir = str(tmp_path / "audit")
    e.audit._ensure_log_dir()
    return e


class TestEngineLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self, engine):
        await engine.start()
        assert engine._running is True
        await asyncio.sleep(0.05)
        await engine.stop()
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_processes_ticks(self, engine):
        await engine.start()
        await asyncio.sleep(0.1)
        await engine.stop()
        assert engine._ticks_processed > 0

    @pytest.mark.asyncio
    async def test_uptime_tracked(self, engine):
        await engine.start()
        await asyncio.sleep(0.05)
        assert engine.uptime_seconds > 0
        await engine.stop()


class TestEngineState:
    @pytest.mark.asyncio
    async def test_get_state_before_start(self, engine):
        state = engine.get_state()
        assert state["running"] is False
        assert state["ticks_processed"] == 0

    @pytest.mark.asyncio
    async def test_get_state_after_ticks(self, engine):
        await engine.start()
        await asyncio.sleep(0.1)
        await engine.stop()
        state = engine.get_state()
        assert state["ticks_processed"] > 0
        assert "crisis_level" in state
        assert "allocation" in state
        assert "audit_summary" in state


class TestEngineCrisis:
    @pytest.mark.asyncio
    async def test_normal_market_stays_normal(self, engine):
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        assert engine.orchestrator.crisis_level.value in ("Normal", "Elevated")

    @pytest.mark.asyncio
    async def test_crisis_detected_on_high_vix(self, engine):
        engine.feed.set_vix(50.0)
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        assert engine.orchestrator.crisis_level.value == "SmartBunker"

    @pytest.mark.asyncio
    async def test_crisis_transition_logged_to_audit(self, engine):
        engine.feed.set_vix(50.0)
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        entries = engine.audit.get_entries(event_type="RISK")
        assert len(entries) > 0
        crisis_entries = [e for e in entries if "CRISIS" in e.get("event_type", "")]
        assert len(crisis_entries) > 0


class TestEngineWithScenario:
    @pytest.mark.asyncio
    async def test_terra_luna_scenario(self, engine):
        """Run a mini Terra Luna scenario through the engine."""
        engine.feed.set_scenario([
            {"vix": 18.0, "depeg_pct": 0.0},   # Normal
            {"vix": 52.0, "depeg_pct": 0.0},   # SmartBunker
            {"vix": 30.0, "depeg_pct": 8.0},   # SurgicalSniper (depeg, not VIX)
            {"vix": 18.0, "depeg_pct": 1.0},   # Recovery
        ])
        await engine.start()
        await asyncio.sleep(0.1)
        await engine.stop()
        assert engine._ticks_processed >= 4

    @pytest.mark.asyncio
    async def test_mock_feed_disconnection(self, engine):
        """Engine handles feed errors gracefully."""
        await engine.start()
        await asyncio.sleep(0.05)
        # Disconnect feed mid-run — should log error, not crash
        await engine.feed.disconnect()
        await asyncio.sleep(0.05)
        await engine.stop()
        # Engine should still be in a valid state
        assert engine._ticks_processed > 0
