"""
Tests for Sleeve 2: Compression & Curve Trading.
Validates all hard-coded rules from the strategy spec.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timedelta, timezone
from strategies.sleeve2_compression_curve import (
    CompressionCurveStrategy, Sleeve2Config, CurveMarketData,
    CurveTradeType, CurveRegime,
)


@pytest.fixture
def strategy():
    return CompressionCurveStrategy()


def make_data(**kwargs) -> CurveMarketData:
    """Helper to create market data with defaults."""
    defaults = dict(
        spread_2s10s=50.0, spread_2s5s=20.0, spread_5s10s=30.0,
        vix=18.0, fed_funds_rate=4.50, fed_dot_median=4.00,
        zn_price=110.0, zf_price=108.0,
    )
    defaults.update(kwargs)
    return CurveMarketData(**defaults)


# ─── Regime Classification ──────────────────────────────────────

class TestRegimeClassification:
    def test_normal_regime(self, strategy):
        data = make_data(spread_2s10s=50.0)
        assert strategy.classify_regime(data) == CurveRegime.NORMAL

    def test_steep_regime(self, strategy):
        data = make_data(spread_2s10s=120.0)
        assert strategy.classify_regime(data) == CurveRegime.STEEP

    def test_inverted_regime(self, strategy):
        data = make_data(spread_2s10s=-30.0)
        assert strategy.classify_regime(data) == CurveRegime.INVERTED

    def test_flat_regime(self, strategy):
        data = make_data(spread_2s10s=15.0)
        assert strategy.classify_regime(data) == CurveRegime.FLAT

    def test_boundary_100bps_is_not_steep(self, strategy):
        """100bps exactly is normal (threshold is >100)."""
        data = make_data(spread_2s10s=100.0)
        assert strategy.classify_regime(data) == CurveRegime.NORMAL

    def test_boundary_0bps_is_not_inverted(self, strategy):
        """0bps exactly is flat (threshold is <0 for inverted)."""
        data = make_data(spread_2s10s=0.0)
        assert strategy.classify_regime(data) == CurveRegime.FLAT


# ─── Flattener Entry Rules ──────────────────────────────────────

class TestFlattenerEntry:
    def test_flattener_fires_on_both_conditions(self, strategy):
        """2s10s > 100bps AND dot median > FF by ≥25bps → entry."""
        data = make_data(
            spread_2s10s=120.0,
            fed_funds_rate=4.50,
            fed_dot_median=4.80,  # 30bps above FF → ≥25bps ✓
        )
        assert strategy.check_flattener_entry(data) is True

    def test_flattener_no_fire_spread_too_narrow(self, strategy):
        """2s10s < 100bps → no entry regardless of Fed."""
        data = make_data(
            spread_2s10s=80.0,
            fed_funds_rate=4.50,
            fed_dot_median=5.00,
        )
        assert strategy.check_flattener_entry(data) is False

    def test_flattener_no_fire_no_hike_signal(self, strategy):
        """Spread wide but dot median not above FF enough → no entry."""
        data = make_data(
            spread_2s10s=120.0,
            fed_funds_rate=4.50,
            fed_dot_median=4.60,  # Only 10bps above FF → <25bps ✗
        )
        assert strategy.check_flattener_entry(data) is False

    def test_flattener_exact_25bps_gap_fires(self, strategy):
        """Exactly 25bps gap should fire (≥25bps)."""
        data = make_data(
            spread_2s10s=101.0,
            fed_funds_rate=4.50,
            fed_dot_median=4.75,  # Exactly 25bps above
        )
        assert strategy.check_flattener_entry(data) is True


# ─── Steepener Entry Rules ──────────────────────────────────────

class TestSteepenerEntry:
    def test_steepener_fires_on_both_conditions(self, strategy):
        """Inverted curve AND VIX > 20 → entry."""
        data = make_data(spread_2s10s=-25.0, vix=25.0)
        assert strategy.check_steepener_entry(data) is True

    def test_steepener_no_fire_not_inverted(self, strategy):
        """Positive spread → no steepener even with high VIX."""
        data = make_data(spread_2s10s=10.0, vix=30.0)
        assert strategy.check_steepener_entry(data) is False

    def test_steepener_no_fire_low_vix(self, strategy):
        """Inverted but VIX < 20 → no confirmation, no entry."""
        data = make_data(spread_2s10s=-15.0, vix=18.0)
        assert strategy.check_steepener_entry(data) is False

    def test_steepener_exactly_vix_20_no_fire(self, strategy):
        """VIX = 20.0 exactly does NOT fire (must be >20)."""
        data = make_data(spread_2s10s=-15.0, vix=20.0)
        assert strategy.check_steepener_entry(data) is False


# ─── Exit Rules ─────────────────────────────────────────────────

class TestExitRules:
    def test_no_exit_when_flat(self, strategy):
        """No trade → no exit signal."""
        data = make_data()
        should_exit, _ = strategy.check_exit(data)
        assert should_exit is False

    def test_flattener_profit_target(self, strategy):
        """Flattener profits when spread narrows by 20bps."""
        strategy.current_trade = CurveTradeType.FLATTENER
        strategy.entry_spread = 120.0
        strategy.last_master_heartbeat = datetime.now(timezone.utc)

        data = make_data(spread_2s10s=100.0)  # Narrowed 20bps ✓
        should_exit, reason = strategy.check_exit(data)
        assert should_exit is True
        assert "profit_target" in reason

    def test_flattener_stop_loss(self, strategy):
        """Flattener stops out when spread widens by 20bps."""
        strategy.current_trade = CurveTradeType.FLATTENER
        strategy.entry_spread = 120.0
        strategy.last_master_heartbeat = datetime.now(timezone.utc)

        data = make_data(spread_2s10s=140.0)  # Widened 20bps ✗
        should_exit, reason = strategy.check_exit(data)
        assert should_exit is True
        assert "stop_loss" in reason

    def test_steepener_profit_target(self, strategy):
        """Steepener profits when spread widens by 20bps."""
        strategy.current_trade = CurveTradeType.STEEPENER
        strategy.entry_spread = -20.0
        strategy.last_master_heartbeat = datetime.now(timezone.utc)

        data = make_data(spread_2s10s=0.0)  # Widened 20bps ✓
        should_exit, reason = strategy.check_exit(data)
        assert should_exit is True
        assert "profit_target" in reason

    def test_steepener_stop_loss(self, strategy):
        """Steepener stops out when spread narrows further."""
        strategy.current_trade = CurveTradeType.STEEPENER
        strategy.entry_spread = -20.0
        strategy.last_master_heartbeat = datetime.now(timezone.utc)

        data = make_data(spread_2s10s=-40.0)  # Narrowed 20bps against ✗
        should_exit, reason = strategy.check_exit(data)
        assert should_exit is True
        assert "stop_loss" in reason

    def test_heartbeat_timeout_exits(self, strategy):
        """Master silent >65 min → emergency exit."""
        strategy.current_trade = CurveTradeType.FLATTENER
        strategy.entry_spread = 120.0
        strategy.last_master_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=70)

        data = make_data(spread_2s10s=120.0)  # No P&L change
        should_exit, reason = strategy.check_exit(data)
        assert should_exit is True
        assert "heartbeat" in reason

    def test_heartbeat_ok_no_exit(self, strategy):
        """Recent heartbeat → no timeout exit."""
        strategy.current_trade = CurveTradeType.FLATTENER
        strategy.entry_spread = 120.0
        strategy.last_master_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)

        data = make_data(spread_2s10s=115.0)  # Small favorable move
        should_exit, reason = strategy.check_exit(data)
        assert should_exit is False


# ─── Leverage Calculation ───────────────────────────────────────

class TestLeverage:
    def test_low_vol_gets_higher_leverage(self, strategy):
        """Low VIX → higher leverage (capped at 2x)."""
        data = make_data(vix=10.0)
        lev = strategy.calculate_leverage(data)
        assert lev <= 2.0
        assert lev > 1.0

    def test_high_vol_gets_lower_leverage(self, strategy):
        """High VIX → lower leverage (vol targeting reduces size)."""
        data = make_data(vix=35.0)
        lev = strategy.calculate_leverage(data)
        assert lev < 1.0

    def test_leverage_never_exceeds_2x(self, strategy):
        """Hard cap at 2x regardless of vol estimate."""
        data = make_data(vix=5.0)  # Very low vol → high desired leverage
        lev = strategy.calculate_leverage(data)
        assert lev <= 2.0

    def test_leverage_never_negative(self, strategy):
        data = make_data(vix=100.0)
        lev = strategy.calculate_leverage(data)
        assert lev >= 0.0


# ─── Trade Lifecycle ────────────────────────────────────────────

class TestTradeLifecycle:
    def test_open_and_close_trade(self, strategy):
        data = make_data(spread_2s10s=120.0)
        strategy._open_trade(CurveTradeType.FLATTENER, data)
        
        assert strategy.current_trade == CurveTradeType.FLATTENER
        assert strategy.entry_spread == 120.0
        assert strategy._trade_count == 1

        strategy._close_trade("test")
        assert strategy.current_trade == CurveTradeType.NONE
        assert strategy.entry_spread == 0.0

    def test_trade_count_increments(self, strategy):
        for i in range(3):
            data = make_data(spread_2s10s=110.0 + i)
            strategy._open_trade(CurveTradeType.FLATTENER, data)
            strategy._close_trade("test")
        assert strategy._trade_count == 3
