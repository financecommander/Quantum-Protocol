"""
Tests for Sleeve 3: Prop-Firm Scaling (The Velocity Sleeve™).

Covers:
  - Account initialization and lifecycle
  - Eval pass criteria (10% profit, <5% DD, 30 days)
  - Breach detection (6% DD, 2% daily loss, 12% max DD, time)
  - Scaling mechanics (2x on pass)
  - Reset mechanics (back to seed)
  - Trade signal generation (RSI, momentum)
  - Position sizing (capital-based, bias-adjusted, leverage-capped)
  - Quarterly review (70% win rate → +50% capital)
  - Permission vector gating
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime
from strategies.sleeve3_prop_scaling import (
    PropScalingStrategy, Sleeve3Config, EvalAccount, AccountPhase,
    SignalType, SignalSource, LLMSignal, AssetClass,
)


@pytest.fixture
def strategy():
    s = PropScalingStrategy()
    s.initialize_accounts(5)
    return s


@pytest.fixture
def account():
    return EvalAccount(
        account_id="TEST-001",
        phase=AccountPhase.EVAL,
        seed_capital=10_000,
        current_capital=10_000,
        peak_capital=10_000,
        eval_start_date=datetime.utcnow(),
    )


class MockMarket:
    def __init__(self, rsi=50.0, trend_strength=0.0, vix=18.0, spx=5000.0):
        self.rsi = rsi
        self.trend_strength = trend_strength
        self.vix = vix
        self.spx = spx
        self.tnx = 42.0
        self.dxy = 104.0
        self.es_price = spx
        self.zn_price = 110.0
        self.zf_price = 108.0
        self.timestamp = datetime.utcnow()


# ═══ Account Initialization ═════════════════════════════════════

class TestAccountInit:
    def test_creates_correct_number(self, strategy):
        assert len(strategy.accounts) == 5

    def test_all_start_in_eval_phase(self, strategy):
        assert all(a.phase == AccountPhase.EVAL for a in strategy.accounts)

    def test_all_start_with_seed_capital(self, strategy):
        assert all(a.current_capital == 10_000 for a in strategy.accounts)

    def test_scaling_starts_at_1x(self, strategy):
        assert all(a.scaling_multiplier == 1.0 for a in strategy.accounts)

    def test_custom_account_count(self):
        s = PropScalingStrategy()
        s.initialize_accounts(10)
        assert len(s.accounts) == 10

    def test_account_ids_unique(self, strategy):
        ids = [a.account_id for a in strategy.accounts]
        assert len(ids) == len(set(ids))


# ═══ Account Properties ═════════════════════════════════════════

class TestAccountProperties:
    def test_drawdown_from_peak(self, account):
        account.peak_capital = 10_000
        account.current_capital = 9_400  # 6% drop
        assert abs(account.drawdown_pct - 0.06) < 0.001

    def test_return_from_seed(self, account):
        account.current_capital = 11_000  # 10% gain
        assert abs(account.return_pct - 0.10) < 0.001

    def test_win_rate(self, account):
        account.trade_count = 10
        account.win_count = 8
        assert abs(account.win_rate - 0.80) < 0.001

    def test_win_rate_zero_trades(self, account):
        assert account.win_rate == 0.0

    def test_daily_loss_pct(self, account):
        account.daily_pnl = -200  # $200 loss on $10K
        assert abs(account.daily_loss_pct - 0.02) < 0.001


# ═══ Eval Pass Criteria ═════════════════════════════════════════

class TestEvalPass:
    def test_pass_on_10pct_profit_under_dd(self, strategy, account):
        """10% profit + <5% DD → pass."""
        account.current_capital = 11_000  # 10% profit
        account.peak_capital = 11_000     # No drawdown
        assert strategy.check_eval_pass(account) is True

    def test_no_pass_below_10pct(self, strategy, account):
        """9% profit → not enough."""
        account.current_capital = 10_900
        account.peak_capital = 10_900
        assert strategy.check_eval_pass(account) is False

    def test_no_pass_with_high_dd(self, strategy, account):
        """10% profit but DD was ≥5% → fail."""
        account.current_capital = 11_000
        account.peak_capital = 11_600  # DD = 600/11600 = 5.2%
        assert strategy.check_eval_pass(account) is False

    def test_no_pass_if_not_in_eval(self, strategy, account):
        """Only EVAL phase accounts can pass."""
        account.phase = AccountPhase.SCALING
        account.current_capital = 25_000  # Way above target
        assert strategy.check_eval_pass(account) is False


# ═══ Eval Breach Detection ══════════════════════════════════════

class TestEvalBreach:
    def test_breach_on_6pct_drawdown(self, strategy, account):
        account.peak_capital = 10_000
        account.current_capital = 9_400  # 6% DD
        breached, reason = strategy.check_eval_breach(account)
        assert breached is True
        assert "drawdown" in reason

    def test_no_breach_at_5pct_drawdown(self, strategy, account):
        account.peak_capital = 10_000
        account.current_capital = 9_500  # 5% DD — still under 6% breach
        breached, _ = strategy.check_eval_breach(account)
        assert breached is False

    def test_breach_on_daily_2pct_loss(self, strategy, account):
        account.daily_pnl = -200  # 2% of 10K
        breached, reason = strategy.check_eval_breach(account)
        assert breached is True
        assert "daily_loss" in reason

    def test_breach_on_12pct_max_dd(self, strategy, account):
        account.peak_capital = 10_000
        account.current_capital = 8_800  # 12% DD
        breached, reason = strategy.check_eval_breach(account)
        # Should breach on 6% first, but 12% also triggers
        assert breached is True

    def test_breach_on_time_without_profit(self, strategy, account):
        """30 days elapsed, <10% profit → time breach."""
        account.days_in_eval = 30
        account.current_capital = 10_500  # Only 5% profit
        breached, reason = strategy.check_eval_breach(account)
        assert breached is True
        assert "time" in reason

    def test_no_time_breach_if_profitable(self, strategy, account):
        """30 days but hit 10% → no time breach."""
        account.days_in_eval = 30
        account.current_capital = 11_000  # 10% profit
        account.peak_capital = 11_000
        breached, _ = strategy.check_eval_breach(account)
        assert breached is False

    def test_no_breach_if_already_breached(self, strategy, account):
        """Don't re-breach an already breached account."""
        account.phase = AccountPhase.BREACHED
        account.current_capital = 5_000
        breached, _ = strategy.check_eval_breach(account)
        assert breached is False


