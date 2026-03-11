"""Tests for regime classifier (from seraph_ai module).
Sleeve-specific tests moved to dedicated files:
  test_sleeve2.py, test_sleeve5.py (test_sleeve1.py and test_sleeve3.py pending rules).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class MockMarket:
    timestamp: datetime = None
    vix: float = 15.0
    spx: float = 5000.0
    tnx: float = 4.5
    dxy: float = 104.0
    es_price: float = 5000.0
    zn_price: float = 110.0
    zf_price: float = 108.0
    rsi: float = 50.0
    trend_strength: float = 0.5
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

class TestRegimeClassifier:
    def test_growth_regime(self):
        from risk.regime_classifier import RegimeClassifier, MarketRegime
        rc = RegimeClassifier()
        regime = rc.classify(vix=14.0, adx=30.0)
        assert regime == MarketRegime.GROWTH

    def test_defensive_regime(self):
        from risk.regime_classifier import RegimeClassifier, MarketRegime
        rc = RegimeClassifier()
        regime = rc.classify(vix=28.0, adx=20.0)
        assert regime == MarketRegime.DEFENSIVE

    def test_crisis_regime(self):
        from risk.regime_classifier import RegimeClassifier, MarketRegime
        rc = RegimeClassifier()
        regime = rc.classify(vix=40.0, adx=35.0)
        assert regime == MarketRegime.CRISIS

    def test_neutral_regime(self):
        from risk.regime_classifier import RegimeClassifier, MarketRegime
        rc = RegimeClassifier()
        regime = rc.classify(vix=20.0, adx=20.0)
        assert regime == MarketRegime.NEUTRAL

    def test_low_vix_but_no_trend_is_neutral(self):
        from risk.regime_classifier import RegimeClassifier, MarketRegime
        rc = RegimeClassifier()
        regime = rc.classify(vix=14.0, adx=10.0)  # Low VIX but no trend
        assert regime == MarketRegime.NEUTRAL, "Need both low VIX AND trending for growth"

    def test_growth_allocation_boost(self):
        from risk.regime_classifier import RegimeClassifier, MarketRegime
        rc = RegimeClassifier()
        rc.classify(vix=14.0, adx=30.0)
        adj = rc.get_allocation_adjustments()
        assert adj["prop_scaling_delta"] == 0.15, "Growth should boost Prop Scaling +15%"

    def test_defensive_reduces_prop(self):
        from risk.regime_classifier import RegimeClassifier
        rc = RegimeClassifier()
        rc.classify(vix=28.0)
        adj = rc.get_allocation_adjustments()
        assert adj["prop_scaling_delta"] < 0, "Defensive should reduce Prop Scaling"
        assert adj["convexity_shield_delta"] > 0, "Defensive should boost hedges"
