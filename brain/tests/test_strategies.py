"""Tests for all strategy modules — matches actual implementations."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import pytest
from dataclasses import dataclass
from datetime import datetime


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
    t2y: float = 3.5
    es_rsi: float = 50.0
    fed_dot_median: float = 5.50
    fed_funds_rate: float = 5.50

    def __post_init__(self):
        if self.timestamp is None:
            from datetime import timezone
            self.timestamp = datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════
# SLEEVE 1: Treasury Yield
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
# SLEEVE 1: See test_sleeve1.py (28 dedicated tests)
# ═══════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════
# SLEEVE 3: Prop Scaling
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
# SLEEVE 3: See test_sleeve3.py (62 dedicated tests)
# ═══════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════
# SLEEVE 5: Convexity Shield
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
# SLEEVE 5: See test_sleeve5.py (57 dedicated tests)
# ═══════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════
# SERAPH AI: Regime Classifier (smoke tests)
# ═══════════════════════════════════════════════════════

class TestSeraphAISmoke:
    def test_regime_detection_works(self):
        from strategies.seraph_ai import SeraphAI, MarketRegime
        s = SeraphAI()
        state = s.classify_regime(vix=40.0, spx=3500)
        assert state.regime == MarketRegime.CRISIS

    def test_allocation_adjustment_works(self):
        from strategies.seraph_ai import SeraphAI
        s = SeraphAI()
        for _ in range(7):
            s.classify_regime(vix=40.0, spx=3500)
        adj = s.get_allocation_adjustment()
        assert adj.sleeve5_delta > 0, "Crisis should boost hedges"