# ═══ Scaling Mechanics ══════════════════════════════════════════

class TestScaling:
    def test_scale_doubles_capital(self, strategy, account):
        strategy.scale_account(account)
        assert account.current_capital == 20_000
        assert account.scaling_multiplier == 2.0

    def test_scale_updates_phase(self, strategy, account):
        strategy.scale_account(account)
        assert account.phase == AccountPhase.SCALING

    def test_scale_resets_eval_timer(self, strategy, account):
        account.days_in_eval = 25
        strategy.scale_account(account)
        assert account.days_in_eval == 0

    def test_double_scale(self, strategy, account):
        """Pass twice → 4x capital."""
        strategy.scale_account(account)  # 1x → 2x
        strategy.scale_account(account)  # 2x → 4x
        assert account.scaling_multiplier == 4.0
        assert account.current_capital == 40_000


# ═══ Reset Mechanics ════════════════════════════════════════════

class TestReset:
    def test_reset_returns_to_seed(self, strategy, account):
        account.current_capital = 20_000
        account.scaling_multiplier = 2.0
        strategy.reset_account(account, "test breach")
        assert account.current_capital == 10_000
        assert account.scaling_multiplier == 1.0

    def test_reset_returns_to_eval_phase(self, strategy, account):
        account.phase = AccountPhase.SCALING
        strategy.reset_account(account, "test")
        assert account.phase == AccountPhase.EVAL

    def test_reset_clears_daily_pnl(self, strategy, account):
        account.daily_pnl = -500
        strategy.reset_account(account, "test")
        assert account.daily_pnl == 0.0

    def test_reset_restarts_timer(self, strategy, account):
        account.days_in_eval = 28
        strategy.reset_account(account, "test")
        assert account.days_in_eval == 0


# ═══ Signal Generation ══════════════════════════════════════════

