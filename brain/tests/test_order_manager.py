"""
Tests for Order Manager — pre-trade risk checks and delta calculation.
These tests don't require an IBKR connection.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock
from execution.order_manager import OrderManager, OrderManagerConfig, TargetPosition
from risk.kill_switch import KillSwitch
from compliance.audit_logger import AuditLogger


@pytest.fixture
def manager():
    """Create OrderManager with mocked IBKR client."""
    mock_ibkr = MagicMock()
    mock_ibkr.is_connected.return_value = True
    mock_ibkr.get_positions = AsyncMock(return_value=[])
    mock_ibkr.get_account_summary = AsyncMock(return_value=None)
    
    ks = KillSwitch()
    audit = AuditLogger(log_dir="/tmp/test_audit")
    
    config = OrderManagerConfig(
        enable_trading=True,
        paper_mode=True,
    )
    
    mgr = OrderManager(mock_ibkr, ks, audit, config)
    mgr._portfolio_value = 100_000
    mgr._daily_pnl = 0
    return mgr


class TestDeltaCalculation:
    def test_new_position_creates_full_delta(self, manager):
        targets = [TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=5.0, target_dollar_value=50_000,
        )]
        manager._current_positions = {}
        deltas = manager.calculate_deltas(targets)
        assert len(deltas) == 1
        assert deltas[0].target_quantity == 5.0

    def test_existing_position_creates_partial_delta(self, manager):
        targets = [TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=5.0, target_dollar_value=50_000,
        )]
        manager._current_positions = {"ZN": 3.0}
        deltas = manager.calculate_deltas(targets)
        assert len(deltas) == 1
        assert deltas[0].target_quantity == 2.0  # Need 2 more

    def test_no_delta_if_already_at_target(self, manager):
        targets = [TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=5.0, target_dollar_value=50_000,
        )]
        manager._current_positions = {"ZN": 5.0}
        deltas = manager.calculate_deltas(targets)
        assert len(deltas) == 0  # Already there

    def test_close_position_creates_negative_delta(self, manager):
        targets = [TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=0.0, target_dollar_value=0,
        )]
        manager._current_positions = {"ZN": 5.0}
        deltas = manager.calculate_deltas(targets)
        assert len(deltas) == 1
        assert deltas[0].target_quantity == -5.0

    def test_max_order_size_cap(self, manager):
        targets = [TargetPosition(
            sleeve_id=3, symbol="ES", sec_type="FUT",
            target_quantity=200.0, target_dollar_value=500_000,
        )]
        manager._current_positions = {}
        deltas = manager.calculate_deltas(targets)
        assert len(deltas) == 1
        assert abs(deltas[0].target_quantity) <= manager.config.max_order_size

    def test_min_order_size_filter(self, manager):
        targets = [TargetPosition(
            sleeve_id=1, symbol="IEF", sec_type="STK",
            target_quantity=0.5, target_dollar_value=100,
        )]
        manager._current_positions = {}
        deltas = manager.calculate_deltas(targets)
        assert len(deltas) == 0  # Below minimum


class TestPreTradeChecks:
    @pytest.mark.asyncio
    async def test_approved_when_all_clear(self, manager):
        order = TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=2.0, target_dollar_value=20_000,
        )
        approved, reason = await manager.pre_trade_checks(order)
        assert approved is True
        assert reason == "approved"

    @pytest.mark.asyncio
    async def test_rejected_when_kill_switch_active(self, manager):
        manager.kill_switch.manual_kill()
        order = TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=2.0, target_dollar_value=20_000,
        )
        approved, reason = await manager.pre_trade_checks(order)
        assert approved is False
        assert "Kill switch" in reason

    @pytest.mark.asyncio
    async def test_rejected_when_trading_disabled(self, manager):
        manager.config.enable_trading = False
        order = TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=2.0, target_dollar_value=20_000,
        )
        approved, reason = await manager.pre_trade_checks(order)
        assert approved is False
        assert "not enabled" in reason

    @pytest.mark.asyncio
    async def test_rejected_on_concentration_breach(self, manager):
        """Position > 25% of portfolio triggers kill switch."""
        order = TargetPosition(
            sleeve_id=3, symbol="ES", sec_type="FUT",
            target_quantity=50.0, target_dollar_value=30_000,  # 30% of 100K
        )
        approved, reason = await manager.pre_trade_checks(order)
        assert approved is False
        assert "concentration" in reason or "Kill switch" in reason

    @pytest.mark.asyncio
    async def test_rejected_on_rate_limit(self, manager):
        manager._orders_this_tick = manager.config.max_orders_per_tick
        order = TargetPosition(
            sleeve_id=2, symbol="ZN", sec_type="FUT",
            target_quantity=1.0, target_dollar_value=10_000,
        )
        approved, reason = await manager.pre_trade_checks(order)
        assert approved is False
        assert "Rate limit" in reason


class TestManagerStatus:
    def test_status_returns_complete_snapshot(self, manager):
        status = manager.get_status()
        assert "connected" in status
        assert "trading_enabled" in status
        assert "paper_mode" in status
        assert "portfolio_value" in status
        assert "kill_switch" in status
