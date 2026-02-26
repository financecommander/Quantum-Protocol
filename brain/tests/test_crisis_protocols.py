"""Tests ported from Rust test suite: crisis protocol boundary conditions."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from risk.crisis_protocols import CrisisProtocol, CrisisLevel


@pytest.fixture
def protocol():
    return CrisisProtocol()


class TestCrisisClassification:
    def test_normal_below_20(self, protocol):
        assert protocol.evaluate(15.0) == CrisisLevel.NORMAL

    def test_elevated_at_20(self, protocol):
        assert protocol.evaluate(20.1) == CrisisLevel.ELEVATED

    def test_severe_at_28(self, protocol):
        assert protocol.evaluate(28.5) == CrisisLevel.SEVERE

    def test_sniper_at_35(self, protocol):
        assert protocol.evaluate(36.0) == CrisisLevel.SURGICAL_SNIPER

    def test_bunker_at_45(self, protocol):
        assert protocol.evaluate(46.0) == CrisisLevel.SMART_BUNKER

    def test_boundary_exactly_20(self, protocol):
        assert protocol.evaluate(20.0) == CrisisLevel.NORMAL


class TestCrisisPrecedence:
    def test_escalation_is_immediate(self, protocol):
        protocol.evaluate(15.0)
        level = protocol.evaluate(50.0)
        assert level == CrisisLevel.SMART_BUNKER

    def test_deescalation_requires_sustained_calm(self, protocol):
        protocol.evaluate(50.0)
        level = protocol.evaluate(15.0)
        assert level == CrisisLevel.SMART_BUNKER
        for _ in range(4):
            protocol.evaluate(15.0)
        level = protocol.evaluate(15.0)
        assert level == CrisisLevel.NORMAL


class TestCrisisPositionMultiplier:
    def test_normal_full_size(self, protocol):
        protocol.evaluate(15.0)
        assert protocol.get_position_multiplier() == 1.0

    def test_severe_reduced_25pct(self, protocol):
        protocol.evaluate(29.0)
        assert protocol.get_position_multiplier() == 0.75

    def test_sniper_reduced_50pct(self, protocol):
        protocol.evaluate(36.0)
        assert protocol.get_position_multiplier() == 0.50

    def test_bunker_flattened(self, protocol):
        protocol.evaluate(46.0)
        assert protocol.get_position_multiplier() == 0.0


class TestSmartBunkerHedgeException:
    def test_bunker_flattens_non_hedge_sleeves(self, protocol):
        protocol.evaluate(50.0)
        assert protocol.should_flatten_sleeve(1) is True
        assert protocol.should_flatten_sleeve(2) is True
        assert protocol.should_flatten_sleeve(3) is True

    def test_bunker_keeps_tail_hedge(self, protocol):
        protocol.evaluate(50.0)
        assert protocol.should_flatten_sleeve(5) is False


class TestTerraLunaReplay:
    def test_terra_luna_escalation(self, protocol):
        protocol.evaluate(20.0)
        assert protocol.state.level == CrisisLevel.NORMAL
        protocol.evaluate(22.0)
        assert protocol.state.level == CrisisLevel.ELEVATED
        protocol.evaluate(30.0)
        assert protocol.state.level == CrisisLevel.SEVERE
        protocol.evaluate(36.0)
        assert protocol.state.level == CrisisLevel.SURGICAL_SNIPER
        assert protocol.get_position_multiplier() == 0.50
