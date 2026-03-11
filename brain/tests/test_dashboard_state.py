"""
Dashboard State Module Tests

Tests brain/dashboard/state.py:
  - Simulated fallback state (when no engine is connected)
  - get_portfolio_state() format compatibility
  - get_sleeve_allocations() format compatibility
  - get_signals(), get_permission_vector(), get_seraph_state()
  - Cache invalidation
"""

import sys
import os
import importlib.util

import pytest
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════════
# Import brain/dashboard/state.py directly via file path
# (avoids package-level import issues when pytest collects brain/tests/)
# ═══════════════════════════════════════════════════════════════════════════

_state_path = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "state.py"
))
_spec = importlib.util.spec_from_file_location("dashboard_state", _state_path)
_state_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_state_mod)

_simulated_state = _state_mod._simulated_state
get_portfolio_state = _state_mod.get_portfolio_state
get_sleeve_allocations = _state_mod.get_sleeve_allocations
get_signals = _state_mod.get_signals
get_permission_vector = _state_mod.get_permission_vector
get_seraph_state = _state_mod.get_seraph_state
invalidate_cache = _state_mod.invalidate_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test to ensure simulated data."""
    invalidate_cache()
    yield
    invalidate_cache()


# ═══════════════════════════════════════════════════════════════════════════
# Simulated State Structure
# ═══════════════════════════════════════════════════════════════════════════

class TestSimulatedState:
    def test_has_required_keys(self):
        state = _simulated_state()
        required = [
            "running", "ticks_processed", "uptime_seconds", "crisis_level",
            "portfolio_value", "signals", "allocation", "seraph", "market",
            "permission_vector", "kill_switch", "human_approval_pending",
            "audit_summary",
        ]
        for key in required:
            assert key in state, f"Missing key: {key}"

    def test_running_is_false(self):
        state = _simulated_state()
        assert state["running"] is False

    def test_portfolio_value_default(self):
        state = _simulated_state()
        assert state["portfolio_value"] == 50_000.0

    def test_allocation_sums_to_one(self):
        state = _simulated_state()
        alloc = state["allocation"]
        total = sum(alloc.values())
        assert abs(total - 1.0) < 0.001

    def test_seraph_has_regime(self):
        state = _simulated_state()
        assert "regime" in state["seraph"]
        assert "confidence" in state["seraph"]

    def test_market_has_vix_and_spx(self):
        state = _simulated_state()
        assert "vix" in state["market"]
        assert "spx" in state["market"]

    def test_audit_summary_finra_compliant(self):
        state = _simulated_state()
        assert state["audit_summary"]["finra_3110_compliant"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio State Format
# ═══════════════════════════════════════════════════════════════════════════

class TestGetPortfolioState:
    """Test format compatibility with the original Streamlit get_portfolio_state()."""

    def test_has_portfolio_value(self):
        ps = get_portfolio_state()
        assert "portfolio_value" in ps
        assert ps["portfolio_value"] > 0

    def test_has_pnl_fields(self):
        ps = get_portfolio_state()
        assert "daily_pnl" in ps
        assert "daily_pnl_pct" in ps
        assert "total_pnl" in ps
        assert "total_pnl_pct" in ps

    def test_has_market_fields(self):
        ps = get_portfolio_state()
        assert "vix" in ps
        assert "spx" in ps
        assert ps["vix"] > 0
        assert ps["spx"] > 0

    def test_has_regime_and_crisis(self):
        ps = get_portfolio_state()
        assert "regime" in ps
        assert "crisis_level" in ps

    def test_has_kill_switch(self):
        ps = get_portfolio_state()
        assert "kill_switch" in ps
        assert isinstance(ps["kill_switch"], bool)

    def test_has_timestamp(self):
        ps = get_portfolio_state()
        assert "timestamp" in ps
        assert isinstance(ps["timestamp"], datetime)

    def test_cash_derived_from_allocation(self):
        ps = get_portfolio_state()
        # Cash should be portfolio_value * cash_allocation
        assert ps["cash"] > 0
        assert ps["cash"] <= ps["portfolio_value"]


# ═══════════════════════════════════════════════════════════════════════════
# Sleeve Allocations Format
# ═══════════════════════════════════════════════════════════════════════════

class TestGetSleeveAllocations:
    def test_has_all_sleeves(self):
        alloc = get_sleeve_allocations()
        assert "Sleeve 1: Treasury Yield" in alloc
        assert "Sleeve 2: Compression & Curve" in alloc
        assert "Sleeve 3: Prop Scaling" in alloc
        assert "Sleeve 4: RWA/Crypto" in alloc
        assert "Sleeve 5: Convexity Shield" in alloc
        assert "Cash Reserve" in alloc

    def test_sleeve_format(self):
        alloc = get_sleeve_allocations()
        for name, data in alloc.items():
            assert "target" in data
            assert "actual" in data
            assert "pnl" in data
            assert "status" in data

    def test_target_allocations_sum_to_one(self):
        alloc = get_sleeve_allocations()
        total = sum(v["target"] for v in alloc.values())
        assert abs(total - 1.0) < 0.001

    def test_sleeve4_active(self):
        alloc = get_sleeve_allocations()
        s4 = alloc["Sleeve 4: RWA/Crypto"]
        assert s4["target"] == 0.10


# ═══════════════════════════════════════════════════════════════════════════
# Signal, Permission Vector, SERAPH accessors
# ═══════════════════════════════════════════════════════════════════════════

class TestAccessors:
    def test_get_signals_returns_list(self):
        signals = get_signals()
        assert isinstance(signals, list)

    def test_get_permission_vector_has_regime(self):
        pv = get_permission_vector()
        assert "regime" in pv
        assert "biases" in pv

    def test_get_permission_vector_biases_are_numeric(self):
        pv = get_permission_vector()
        for sleeve_id, bias in pv["biases"].items():
            assert isinstance(bias, (int, float))

    def test_get_seraph_state_has_regime(self):
        seraph = get_seraph_state()
        assert "regime" in seraph

    def test_get_seraph_state_has_confidence(self):
        seraph = get_seraph_state()
        assert "confidence" in seraph
        assert 0 <= seraph["confidence"] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Cache Invalidation
# ═══════════════════════════════════════════════════════════════════════════

class TestCacheInvalidation:
    def test_invalidate_clears_cache(self):
        invalidate_cache()
        assert _state_mod._cached_state is None
        assert _state_mod._cache_time == 0.0
