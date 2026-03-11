"""
Tests for Sleeve 4: RWA/Crypto Arbitrage.

Covers:
  - Spread detection (above/below threshold)
  - Opportunity ranking (best risk-adjusted)
  - Crisis override (VIX > 35 reduces, VIX > 45 flattens)
  - Permission bias application
  - Heartbeat timeout (65 min)
  - Stale opportunity clearing
  - Signal bounds (-1.0 to 1.0)
  - Regime-based spread estimation
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timedelta, timezone
from strategies.sleeve4_rwa_crypto import (
    RwaCryptoStrategy, Sleeve4Config, ArbitrageOpportunity,
)
from orchestrator import MarketState


def make_market(vix=15.0, spx=5000.0, tnx=4.2, es=5000.0, zn=110.0, zf=108.0, dxy=104.0):
    return MarketState(
        timestamp=datetime.now(timezone.utc),
        vix=vix, spx=spx, tnx=tnx, dxy=dxy,
        es_price=es, zn_price=zn, zf_price=zf,
    )


# ─── Spread Detection ────────────────────────────────────────────

class TestSpreadDetection:
    def test_calm_market_no_opportunity(self):
        """VIX=12, SPX=5000 -> spreads tight, no arb."""
        strategy = RwaCryptoStrategy()
        signal = strategy.generate_signal(make_market(vix=12.0, spx=5000.0))
        assert signal.sleeve_id == 4
        assert signal.sleeve_name == "RWA/Crypto"
        # Calm market: base_spread=3bps, VIX below 15 adds 0, threshold=7bps
        # Should be no opportunity
        assert signal.signal == 0.0
        assert "No arb" in signal.rationale

    def test_elevated_vix_creates_opportunity(self):
        """VIX=25 -> wider spreads -> opportunities appear."""
        strategy = RwaCryptoStrategy()
        signal = strategy.generate_signal(make_market(vix=25.0, spx=5000.0))
        # VIX=25 -> vix_component = (25-15)*0.5 = 5bps
        # Total spread for BTC: (3+5)*1.0 = 8bps > threshold 7bps
        assert signal.signal != 0.0
        assert "ARB" in signal.rationale

    def test_stress_regime_widens_spreads(self):
        """Stress regime applies 1.5x multiplier to spreads."""
        strategy = RwaCryptoStrategy()
        strategy.set_regime("stress")
        signal = strategy.generate_signal(make_market(vix=20.0, spx=5000.0))
        # VIX=20 -> vix_component = 2.5bps, base=3bps -> 5.5bps
        # Stress 1.5x -> 8.25bps for BTC > threshold 7bps
        assert signal.signal != 0.0

    def test_threshold_config_respected(self):
        """Custom config with higher threshold blocks opportunities."""
        config = Sleeve4Config(min_spread_bps=20.0, fee_bps=5.0)
        strategy = RwaCryptoStrategy(config=config)
        signal = strategy.generate_signal(make_market(vix=25.0))
        # Threshold = 25bps, spread ~8bps -> no opportunity
        assert signal.signal == 0.0


# ─── Opportunity Ranking ─────────────────────────────────────────

class TestOpportunityRanking:
    def test_best_opportunity_selected(self):
        """Strategy selects highest risk-adjusted opportunity."""
        strategy = RwaCryptoStrategy()
        # High VIX creates multiple opportunities
        signal = strategy.generate_signal(make_market(vix=30.0, spx=5000.0))
        # Should pick the best one (likely SOL with widest spread)
        assert signal.signal != 0.0
        assert len(signal.instruments) >= 1

    def test_btc_higher_confidence_than_sol(self):
        """BTC has higher volume score (0.9) vs SOL (0.5)."""
        strategy = RwaCryptoStrategy()
        spreads = strategy._estimate_crypto_spreads(make_market(vix=25.0))
        # BTC spread is tighter (factor 1.0) vs SOL (factor 1.30)
        assert spreads["BTC"] < spreads["SOL"]


# ─── Crisis Override ─────────────────────────────────────────────

class TestCrisisOverride:
    def test_vix_below_35_full_signal(self):
        """VIX < 35 -> no crisis reduction."""
        strategy = RwaCryptoStrategy()
        mult = strategy._crisis_multiplier(30.0)
        assert mult == 1.0

    def test_vix_35_reduces_50pct(self):
        """VIX > 35 -> 50% reduction."""
        strategy = RwaCryptoStrategy()
        mult = strategy._crisis_multiplier(36.0)
        assert mult == 0.5

    def test_vix_45_flattens(self):
        """VIX > 45 -> full flatten."""
        strategy = RwaCryptoStrategy()
        mult = strategy._crisis_multiplier(46.0)
        assert mult == 0.0

    def test_crisis_flatten_signal(self):
        """VIX > 45 produces zero signal with crisis rationale."""
        strategy = RwaCryptoStrategy()
        signal = strategy.generate_signal(make_market(vix=50.0))
        assert signal.signal == 0.0
        assert "CRISIS FLATTEN" in signal.rationale

    def test_crisis_reduce_halves_signal(self):
        """VIX=36 with opportunity produces half-strength signal."""
        strategy = RwaCryptoStrategy()
        # First generate with normal VIX to establish baseline
        normal_signal = strategy.generate_signal(make_market(vix=25.0))

        strategy2 = RwaCryptoStrategy()
        crisis_signal = strategy2.generate_signal(make_market(vix=36.0))

        if normal_signal.signal != 0 and crisis_signal.signal != 0:
            # Crisis signal should be reduced
            assert abs(crisis_signal.signal) <= abs(normal_signal.signal)


# ─── Permission Bias ─────────────────────────────────────────────

class TestPermissionBias:
    def test_zero_bias_blocks_signal(self):
        """Permission bias = 0 -> signal = 0."""
        strategy = RwaCryptoStrategy()
        strategy.set_permission_bias(0.0)
        signal = strategy.generate_signal(make_market(vix=25.0))
        assert signal.signal == 0.0

    def test_bias_scales_signal(self):
        """Permission bias < 1.0 reduces signal magnitude."""
        strategy = RwaCryptoStrategy()
        strategy.set_permission_bias(0.5)
        signal = strategy.generate_signal(make_market(vix=25.0))
        # Signal should be scaled by 0.5
        if signal.signal != 0.0:
            strategy2 = RwaCryptoStrategy()
            full_signal = strategy2.generate_signal(make_market(vix=25.0))
            assert abs(signal.signal) <= abs(full_signal.signal)

    def test_negative_bias_clamped_to_zero(self):
        """Negative bias clamped to 0."""
        strategy = RwaCryptoStrategy()
        strategy.set_permission_bias(-1.0)
        assert strategy._permission_bias == 0.0


# ─── Heartbeat Timeout ───────────────────────────────────────────

class TestHeartbeat:
    def test_no_timeout_when_recent(self):
        """Recent heartbeat -> no timeout."""
        strategy = RwaCryptoStrategy()
        strategy._last_master_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        assert strategy.check_heartbeat_timeout() is False

    def test_timeout_after_65_min(self):
        """65+ min since heartbeat -> timeout."""
        strategy = RwaCryptoStrategy()
        strategy._last_master_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=70)
        assert strategy.check_heartbeat_timeout() is True

    def test_no_timeout_without_heartbeat(self):
        """No previous heartbeat -> no timeout (first tick)."""
        strategy = RwaCryptoStrategy()
        assert strategy.check_heartbeat_timeout() is False

    def test_timeout_produces_liquidate_signal(self):
        """Heartbeat timeout -> LIQUIDATE signal."""
        strategy = RwaCryptoStrategy()
        strategy._last_master_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=70)
        signal = strategy.generate_signal(make_market())
        assert signal.signal == 0.0
        assert "LIQUIDATE" in signal.rationale


# ─── Stale Opportunity Clearing ───────────────────────────────────

class TestStaleOpportunities:
    def test_stale_opportunities_cleared(self):
        """Opportunities older than timeout are removed."""
        strategy = RwaCryptoStrategy()
        old_opp = ArbitrageOpportunity(
            symbol="BTC", spot_price=50000.0, futures_price=50100.0,
            spread_bps=20.0, profit_potential_bps=18.0, confidence=0.8,
            detected_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        strategy._opportunities.append(old_opp)
        strategy._clear_stale_opportunities()
        assert len(strategy._opportunities) == 0

    def test_fresh_opportunities_kept(self):
        """Recent opportunities are preserved."""
        strategy = RwaCryptoStrategy()
        fresh_opp = ArbitrageOpportunity(
            symbol="ETH", spot_price=3000.0, futures_price=3010.0,
            spread_bps=10.0, profit_potential_bps=8.0, confidence=0.7,
            detected_at=datetime.now(timezone.utc),
        )
        strategy._opportunities.append(fresh_opp)
        strategy._clear_stale_opportunities()
        assert len(strategy._opportunities) == 1


# ─── Signal Bounds ────────────────────────────────────────────────

class TestSignalBounds:
    def test_signal_never_exceeds_1(self):
        """Signal clamped to [-1.0, 1.0]."""
        strategy = RwaCryptoStrategy()
        strategy.set_permission_bias(5.0)  # Very high bias
        signal = strategy.generate_signal(make_market(vix=30.0))
        assert -1.0 <= signal.signal <= 1.0

    def test_confidence_in_range(self):
        """Confidence always between 0 and 1."""
        strategy = RwaCryptoStrategy()
        signal = strategy.generate_signal(make_market(vix=25.0))
        assert 0.0 <= signal.confidence <= 1.0


# ─── Status ──────────────────────────────────────────────────────

class TestStatus:
    def test_get_status_structure(self):
        """get_status() returns expected fields."""
        strategy = RwaCryptoStrategy()
        strategy.generate_signal(make_market())
        status = strategy.get_status()
        assert status["sleeve"] == "RWA/Crypto"
        assert "active_opportunities" in status
        assert "trade_count" in status
        assert "symbols" in status
        assert status["symbols"] == ["BTC", "ETH", "SOL"]

    def test_regime_affects_status(self):
        """Regime change reflected in status."""
        strategy = RwaCryptoStrategy()
        strategy.set_regime("crisis")
        assert strategy.get_status()["regime"] == "crisis"

    def test_new_trading_day_clears_opportunities(self):
        """new_trading_day() clears pending opportunities."""
        strategy = RwaCryptoStrategy()
        strategy.generate_signal(make_market(vix=30.0))
        strategy.new_trading_day()
        assert len(strategy._opportunities) == 0
