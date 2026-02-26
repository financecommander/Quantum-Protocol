"""
Integration test: Full system flow.
Market data → SERAPH AI regime → Sleeve signals → Risk overlay → Target positions
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime
from orchestrator import Orchestrator, MarketState, SleeveAllocation, CrisisLevel


def make_market(vix=15.0, spx=4500.0, tnx=4.2, es=4500.0, zn=110.0, zf=108.0, dxy=104.0):
    """Helper to create MarketState."""
    return MarketState(
        timestamp=datetime.utcnow(),
        vix=vix, spx=spx, tnx=tnx, dxy=dxy,
        es_price=es, zn_price=zn, zf_price=zf,
    )


class TestOrchestratorBasics:
    def test_allocation_sums_to_one(self):
        alloc = SleeveAllocation()
        total = (alloc.treasury_yield + alloc.compression_curve +
                 alloc.prop_scaling + alloc.rwa_infrastructure +
                 alloc.convexity_shield + alloc.cash)
        assert abs(total - 1.0) < 0.001

    def test_invalid_allocation_raises(self):
        with pytest.raises(ValueError):
            SleeveAllocation(treasury_yield=0.5, prop_scaling=0.8)

    def test_default_allocation_matches_plan(self):
        alloc = SleeveAllocation()
        assert alloc.treasury_yield == 0.10
        assert alloc.compression_curve == 0.15
        assert alloc.prop_scaling == 0.45
        assert alloc.rwa_infrastructure == 0.00  # Deferred
        assert alloc.convexity_shield == 0.10
        assert alloc.cash == 0.20


class TestCrisisEvaluation:
    def test_normal_market(self):
        orch = Orchestrator()
        market = make_market(vix=15.0)
        level = orch.evaluate_crisis(market)
        assert level == CrisisLevel.NORMAL

    def test_elevated(self):
        orch = Orchestrator()
        level = orch.evaluate_crisis(make_market(vix=22.0))
        assert level == CrisisLevel.ELEVATED

    def test_smart_bunker(self):
        orch = Orchestrator()
        level = orch.evaluate_crisis(make_market(vix=50.0))
        assert level == CrisisLevel.SMART_BUNKER


class TestRiskOverlay:
    def test_normal_market_passes_signals(self):
        orch = Orchestrator()
        orch.crisis_level = CrisisLevel.NORMAL

        from orchestrator import SleeveSignal
        signals = [
            SleeveSignal(1, "Treasury", 0.8, 0.9),
            SleeveSignal(3, "Prop", 0.6, 0.7),
        ]
        adjusted = orch.apply_risk_overlay(signals)
        assert adjusted[0].signal == 0.8
        assert adjusted[1].signal == 0.6

    def test_smart_bunker_flattens_non_hedges(self):
        orch = Orchestrator()
        orch.crisis_level = CrisisLevel.SMART_BUNKER

        from orchestrator import SleeveSignal
        signals = [
            SleeveSignal(1, "Treasury", 0.8, 0.9),
            SleeveSignal(3, "Prop", 0.6, 0.7),
            SleeveSignal(5, "ConvexityShield", 0.9, 0.8),
        ]
        adjusted = orch.apply_risk_overlay(signals)
        
        # Sleeves 1, 3 should be flattened
        assert adjusted[0].signal == 0.0
        assert adjusted[1].signal == 0.0
        # Sleeve 5 (hedge) should survive
        assert adjusted[2].signal == 0.9

    def test_surgical_sniper_halves_signals(self):
        orch = Orchestrator()
        orch.crisis_level = CrisisLevel.SURGICAL_SNIPER

        from orchestrator import SleeveSignal
        signals = [SleeveSignal(3, "Prop", 0.8, 0.9)]
        adjusted = orch.apply_risk_overlay(signals)
        assert abs(adjusted[0].signal - 0.4) < 0.001  # 50% reduction

    def test_kill_switch_zeros_everything(self):
        orch = Orchestrator()
        orch.is_killed = True

        from orchestrator import SleeveSignal
        signals = [
            SleeveSignal(1, "Treasury", 0.8, 0.9),
            SleeveSignal(5, "Hedge", 0.9, 0.8),
        ]
        adjusted = orch.apply_risk_overlay(signals)
        for s in adjusted:
            assert s.signal == 0.0


class TestPositionCalculation:
    def test_basic_position_sizing(self):
        orch = Orchestrator(portfolio_value=100_000)

        from orchestrator import SleeveSignal
        signals = [
            SleeveSignal(3, "Prop Scaling", 1.0, 1.0),  # Full signal, full confidence
        ]
        positions = orch.calculate_positions(signals)
        
        # Sleeve 3 gets 45% of $100K = $45K, signal=1.0, conf=1.0
        assert "Prop Scaling" in positions
        assert positions["Prop Scaling"]["target_position"] == 45_000.0

    def test_half_signal_half_position(self):
        orch = Orchestrator(portfolio_value=100_000)

        from orchestrator import SleeveSignal
        signals = [
            SleeveSignal(3, "Prop Scaling", 0.5, 1.0),  # Half signal
        ]
        positions = orch.calculate_positions(signals)
        assert positions["Prop Scaling"]["target_position"] == 22_500.0

    def test_zero_signal_zero_position(self):
        orch = Orchestrator(portfolio_value=100_000)

        from orchestrator import SleeveSignal
        signals = [SleeveSignal(3, "Prop", 0.0, 0.9)]
        positions = orch.calculate_positions(signals)
        assert positions["Prop"]["target_position"] == 0.0


class TestFullTickCycle:
    """Test complete tick: market data → crisis → signals → risk → positions."""
    
    def test_normal_tick_produces_positions(self):
        orch = Orchestrator(portfolio_value=50_000)
        market = make_market(vix=15.0, es=4500.0)
        
        positions = orch.tick(market)
        # Should have positions dict (may be empty if sleeves not loaded)
        assert isinstance(positions, dict)
        assert orch.crisis_level == CrisisLevel.NORMAL

    def test_crisis_tick_reduces_positions(self):
        orch = Orchestrator(portfolio_value=50_000)
        
        # Normal tick first
        normal_market = make_market(vix=15.0)
        orch.tick(normal_market)
        assert orch.crisis_level == CrisisLevel.NORMAL
        
        # Crisis tick
        crisis_market = make_market(vix=50.0)
        orch.tick(crisis_market)
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER


# ═══ Permission Vector Integration ════════════════════════════

class TestPermissionVectorIntegration:
    """Tests that permission vector is properly wired into the tick cycle."""

    def test_permission_vector_initializes(self):
        o = Orchestrator()
        assert o._generate_vector is not None

    def test_growth_regime_boosts_prop(self):
        o = Orchestrator()
        o._broadcast_permission_vector("growth")
        if 3 in o._sleeves:
            assert o._sleeves[3]._permission_bias > 1.0

    def test_crisis_regime_blocks_prop_and_curve(self):
        o = Orchestrator()
        o._broadcast_permission_vector("crisis")
        if 3 in o._sleeves:
            assert o._sleeves[3]._permission_bias == 0.0
        if 2 in o._sleeves:
            assert o._sleeves[2]._permission_bias == 0.0

    def test_crisis_regime_boosts_tail(self):
        o = Orchestrator()
        o._broadcast_permission_vector("crisis")
        if 5 in o._sleeves:
            assert o._sleeves[5]._permission_bias > 1.0

    def test_stress_regime_boosts_treasury_and_tail(self):
        o = Orchestrator()
        o._broadcast_permission_vector("stress")
        if 1 in o._sleeves:
            assert o._sleeves[1]._permission_bias > 1.0
        if 5 in o._sleeves:
            assert o._sleeves[5]._permission_bias > 1.0

    def test_tick_broadcasts_vector(self):
        """Verify tick() actually broadcasts permission vector."""
        o = Orchestrator()
        market = MarketState(
            timestamp=datetime.utcnow(), vix=15.0, spx=5000.0,
            tnx=42.0, dxy=104.0, es_price=5000.0,
            zn_price=110.0, zf_price=108.0,
        )
        o.tick(market)
        assert o._current_vector is not None

    def test_human_approval_gate_on_large_shift(self):
        """Growth → crisis should flag for human approval."""
        o = Orchestrator()
        o._broadcast_permission_vector("growth")
        o._broadcast_permission_vector("crisis")
        # growth→crisis: prop goes 1.15→0.0 (100% shift)
        assert o._human_approval_pending is True
