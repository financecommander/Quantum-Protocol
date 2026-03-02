"""
Market Data Feed Tests

Tests MockMarketDataFeed scenario replay, overrides, lifecycle,
error handling, and AlpacaMarketDataFeed fallback behavior.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain"))

import pytest
from feeds.market_data import MockMarketDataFeed, AlpacaMarketDataFeed
from orchestrator import MarketState


# ═══════════════════════════════════════════════════════════════════════════
# MockMarketDataFeed Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestMockFeedLifecycle:
    @pytest.mark.asyncio
    async def test_connect_succeeds(self):
        feed = MockMarketDataFeed()
        assert await feed.connect() is True

    @pytest.mark.asyncio
    async def test_disconnect(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        await feed.disconnect()
        assert feed._connected is False

    @pytest.mark.asyncio
    async def test_get_market_state_requires_connection(self):
        feed = MockMarketDataFeed()
        with pytest.raises(ConnectionError):
            await feed.get_market_state()

    @pytest.mark.asyncio
    async def test_subscribe_is_noop(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        await feed.subscribe(["SPY", "TLT"])  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# MockMarketDataFeed Defaults
# ═══════════════════════════════════════════════════════════════════════════

class TestMockFeedDefaults:
    @pytest.mark.asyncio
    async def test_default_vix(self):
        feed = MockMarketDataFeed(default_vix=20.0)
        await feed.connect()
        state = await feed.get_market_state()
        assert state.vix == 20.0

    @pytest.mark.asyncio
    async def test_default_spx(self):
        feed = MockMarketDataFeed(default_spx=4800.0)
        await feed.connect()
        state = await feed.get_market_state()
        assert state.spx == 4800.0

    @pytest.mark.asyncio
    async def test_returns_market_state(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        state = await feed.get_market_state()
        assert isinstance(state, MarketState)
        assert state.tnx == 40.0
        assert state.dxy == 104.0

    @pytest.mark.asyncio
    async def test_timestamp_is_aware(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        state = await feed.get_market_state()
        assert state.timestamp.tzinfo is not None


# ═══════════════════════════════════════════════════════════════════════════
# VIX and Depeg Overrides
# ═══════════════════════════════════════════════════════════════════════════

class TestMockFeedOverrides:
    @pytest.mark.asyncio
    async def test_set_vix_override(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        feed.set_vix(45.0)
        state = await feed.get_market_state()
        assert state.vix == 45.0

    @pytest.mark.asyncio
    async def test_set_depeg_override(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        feed.set_depeg(8.0)
        state = await feed.get_market_state()
        assert state.depeg_pct == 8.0

    @pytest.mark.asyncio
    async def test_override_persists_across_ticks(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        feed.set_vix(30.0)
        state1 = await feed.get_market_state()
        state2 = await feed.get_market_state()
        assert state1.vix == 30.0
        assert state2.vix == 30.0


# ═══════════════════════════════════════════════════════════════════════════
# Scenario Replay
# ═══════════════════════════════════════════════════════════════════════════

class TestMockFeedScenario:
    @pytest.mark.asyncio
    async def test_scenario_replays_in_order(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        feed.set_scenario([
            {"vix": 18.0},
            {"vix": 25.0},
            {"vix": 52.0},
        ])
        s1 = await feed.get_market_state()
        s2 = await feed.get_market_state()
        s3 = await feed.get_market_state()
        assert s1.vix == 18.0
        assert s2.vix == 25.0
        assert s3.vix == 52.0

    @pytest.mark.asyncio
    async def test_scenario_falls_through_to_defaults(self):
        """After scenario exhausted, falls back to defaults."""
        feed = MockMarketDataFeed(default_vix=20.0)
        await feed.connect()
        feed.set_scenario([{"vix": 50.0}])
        s1 = await feed.get_market_state()
        s2 = await feed.get_market_state()
        assert s1.vix == 50.0
        assert s2.vix == 20.0  # Fell through to default

    @pytest.mark.asyncio
    async def test_scenario_with_depeg(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        feed.set_scenario([
            {"vix": 52.0, "depeg_pct": 0.0},
            {"vix": 30.0, "depeg_pct": 8.0},
        ])
        s1 = await feed.get_market_state()
        s2 = await feed.get_market_state()
        assert s1.depeg_pct == 0.0
        assert s2.depeg_pct == 8.0

    @pytest.mark.asyncio
    async def test_scenario_with_all_fields(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        feed.set_scenario([{
            "vix": 25.0,
            "spx": 4200.0,
            "tnx": 45.0,
            "dxy": 108.0,
            "es_price": 4200.0,
            "zn_price": 112.0,
            "zf_price": 109.0,
            "depeg_pct": 3.0,
        }])
        s = await feed.get_market_state()
        assert s.vix == 25.0
        assert s.spx == 4200.0
        assert s.tnx == 45.0
        assert s.dxy == 108.0
        assert s.es_price == 4200.0
        assert s.zn_price == 112.0
        assert s.zf_price == 109.0
        assert s.depeg_pct == 3.0

    @pytest.mark.asyncio
    async def test_tick_count_increments(self):
        feed = MockMarketDataFeed()
        await feed.connect()
        assert feed._tick_count == 0
        await feed.get_market_state()
        await feed.get_market_state()
        assert feed._tick_count == 2


# ═══════════════════════════════════════════════════════════════════════════
# AlpacaMarketDataFeed Fallback
# ═══════════════════════════════════════════════════════════════════════════

class TestAlpacaFeedFallback:
    @pytest.mark.asyncio
    async def test_connect_without_key_enters_fallback(self):
        """Without API key, Alpaca feed should connect in fallback mode."""
        feed = AlpacaMarketDataFeed(api_key="", secret_key="")
        result = await feed.connect()
        assert result is True
        assert feed._connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self):
        feed = AlpacaMarketDataFeed(api_key="", secret_key="")
        await feed.connect()
        await feed.disconnect()
        assert feed._connected is False

    @pytest.mark.asyncio
    async def test_subscribe_updates_symbols(self):
        feed = AlpacaMarketDataFeed()
        await feed.subscribe(["AAPL", "TSLA"])
        assert feed._symbols == ["AAPL", "TSLA"]

    @pytest.mark.asyncio
    async def test_fallback_returns_market_state(self):
        """In fallback mode (no key), get_market_state should still work."""
        feed = AlpacaMarketDataFeed(api_key="", secret_key="")
        await feed.connect()
        state = await feed.get_market_state()
        assert isinstance(state, MarketState)
        assert state.timestamp.tzinfo is not None
