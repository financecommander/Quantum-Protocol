"""
MATRIX PROTOCOL™ v1.0 — Regime Classifier

Deterministic implementation of SERAPH AI™ regime detection.

System prompt says:
  - Random Forest on VIX, ADX, TVL → regime label (91% accuracy)
  - Quarterly rebalancing shifts (e.g., +15% to Prop in growth)
  - +12-14% uplift vs static allocation

v1.0: Hard-coded thresholds (deterministic, auditable, FINRA-compliant)
v2.0: Trained RF model with daily retrain cycle
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.risk.regime")


class MarketRegime(Enum):
    GROWTH = "growth"           # Low vol, trending up → favor Prop Scaling
    NEUTRAL = "neutral"         # Normal conditions → balanced allocation
    DEFENSIVE = "defensive"     # Elevated vol → reduce risk, increase hedges
    CRISIS = "crisis"           # High vol → SmartBunker (handled by crisis_protocols)


@dataclass
class RegimeConfig:
    """Thresholds for regime classification."""
    # VIX thresholds
    vix_growth_ceiling: float = 18.0      # VIX < 18 → growth
    vix_defensive_floor: float = 25.0     # VIX > 25 → defensive
    vix_crisis_floor: float = 35.0        # VIX > 35 → crisis

    # ADX thresholds (trend strength, 0-100)
    adx_trending: float = 25.0            # ADX > 25 → trending market
    adx_weak: float = 15.0               # ADX < 15 → no trend

    # Allocation adjustments per regime
    growth_prop_boost: float = 0.15       # +15% to Sleeve 3 in growth
    defensive_hedge_boost: float = 0.10   # +10% to Sleeve 5 in defensive
    defensive_prop_reduction: float = 0.10 # -10% from Sleeve 3 in defensive


class RegimeClassifier:
    """
    Deterministic regime classifier.
    
    v1.0: Uses VIX and ADX thresholds.
    v2.0 will use trained RF model on VIX, ADX, TVL with daily retrain.
    """

    def __init__(self, config: Optional[RegimeConfig] = None):
        self.config = config or RegimeConfig()
        self.current_regime = MarketRegime.NEUTRAL
        self.regime_history: list[tuple[str, MarketRegime]] = []

    def classify(self, vix: float, adx: float = 20.0) -> MarketRegime:
        """
        Classify current market regime from VIX and ADX.
        
        Args:
            vix: Current VIX level
            adx: Current ADX (Average Directional Index). Default 20 if unavailable.
        
        Returns:
            MarketRegime classification
        """
        old_regime = self.current_regime

        if vix >= self.config.vix_crisis_floor:
            self.current_regime = MarketRegime.CRISIS
        elif vix >= self.config.vix_defensive_floor:
            self.current_regime = MarketRegime.DEFENSIVE
        elif vix <= self.config.vix_growth_ceiling and adx >= self.config.adx_trending:
            self.current_regime = MarketRegime.GROWTH
        else:
            self.current_regime = MarketRegime.NEUTRAL

        if self.current_regime != old_regime:
            logger.info(f"Regime change: {old_regime.value} → {self.current_regime.value} (VIX={vix:.1f}, ADX={adx:.1f})")

        return self.current_regime

    def get_allocation_adjustments(self) -> dict:
        """
        Return allocation adjustments for current regime.
        These are DELTAS to apply on top of the base allocation.
        """
        if self.current_regime == MarketRegime.GROWTH:
            return {
                "prop_scaling_delta": +self.config.growth_prop_boost,
                "convexity_shield_delta": 0.0,
                "treasury_yield_delta": -self.config.growth_prop_boost / 2,
                "compression_curve_delta": -self.config.growth_prop_boost / 2,
                "rationale": "Growth regime: shifting to Prop Scaling for momentum capture",
            }
        elif self.current_regime == MarketRegime.DEFENSIVE:
            return {
                "prop_scaling_delta": -self.config.defensive_prop_reduction,
                "convexity_shield_delta": +self.config.defensive_hedge_boost,
                "treasury_yield_delta": 0.0,
                "compression_curve_delta": 0.0,
                "rationale": "Defensive regime: reducing risk, increasing hedges",
            }
        elif self.current_regime == MarketRegime.CRISIS:
            return {
                "prop_scaling_delta": -0.20,
                "convexity_shield_delta": +0.10,
                "treasury_yield_delta": +0.05,
                "compression_curve_delta": +0.05,
                "rationale": "Crisis regime: max defensive posture",
            }
        else:  # NEUTRAL
            return {
                "prop_scaling_delta": 0.0,
                "convexity_shield_delta": 0.0,
                "treasury_yield_delta": 0.0,
                "compression_curve_delta": 0.0,
                "rationale": "Neutral regime: base allocation",
            }