class TestSignalGeneration:
    def test_long_on_oversold_rsi(self, strategy):
        market = MockMarket(rsi=25.0)
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.LONG
        assert source == SignalSource.RSI

    def test_short_on_overbought_rsi(self, strategy):
        market = MockMarket(rsi=75.0)
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.SHORT
        assert source == SignalSource.RSI

    def test_none_on_neutral_rsi(self, strategy):
        market = MockMarket(rsi=50.0, trend_strength=0.0)
        signal, _ = strategy.generate_trade_signal(market)
        assert signal == SignalType.NONE

    def test_long_on_strong_trend(self, strategy):
        market = MockMarket(rsi=50.0, trend_strength=0.7)
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.LONG
        assert source == SignalSource.MOMENTUM

    def test_short_on_negative_trend(self, strategy):
        market = MockMarket(rsi=50.0, trend_strength=-0.7)
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.SHORT
        assert source == SignalSource.MOMENTUM

    def test_rsi_takes_priority_over_trend(self, strategy):
        """RSI checked before momentum in resolution cascade."""
        market = MockMarket(rsi=25.0, trend_strength=-0.8)
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.LONG
        assert source == SignalSource.RSI


# ═══ Position Sizing ════════════════════════════════════════════

class TestPositionSizing:
    def test_base_size_is_10pct_of_capital(self, strategy, account):
        size = strategy.calculate_position_size(account, SignalType.LONG)
        assert abs(size - 1_000.0) < 1.0  # 10% of $10K

    def test_no_size_on_no_signal(self, strategy, account):
        size = strategy.calculate_position_size(account, SignalType.NONE)
        assert size == 0.0

    def test_no_size_on_breached_account(self, strategy, account):
        account.phase = AccountPhase.BREACHED
        size = strategy.calculate_position_size(account, SignalType.LONG)
        assert size == 0.0

    def test_no_size_on_paused_account(self, strategy, account):
        account.phase = AccountPhase.PAUSED
        size = strategy.calculate_position_size(account, SignalType.LONG)
        assert size == 0.0

    def test_bias_scales_size(self, strategy, account):
        strategy._permission_bias = 1.5
        size = strategy.calculate_position_size(account, SignalType.LONG)
        assert abs(size - 1_500.0) < 1.0  # 10% × 1.5 bias

    def test_leverage_cap_at_2x(self, strategy, account):
        """Even with high bias, can't exceed 2x capital."""
        strategy._permission_bias = 50.0  # Extreme bias
        size = strategy.calculate_position_size(account, SignalType.LONG)
        assert size <= account.current_capital * strategy.config.max_leverage

    def test_zero_bias_blocks_trading(self, strategy, account):
        strategy._permission_bias = 0.0
        size = strategy.calculate_position_size(account, SignalType.LONG)
        assert size == 0.0

    def test_scaled_account_larger_positions(self, strategy, account):
        """2x scaled account should have 2x position size."""
        base_size = strategy.calculate_position_size(account, SignalType.LONG)
        strategy.scale_account(account)
        scaled_size = strategy.calculate_position_size(account, SignalType.LONG)
        assert abs(scaled_size / base_size - 2.0) < 0.01


# ═══ Aggregate Signal ═══════════════════════════════════════════

class TestAggregateSignal:
    def test_long_signal_positive(self, strategy):
        market = MockMarket(rsi=25.0)
        signal = strategy.generate_signal(market)
        assert signal.signal > 0
        assert signal.sleeve_id == 3
        assert "LONG" in signal.rationale

    def test_short_signal_negative(self, strategy):
        market = MockMarket(rsi=75.0)
        signal = strategy.generate_signal(market)
        assert signal.signal < 0
        assert "SHORT" in signal.rationale

    def test_neutral_signal_zero(self, strategy):
        market = MockMarket(rsi=50.0, trend_strength=0.0)
        signal = strategy.generate_signal(market)
        assert signal.signal == 0.0

    def test_all_breached_returns_zero(self, strategy):
        for acct in strategy.accounts:
            acct.phase = AccountPhase.BREACHED
        market = MockMarket(rsi=25.0)
        signal = strategy.generate_signal(market)
        assert signal.signal == 0.0
        assert "No active accounts" in signal.rationale

    def test_signal_bounded(self, strategy):
        """Signal always in [-1, 1]."""
        for rsi in [10, 25, 50, 75, 90]:
            market = MockMarket(rsi=rsi)
            signal = strategy.generate_signal(market)
            assert -1.0 <= signal.signal <= 1.0


