"""
QUANTUM PROTOCOL™ v1.1 — Aggregation Engine
============================================
Applies compound AI aggregation theory (ICLR 2026: "Power and Limitations
of Aggregation in Compound AI Systems") to sleeve signal combination.

Three mechanisms govern when multi-sleeve aggregation adds value:
  1. Feasibility Expansion  — produce portfolio states no single sleeve can reach
  2. Support Expansion      — combine narrow signals into broad coverage
  3. Binding Set Contraction — relax constraints via cross-sleeve regime shifts

The engine dynamically selects aggregation mode based on which mechanism
is active, avoiding pure-overhead aggregation when none apply (Theorem 3.7).

Integration: replaces simple weighted-sum in Orchestrator.aggregate_signals()

Author: Calculus Holdings LLC — generated via poly-agent orchestration
Date: 2026-02-26
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("quantum.aggregation")


# ═══════════════════════════════════════════════════════════════════
#  ENUMS & TYPES
# ═══════════════════════════════════════════════════════════════════

class AggregationMode(Enum):
    """Which aggregation mechanism is active on this tick."""
    ADDITION = "addition"           # Weighted sum (normal alpha capture)
    INTERSECTION = "intersection"   # Coordinate-wise min (risk filtering)
    HYBRID = "hybrid"               # Dual-mode: intersection on risk, addition on alpha
    PASSTHROUGH = "passthrough"     # Single best sleeve (no aggregation benefit)


class MechanismType(Enum):
    """The three mechanisms from the paper."""
    FEASIBILITY_EXPANSION = "feasibility_expansion"
    SUPPORT_EXPANSION = "support_expansion"
    BINDING_SET_CONTRACTION = "binding_set_contraction"
    NONE = "none"


class CrisisLevel(Enum):
    NORMAL = "Normal"
    ELEVATED = "Elevated"
    SEVERE = "Severe"
    SMART_BUNKER = "SmartBunker"
    SURGICAL_SNIPER = "SurgicalSniper"


# ═══════════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SleeveSignal:
    """Output from a sleeve strategy module."""
    sleeve_id: int
    sleeve_name: str
    signal: float           # -1.0 (max short) to +1.0 (max long)
    confidence: float       # 0.0 to 1.0
    instruments: list[str] = field(default_factory=list)
    rationale: str = ""
    # New fields for aggregation analysis
    binding_constraints: list[str] = field(default_factory=list)
    support_dimensions: set[str] = field(default_factory=set)
    feasibility_violations: list[str] = field(default_factory=list)


@dataclass
class AggregatedSignal:
    """Output of the aggregation engine."""
    signal: float
    confidence: float
    mode_used: AggregationMode
    mechanisms_active: list[MechanismType]
    sleeve_contributions: dict[int, float]
    instruments: list[str] = field(default_factory=list)
    rationale: str = ""
    elicitability_expanded: bool = False


@dataclass
class MarketState:
    """Current market data snapshot."""
    timestamp: datetime
    vix: float
    spx: float
    tnx: float      # 10-year yield
    dxy: float       # Dollar index
    es_price: float
    zn_price: float
    zf_price: float


@dataclass
class AggregationConstraints:
    """
    Conic constraints on portfolio output space (paper's C matrix).
    Each constraint: c^T x <= 0 where x is the portfolio output vector.
    """
    max_portfolio_leverage: float = 2.0
    max_correlation_between_sleeves: float = 0.2
    max_single_sleeve_allocation: float = 0.50
    max_daily_loss_pct: float = 0.02
    max_drawdown_pct: float = 0.12
    premium_budget_annual_pct: float = 0.02   # Sleeve 5 cap
    heartbeat_timeout_minutes: int = 65


# ═══════════════════════════════════════════════════════════════════
#  MECHANISM DETECTORS
# ═══════════════════════════════════════════════════════════════════

class MechanismDetector:
    """
    Detects which of the paper's three mechanisms are active given
    current sleeve signals and market state. This determines which
    aggregation mode will produce elicitability-expanding outputs
    vs. pure overhead (Theorem 3.7).
    """

    def __init__(self, constraints: AggregationConstraints):
        self.constraints = constraints

    def detect_active_mechanisms(
        self,
        signals: list[SleeveSignal],
        market: MarketState,
        crisis_level: CrisisLevel,
    ) -> list[MechanismType]:
        """Identify which mechanisms are active on this tick."""
        active = []

        if self._check_feasibility_expansion(signals, market, crisis_level):
            active.append(MechanismType.FEASIBILITY_EXPANSION)

        if self._check_support_expansion(signals):
            active.append(MechanismType.SUPPORT_EXPANSION)

        if self._check_binding_set_contraction(signals, crisis_level):
            active.append(MechanismType.BINDING_SET_CONTRACTION)

        if not active:
            active.append(MechanismType.NONE)

        return active

    def _check_feasibility_expansion(
        self,
        signals: list[SleeveSignal],
        market: MarketState,
        crisis_level: CrisisLevel,
    ) -> bool:
        """
        Feasibility expansion: aggregation produces outputs outside any
        single sleeve's feasible set.

        In Quantum Protocol, this occurs when:
        - Sleeve 5 (Convexity Shield) absorbs negative carry in normal markets
          so Sleeve 3 (Prop Scaling) can run without crash exposure
        - No single sleeve can produce "positive returns during crash"
          without also eating premium in normal markets
        - The combined portfolio reaches a risk/return state impossible
          for any individual strategy
        """
        if crisis_level in (CrisisLevel.SEVERE, CrisisLevel.SMART_BUNKER):
            # During crisis, Sleeve 5 pays off while Sleeve 3 is constrained
            # Combined output: crash protection + alpha preservation
            # No single sleeve can produce this
            hedge_signals = [s for s in signals if s.sleeve_id == 5]
            alpha_signals = [s for s in signals if s.sleeve_id == 3]

            if hedge_signals and alpha_signals:
                hedge_active = any(s.signal < -0.3 for s in hedge_signals)
                alpha_constrained = any(s.confidence < 0.3 for s in alpha_signals)
                if hedge_active and alpha_constrained:
                    return True

        # Cross-sleeve hedging: long equities + long vol simultaneously
        # infeasible for any single strategy due to negative carry drag
        long_equity = any(
            s.signal > 0.3 and "ES" in s.instruments
            for s in signals
        )
        long_vol = any(
            s.signal > 0 and any(i in s.instruments for i in ["VIX", "UVXY"])
            for s in signals
        )
        if long_equity and long_vol:
            return True

        return False

    def _check_support_expansion(self, signals: list[SleeveSignal]) -> bool:
        """
        Support expansion: combining narrow signals into broad coverage.

        In Quantum Protocol, this occurs when:
        - Each eval account in Sleeve 3 specializes on a subset of
          instruments/signals (RSI oversold vs momentum crossover)
        - Individual sleeves cover different asset classes
        - Combined instrument coverage exceeds any single sleeve

        Paper proof: this works when features (market indicators) can't
        simultaneously optimize all dimensions — which is exactly the case
        when RSI and trend momentum are contradictory.
        """
        if len(signals) < 2:
            return False

        # Check if sleeves cover different instrument sets
        all_instruments = set()
        individual_max = 0
        for s in signals:
            s_instruments = set(s.instruments)
            all_instruments.update(s_instruments)
            individual_max = max(individual_max, len(s_instruments))

        # Support expansion: combined coverage > any individual
        if len(all_instruments) > individual_max:
            return True

        # Check if sleeves have non-overlapping support dimensions
        # (different aspects of the market they respond to)
        all_dimensions = set()
        for s in signals:
            all_dimensions.update(s.support_dimensions)
        individual_max_dims = max(
            (len(s.support_dimensions) for s in signals), default=0
        )
        if len(all_dimensions) > individual_max_dims:
            return True

        return False

    def _check_binding_set_contraction(
        self,
        signals: list[SleeveSignal],
        crisis_level: CrisisLevel,
    ) -> bool:
        """
        Binding set contraction: aggregation relaxes constraints that
        bind individual sleeves.

        In Quantum Protocol, this occurs when:
        - SERAPH AI shifts regime → constraints that bound Sleeve 3
          (no new positions in crisis) are relaxed for Sleeve 5
          (profit-taking in crisis)
        - Sleeve 2 flattener constraint (2s10s spread) doesn't bind
          on Sleeve 1 (different yield curve exposure)
        - Combined output has fewer binding constraints than any
          individual sleeve
        """
        if len(signals) < 2:
            return False

        # Count binding constraints per sleeve
        binding_counts = [len(s.binding_constraints) for s in signals]
        total_unique_bindings = len(
            set().union(*(set(s.binding_constraints) for s in signals))
        )

        # If individual sleeves are constrained but the combination
        # has fewer effective constraints, binding set contraction is active
        max_individual_bindings = max(binding_counts) if binding_counts else 0
        if max_individual_bindings > 0 and total_unique_bindings < sum(binding_counts):
            return True

        # Regime-driven contraction: crisis mode relaxes hedge constraints
        # while tightening alpha constraints
        if crisis_level != CrisisLevel.NORMAL:
            alpha_bound = any(
                "max_leverage" in s.binding_constraints
                or "position_limit" in s.binding_constraints
                for s in signals if s.sleeve_id == 3
            )
            hedge_free = any(
                len(s.binding_constraints) == 0
                for s in signals if s.sleeve_id == 5
            )
            if alpha_bound and hedge_free:
                return True

        return False


# ═══════════════════════════════════════════════════════════════════
#  AGGREGATION ENGINE
# ═══════════════════════════════════════════════════════════════════

class AggregationEngine:
    """
    Dynamically selects aggregation mode based on active mechanisms.

    From the paper (Theorem 3.7): aggregation only expands the set of
    elicitable outputs if at least one mechanism is active. When no
    mechanism is active, multi-sleeve aggregation is pure overhead —
    route to the single best sleeve instead.

    Mode selection:
    - FEASIBILITY_EXPANSION active → HYBRID (intersection on risk,
      addition on alpha). Paper: intersection aggregation implements
      feasibility expansion (Example 3.2)
    - SUPPORT_EXPANSION only → ADDITION (weighted sum across sleeves).
      Paper: addition aggregation implements support expansion (Example 3.4)
    - BINDING_SET_CONTRACTION only → HYBRID (exploit constraint relaxation).
      Paper: both intersection and addition can implement this (Table 1)
    - NONE → PASSTHROUGH (best single sleeve, skip aggregation overhead)
    """

    def __init__(
        self,
        constraints: Optional[AggregationConstraints] = None,
        sleeve_weights: Optional[dict[int, float]] = None,
    ):
        self.constraints = constraints or AggregationConstraints()
        self.detector = MechanismDetector(self.constraints)

        # Default sleeve weights (from SleeveAllocation)
        self.sleeve_weights = sleeve_weights or {
            1: 0.10,   # Treasury Yield
            2: 0.15,   # Compression & Curve
            3: 0.45,   # Prop Scaling (primary alpha)
            5: 0.10,   # Convexity Shield
        }

        # Risk vs alpha classification for hybrid mode
        self.risk_sleeves = {5}          # Convexity Shield
        self.alpha_sleeves = {1, 2, 3}   # Revenue-generating sleeves

    def aggregate(
        self,
        signals: list[SleeveSignal],
        market: MarketState,
        crisis_level: CrisisLevel = CrisisLevel.NORMAL,
    ) -> AggregatedSignal:
        """
        Main entry point. Detects active mechanisms, selects mode,
        and produces aggregated signal.
        """
        if not signals:
            return self._empty_signal()

        # Step 1: Detect which mechanisms are active
        mechanisms = self.detector.detect_active_mechanisms(
            signals, market, crisis_level
        )
        logger.info(
            f"Active mechanisms: {[m.value for m in mechanisms]}"
        )

        # Step 2: Select aggregation mode (Theorem 3.7 application)
        mode = self._select_mode(mechanisms, crisis_level)
        logger.info(f"Aggregation mode: {mode.value}")

        # Step 3: Execute aggregation
        if mode == AggregationMode.PASSTHROUGH:
            result = self._passthrough(signals)
        elif mode == AggregationMode.ADDITION:
            result = self._addition_aggregate(signals)
        elif mode == AggregationMode.INTERSECTION:
            result = self._intersection_aggregate(signals)
        elif mode == AggregationMode.HYBRID:
            result = self._hybrid_aggregate(signals)
        else:
            result = self._addition_aggregate(signals)

        result.mode_used = mode
        result.mechanisms_active = mechanisms
        result.elicitability_expanded = MechanismType.NONE not in mechanisms

        return result

    def _select_mode(
        self,
        mechanisms: list[MechanismType],
        crisis_level: CrisisLevel,
    ) -> AggregationMode:
        """
        Map active mechanisms to aggregation mode.

        Paper insight: the aggregation rule determines which mechanisms
        it CAN implement (Table 1):
        - Intersection: feasibility expansion ✓, binding set contraction ✓,
          support expansion ✗
        - Addition: support expansion ✓, binding set contraction ✓,
          feasibility expansion ✗

        So we must pick the rule that matches the active mechanism.
        """
        has_feasibility = MechanismType.FEASIBILITY_EXPANSION in mechanisms
        has_support = MechanismType.SUPPORT_EXPANSION in mechanisms
        has_binding = MechanismType.BINDING_SET_CONTRACTION in mechanisms
        has_none = MechanismType.NONE in mechanisms

        if has_none and not has_feasibility and not has_support and not has_binding:
            return AggregationMode.PASSTHROUGH

        # Feasibility expansion requires intersection (at least on risk dims)
        if has_feasibility:
            # If support expansion also active, use hybrid to get both
            if has_support:
                return AggregationMode.HYBRID
            return AggregationMode.HYBRID  # intersection on risk, addition on alpha

        # Pure support expansion → addition (intersection can't do this)
        if has_support and not has_binding:
            return AggregationMode.ADDITION

        # Pure binding set contraction → hybrid (both rules can implement)
        if has_binding:
            return AggregationMode.HYBRID

        # Crisis override: always use hybrid in elevated+ regimes
        if crisis_level != CrisisLevel.NORMAL:
            return AggregationMode.HYBRID

        return AggregationMode.ADDITION

    # ─── Aggregation Implementations ──────────────────────────────

    def _addition_aggregate(self, signals: list[SleeveSignal]) -> AggregatedSignal:
        """
        Weighted sum aggregation (paper Equation 2).
        Implements support expansion: combines signals across
        different instrument/dimension spaces.
        """
        total_weight = 0.0
        weighted_signal = 0.0
        weighted_confidence = 0.0
        all_instruments = []
        contributions = {}
        rationale_parts = []

        for s in signals:
            w = self.sleeve_weights.get(s.sleeve_id, 0.0)
            if w <= 0 or s.confidence <= 0:
                contributions[s.sleeve_id] = 0.0
                continue

            effective_weight = w * s.confidence
            weighted_signal += effective_weight * s.signal
            weighted_confidence += effective_weight * s.confidence
            total_weight += effective_weight
            contributions[s.sleeve_id] = effective_weight * s.signal

            all_instruments.extend(s.instruments)
            if abs(s.signal) > 0.1:
                rationale_parts.append(
                    f"S{s.sleeve_id}({s.sleeve_name}): "
                    f"{s.signal:+.2f}@{s.confidence:.0%}"
                )

        if total_weight > 0:
            final_signal = weighted_signal / total_weight
            final_confidence = weighted_confidence / total_weight
        else:
            final_signal = 0.0
            final_confidence = 0.0

        return AggregatedSignal(
            signal=max(-1.0, min(1.0, final_signal)),
            confidence=max(0.0, min(1.0, final_confidence)),
            mode_used=AggregationMode.ADDITION,
            mechanisms_active=[],
            sleeve_contributions=contributions,
            instruments=list(set(all_instruments)),
            rationale=f"ADD: {' | '.join(rationale_parts)}",
        )

    def _intersection_aggregate(self, signals: list[SleeveSignal]) -> AggregatedSignal:
        """
        Coordinate-wise minimum aggregation (paper Equation 1).
        Implements feasibility expansion: filters out infeasible
        components (hallucinations in the paper's language,
        excessive risk in ours).
        """
        if not signals:
            return self._empty_signal()

        # Take the most conservative signal (min absolute magnitude)
        min_signal = min(signals, key=lambda s: abs(s.signal))
        min_confidence = min(s.confidence for s in signals)

        # Instruments: only keep those that appear in ALL sleeve outputs
        instrument_sets = [set(s.instruments) for s in signals if s.instruments]
        if instrument_sets:
            common_instruments = instrument_sets[0]
            for iset in instrument_sets[1:]:
                common_instruments &= iset
        else:
            common_instruments = set()

        contributions = {
            s.sleeve_id: min_signal.signal * self.sleeve_weights.get(s.sleeve_id, 0)
            for s in signals
        }

        return AggregatedSignal(
            signal=min_signal.signal,
            confidence=min_confidence,
            mode_used=AggregationMode.INTERSECTION,
            mechanisms_active=[],
            sleeve_contributions=contributions,
            instruments=list(common_instruments),
            rationale=(
                f"INTERSECT: conservative consensus "
                f"sig={min_signal.signal:+.2f}, "
                f"floor_conf={min_confidence:.0%}"
            ),
        )

    def _hybrid_aggregate(self, signals: list[SleeveSignal]) -> AggregatedSignal:
        """
        Dual-mode aggregation: intersection on risk signals,
        addition on alpha signals.

        This is the key paper insight applied: use intersection
        where feasibility expansion is needed (risk filtering)
        and addition where support expansion is needed (alpha capture).
        """
        risk_signals = [s for s in signals if s.sleeve_id in self.risk_sleeves]
        alpha_signals = [s for s in signals if s.sleeve_id in self.alpha_sleeves]

        # Addition-aggregate the alpha sleeves (support expansion)
        alpha_result = self._addition_aggregate(alpha_signals) if alpha_signals else None

        # Intersection-aggregate the risk sleeves (feasibility expansion)
        risk_result = self._intersection_aggregate(risk_signals) if risk_signals else None

        # Combine: risk signal acts as a constraint on the alpha signal
        if alpha_result and risk_result:
            # If risk signal is strongly negative (hedging active),
            # dampen the alpha signal proportionally
            risk_dampener = 1.0 + risk_result.signal  # 0.0 when signal=-1, 1.0 when signal=0
            risk_dampener = max(0.1, min(1.0, risk_dampener))

            final_signal = alpha_result.signal * risk_dampener
            final_confidence = min(alpha_result.confidence, risk_result.confidence)

            all_instruments = list(
                set(alpha_result.instruments) | set(risk_result.instruments)
            )
            contributions = {**alpha_result.sleeve_contributions}
            contributions.update(risk_result.sleeve_contributions)

            return AggregatedSignal(
                signal=max(-1.0, min(1.0, final_signal)),
                confidence=final_confidence,
                mode_used=AggregationMode.HYBRID,
                mechanisms_active=[],
                sleeve_contributions=contributions,
                instruments=all_instruments,
                rationale=(
                    f"HYBRID: alpha={alpha_result.signal:+.2f} × "
                    f"risk_damp={risk_dampener:.2f} → {final_signal:+.2f}"
                ),
            )
        elif alpha_result:
            return alpha_result
        elif risk_result:
            return risk_result
        else:
            return self._empty_signal()

    def _passthrough(self, signals: list[SleeveSignal]) -> AggregatedSignal:
        """
        No mechanism active → skip aggregation overhead.
        Route to highest-confidence single sleeve.
        Paper (Theorem 3.7): aggregation adds no power here.
        """
        best = max(signals, key=lambda s: s.confidence * abs(s.signal))
        return AggregatedSignal(
            signal=best.signal,
            confidence=best.confidence,
            mode_used=AggregationMode.PASSTHROUGH,
            mechanisms_active=[MechanismType.NONE],
            sleeve_contributions={best.sleeve_id: best.signal},
            instruments=best.instruments,
            rationale=(
                f"PASSTHROUGH: no aggregation benefit detected, "
                f"routing to S{best.sleeve_id}({best.sleeve_name})"
            ),
            elicitability_expanded=False,
        )

    def _empty_signal(self) -> AggregatedSignal:
        return AggregatedSignal(
            signal=0.0,
            confidence=0.0,
            mode_used=AggregationMode.PASSTHROUGH,
            mechanisms_active=[MechanismType.NONE],
            sleeve_contributions={},
            rationale="No signals received",
        )


# ═══════════════════════════════════════════════════════════════════
#  ELICITABILITY ANALYZER (diagnostic / dashboard use)
# ═══════════════════════════════════════════════════════════════════

class ElicitabilityAnalyzer:
    """
    Diagnostic tool: answers "is aggregation actually helping?"
    for dashboard display and strategy tuning.

    Maps to paper's Theorem 4.1: checks whether the feasible
    perturbation set B_{S,V} intersects with feature-improving
    directions for each sleeve and for the aggregate.
    """

    def __init__(self, engine: AggregationEngine):
        self.engine = engine
        self.history: list[dict] = []

    def analyze_tick(
        self,
        signals: list[SleeveSignal],
        aggregated: AggregatedSignal,
    ) -> dict:
        """
        Per-tick analysis: which mechanisms fired, did aggregation
        actually produce an expanded output?
        """
        analysis = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": aggregated.mode_used.value,
            "mechanisms": [m.value for m in aggregated.mechanisms_active],
            "elicitability_expanded": aggregated.elicitability_expanded,
            "sleeve_signals": {
                s.sleeve_id: {"signal": s.signal, "confidence": s.confidence}
                for s in signals
            },
            "aggregated_signal": aggregated.signal,
            "aggregated_confidence": aggregated.confidence,
            "overhead_avoided": aggregated.mode_used == AggregationMode.PASSTHROUGH,
        }

        # Track expansion rate over time
        self.history.append(analysis)
        if len(self.history) > 1000:
            self.history = self.history[-500:]

        return analysis

    def expansion_rate(self, window: int = 100) -> float:
        """Fraction of recent ticks where aggregation expanded elicitability."""
        recent = self.history[-window:]
        if not recent:
            return 0.0
        expanded = sum(1 for a in recent if a["elicitability_expanded"])
        return expanded / len(recent)

    def mechanism_frequency(self, window: int = 100) -> dict[str, float]:
        """How often each mechanism fires."""
        recent = self.history[-window:]
        if not recent:
            return {}
        counts: dict[str, int] = {}
        for a in recent:
            for m in a["mechanisms"]:
                counts[m] = counts.get(m, 0) + 1
        return {k: v / len(recent) for k, v in counts.items()}

    def passthrough_savings(self, window: int = 100) -> dict:
        """Estimate API/compute savings from skipping useless aggregation."""
        recent = self.history[-window:]
        if not recent:
            return {"ticks_analyzed": 0, "overhead_avoided": 0, "pct": 0}
        avoided = sum(1 for a in recent if a["overhead_avoided"])
        return {
            "ticks_analyzed": len(recent),
            "overhead_avoided": avoided,
            "pct": avoided / len(recent),
        }
