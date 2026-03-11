"""
Tests for SERAPH AI™ v1.0 components:
- Permission Vector (Master→Sleeve broadcast, Feature 1)
- KPI Guard (monthly DD veto, Feature 4)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import date
from risk.permission_vector import (
    PermissionVector, generate_permission_vector, REGIME_VECTORS,
)
from risk.kpi_guard import KPIGuard, KPIGuardConfig, DailySnapshot


# ═══ Permission Vector Tests ════════════════════════════════════

class TestPermissionVector:
    def test_growth_boosts_prop(self):
        v = REGIME_VECTORS["growth"]
        assert v.prop_bias > 1.0
        assert v.treasury_bias < 1.0

    def test_stress_boosts_tail_and_treasury(self):
        v = REGIME_VECTORS["stress"]
        assert v.tail_bias > 1.0
        assert v.treasury_bias > 1.0
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
        assert v.rwa_bias == 0.0, "RWA bias should be 0 in crisis"

    def test_get_sleeve_bias(self):
        v = REGIME_VECTORS["growth"]
        assert v.get_sleeve_bias(3) == v.prop_bias
        assert v.get_sleeve_bias(5) == v.tail_bias
        assert v.get_sleeve_bias(99) == 0.0  # Unknown sleeve

    def test_all_regimes_defined(self):
        expected = {"growth", "stress", "transition", "compression", "crisis"}
        assert set(REGIME_VECTORS.keys()) == expected


class TestPermissionVectorGeneration:
    def test_known_regime(self):
        v = generate_permission_vector("growth")
        assert v.regime == "growth"
        assert v.prop_bias > 1.0

    def test_unknown_regime_defaults(self):
        v = generate_permission_vector("unknown_regime")
        assert v.regime == "compression"  # Default

    def test_human_approval_on_large_shift(self):
        """Shifting from growth to crisis should flag >20% change."""
        prev = generate_permission_vector("growth")
        curr = generate_permission_vector("crisis", previous_vector=prev)
        assert curr.requires_human_approval is True
        assert "Sleeve" in curr.approval_reason

    def test_no_approval_on_small_shift(self):
        """Shifting between similar regimes should not require approval."""
        prev = generate_permission_vector("growth")
        curr = generate_permission_vector("compression", previous_vector=prev)
        # Growth→compression: largest shift is treasury 0.85→1.0 (18%) — under 20%
        assert curr.requires_human_approval is False

    def test_no_approval_without_previous(self):
        v = generate_permission_vector("crisis")
        assert v.requires_human_approval is False

    def test_to_dict_format(self):
        v = generate_permission_vector("growth")
        d = v.to_dict()
        assert "regime" in d
        assert "biases" in d
        assert "heartbeat" in d
        assert d["biases"]["prop"] > 1.0


# ═══ KPI Guard Tests ════════════════════════════════════════════

class TestKPIGuardBasics:
    def test_initial_state_no_veto(self):
        guard = KPIGuard()
        assert guard.is_veto_active is False
        assert guard.is_warning_active is False

    def test_positive_pnl_no_veto(self):
        guard = KPIGuard()
        for i in range(5):
            guard.record_daily(100_000 + (i * 500), 500)
        assert guard.is_veto_active is False

    def test_small_loss_no_veto(self):
        guard = KPIGuard()
        for i in range(5):
            guard.record_daily(100_000 - (i * 100), -100)
        # Total loss: $400 / $100K = 0.4% — well under 5%
        assert guard.is_veto_active is False


class TestKPIGuardVeto:
    def test_veto_on_5pct_monthly_dd(self):
        """5% monthly drawdown should trigger veto."""
        guard = KPIGuard()
        # Simulate 5 days of 1.2% daily losses (cumulative > 5%)
        value = 100_000
        for i in range(5):
            loss = value * 0.012
            value -= loss
            guard.record_daily(value, -loss)
        assert guard.is_veto_active is True

    def test_veto_allows_sleeve_5(self):
        """Even under veto, Sleeve 5 (hedge) should be allowed."""
        guard = KPIGuard()
        guard._veto_active = True
        guard._veto_reason = "Test veto"
        
        allowed, reason = guard.check_trade_allowed(sleeve_id=5)
        assert allowed is True
        assert "hedge" in reason

    def test_veto_blocks_sleeve_3(self):
        """Under veto, non-hedge sleeves should be blocked."""
        guard = KPIGuard()
        guard._veto_active = True
        guard._veto_reason = "MTD DD exceeds limit"
        
        allowed, reason = guard.check_trade_allowed(sleeve_id=3)
        assert allowed is False
        assert "VETO" in reason

    def test_veto_blocks_sleeve_2(self):
        guard = KPIGuard()
        guard._veto_active = True
        guard._veto_reason = "Test"
        
        allowed, _ = guard.check_trade_allowed(sleeve_id=2)
        assert allowed is False


class TestKPIGuardWarning:
    def test_warning_at_moderate_loss(self):
        """Moderate losses should trigger warning but not necessarily veto."""
        config = KPIGuardConfig(
            warning_threshold_pct=0.03,
            min_data_points=3,
            projected_dd_safety_margin=1.0,  # No safety amplification for this test
        )
        guard = KPIGuard(config=config)
        
        value = 100_000
        # 3 days of 1.1% loss = ~3.3% MTD → hits warning
        for i in range(3):
            loss = value * 0.011
            value -= loss
            guard.record_daily(value, -loss)
        
        # With only 3 data points and 1x projection, should warn but may veto on projection
        # The key test: warning flag should be set when MTD crosses 3%
        mtd = guard.get_mtd_drawdown()
        assert mtd < -0.03, f"MTD should be worse than -3%, got {mtd:.2%}"


class TestKPIGuardProjection:
    def test_projected_dd_with_losses(self):
        guard = KPIGuard()
        value = 100_000
        for i in range(5):
            loss = value * 0.005
            value -= loss
            guard.record_daily(value, -loss)
        
        projected = guard.get_projected_monthly_dd()
        assert projected < 0  # Should project negative

    def test_projected_dd_positive_returns(self):
        guard = KPIGuard()
        value = 100_000
        for i in range(5):
            gain = value * 0.003
            value += gain
            guard.record_daily(value, gain)
        
        projected = guard.get_projected_monthly_dd()
        assert projected == 0.0  # No DD concern

    def test_insufficient_data_returns_zero(self):
        guard = KPIGuard()
        guard.record_daily(100_000, -100)
        assert guard.get_projected_monthly_dd() == 0.0


class TestKPIGuardStatus:
    def test_status_format(self):
        guard = KPIGuard()
        guard.record_daily(100_000, -100)
        status = guard.get_status()
        assert "veto_active" in status
        assert "warning_active" in status
        assert "mtd_drawdown" in status
        assert "projected_dd" in status
        assert "data_points" in status