# ═══ Fill Recording ═════════════════════════════════════════════

class TestFillRecording:
    def test_winning_trade_updates(self, strategy):
        acct = strategy.accounts[0]
        strategy.record_fill(acct.account_id, pnl=500, is_win=True)
        assert acct.current_capital == 10_500
        assert acct.trade_count == 1
        assert acct.win_count == 1

    def test_losing_trade_updates(self, strategy):
        acct = strategy.accounts[0]
        strategy.record_fill(acct.account_id, pnl=-300, is_win=False)
        assert acct.current_capital == 9_700
        assert acct.trade_count == 1
        assert acct.win_count == 0

    def test_peak_updates_on_profit(self, strategy):
        acct = strategy.accounts[0]
        strategy.record_fill(acct.account_id, pnl=500, is_win=True)
        assert acct.peak_capital == 10_500

    def test_peak_stays_on_loss(self, strategy):
        acct = strategy.accounts[0]
        acct.peak_capital = 10_500  # Previous high
        strategy.record_fill(acct.account_id, pnl=-200, is_win=False)
        assert acct.peak_capital == 10_500  # Unchanged


# ═══ New Trading Day ════════════════════════════════════════════

class TestNewTradingDay:
    def test_resets_daily_pnl(self, strategy):
        strategy.accounts[0].daily_pnl = -500
        strategy.new_trading_day()
        assert strategy.accounts[0].daily_pnl == 0.0

    def test_increments_days_in_eval(self, strategy):
        strategy.accounts[0].days_in_eval = 5
        strategy.new_trading_day()
        assert strategy.accounts[0].days_in_eval == 6


# ═══ Quarterly Review ═══════════════════════════════════════════

class TestQuarterlyReview:
    def test_boost_on_70pct_win_rate(self, strategy):
        for acct in strategy.accounts:
            acct.trade_count = 10
            acct.win_count = 8  # 80% win rate
        result = strategy.quarterly_review()
        assert result["action"] == "boosted"
        # Check capital boosted by 50%
        assert strategy.accounts[0].current_capital == 15_000

    def test_no_boost_below_threshold(self, strategy):
        for acct in strategy.accounts:
            acct.trade_count = 10
            acct.win_count = 5  # 50% win rate
        result = strategy.quarterly_review()
        assert result["action"] == "none"
        assert strategy.accounts[0].current_capital == 10_000

    def test_no_boost_zero_trades(self, strategy):
        result = strategy.quarterly_review()
        assert result["action"] == "none"


# ═══ Pause All ══════════════════════════════════════════════════

class TestPauseAll:
    def test_pauses_active_accounts(self, strategy):
        strategy.pause_all_accounts("heartbeat timeout")
        paused = [a for a in strategy.accounts if a.phase == AccountPhase.PAUSED]
        assert len(paused) == 5

    def test_doesnt_pause_already_breached(self, strategy):
        strategy.accounts[0].phase = AccountPhase.BREACHED
        strategy.pause_all_accounts("test")
        assert strategy.accounts[0].phase == AccountPhase.BREACHED


# ═══ Full Lifecycle Scenarios ═══════════════════════════════════

class TestLifecycle:
    def test_eval_to_scaling_to_breach_to_reset(self, strategy):
        """Full lifecycle: eval → pass → scale → breach → reset."""
        acct = strategy.accounts[0]

        # Start in eval
        assert acct.phase == AccountPhase.EVAL

        # Simulate profits → pass eval
        acct.current_capital = 11_000
        acct.peak_capital = 11_000
        assert strategy.check_eval_pass(acct) is True
        strategy.scale_account(acct)
        assert acct.phase == AccountPhase.SCALING
        assert acct.current_capital == 20_000

        # Simulate drawdown → breach
        acct.peak_capital = 20_000
        acct.current_capital = 18_800  # 6% DD
        breached, reason = strategy.check_eval_breach(acct)
        assert breached is True
        strategy.reset_account(acct, reason)

        # Back to eval at seed
        assert acct.phase == AccountPhase.EVAL
        assert acct.current_capital == 10_000
        assert acct.scaling_multiplier == 1.0

    def test_multiple_scale_ups(self, strategy):
        """Account passes multiple times → exponential scaling."""
        acct = strategy.accounts[0]

        # First pass: 1x → 2x
        acct.current_capital = 11_000
        acct.peak_capital = 11_000
        strategy.scale_account(acct)
        assert acct.current_capital == 20_000

        # Second pass: 2x → 4x
        acct.current_capital = 22_000  # 10% profit on $20K
        acct.peak_capital = 22_000
        strategy.scale_account(acct)
        assert acct.current_capital == 40_000
        assert acct.scaling_multiplier == 4.0


