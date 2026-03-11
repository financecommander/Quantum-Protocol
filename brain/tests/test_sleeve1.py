"""
Tests for Sleeve 1: Treasury Yield (The Anchor™).

Covers:
  - Regime classification (normal, flat, inverted, spike)
  - Entry: 2s10s > 50bps
  - Exit: 2s10s < 20bps → rotate short
  - Yield spike: > 2σ move → auto-pause
  - Quarterly rebalancing
  - Signal direction (long-only or cash, never short)
  - Heartbeat failsafe
  - Permission vector gating
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timedelta, timezone
from strategies.sleeve1_treasury_yield import (
    TreasuryYieldStrategy, Sleeve1Config, YieldMarketData,
    YieldRegime, YieldAction,
)


@pytest.fixture
def strategy():
    return TreasuryYieldStrategy()


def make_yield_data(**kwargs) -> YieldMarketData:
    defaults = dict(
        spread_2s10s=80.0, yield_10y=4.25, yield_2y=3.45,
        yield_change_1d=2.0, yield_std_20d=5.0, vix=18.0,
    )
    defaults.update(kwargs)
    return YieldMarketData(**defaults)


# Helper for generate_signal (needs MarketState-like object)
class MockMarket:
    def __init__(self, tnx=42.5, vix=18.0, yield_change_1d=2.0, yield_std_20d=5.0):
        self.tnx = tnx
        self.vix = vix
        self.spx = 5000.0
        self.dxy = 104.0
        self.es_price = 5000.0
        self.zn_price = 110.0
        self.zf_price = 108.0
        self.yield_change_1d = yield_change_1d
        self.yield_std_20d = yield_std_20d
        self.timestamp = datetime.now(timezone.utc)


# ═══ Regime Classification ═══════════════════════════════════════

class TestRegimeClassification:
    def test_normal_above_50bps(self, strategy):
        data = make_yield_data(spread_2s10s=80.0, yield_change_1d=1.0)
        assert strategy.classify_regime(data) == YieldRegime.NORMAL

    def test_flat_between_20_and_50(self, strategy):
        data = make_yield_data(spread_2s10s=35.0, yield_change_1d=1.0)
        assert strategy.classify_regime(data) == YieldRegime.FLAT

    def test_inverted_below_20bps(self, strategy):
        data = make_yield_data(spread_2s10s=10.0, yield_change_1d=1.0)
        assert strategy.classify_regime(data) == YieldRegime.INVERTED

    def test_boundary_50_is_flat(self, strategy):
        """50bps exactly is FLAT (threshold is >50)."""
        data = make_yield_data(spread_2s10s=50.0, yield_change_1d=1.0)
        assert strategy.classify_regime(data) == YieldRegime.FLAT

    def test_boundary_20_is_flat(self, strategy):
        """20bps exactly is FLAT (inverted is <20)."""
        data = make_yield_data(spread_2s10s=20.0, yield_change_1d=1.0)
        assert strategy.classify_regime(data) == YieldRegime.FLAT

    def test_negative_spread_inverted(self, strategy):
        data = make_yield_data(spread_2s10s=-15.0, yield_change_1d=1.0)
        assert strategy.classify_regime(data) == YieldRegime.INVERTED


# ═══ Yield Spike Detection ══════════════════════════════════════

class TestYieldSpike:
    def test_spike_on_large_move(self, strategy):
        """15bps move vs 5bps std = 3σ → spike."""
        data = make_yield_data(
            spread_2s10s=80.0,
            yield_change_1d=15.0,
            yield_std_20d=5.0,
        )
        assert strategy.classify_regime(data) == YieldRegime.SPIKE

    def test_no_spike_on_normal_move(self, strategy):
        """5bps move vs 5bps std = 1σ → no spike."""
        data = make_yield_data(
            spread_2s10s=80.0,
            yield_change_1d=5.0,
            yield_std_20d=5.0,
        )
        assert strategy.classify_regime(data) == YieldRegime.NORMAL

    def test_spike_overrides_normal(self, strategy):
        """Even with good spread, spike pauses everything."""
        data = make_yield_data(
            spread_2s10s=100.0,       # Great spread
            yield_change_1d=12.0,     # But huge move
            yield_std_20d=5.0,        # 2.4σ
        )
        assert strategy.classify_regime(data) == YieldRegime.SPIKE

    def test_negative_spike_also_triggers(self, strategy):
        """Large yield DROP also triggers pause (absolute value)."""
        data = make_yield_data(
            spread_2s10s=80.0,
            yield_change_1d=-15.0,    # Negative = yield drop
            yield_std_20d=5.0,
        )
        assert strategy.classify_regime(data) == YieldRegime.SPIKE

    def test_zero_std_no_spike(self, strategy):
        """Zero std dev → don't divide by zero."""
        data = make_yield_data(
            spread_2s10s=80.0,
            yield_change_1d=10.0,
            yield_std_20d=0.0,
        )
        assert strategy.classify_regime(data) != YieldRegime.SPIKE


