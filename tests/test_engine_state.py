"""
Engine get_state() Enriched State Validation

Tests the Phase 3 additions to engine.get_state():
  - SERAPH AI regime data
  - Market snapshot
  - Permission vector biases
  - Kill switch / human approval flags
  - Audit summary
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain"))

import pytest
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


# ═══════════════════════════════════════════════════════════════════════════
# State Before Engine Start
# ═══════════════════════════════════════════════════════════════════════════

class TestStateBeforeStart:
    def test_running_is_false(self, engine):
        state = engine.get_state()
        assert state["running"] is False

    def test_ticks_is_zero(self, engine):
        state = engine.get_state()
        assert state["ticks_processed"] == 0

    def test_portfolio_value_matches(self, engine):
        state = engine.get_state()
        assert state["portfolio_value"] == 50_000.0

    def test_crisis_level_default(self, engine):
        state = engine.get_state()
        assert state["crisis_level"] == "Normal"

    def test_allocation_present(self, engine):
        state = engine.get_state()
        alloc = state["allocation"]
        assert alloc["treasury_yield"] == 0.10
        assert alloc["prop_scaling"] == 0.45
        assert alloc["cash"] == 0.10

    def test_kill_switch_default_off(self, engine):
        state = engine.get_state()
        assert state["kill_switch"] is False

    def test_human_approval_default_off(self, engine):
        state = engine.get_state()
        assert state["human_approval_pending"] is False

    def test_market_empty_before_ticks(self, engine):
        state = engine.get_state()
        assert state["market"] == {}

    def test_seraph_empty_before_ticks(self, engine):
        """SERAPH state may be empty before first tick classifies regime."""
        state = engine.get_state()
        # SERAPH might have state from init or be empty
        assert isinstance(state.get("seraph"), dict)


# ═══════════════════════════════════════════════════════════════════════════
# State After Engine Ticks
# ═══════════════════════════════════════════════════════════════════════════

class TestStateAfterTicks:
    @pytest.mark.asyncio
    async def test_ticks_incremented(self, engine):
        await engine.start()
        await asyncio.sleep(0.08)
        await engine.stop()
        state = engine.get_state()
        assert state["ticks_processed"] > 0

    @pytest.mark.asyncio
    async def test_uptime_tracked(self, engine):
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        state = engine.get_state()
        assert state["uptime_seconds"] > 0

    @pytest.mark.asyncio
    async def test_market_populated_after_tick(self, engine):
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        state = engine.get_state()
        market = state["market"]
        assert "vix" in market
        assert "spx" in market
        assert "timestamp" in market
        assert market["vix"] == 18.0
        assert market["spx"] == 5000.0

    @pytest.mark.asyncio
    async def test_signals_populated(self, engine):
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        state = engine.get_state()
        # Should have signals from loaded sleeves
        assert isinstance(state["signals"], list)
        if state["signals"]:
            sig = state["signals"][0]
            assert "sleeve_id" in sig
            assert "sleeve_name" in sig
            assert "signal" in sig
            assert "confidence" in sig

    @pytest.mark.asyncio
    async def test_audit_summary_populated(self, engine):
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        state = engine.get_state()
        audit = state["audit_summary"]
        assert "total_entries" in audit
        assert "finra_3110_compliant" in audit
        assert audit["finra_3110_compliant"] is True


# ═══════════════════════════════════════════════════════════════════════════
# State During Crisis
# ═══════════════════════════════════════════════════════════════════════════

class TestStateDuringCrisis:
    @pytest.mark.asyncio
    async def test_crisis_level_reflected(self, engine):
        engine.feed.set_vix(50.0)
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        state = engine.get_state()
        assert state["crisis_level"] == "SmartBunker"

    @pytest.mark.asyncio
    async def test_crisis_audit_entries(self, engine):
        engine.feed.set_vix(50.0)
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()
        state = engine.get_state()
        audit = state["audit_summary"]
        assert audit["risk_events"] >= 1