# ═══ LLM Signal Injection ═══════════════════════════════════════

class TestLLMInjection:
    """External LLM signals (Grok Arena-style picks)."""

    def test_inject_valid_signal(self, strategy):
        sig = LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=0.85,
                        thesis="AI capex cycle", source_model="grok")
        strategy.inject_llm_signal(sig)
        assert len(strategy._llm_signals) == 1

    def test_reject_none_direction(self, strategy):
        sig = LLMSignal(ticker="MU", direction=SignalType.NONE, conviction=0.85)
        strategy.inject_llm_signal(sig)
        assert len(strategy._llm_signals) == 0

    def test_reject_invalid_conviction(self, strategy):
        sig = LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=1.5)
        strategy.inject_llm_signal(sig)
        assert len(strategy._llm_signals) == 0

    def test_get_best_by_conviction(self, strategy):
        strategy.inject_llm_signal(
            LLMSignal(ticker="CRM", direction=SignalType.LONG, conviction=0.6))
        strategy.inject_llm_signal(
            LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=0.9))
        strategy.inject_llm_signal(
            LLMSignal(ticker="NOW", direction=SignalType.LONG, conviction=0.75))
        best = strategy.get_best_llm_signal()
        assert best.ticker == "MU"
        assert best.conviction == 0.9

    def test_consume_removes_signal(self, strategy):
        strategy.inject_llm_signal(
            LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=0.85))
        strategy.inject_llm_signal(
            LLMSignal(ticker="CRM", direction=SignalType.LONG, conviction=0.6))
        strategy.consume_llm_signal("MU")
        assert len(strategy._llm_signals) == 1
        assert strategy._llm_signals[0].ticker == "CRM"


# ═══ Multi-Source Signal Resolution ═════════════════════════════

class TestMultiSourceResolution:
    """Signal priority: LLM high-conv > RSI > Momentum > LLM med-conv."""

    def test_high_conviction_llm_overrides_rsi(self, strategy):
        """LLM at 0.85 conviction overrides RSI signal."""
        strategy.inject_llm_signal(
            LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=0.85))
        market = MockMarket(rsi=75.0)  # RSI says SHORT
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.LONG
        assert source == SignalSource.LLM_CONVICTION

    def test_medium_conviction_yields_to_rsi(self, strategy):
        """LLM at 0.5 conviction loses to RSI extreme."""
        strategy.inject_llm_signal(
            LLMSignal(ticker="CRM", direction=SignalType.LONG, conviction=0.5))
        market = MockMarket(rsi=75.0)  # RSI says SHORT
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.SHORT
        assert source == SignalSource.RSI

    def test_medium_conviction_fallback_when_silent(self, strategy):
        """LLM at 0.5 fires when technicals are neutral."""
        strategy.inject_llm_signal(
            LLMSignal(ticker="FSLR", direction=SignalType.LONG, conviction=0.5))
        market = MockMarket(rsi=50.0, trend_strength=0.0)
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.LONG
        assert source == SignalSource.LLM_CONVICTION

    def test_low_conviction_ignored(self, strategy):
        """LLM at 0.3 conviction doesn't fire at all."""
        strategy.inject_llm_signal(
            LLMSignal(ticker="X", direction=SignalType.LONG, conviction=0.3))
        market = MockMarket(rsi=50.0, trend_strength=0.0)
        signal, _ = strategy.generate_trade_signal(market)
        assert signal == SignalType.NONE

    def test_no_llm_signals_uses_technicals(self, strategy):
        """Without LLM signals, falls back to RSI/momentum as before."""
        market = MockMarket(rsi=25.0)
        signal, source = strategy.generate_trade_signal(market)
        assert signal == SignalType.LONG
        assert source == SignalSource.RSI

    def test_llm_signal_appears_in_aggregate(self, strategy):
        """LLM signal flows through to generate_signal rationale."""
        strategy.inject_llm_signal(
            LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=0.85,
                      source_model="grok"))
        market = MockMarket(rsi=50.0, trend_strength=0.0)
        signal = strategy.generate_signal(market)
        assert signal.signal > 0
        assert "llm" in signal.rationale
        assert "grok" in signal.rationale

    def test_llm_ticker_added_to_instruments(self, strategy):
        """LLM-sourced signal includes the ticker in instruments."""
        strategy.inject_llm_signal(
            LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=0.85))
        market = MockMarket(rsi=50.0, trend_strength=0.0)
        signal = strategy.generate_signal(market)
        assert "MU" in signal.instruments


