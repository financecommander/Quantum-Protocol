"""Tests for Permission Vector — Master→Sleeve broadcast."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from risk.permission_vector import (
    PermissionVector, generate_permission_vector, REGIME_VECTORS,
)


class TestRegimeVectors:
    def test_growth_boosts_prop(self):
        v = REGIME_VECTORS["growth"]
        assert v.prop_bias > 1.0
        assert v.tail_bias < 1.0

    def test_stress_boosts_tail(self):
        v = REGIME_VECTORS["stress"]
        assert v.tail_bias > 1.0
        assert v.prop_bias < 1.0

    def test_transition_boosts_curve(self):
        v = REGIME_VECTORS["transition"]
        assert v.curve_bias > 1.0

    def test_crisis_blocks_prop_and_curve(self):
        v = REGIME_VECTORS["crisis"]
        assert v.prop_bias == 0.0
        assert v.curve_bias == 0.0
        assert v.tail_bias > 1.0

    def test_rwa_zero_in_crisis(self):
        """Sleeve 4 blocked in crisis (crypto correlates with equities)."""
        v = REGIME_VECTORS["crisis"]
        assert v.rwa_bias == 0.0, "RWA should be 0 in crisis"


class TestGetSleeveBias:
    def test_sleeve_1_is_treasury(self):
        v = REGIME_VECTORS["growth"]
        assert v.get_sleeve_bias(1) == v.treasury_bias

    def test_sleeve_3_is_prop(self):
        v = REGIME_VECTORS["growth"]
        assert v.get_sleeve_bias(3) == v.prop_bias

    def test_sleeve_5_is_tail(self):
        v = REGIME_VECTORS["stress"]
        assert v.get_sleeve_bias(5) == v.tail_bias

    def test_unknown_sleeve_returns_zero(self):
        v = REGIME_VECTORS["growth"]
        assert v.get_sleeve_bias(99) == 0.0


class TestHumanApprovalGate:
    """Feature 7: >20% shift requires human approval."""

    def test_large_shift_flags_approval(self):
        prev = REGIME_VECTORS["growth"]
        current = generate_permission_vector("crisis", previous_vector=prev)
        # growth→crisis: prop goes 1.15→0.0 (100% shift)
        assert current.requires_human_approval is True
        assert "Sleeve" in current.approval_reason

    def test_small_shift_no_approval(self):
        prev = REGIME_VECTORS["growth"]
        current = generate_permission_vector("compression", previous_vector=prev)
        # growth→compression: prop goes 1.15→1.10 (4% shift) — under 20%
        assert current.requires_human_approval is False

    def test_no_previous_no_approval(self):
        v = generate_permission_vector("crisis", previous_vector=None)
        assert v.requires_human_approval is False

    def test_unknown_regime_defaults_compression(self):
        v = generate_permission_vector("unknown_regime")
        assert v.regime == "compression"


class TestVectorSerialization:
    def test_to_dict_has_all_fields(self):
        v = REGIME_VECTORS["growth"]
        d = v.to_dict()
        assert "regime" in d
        assert "biases" in d
        assert "heartbeat" in d
        assert len(d["biases"]) == 5
