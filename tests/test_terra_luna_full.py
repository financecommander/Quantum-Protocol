"""
Terra Luna Full Orchestrator Replay

Replays the May 2022 Terra Luna / UST crisis through the full orchestrator
tick cycle: market data → SERAPH regime → permission vector → crisis eval →
signals → risk overlay → position calculation → audit logging.

Unlike the simplified parity tests, this validates the complete system behavior:
  - Crisis transitions happen at correct VIX/depeg thresholds
  - Risk overlay flattens/reduces positions correctly per crisis level
  - Sleeve 5 (tail hedge) survives SmartBunker
  - Permission vector shifts are detected
  - Audit trail captures all crisis transitions
  - System recovers cleanly to Normal
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain"))

import pytest
from datetime import datetime, timezone, timedelta
from orchestrator import Orchestrator, MarketState, CrisisLevel, SleeveSignal


def make_market(
    vix=15.0, spx=5000.0, tnx=40.0, dxy=104.0,
    es=5000.0, zn=110.0, zf=108.0, depeg_pct=0.0,
    ts=None,
):
    """Create a MarketState with sane defaults."""
    return MarketState(
        timestamp=ts or datetime.now(timezone.utc),
        vix=vix, spx=spx, tnx=tnx, dxy=dxy,
        es_price=es, zn_price=zn, zf_price=zf,
        depeg_pct=depeg_pct,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Phase-by-Phase Crisis Transitions
# ═══════════════════════════════════════════════════════════════════════════

class TestTerraLunaCrisisTransitions:
    """Validate crisis level at each phase of the crash timeline."""

    def test_phase1_normal_market(self):
        """Pre-crash: VIX=18, everything Normal."""
        orch = Orchestrator(portfolio_value=50_000)
        positions = orch.tick(make_market(vix=18.0, spx=4500.0))
        assert orch.crisis_level == CrisisLevel.NORMAL

    def test_phase2_stress_building(self):
        """Early stress: VIX rises to 25 → Elevated."""
        orch = Orchestrator(portfolio_value=50_000)
        orch.tick(make_market(vix=25.0))
        assert orch.crisis_level == CrisisLevel.ELEVATED

    def test_phase2b_severe_stress(self):
        """Severe stress: VIX rises to 32 → Severe."""
        orch = Orchestrator(portfolio_value=50_000)
        orch.tick(make_market(vix=32.0))
        assert orch.crisis_level == CrisisLevel.SEVERE

    def test_phase3_vix_spike_smart_bunker(self):
        """VIX spikes above 45 → SmartBunker."""
        orch = Orchestrator(portfolio_value=50_000)
        orch.tick(make_market(vix=52.0))
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER

    def test_phase4_depeg_after_vix_normalizes(self):
        """VIX drops to 35 but depeg_pct > 5% → SurgicalSniper (via VIX > 35)."""
        orch = Orchestrator(portfolio_value=50_000)
        orch.tick(make_market(vix=36.0, depeg_pct=8.0))
        assert orch.crisis_level == CrisisLevel.SURGICAL_SNIPER

    def test_phase5_recovery(self):
        """Recovery: VIX back to 18, depeg clears → Normal."""
        orch = Orchestrator(portfolio_value=50_000)
        # Run through crisis first
        orch.tick(make_market(vix=52.0))
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER
        # Recovery tick
        orch.tick(make_market(vix=18.0, depeg_pct=1.0))
        assert orch.crisis_level == CrisisLevel.NORMAL


# ═══════════════════════════════════════════════════════════════════════════
# Full 5-Phase Timeline
# ═══════════════════════════════════════════════════════════════════════════

class TestTerraLunaFullTimeline:
    """Run the complete 5-phase timeline through the orchestrator."""

    @pytest.fixture
    def orch(self):
        return Orchestrator(portfolio_value=100_000)

    def test_full_crash_and_recovery(self, orch):
        """
        5-phase Terra Luna timeline:
          Phase 1: Normal (VIX=18)
          Phase 2: Stress (VIX=25→35)
          Phase 3: SmartBunker (VIX=52)
          Phase 4: SurgicalSniper (VIX=36, depeg=8%)
          Phase 5: Recovery (VIX=18)
        """
        crisis_history = []

        timeline = [
            make_market(vix=18.0, depeg_pct=0.0),   # Phase 1: Normal
            make_market(vix=25.0, depeg_pct=0.0),   # Phase 2a: Elevated
            make_market(vix=32.0, depeg_pct=0.0),   # Phase 2b: Severe
            make_market(vix=52.0, depeg_pct=0.0),   # Phase 3: SmartBunker
            make_market(vix=36.0, depeg_pct=8.0),   # Phase 4: SurgicalSniper
            make_market(vix=22.0, depeg_pct=2.0),   # Recovery start: Elevated
            make_market(vix=18.0, depeg_pct=0.5),   # Phase 5: Normal
        ]

        for market in timeline:
            orch.tick(market)
            crisis_history.append(orch.crisis_level)

        # Validate the crisis progression
        assert crisis_history[0] == CrisisLevel.NORMAL
        assert crisis_history[1] == CrisisLevel.ELEVATED
        assert crisis_history[2] == CrisisLevel.SEVERE
        assert crisis_history[3] == CrisisLevel.SMART_BUNKER
        assert crisis_history[4] == CrisisLevel.SURGICAL_SNIPER
        assert crisis_history[5] == CrisisLevel.ELEVATED
        assert crisis_history[6] == CrisisLevel.NORMAL

    def test_no_crash_during_replay(self, orch):
        """System must not crash during 110-tick replay."""
        ticks_processed = 0
        timeline = (
            [make_market(vix=18.0)] * 50 +                          # Normal
            [make_market(vix=25.0 + i * 0.5) for i in range(20)] +  # Stress
            [make_market(vix=48.0 + i) for i in range(10)] +        # Spike
            [make_market(vix=30.0 - i, depeg_pct=8.0 + i * 0.5) for i in range(10)] +  # Depeg
            [make_market(vix=18.0, depeg_pct=1.0)] * 20             # Recovery
        )
        for market in timeline:
            orch.tick(market)
            ticks_processed += 1

        assert ticks_processed == 110


# ═══════════════════════════════════════════════════════════════════════════
# Risk Overlay Behavior During Crisis
# ═══════════════════════════════════════════════════════════════════════════

class TestTerraLunaRiskOverlay:
    """Validate that risk overlay behaves correctly at each crisis level."""

    @pytest.fixture
    def orch(self):
        return Orchestrator(portfolio_value=100_000)

    def test_smart_bunker_flattens_non_hedges(self, orch):
        """During SmartBunker, sleeves 1-3 should be flattened to 0."""
        orch.tick(make_market(vix=52.0))
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER

        # Manually create signals and apply risk overlay
        signals = [
            SleeveSignal(1, "Treasury", 0.8, 0.9),
            SleeveSignal(2, "Curve", 0.6, 0.8),
            SleeveSignal(3, "Prop", 0.9, 0.95),
            SleeveSignal(5, "Hedge", 0.7, 0.85),
        ]
        adjusted = orch.apply_risk_overlay(signals)

        # Sleeves 1, 2, 3 should be zeroed
        for s in adjusted:
            if s.sleeve_id in (1, 2, 3):
                assert s.signal == 0.0, f"Sleeve {s.sleeve_id} should be flattened"
            elif s.sleeve_id == 5:
                assert s.signal == 0.7, "Sleeve 5 (hedge) should survive SmartBunker"

    def test_surgical_sniper_halves_all(self, orch):
        """During SurgicalSniper, all signals halved."""
        orch.tick(make_market(vix=36.0))
        assert orch.crisis_level == CrisisLevel.SURGICAL_SNIPER

        signals = [
            SleeveSignal(1, "Treasury", 0.8, 0.9),
            SleeveSignal(3, "Prop", 0.6, 0.7),
        ]
        adjusted = orch.apply_risk_overlay(signals)
        assert abs(adjusted[0].signal - 0.4) < 0.001
        assert abs(adjusted[1].signal - 0.3) < 0.001

    def test_severe_reduces_by_25pct(self, orch):
        """During Severe, signals reduced by 25%."""
        orch.tick(make_market(vix=32.0))
        assert orch.crisis_level == CrisisLevel.SEVERE

        signals = [SleeveSignal(3, "Prop", 0.8, 0.9)]
        adjusted = orch.apply_risk_overlay(signals)
        assert abs(adjusted[0].signal - 0.6) < 0.001  # 0.8 * 0.75

    def test_normal_passes_through(self, orch):
        """Normal market: signals pass through unchanged."""
        orch.tick(make_market(vix=15.0))
        assert orch.crisis_level == CrisisLevel.NORMAL

        signals = [SleeveSignal(3, "Prop", 0.8, 0.9)]
        adjusted = orch.apply_risk_overlay(signals)
        assert adjusted[0].signal == 0.8

    def test_kill_switch_overrides_crisis(self, orch):
        """Kill switch zeros everything regardless of crisis level."""
        orch.is_killed = True
        signals = [
            SleeveSignal(1, "Treasury", 0.8, 0.9),
            SleeveSignal(5, "Hedge", 0.9, 0.85),
        ]
        adjusted = orch.apply_risk_overlay(signals)
        for s in adjusted:
            assert s.signal == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Position Calculation Through Crisis Cycle
# ═══════════════════════════════════════════════════════════════════════════

class TestTerraLunaPositions:
    """Validate position sizes change correctly through the crisis cycle."""

    def test_positions_reduce_in_crisis(self):
        """Positions should shrink as crisis level increases."""
        orch = Orchestrator(portfolio_value=100_000)

        # Normal tick — should produce non-zero positions
        normal_positions = orch.tick(make_market(vix=15.0))

        # SmartBunker tick — non-hedge positions should be zero
        crisis_positions = orch.tick(make_market(vix=52.0))
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER

        for name, pos in crisis_positions.items():
            if pos["sleeve_id"] != 5:  # Non-hedge sleeves
                assert pos["target_position"] == 0.0, \
                    f"{name} should have zero position in SmartBunker"

    def test_hedge_not_flattened_by_risk_overlay(self):
        """Risk overlay preserves Sleeve 5 signal in SmartBunker (unlike sleeves 1-3)."""
        orch = Orchestrator(portfolio_value=100_000)
        orch.tick(make_market(vix=52.0))
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER

        # Verify via manual risk overlay: sleeve 5 signal passes through
        signals = [
            SleeveSignal(3, "Prop", 0.9, 0.95),
            SleeveSignal(5, "Hedge", 0.7, 0.85),
        ]
        adjusted = orch.apply_risk_overlay(signals)
        assert adjusted[0].signal == 0.0, "Sleeve 3 should be flattened"
        assert adjusted[1].signal == 0.7, "Sleeve 5 signal should pass through"

    def test_positions_recover_after_crisis(self):
        """After crisis ends, positions should return to normal sizing."""
        orch = Orchestrator(portfolio_value=100_000)

        # Crisis
        orch.tick(make_market(vix=52.0))
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER

        # Recovery
        recovery_positions = orch.tick(make_market(vix=15.0))
        assert orch.crisis_level == CrisisLevel.NORMAL

        # At least some positions should be non-zero
        has_active = any(
            abs(p["target_position"]) > 0.01
            for p in recovery_positions.values()
        )
        assert has_active, "Should have active positions after recovery"


# ═══════════════════════════════════════════════════════════════════════════
# Permission Vector Shifts During Crisis
# ═══════════════════════════════════════════════════════════════════════════

class TestTerraLunaPermissionVector:
    """Validate permission vector shifts through crisis cycle."""

    def test_regime_shifts_during_crisis(self):
        """SERAPH regime should shift as VIX changes."""
        orch = Orchestrator(portfolio_value=50_000)

        # Normal market → growth or compression
        orch.tick(make_market(vix=14.0, spx=5000.0))
        normal_regime = orch._seraph.state.regime.value if orch._seraph and orch._seraph.state else "unknown"

        # High VIX → volatile or crisis
        orch.tick(make_market(vix=52.0, spx=4200.0))
        crisis_regime = orch._seraph.state.regime.value if orch._seraph and orch._seraph.state else "unknown"

        # Regime should have changed
        assert normal_regime != crisis_regime, \
            f"Regime should shift between normal ({normal_regime}) and crisis ({crisis_regime})"

    def test_human_approval_on_large_shift(self):
        """Growth → crisis should trigger human approval flag."""
        orch = Orchestrator(portfolio_value=50_000)

        # Establish growth regime
        orch._broadcast_permission_vector("growth")
        assert orch._human_approval_pending is False

        # Shift to crisis (prop: 1.15→0.0, a >20% shift)
        orch._broadcast_permission_vector("crisis")
        assert orch._human_approval_pending is True

    def test_vector_exists_after_tick(self):
        """Permission vector should be populated after every tick."""
        orch = Orchestrator(portfolio_value=50_000)
        orch.tick(make_market(vix=15.0))
        assert orch._current_vector is not None


# ═══════════════════════════════════════════════════════════════════════════
# Async Engine Terra Luna Replay
# ═══════════════════════════════════════════════════════════════════════════

class TestTerraLunaEngine:
    """Run Terra Luna through the full async engine."""

    @pytest.fixture
    def engine(self, tmp_path):
        from engine import QuantumEngine
        from feeds.market_data import MockMarketDataFeed
        e = QuantumEngine(portfolio_value=100_000, tick_interval=0.01)
        feed = MockMarketDataFeed()
        feed.set_scenario([
            {"vix": 18.0, "depeg_pct": 0.0},   # Phase 1: Normal
            {"vix": 25.0, "depeg_pct": 0.0},   # Phase 2: Elevated
            {"vix": 32.0, "depeg_pct": 0.0},   # Phase 2b: Severe
            {"vix": 52.0, "depeg_pct": 0.0},   # Phase 3: SmartBunker
            {"vix": 36.0, "depeg_pct": 8.0},   # Phase 4: SurgicalSniper
            {"vix": 22.0, "depeg_pct": 2.0},   # Recovery start
            {"vix": 18.0, "depeg_pct": 0.0},   # Phase 5: Normal
        ])
        e.set_feed(feed)
        e.audit.log_dir = str(tmp_path / "audit")
        e.audit._ensure_log_dir()
        return e

    @pytest.mark.asyncio
    async def test_engine_processes_all_phases(self, engine):
        """Engine must process all 7 timeline ticks."""
        import asyncio
        await engine.start()
        await asyncio.sleep(0.15)
        await engine.stop()
        assert engine._ticks_processed >= 7

    @pytest.mark.asyncio
    async def test_engine_audit_captures_transitions(self, engine):
        """Audit log should have crisis transition entries."""
        import asyncio
        await engine.start()
        await asyncio.sleep(0.15)
        await engine.stop()
        entries = engine.audit.get_entries(event_type="RISK")
        crisis_entries = [e for e in entries if "CRISIS" in e.get("event_type", "")]
        assert len(crisis_entries) >= 2, \
            f"Expected >=2 crisis transitions, got {len(crisis_entries)}"

    @pytest.mark.asyncio
    async def test_engine_state_reflects_last_tick(self, engine):
        """get_state() should reflect the engine's final state."""
        import asyncio
        await engine.start()
        await asyncio.sleep(0.15)
        await engine.stop()
        state = engine.get_state()
        assert state["ticks_processed"] >= 7
        assert "crisis_level" in state
        assert state["portfolio_value"] == 100_000