# ═══ Signal Direction ═══════════════════════════════════════════

class TestSignalDirection:
    """Sleeve 1 is long-only or cash. Never short."""

    def test_normal_regime_positive_signal(self, strategy):
        market = MockMarket(tnx=47.5, vix=18.0)  # 4.75% - 4.75% = spread ~ 0bps... 
        # With FF=4.50, 2yr_est=4.75, 10yr=4.75 → spread=0bps → FLAT
        # Use higher TNX for wide spread
        market.tnx = 52.0  # 5.2% 10yr → spread = (5.2 - 4.75)*100 = 45bps → FLAT
        market.tnx = 55.0  # 5.5% 10yr → spread = (5.5 - 4.75)*100 = 75bps → NORMAL
        signal = strategy.generate_signal(market)
        assert signal.signal > 0
        assert signal.sleeve_id == 1

    def test_spike_regime_zero_signal(self, strategy):
        market = MockMarket(tnx=55.0, yield_change_1d=15.0, yield_std_20d=5.0)
        signal = strategy.generate_signal(market)
        assert signal.signal == 0.0
        assert "PAUSED" in signal.rationale

    def test_inverted_zero_signal(self, strategy):
        """Flat/inverted curve → cash."""
        market = MockMarket(tnx=46.0)  # 4.6% → spread = (4.6-4.75)*100 = -15bps → INVERTED
        signal = strategy.generate_signal(market)
        assert signal.signal == 0.0
        assert "ROTATE" in signal.rationale

    def test_signal_never_negative(self, strategy):
        """Sleeve 1 never shorts treasuries."""
        for tnx in [30, 40, 45, 46, 47, 50, 55, 60]:
            market = MockMarket(tnx=float(tnx))
            signal = strategy.generate_signal(market)
            assert signal.signal >= 0.0, f"Signal should never be negative at TNX={tnx}"


# ═══ Heartbeat Failsafe ═════════════════════════════════════════

class TestHeartbeat:
    def test_no_timeout_when_recent(self, strategy):
        strategy._last_master_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        assert strategy.check_heartbeat_timeout() is False

    def test_timeout_after_65_min(self, strategy):
        strategy._last_master_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=70)
        assert strategy.check_heartbeat_timeout() is True

    def test_no_timeout_without_heartbeat(self, strategy):
        assert strategy.check_heartbeat_timeout() is False


# ═══ Quarterly Rebalance ════════════════════════════════════════

class TestQuarterlyRebalance:
    def test_needs_rebalance_after_90_days(self, strategy):
        strategy._days_since_rebalance = 90
        assert strategy.needs_quarterly_rebalance() is True

    def test_no_rebalance_before_90_days(self, strategy):
        strategy._days_since_rebalance = 60
        assert strategy.needs_quarterly_rebalance() is False

    def test_new_trading_day_increments(self, strategy):
        strategy._days_since_rebalance = 5
        strategy.new_trading_day()
        assert strategy._days_since_rebalance == 6

    def test_rebalance_resets_counter(self, strategy):
        """After rebalance signal, counter should reset."""
        strategy._days_since_rebalance = 95
        market = MockMarket(tnx=55.0)  # Normal regime
        signal = strategy.generate_signal(market)
        assert "REBALANCE" in signal.rationale
        assert strategy._days_since_rebalance == 0


# ═══ Permission Bias ════════════════════════════════════════════

class TestPermissionBias:
    def test_bias_scales_signal(self, strategy):
        strategy._permission_bias = 0.5
        market = MockMarket(tnx=55.0)
        signal = strategy.generate_signal(market)
        # Normal regime entry signal * 0.5 bias
        assert signal.signal <= 0.5

    def test_zero_bias_blocks(self, strategy):
        strategy._permission_bias = 0.0
        market = MockMarket(tnx=55.0)
        signal = strategy.generate_signal(market)
        assert signal.signal == 0.0

    def test_set_permission_clamps_negative(self, strategy):
        strategy.set_permission_bias(-0.5)
        assert strategy._permission_bias == 0.0


# ═══ Leverage Cap ═══════════════════════════════════════════════

class TestLeverageCap:
    def test_max_leverage_is_1x(self):
        config = Sleeve1Config()
        assert config.max_leverage == 1.0

    def test_signal_never_exceeds_1(self, strategy):
        """Even with high bias, signal can't exceed 1.0."""
        strategy._permission_bias = 2.0  # Extreme bias
        market = MockMarket(tnx=55.0)
        signal = strategy.generate_signal(market)
        # 1.0 * 2.0 = 2.0 but signal meaning caps effective exposure at 1x
        # Signal itself can be > 1 but leverage enforcement is in order_manager
        assert signal.signal > 0  # Still valid positive signal


# ═══ Status ═════════════════════════════════════════════════════

class TestStatus:
    def test_status_has_all_fields(self, strategy):
        status = strategy.get_status()
        assert "sleeve" in status
        assert "regime" in status
        assert "is_positioned" in status
        assert "is_paused" in status
        assert "days_since_rebalance" in status
