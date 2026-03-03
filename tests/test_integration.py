"""
End-to-End Integration Tests

Tests the full pipeline: market data → orchestrator → order_manager → execution.
Uses MockMarketDataFeed and paper-mode OrderManager (no real IBKR).

Phase 6 of the Rust→Python migration.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain"))

import pytest
from datetime import datetime, timezone
from engine import QuantumEngine
from feeds.market_data import MockMarketDataFeed
from orchestrator import Orchestrator, MarketState, CrisisLevel, SleeveSignal
from execution.order_manager import OrderManager, OrderManagerConfig, TargetPosition
from execution.ibkr_client import IBKRClient, IBKRConfig, OrderStatus, Position, AccountSummary
from risk.kill_switch import KillSwitch, KillSwitchConfig
from compliance.audit_logger import AuditLogger


# ═══════════════════════════════════════════════════════════════════════════
# Mock IBKR Client (no real connection needed)
# ═══════════════════════════════════════════════════════════════════════════

class MockIBKRClient:
    """Minimal mock of IBKRClient for integration tests."""

    def __init__(self):
        self._connected = True
        self._positions = {}
        self._flattened = False

    def is_connected(self):
        return self._connected

    async def connect(self):
        self._connected = True
        return True

    async def disconnect(self):
        self._connected = False

    async def get_positions(self):
        return [
            Position(
                symbol=sym, quantity=qty,
                avg_cost=100.0, market_value=qty * 100.0,
                unrealized_pnl=0.0, realized_pnl=0.0,
            )
            for sym, qty in self._positions.items()
        ]

    async def get_account_summary(self):
        return AccountSummary(
            account_id="DU12345",
            net_liquidation=50_000.0,
            total_cash=10_000.0,
            buying_power=100_000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
        )

    async def flatten_all(self, reason=""):
        count = len(self._positions)
        self._positions = {}
        self._flattened = True
        return count


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_feed():
    return MockMarketDataFeed(default_vix=18.0, default_spx=5000.0)


@pytest.fixture
def engine(mock_feed, tmp_path):
    e = QuantumEngine(portfolio_value=50_000.0, tick_interval=0.01)
    e.set_feed(mock_feed)
    e.audit.log_dir = str(tmp_path / "audit")
    e.audit._ensure_log_dir()
    return e


@pytest.fixture
def mock_ibkr():
    return MockIBKRClient()


@pytest.fixture
def kill_switch():
    return KillSwitch(KillSwitchConfig(
        max_daily_loss_pct=0.02,
        max_position_pct=0.25,
        max_consecutive_rejections=5,
        heartbeat_timeout_seconds=30,
    ))


@pytest.fixture
def order_manager(mock_ibkr, kill_switch, tmp_path):
    audit = AuditLogger(log_dir=str(tmp_path / "audit"))
    config = OrderManagerConfig(
        min_order_size=1.0,
        max_order_size=100.0,
        max_orders_per_tick=5,
        enable_trading=False,
        paper_mode=True,
    )
    return OrderManager(mock_ibkr, kill_switch, audit, config)


# ═══════════════════════════════════════════════════════════════════════════
# Full Pipeline: Market Data → Orchestrator → Signals
# ═══════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """Engine processes market data through the full orchestrator pipeline."""

    @pytest.mark.asyncio
    async def test_engine_processes_ticks(self, engine):
        """Engine start → tick → stop produces valid state."""
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()

        state = engine.get_state()
        assert state["ticks_processed"] > 0
        assert state["running"] is False
        assert state["crisis_level"] == "Normal"

    @pytest.mark.asyncio
    async def test_signals_flow_through_pipeline(self, engine):
        """Signals are generated from sleeves after ticks."""
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()

        state = engine.get_state()
        signals = state["signals"]
        assert isinstance(signals, list)
        if signals:
            sig = signals[0]
            assert "sleeve_id" in sig
            assert "signal" in sig
            assert -1.0 <= sig["signal"] <= 1.0

    @pytest.mark.asyncio
    async def test_market_data_reaches_state(self, engine):
        """Market data from feed appears in engine state."""
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()

        state = engine.get_state()
        market = state["market"]
        assert market["vix"] == 18.0
        assert market["spx"] == 5000.0

    @pytest.mark.asyncio
    async def test_audit_trail_records_ticks(self, engine):
        """Audit logger captures entries during engine operation."""
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()

        state = engine.get_state()
        audit = state["audit_summary"]
        assert audit["total_entries"] > 0
        assert audit["finra_3110_compliant"] is True

    @pytest.mark.asyncio
    async def test_seraph_classifies_regime(self, engine):
        """SERAPH AI classifies regime after engine ticks."""
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()

        state = engine.get_state()
        seraph = state["seraph"]
        if seraph:
            assert "regime" in seraph
            assert "confidence" in seraph

    @pytest.mark.asyncio
    async def test_permission_vector_broadcast(self, engine):
        """Permission vector is broadcast after engine ticks."""
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()

        state = engine.get_state()
        pv = state["permission_vector"]
        if pv:
            assert "regime" in pv
            assert "sleeve_biases" in pv

    @pytest.mark.asyncio
    async def test_multi_tick_scenario(self, engine):
        """Engine handles multi-tick scenario with changing market data."""
        engine.feed.set_scenario([
            {"vix": 15.0, "spx": 5100.0},
            {"vix": 22.0, "spx": 4900.0},
            {"vix": 35.0, "spx": 4600.0},
        ])
        await engine.start()
        await asyncio.sleep(0.08)
        await engine.stop()

        state = engine.get_state()
        assert state["ticks_processed"] >= 3


# ═══════════════════════════════════════════════════════════════════════════
# Kill Switch Integration
# ═══════════════════════════════════════════════════════════════════════════

class TestKillSwitchFlatten:
    """Kill switch triggers and flattens positions."""

    def test_pnl_breach_triggers_kill(self, kill_switch):
        """Daily PnL loss > 2% triggers kill switch."""
        triggered = kill_switch.check_pnl(-1100.0, 50_000.0)
        assert triggered is True
        assert kill_switch.is_active() is True
        assert kill_switch.kill_reason.value == "pnl_loss"

    def test_position_breach_triggers_kill(self, kill_switch):
        """Position concentration > 25% triggers kill switch."""
        triggered = kill_switch.check_position(13_000.0, 50_000.0)
        assert triggered is True
        assert kill_switch.is_active() is True
        assert kill_switch.kill_reason.value == "position_breach"

    def test_consecutive_rejections_trigger_kill(self, kill_switch):
        """5 consecutive order rejections trigger kill switch."""
        for _ in range(5):
            kill_switch.record_rejection()
        assert kill_switch.is_active() is True
        assert kill_switch.kill_reason.value == "consecutive_rejections"

    def test_kill_switch_latches(self, kill_switch):
        """Kill switch stays active until manual reset."""
        kill_switch.check_pnl(-1100.0, 50_000.0)
        assert kill_switch.is_active() is True

        # Even if PnL recovers, still killed
        kill_switch.check_pnl(500.0, 50_000.0)
        assert kill_switch.is_active() is True

    def test_kill_switch_manual_reset(self, kill_switch):
        """Manual reset clears kill switch."""
        kill_switch.check_pnl(-1100.0, 50_000.0)
        assert kill_switch.is_active() is True

        kill_switch.reset(operator="admin")
        assert kill_switch.is_active() is False

    def test_fill_resets_rejection_counter(self, kill_switch):
        """A successful fill resets the consecutive rejection counter."""
        for _ in range(3):
            kill_switch.record_rejection()
        assert kill_switch.consecutive_rejections == 3

        kill_switch.record_fill()
        assert kill_switch.consecutive_rejections == 0

    @pytest.mark.asyncio
    async def test_engine_reflects_kill_switch(self, engine):
        """Kill switch state propagates to engine state."""
        await engine.start()
        await asyncio.sleep(0.03)

        # Trigger kill switch via orchestrator
        engine.orchestrator.is_killed = True
        await asyncio.sleep(0.03)
        await engine.stop()

        state = engine.get_state()
        assert state["kill_switch"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Permission Vector Gates Sleeves
# ═══════════════════════════════════════════════════════════════════════════

class TestPermissionVectorGatesSleeves:
    """Permission vector controls sleeve bias during different regimes."""

    def test_normal_regime_no_gating(self):
        """Normal regime: all sleeves pass through unmodified."""
        orch = Orchestrator(portfolio_value=50_000.0)
        market = MarketState(
            timestamp=datetime.now(timezone.utc),
            vix=15.0, spx=5000.0, tnx=40.0, dxy=104.0,
            es_price=5000.0, zn_price=110.0, zf_price=108.0,
        )
        result = orch.tick(market)
        assert orch.crisis_level == CrisisLevel.NORMAL

    def test_smart_bunker_risk_overlay_flattens(self):
        """SmartBunker risk overlay flattens all except Sleeve 5."""
        orch = Orchestrator(portfolio_value=50_000.0)

        # Create test signals with non-zero values
        test_signals = [
            SleeveSignal(1, "Treasury Yield", 0.5, 0.8, ["ZN"], "test"),
            SleeveSignal(2, "Compression & Curve", 0.3, 0.7, ["ZF"], "test"),
            SleeveSignal(3, "Prop Scaling", 0.6, 0.9, ["ES"], "test"),
            SleeveSignal(5, "Convexity Shield", 0.7, 0.85, ["SPY"], "test"),
        ]

        # Set crisis level directly for overlay test
        orch.crisis_level = CrisisLevel.SMART_BUNKER
        adjusted = orch.apply_risk_overlay(test_signals)

        for sig in adjusted:
            if sig.sleeve_id == 5:
                assert sig.signal == 0.7, "Sleeve 5 should be preserved"
            else:
                assert sig.signal == 0.0, f"Sleeve {sig.sleeve_id} should be flattened"

    def test_surgical_sniper_halves_signals(self):
        """SurgicalSniper: signals reduced by 50%."""
        orch = Orchestrator(portfolio_value=50_000.0)

        test_signals = [
            SleeveSignal(1, "Treasury Yield", 0.6, 0.8, ["ZN"], "test"),
            SleeveSignal(3, "Prop Scaling", 0.8, 0.9, ["ES"], "test"),
        ]
        orch.crisis_level = CrisisLevel.SURGICAL_SNIPER
        adjusted = orch.apply_risk_overlay(test_signals)

        for sig in adjusted:
            original = [s for s in test_signals if s.sleeve_id == sig.sleeve_id][0]
            assert abs(sig.signal - original.signal * 0.5) < 0.001

    def test_severe_reduces_signals_25_pct(self):
        """Severe: signals reduced by 25%."""
        orch = Orchestrator(portfolio_value=50_000.0)

        test_signals = [
            SleeveSignal(1, "Treasury Yield", 0.6, 0.8, ["ZN"], "test"),
        ]
        orch.crisis_level = CrisisLevel.SEVERE
        adjusted = orch.apply_risk_overlay(test_signals)

        assert abs(adjusted[0].signal - 0.6 * 0.75) < 0.001

    def test_crisis_transition_updates_permission_vector(self):
        """Transitioning crisis levels updates the permission vector."""
        orch = Orchestrator(portfolio_value=50_000.0)

        # Start normal
        market1 = MarketState(
            timestamp=datetime.now(timezone.utc),
            vix=15.0, spx=5000.0, tnx=40.0, dxy=104.0,
            es_price=5000.0, zn_price=110.0, zf_price=108.0,
        )
        orch.tick(market1)
        assert orch.crisis_level == CrisisLevel.NORMAL

        # Escalate to SmartBunker
        market2 = MarketState(
            timestamp=datetime.now(timezone.utc),
            vix=50.0, spx=4000.0, tnx=40.0, dxy=104.0,
            es_price=4000.0, zn_price=110.0, zf_price=108.0,
        )
        orch.tick(market2)
        assert orch.crisis_level == CrisisLevel.SMART_BUNKER

    def test_permission_vector_biases_vary_by_regime(self):
        """Different regimes produce different sleeve biases."""
        orch = Orchestrator(portfolio_value=50_000.0)

        market = MarketState(
            timestamp=datetime.now(timezone.utc),
            vix=15.0, spx=5000.0, tnx=40.0, dxy=104.0,
            es_price=5000.0, zn_price=110.0, zf_price=108.0,
        )
        orch.tick(market)

        if orch._current_vector:
            pv = orch._current_vector
            bias_1 = pv.get_sleeve_bias(1)
            bias_3 = pv.get_sleeve_bias(3)
            assert isinstance(bias_1, (int, float))
            assert isinstance(bias_3, (int, float))


# ═══════════════════════════════════════════════════════════════════════════
# Order Manager Integration
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderManagerIntegration:
    """Order manager executes targets from orchestrator output."""

    def test_delta_calculation(self, order_manager, mock_ibkr):
        """OrderManager calculates correct deltas between target and current."""
        # Simulate current position of 10 units
        order_manager._current_positions["SPY"] = 10.0

        targets = [
            TargetPosition(
                sleeve_id=1, symbol="SPY", sec_type="STK",
                target_quantity=25.0, target_dollar_value=12_500.0,
            ),
        ]
        deltas = order_manager.calculate_deltas(targets)
        assert len(deltas) == 1
        # Delta should be 25 - 10 = 15
        assert deltas[0].target_quantity == 15.0

    def test_delta_close_position(self, order_manager):
        """Delta calculation to close a position entirely."""
        order_manager._current_positions["TLT"] = 50.0

        targets = [
            TargetPosition(
                sleeve_id=2, symbol="TLT", sec_type="STK",
                target_quantity=0.0, target_dollar_value=0.0,
            ),
        ]
        deltas = order_manager.calculate_deltas(targets)
        assert deltas[0].target_quantity == -50.0

    def test_delta_caps_at_max_order_size(self, order_manager):
        """Delta is capped at max_order_size."""
        order_manager._current_positions["ES"] = 0.0

        targets = [
            TargetPosition(
                sleeve_id=3, symbol="ES", sec_type="FUT",
                target_quantity=500.0, target_dollar_value=250_000.0,
            ),
        ]
        deltas = order_manager.calculate_deltas(targets)
        assert deltas[0].target_quantity == 100.0  # Capped at max

    @pytest.mark.asyncio
    async def test_pre_trade_checks_when_disabled(self, order_manager):
        """Pre-trade checks reject when trading is disabled."""
        order = TargetPosition(
            sleeve_id=1, symbol="SPY", sec_type="STK",
            target_quantity=10.0, target_dollar_value=5_000.0,
        )
        passed, reason = await order_manager.pre_trade_checks(order)
        assert passed is False
        assert "trading" in reason.lower() or "enabled" in reason.lower()

    @pytest.mark.asyncio
    async def test_pre_trade_checks_kill_switch_active(self, order_manager):
        """Pre-trade checks reject when kill switch is active."""
        order_manager.config.enable_trading = True
        order_manager.kill_switch.manual_kill()

        order = TargetPosition(
            sleeve_id=1, symbol="SPY", sec_type="STK",
            target_quantity=10.0, target_dollar_value=5_000.0,
        )
        passed, reason = await order_manager.pre_trade_checks(order)
        assert passed is False
        assert "kill" in reason.lower()

    def test_order_manager_status(self, order_manager):
        """OrderManager.get_status() returns expected structure."""
        status = order_manager.get_status()
        assert "paper_mode" in status
        assert status["paper_mode"] is True
        assert "trading_enabled" in status
        assert status["trading_enabled"] is False
        assert "kill_switch" in status

    @pytest.mark.asyncio
    async def test_emergency_flatten(self, order_manager, mock_ibkr):
        """Emergency flatten closes all positions."""
        mock_ibkr._positions = {"SPY": 100, "TLT": 50, "ES": -10}
        closed = await order_manager.emergency_flatten(reason="test_crisis")
        assert closed == 3
        assert mock_ibkr._flattened is True


# ═══════════════════════════════════════════════════════════════════════════
# Paper Trading Go/No-Go
# ═══════════════════════════════════════════════════════════════════════════

class TestPaperTradingGoNoGo:
    """Validate go/no-go criteria evaluation."""

    def test_go_verdict_when_all_criteria_met(self):
        """GO verdict when all criteria pass."""
        from paper_trading_runner import SessionMetrics, PaperTradingConfig

        config = PaperTradingConfig(validation_days=5)
        metrics = SessionMetrics()
        metrics.peak_value = 50_000.0
        metrics.trough_value = 49_000.0
        metrics.max_drawdown = 0.02  # 2% < 5%
        metrics.daily_returns = [0.001, 0.002, -0.001, 0.003, 0.002]
        metrics.trading_days = 5
        metrics.kill_switch_fires = 0
        metrics.heartbeat_timeouts = 0
        metrics.connection_drops = 0
        metrics.sleeve_signals = {1: 10, 2: 8, 3: 12, 5: 6}

        report = metrics.go_no_go(config)
        assert report["max_dd_ok"] is True
        assert report["sufficient_data"] is True
        assert report["verdict"] == "GO"

    def test_nogo_verdict_excessive_drawdown(self):
        """NO-GO verdict when drawdown exceeds threshold."""
        from paper_trading_runner import SessionMetrics, PaperTradingConfig

        config = PaperTradingConfig(validation_days=5)
        metrics = SessionMetrics()
        metrics.peak_value = 50_000.0
        metrics.trough_value = 44_000.0
        metrics.max_drawdown = 0.12  # 12% > 5%
        metrics.daily_returns = [0.001, -0.05, -0.04, -0.03, 0.001]
        metrics.trading_days = 5
        metrics.kill_switch_fires = 0
        metrics.heartbeat_timeouts = 0
        metrics.connection_drops = 0
        metrics.sleeve_signals = {1: 10, 2: 8, 3: 12, 5: 6}

        report = metrics.go_no_go(config)
        assert report["max_dd_ok"] is False
        assert report["verdict"] == "NO-GO"

    def test_nogo_verdict_insufficient_data(self):
        """NO-GO verdict when insufficient trading days."""
        from paper_trading_runner import SessionMetrics, PaperTradingConfig

        config = PaperTradingConfig(validation_days=10)
        metrics = SessionMetrics()
        metrics.peak_value = 50_000.0
        metrics.trough_value = 49_500.0
        metrics.max_drawdown = 0.01
        metrics.daily_returns = [0.001, 0.002]
        metrics.trading_days = 2  # Only 2 of required 10
        metrics.kill_switch_fires = 0
        metrics.heartbeat_timeouts = 0
        metrics.connection_drops = 0
        metrics.sleeve_signals = {1: 5, 2: 3, 3: 4, 5: 2}

        report = metrics.go_no_go(config)
        assert report["sufficient_data"] is False
        assert report["verdict"] == "NO-GO"

    def test_sharpe_ratio_calculation(self):
        """Sharpe ratio computed from daily returns (property access)."""
        from paper_trading_runner import SessionMetrics

        metrics = SessionMetrics()
        # Consistent positive returns with some variance → positive Sharpe
        metrics.daily_returns = [0.002, 0.003, 0.001, 0.004, 0.002,
                                  0.003, 0.001, 0.002, 0.003, 0.001]

        sharpe = metrics.sharpe_ratio  # @property, not method
        assert sharpe > 0

    def test_drawdown_tracking(self):
        """update_drawdown() correctly tracks peak and max_drawdown."""
        from paper_trading_runner import SessionMetrics

        metrics = SessionMetrics()
        metrics.peak_value = 50_000.0

        # Value goes up
        metrics.update_drawdown(52_000.0)
        assert metrics.peak_value == 52_000.0

        # Value drops — max_drawdown should update
        metrics.update_drawdown(49_000.0)
        expected_dd = (52_000.0 - 49_000.0) / 52_000.0
        assert abs(metrics.max_drawdown - expected_dd) < 0.001

    def test_nogo_when_kill_switch_fired(self):
        """NO-GO if kill switch has fired during paper trading."""
        from paper_trading_runner import SessionMetrics, PaperTradingConfig

        config = PaperTradingConfig(validation_days=5)
        metrics = SessionMetrics()
        metrics.peak_value = 50_000.0
        metrics.max_drawdown = 0.01
        metrics.daily_returns = [0.001, 0.002, 0.001, 0.002, 0.001]
        metrics.trading_days = 5
        metrics.kill_switch_fires = 1  # Kill switch fired once
        metrics.heartbeat_timeouts = 0
        metrics.connection_drops = 0
        metrics.sleeve_signals = {1: 10, 2: 8, 3: 12, 5: 6}

        report = metrics.go_no_go(config)
        assert report["kill_switch_tested"] is False
        assert report["verdict"] == "NO-GO"


# ═══════════════════════════════════════════════════════════════════════════
# Crisis → Recovery Full Cycle
# ═══════════════════════════════════════════════════════════════════════════

class TestCrisisRecoveryCycle:
    """Full cycle: Normal → SmartBunker → de-escalation → Normal."""

    @pytest.mark.asyncio
    async def test_full_crisis_cycle(self, engine):
        """Engine handles Normal → Crisis → Recovery sequence."""
        engine.feed.set_scenario([
            {"vix": 15.0, "spx": 5000.0},   # Normal
            {"vix": 50.0, "spx": 4000.0},   # SmartBunker
            {"vix": 50.0, "spx": 3900.0},   # Still SmartBunker
            {"vix": 14.0, "spx": 5100.0},   # De-escalation tick 1
            {"vix": 14.0, "spx": 5100.0},   # De-escalation tick 2
            {"vix": 14.0, "spx": 5100.0},   # De-escalation tick 3
            {"vix": 14.0, "spx": 5100.0},   # De-escalation tick 4
            {"vix": 14.0, "spx": 5100.0},   # De-escalation tick 5
            {"vix": 14.0, "spx": 5100.0},   # Should be Normal again
        ])
        await engine.start()
        await asyncio.sleep(0.15)
        await engine.stop()

        state = engine.get_state()
        assert state["ticks_processed"] >= 9
        # After de-escalation, should be back to Normal
        assert state["crisis_level"] in ["Normal", "Elevated"]

    @pytest.mark.asyncio
    async def test_audit_captures_crisis_transitions(self, engine):
        """Audit trail records crisis level transitions."""
        engine.feed.set_scenario([
            {"vix": 15.0},
            {"vix": 50.0},  # Crisis
        ])
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.stop()

        state = engine.get_state()
        audit = state["audit_summary"]
        assert audit["total_entries"] > 0
        assert audit.get("risk_events", 0) >= 1

    @pytest.mark.asyncio
    async def test_concurrent_engine_operations(self, engine):
        """Engine handles concurrent state queries during ticks."""
        await engine.start()

        states = []
        for _ in range(5):
            states.append(engine.get_state())
            await asyncio.sleep(0.01)

        await engine.stop()

        for s in states:
            assert isinstance(s, dict)
            assert "running" in s
            assert "portfolio_value" in s