# ═══ Multi-Source Confidence ════════════════════════════════════

class TestMultiSourceConfidence:
    def test_agreement_boosts_confidence(self, strategy):
        """RSI + LLM agree → higher confidence than RSI alone."""
        # RSI-only signal
        market_rsi = MockMarket(rsi=25.0, trend_strength=0.0)
        sig_rsi = strategy.generate_signal(market_rsi)

        # Now add agreeing LLM signal
        strategy.inject_llm_signal(
            LLMSignal(ticker="ES", direction=SignalType.LONG, conviction=0.8))
        sig_both = strategy.generate_signal(market_rsi)

        assert sig_both.confidence >= sig_rsi.confidence

    def test_llm_confidence_maps_from_conviction(self, strategy):
        """Higher LLM conviction → higher base confidence."""
        strategy.inject_llm_signal(
            LLMSignal(ticker="MU", direction=SignalType.LONG, conviction=0.95))
        market = MockMarket(rsi=50.0, trend_strength=0.0)
        sig = strategy.generate_signal(market)
        # 0.60 + (0.95 * 0.30) = 0.885 base
        assert sig.confidence > 0.80


# ═══ Source Performance Tracking ════════════════════════════════

class TestSourceTracking:
    def test_record_fill_with_source(self, strategy):
        acct = strategy.accounts[0]
        strategy.record_fill(acct.account_id, pnl=500, is_win=True,
                            source=SignalSource.LLM_CONVICTION)
        assert acct.source_stats["llm"]["trades"] == 1
        assert acct.source_stats["llm"]["wins"] == 1
        assert acct.source_stats["llm"]["pnl"] == 500.0

    def test_record_fill_rsi_source(self, strategy):
        acct = strategy.accounts[0]
        strategy.record_fill(acct.account_id, pnl=-200, is_win=False,
                            source=SignalSource.RSI)
        assert acct.source_stats["rsi"]["trades"] == 1
        assert acct.source_stats["rsi"]["wins"] == 0
        assert acct.source_stats["rsi"]["pnl"] == -200.0

    def test_record_fill_without_source_still_works(self, strategy):
        """Backwards compatible — source=None doesn't crash."""
        acct = strategy.accounts[0]
        strategy.record_fill(acct.account_id, pnl=500, is_win=True)
        assert acct.trade_count == 1  # Still tracked

    def test_source_scorecard(self, strategy):
        acct = strategy.accounts[0]
        # 3 LLM trades: 2 wins, 1 loss
        strategy.record_fill(acct.account_id, 500, True, SignalSource.LLM_CONVICTION)
        strategy.record_fill(acct.account_id, 300, True, SignalSource.LLM_CONVICTION)
        strategy.record_fill(acct.account_id, -200, False, SignalSource.LLM_CONVICTION)
        # 2 RSI trades: 1 win, 1 loss
        strategy.record_fill(acct.account_id, 100, True, SignalSource.RSI)
        strategy.record_fill(acct.account_id, -150, False, SignalSource.RSI)

        card = strategy.get_source_scorecard()
        assert card["llm"]["trades"] == 3
        assert card["llm"]["wins"] == 2
        assert abs(card["llm"]["win_rate"] - 0.667) < 0.01
        assert card["llm"]["total_pnl"] == 600.0
        assert card["rsi"]["trades"] == 2
        assert card["rsi"]["total_pnl"] == -50.0

    def test_scorecard_in_status(self, strategy):
        status = strategy.get_status()
        assert "signal_sources" in status
        assert "source_scorecard" in status["signal_sources"]
        assert "llm_signals_pending" in status["signal_sources"]
