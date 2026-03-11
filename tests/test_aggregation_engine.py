"""
Tests for QUANTUM PROTOCOL Aggregation Engine
=============================================
Validates mechanism detection, mode selection, and aggregation
outputs against the paper's theoretical predictions.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategies", "aggregation"))

import pytest
from datetime import datetime, timezone
from aggregation_engine import (
    AggregationEngine,
    AggregationConstraints,
    AggregationMode,
    AggregatedSignal,
    CrisisLevel,
    ElicitabilityAnalyzer,
    MarketState,
    MechanismDetector,
    MechanismType,
    SleeveSignal,
)


# ═══ Fixtures ═══════════════════════════════════════════════════

@pytest.fixture
def market_normal():
    return MarketState(
        timestamp=datetime.now(timezone.utc),
        vix=15.0, spx=5800.0, tnx=4.2, dxy=104.0,
        es_price=5800.0, zn_price=110.5, zf_price=108.0,
    )

@pytest.fixture
def market_crisis():
    return MarketState(
        timestamp=datetime.now(timezone.utc),
        vix=45.0, spx=4800.0, tnx=3.5, dxy=98.0,
        es_price=4800.0, zn_price=115.0, zf_price=112.0,
    )

@pytest.fixture
def engine():
    return AggregationEngine()

@pytest.fixture
def detector():
    return MechanismDetector(AggregationConstraints())


def _make_signal(sleeve_id, name, signal, confidence,
                 instruments=None, binding=None, support=None):
    return SleeveSignal(
        sleeve_id=sleeve_id, sleeve_name=name,
        signal=signal, confidence=confidence,
        instruments=instruments or [],
        binding_constraints=binding or [],
        support_dimensions=support or set(),
    )


# ═══ Mechanism Detection ════════════════════════════════════════

class TestFeasibilityExpansion:
    """Paper Example 3.2: aggregation produces infeasible-for-individual outputs."""

    def test_crisis_triggers_feasibility_expansion(self, detector, market_crisis):
        signals = [
            _make_signal(3, "Prop Scaling", 0.1, 0.2,
                         instruments=["ES"],
                         binding=["position_limit"]),
            _make_signal(5, "Convexity Shield", -0.8, 0.9,
                         instruments=["VIX"]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_crisis, CrisisLevel.SEVERE
        )
        assert MechanismType.FEASIBILITY_EXPANSION in mechanisms

    def test_long_equity_plus_long_vol(self, detector, market_normal):
        signals = [
            _make_signal(3, "Prop Scaling", 0.5, 0.7,
                         instruments=["ES"]),
            _make_signal(5, "Convexity Shield", 0.3, 0.6,
                         instruments=["VIX"]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.FEASIBILITY_EXPANSION in mechanisms

    def test_no_feasibility_when_same_direction(self, detector, market_normal):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7,
                         instruments=["IEF"]),
            _make_signal(2, "Compression", 0.2, 0.6,
                         instruments=["ZN"]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.FEASIBILITY_EXPANSION not in mechanisms


class TestSupportExpansion:
    """Paper Example 3.4: combining narrow signals into broad coverage."""

    def test_different_instruments_trigger_support(self, detector, market_normal):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7,
                         instruments=["IEF", "TLT"]),
            _make_signal(3, "Prop Scaling", 0.5, 0.8,
                         instruments=["ES", "EUR/USD"]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.SUPPORT_EXPANSION in mechanisms

    def test_different_dimensions_trigger_support(self, detector, market_normal):
        signals = [
            _make_signal(2, "Compression", 0.2, 0.6,
                         support={"yield_curve", "term_premium"}),
            _make_signal(3, "Prop Scaling", 0.5, 0.8,
                         support={"momentum", "mean_reversion"}),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.SUPPORT_EXPANSION in mechanisms

    def test_identical_instruments_no_support(self, detector, market_normal):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7,
                         instruments=["IEF"]),
            _make_signal(2, "Compression", 0.2, 0.6,
                         instruments=["IEF"]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.SUPPORT_EXPANSION not in mechanisms

    def test_single_signal_no_support(self, detector, market_normal):
        signals = [
            _make_signal(3, "Prop Scaling", 0.5, 0.8,
                         instruments=["ES", "EUR/USD"]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.SUPPORT_EXPANSION not in mechanisms


class TestBindingSetContraction:
    """Paper Example 3.6: aggregation relaxes binding constraints."""

    def test_shared_constraints_contract(self, detector, market_normal):
        signals = [
            _make_signal(2, "Compression", 0.2, 0.6,
                         binding=["max_leverage", "spread_limit"]),
            _make_signal(3, "Prop Scaling", 0.5, 0.8,
                         binding=["max_leverage", "position_limit"]),
        ]
        # "max_leverage" appears in both → counted once in union
        # sum of individual bindings (4) > unique bindings (3)
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.BINDING_SET_CONTRACTION in mechanisms

    def test_crisis_regime_contraction(self, detector, market_crisis):
        signals = [
            _make_signal(3, "Prop Scaling", 0.1, 0.2,
                         binding=["max_leverage", "position_limit"]),
            _make_signal(5, "Convexity Shield", -0.7, 0.9,
                         binding=[]),  # No constraints in crisis
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_crisis, CrisisLevel.SEVERE
        )
        assert MechanismType.BINDING_SET_CONTRACTION in mechanisms

    def test_no_contraction_when_no_bindings(self, detector, market_normal):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7, binding=[]),
            _make_signal(2, "Compression", 0.2, 0.6, binding=[]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.BINDING_SET_CONTRACTION not in mechanisms


class TestNoMechanism:
    """Paper Theorem 3.7: no mechanism → aggregation adds no power."""

    def test_no_mechanisms_detected(self, detector, market_normal):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7,
                         instruments=["IEF"], binding=[]),
            _make_signal(2, "Compression", 0.2, 0.6,
                         instruments=["IEF"], binding=[]),
        ]
        mechanisms = detector.detect_active_mechanisms(
            signals, market_normal, CrisisLevel.NORMAL
        )
        assert MechanismType.NONE in mechanisms


# ═══ Mode Selection ═════════════════════════════════════════════

class TestModeSelection:
    def test_no_mechanism_selects_passthrough(self, engine):
        mode = engine._select_mode(
            [MechanismType.NONE], CrisisLevel.NORMAL
        )
        assert mode == AggregationMode.PASSTHROUGH

    def test_feasibility_selects_hybrid(self, engine):
        mode = engine._select_mode(
            [MechanismType.FEASIBILITY_EXPANSION], CrisisLevel.NORMAL
        )
        assert mode == AggregationMode.HYBRID

    def test_support_only_selects_addition(self, engine):
        mode = engine._select_mode(
            [MechanismType.SUPPORT_EXPANSION], CrisisLevel.NORMAL
        )
        assert mode == AggregationMode.ADDITION

    def test_binding_selects_hybrid(self, engine):
        mode = engine._select_mode(
            [MechanismType.BINDING_SET_CONTRACTION], CrisisLevel.NORMAL
        )
        assert mode == AggregationMode.HYBRID

    def test_feasibility_plus_support_selects_hybrid(self, engine):
        mode = engine._select_mode(
            [MechanismType.FEASIBILITY_EXPANSION,
             MechanismType.SUPPORT_EXPANSION],
            CrisisLevel.NORMAL,
        )
        assert mode == AggregationMode.HYBRID


# ═══ Aggregation Outputs ════════════════════════════════════════

class TestAdditionAggregation:
    def test_weighted_sum(self, engine):
        signals = [
            _make_signal(1, "Treasury", 0.4, 0.8, instruments=["IEF"]),
            _make_signal(3, "Prop Scaling", 0.6, 0.9, instruments=["ES"]),
        ]
        result = engine._addition_aggregate(signals)
        assert result.signal != 0.0
        assert 1 in result.sleeve_contributions
        assert 3 in result.sleeve_contributions
        assert "IEF" in result.instruments
        assert "ES" in result.instruments

    def test_zero_confidence_excluded(self, engine):
        signals = [
            _make_signal(1, "Treasury", 0.4, 0.0, instruments=["IEF"]),
            _make_signal(3, "Prop Scaling", 0.6, 0.9, instruments=["ES"]),
        ]
        result = engine._addition_aggregate(signals)
        assert result.sleeve_contributions.get(1, 0.0) == 0.0


class TestIntersectionAggregation:
    def test_conservative_signal(self, engine):
        signals = [
            _make_signal(1, "Treasury", 0.8, 0.9),
            _make_signal(3, "Prop Scaling", 0.2, 0.6),
        ]
        result = engine._intersection_aggregate(signals)
        # Should take the most conservative (smallest abs)
        assert abs(result.signal) <= 0.2
        assert result.confidence == 0.6  # min confidence

    def test_common_instruments_only(self, engine):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7,
                         instruments=["IEF", "ES"]),
            _make_signal(3, "Prop Scaling", 0.5, 0.8,
                         instruments=["ES", "EUR/USD"]),
        ]
        result = engine._intersection_aggregate(signals)
        assert "ES" in result.instruments
        assert "IEF" not in result.instruments
        assert "EUR/USD" not in result.instruments


class TestHybridAggregation:
    def test_risk_dampens_alpha(self, engine):
        signals = [
            _make_signal(1, "Treasury", 0.5, 0.8, instruments=["IEF"]),
            _make_signal(3, "Prop Scaling", 0.7, 0.9, instruments=["ES"]),
            _make_signal(5, "Convexity Shield", -0.5, 0.8,
                         instruments=["VIX"]),
        ]
        result = engine._hybrid_aggregate(signals)
        # Alpha should be dampened by risk signal
        assert result.signal < 0.7  # Less than pure Sleeve 3

    def test_no_risk_sleeves_falls_back_to_addition(self, engine):
        signals = [
            _make_signal(1, "Treasury", 0.5, 0.8),
            _make_signal(3, "Prop Scaling", 0.7, 0.9),
        ]
        result = engine._hybrid_aggregate(signals)
        assert result.signal > 0  # Addition of positive signals


class TestPassthrough:
    def test_routes_to_best_sleeve(self, engine):
        signals = [
            _make_signal(1, "Treasury", 0.2, 0.5),
            _make_signal(3, "Prop Scaling", 0.8, 0.9),
        ]
        result = engine._passthrough(signals)
        assert result.signal == 0.8
        assert result.mode_used == AggregationMode.PASSTHROUGH
        assert not result.elicitability_expanded


# ═══ End-to-End ══════════════════════════════════════════════════

class TestEndToEnd:
    def test_normal_market_support_expansion(self, engine, market_normal):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7,
                         instruments=["IEF"]),
            _make_signal(3, "Prop Scaling", 0.6, 0.9,
                         instruments=["ES", "EUR/USD"]),
            _make_signal(5, "Convexity Shield", -0.1, 0.5,
                         instruments=["VIX"]),
        ]
        result = engine.aggregate(signals, market_normal, CrisisLevel.NORMAL)
        assert result.elicitability_expanded
        assert result.mode_used != AggregationMode.PASSTHROUGH

    def test_crisis_market_feasibility_expansion(self, engine, market_crisis):
        signals = [
            _make_signal(3, "Prop Scaling", 0.1, 0.2,
                         instruments=["ES"],
                         binding=["max_leverage"]),
            _make_signal(5, "Convexity Shield", -0.8, 0.9,
                         instruments=["VIX"]),
        ]
        result = engine.aggregate(signals, market_crisis, CrisisLevel.SEVERE)
        assert MechanismType.FEASIBILITY_EXPANSION in result.mechanisms_active
        assert result.mode_used == AggregationMode.HYBRID

    def test_no_signals_returns_empty(self, engine, market_normal):
        result = engine.aggregate([], market_normal)
        assert result.signal == 0.0
        assert result.confidence == 0.0

    def test_identical_sleeves_passthrough(self, engine, market_normal):
        signals = [
            _make_signal(1, "Treasury", 0.3, 0.7,
                         instruments=["IEF"], binding=[]),
            _make_signal(2, "Compression", 0.2, 0.6,
                         instruments=["IEF"], binding=[]),
        ]
        result = engine.aggregate(signals, market_normal, CrisisLevel.NORMAL)
        assert result.mode_used == AggregationMode.PASSTHROUGH
        assert not result.elicitability_expanded


# ═══ Elicitability Analyzer ═════════════════════════════════════

class TestElicitabilityAnalyzer:
    def test_expansion_rate(self, engine):
        analyzer = ElicitabilityAnalyzer(engine)
        for i in range(10):
            signals = [_make_signal(3, "Prop", 0.5, 0.8)]
            agg = AggregatedSignal(
                signal=0.5, confidence=0.8,
                mode_used=AggregationMode.PASSTHROUGH,
                mechanisms_active=[MechanismType.NONE],
                sleeve_contributions={3: 0.5},
                elicitability_expanded=(i % 3 == 0),
            )
            analyzer.analyze_tick(signals, agg)

        rate = analyzer.expansion_rate(window=10)
        assert 0.0 < rate < 1.0

    def test_mechanism_frequency(self, engine):
        analyzer = ElicitabilityAnalyzer(engine)
        for _ in range(5):
            agg = AggregatedSignal(
                signal=0.5, confidence=0.8,
                mode_used=AggregationMode.HYBRID,
                mechanisms_active=[MechanismType.FEASIBILITY_EXPANSION],
                sleeve_contributions={},
            )
            analyzer.analyze_tick([], agg)

        freq = analyzer.mechanism_frequency(window=10)
        assert freq.get("feasibility_expansion", 0) == 1.0

    def test_passthrough_savings(self, engine):
        analyzer = ElicitabilityAnalyzer(engine)
        for i in range(10):
            agg = AggregatedSignal(
                signal=0.5, confidence=0.8,
                mode_used=(
                    AggregationMode.PASSTHROUGH if i < 6
                    else AggregationMode.HYBRID
                ),
                mechanisms_active=[MechanismType.NONE],
                sleeve_contributions={},
            )
            analyzer.analyze_tick(
                [], agg
            )
            # Manually set overhead_avoided in the last history entry
            analyzer.history[-1]["overhead_avoided"] = (i < 6)

        savings = analyzer.passthrough_savings(window=10)
        assert savings["overhead_avoided"] == 6
        assert savings["pct"] == 0.6
