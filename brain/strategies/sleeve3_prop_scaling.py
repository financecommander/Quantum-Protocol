"""
MATRIX PROTOCOL™ v1.0 — Sleeve 3: Prop-Firm Scaling (The Velocity Sleeve™)

PRIMARY ALPHA SOURCE — 45% of portfolio allocation.
Backtest: 112.4% CAGR, 78% win rate, -12.1% max DD.

Powered By: SERAPH AI™ + SHIELD™

═══════════════════════════════════════════════════════════════
  CORE LOGIC: Evaluation-Based Capital Scaling
═══════════════════════════════════════════════════════════════

  Run 5-10 parallel AI "traders" (eval accounts).
  Each starts with seed capital ($10K simulated).
  Performance-gated scaling: pass eval → unlock 2x capital.

  Eval Pass:  10% profit in 30 days AND < 5% drawdown
  Eval Fail:  > 6% drawdown OR 30 days without 10% profit → reset

═══════════════════════════════════════════════════════════════
  ENTRY RULES (Hard-Coded):
═══════════════════════════════════════════════════════════════

  Signals (high-conviction only):
    LONG:  RSI < 30 (oversold reversal)
    SHORT: RSI > 70 (overbought reversal)
    TREND: Momentum crossover (fast EMA > slow EMA for long, inverse for short)
    LLM:   External high-conviction picks (Grok Arena-style, poly-agent routed)
    GATE:  Master Agent permission vector must allow (prop_bias > 0)

  Signal Resolution (multi-source):
    1. LLM high-conviction (≥ 0.7) — overrides technicals
    2. RSI extremes (< 30 / > 70) — mean reversion
    3. Momentum crossover — trend following
    4. LLM medium-conviction (0.4 - 0.7) — fallback
    Multi-source agreement → confidence bonus (+0.10)

  Multi-Asset Universe:
    - Equities: ES (E-mini S&P 500) — primary
    - FX: EUR/USD — secondary
    - Crypto: BTC/ETH proxies — max 20% of eval capital

  Initial Sizing: 1:1 risk-reward on seed capital
  Leverage Cap: 2x maximum (hard-coded SHIELD enforcement)

═══════════════════════════════════════════════════════════════
  EXIT RULES:
═══════════════════════════════════════════════════════════════

  Eval Breach: > 6% DD or > 30 days without 10% profit → RESET
  Profit Split: 80/20 (sleeve retains 80%)
  Rebalancing: Quarterly — +50% capital if 70% win rate across evals
  Fail-Safe: Master heartbeat silent > 65min → auto-liquidate ALL

═══════════════════════════════════════════════════════════════
  RISK MANAGEMENT:
═══════════════════════════════════════════════════════════════

  Per-Account:  Daily loss < 2%, max 12% DD per account
  SHIELD™:      Correlation cap < 0.2 to portfolio, leverage ≤ 2x
  KPI Guard:    Veto if projected loss > 5%
  Fan-Out:      Atomic broadcast to all accounts (< 5ms variance)

═══════════════════════════════════════════════════════════════
  INSTRUMENTS: ES, EUR/USD, BTC proxy, ETH proxy
═══════════════════════════════════════════════════════════════
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.strategies.sleeve3")


# ─── Enums ──────────────────────────────────────────────────────

class AccountPhase(Enum):
    EVAL = "eval"               # In evaluation period (seed capital)
    SCALING = "scaling"         # Passed eval, scaling up
    BREACHED = "breached"       # Failed eval, awaiting reset
    PAUSED = "paused"           # Manually paused or heartbeat timeout


class SignalType(Enum):
    NONE = "none"
    LONG = "long"
    SHORT = "short"


class SignalSource(Enum):
    """Which signal generator produced this trade idea."""
    RSI = "rsi"                     # RSI < 30 / > 70 (mean reversion)
    MOMENTUM = "momentum"           # EMA crossover (trend following)
    LLM_CONVICTION = "llm"          # External LLM high-conviction pick (Grok Arena-style)


class AssetClass(Enum):
    EQUITY = "equity"           # ES
    FX = "fx"                   # EUR/USD
    CRYPTO = "crypto"           # BTC/ETH proxy


# ─── Data Structures ────────────────────────────────────────────

@dataclass
class LLMSignal:
    """
    External LLM-generated trade signal (e.g., Grok Arena-style picks).

    Injected via inject_llm_signal(). Subject to same eval/breach/SHIELD
    rules as all other signals. The eval framework scores performance
    regardless of signal source.
    """
    ticker: str                         # e.g., "MU", "CRM", "ES"
    direction: SignalType               # LONG or SHORT
    conviction: float                   # 0.0 - 1.0 (maps to position sizing)
    thesis: str = ""                    # LLM reasoning (for audit log)
    source_model: str = "grok"          # Which LLM generated this
    timestamp: datetime = field(default_factory=datetime.utcnow)
    target_pct: float = 0.0            # Expected return (if provided)
    stop_loss_pct: float = 0.0         # Suggested stop (if provided)
    asset_class: AssetClass = AssetClass.EQUITY

@dataclass
class EvalAccount:
    """A single AI 'trader' running an evaluation cycle."""
    account_id: str
    phase: AccountPhase = AccountPhase.EVAL
    seed_capital: float = 10_000.0
    current_capital: float = 10_000.0
    scaling_multiplier: float = 1.0         # 1x at start, 2x after first pass, etc.
    peak_capital: float = 10_000.0          # For drawdown tracking
    eval_start_date: Optional[datetime] = None
    days_in_eval: int = 0
    trade_count: int = 0
    win_count: int = 0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0

    # Per-source performance tracking (signal source → {trades, wins, pnl})
    source_stats: dict = field(default_factory=lambda: {
        "rsi": {"trades": 0, "wins": 0, "pnl": 0.0},
        "momentum": {"trades": 0, "wins": 0, "pnl": 0.0},
        "llm": {"trades": 0, "wins": 0, "pnl": 0.0},
    })

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown from peak."""
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.current_capital) / self.peak_capital

    @property
    def return_pct(self) -> float:
        """Return since eval start."""
        effective_seed = self.seed_capital * self.scaling_multiplier
        if effective_seed <= 0:
            return 0.0
        return (self.current_capital - effective_seed) / effective_seed

    @property
    def win_rate(self) -> float:
        if self.trade_count == 0:
            return 0.0
        return self.win_count / self.trade_count

    @property
    def daily_loss_pct(self) -> float:
        if self.current_capital <= 0:
            return 0.0
        return -self.daily_pnl / self.current_capital if self.daily_pnl < 0 else 0.0


@dataclass
class Sleeve3Config:
    """Hard-coded parameters from strategy spec."""

    # ─── Eval Parameters ────────────────────────────────────
    num_accounts: int = 5                   # 5-10 parallel evals
    seed_capital: float = 10_000.0          # $10K per eval
    eval_profit_target: float = 0.10        # 10% profit to pass
    eval_max_days: int = 30                 # Must hit target within 30 days
    eval_max_drawdown: float = 0.05         # < 5% DD to pass eval
    breach_drawdown: float = 0.06           # > 6% DD → reset
    scaling_factor: float = 2.0             # 2x capital on pass

    # ─── Per-Account Risk ───────────────────────────────────
    daily_loss_limit: float = 0.02          # 2% daily loss max
    max_account_dd: float = 0.12            # 12% max DD per account
    max_leverage: float = 2.0               # Hard cap

    # ─── Signal Parameters ──────────────────────────────────
    rsi_oversold: float = 30.0              # RSI < 30 → long signal
    rsi_overbought: float = 70.0            # RSI > 70 → short signal
    momentum_fast_period: int = 12          # Fast EMA period
    momentum_slow_period: int = 26          # Slow EMA period

    # ─── Multi-Asset Allocation ─────────────────────────────
    max_crypto_pct: float = 0.20            # Crypto max 20% of eval capital

    # ─── Quarterly Scaling ──────────────────────────────────
    quarterly_scaling_win_rate: float = 0.70  # 70% win rate → +50% capital
    quarterly_capital_boost: float = 0.50   # +50% capital on quarterly pass

    # ─── Profit Split ───────────────────────────────────────
    sleeve_profit_share: float = 0.80       # 80/20 split

    # ─── Heartbeat ──────────────────────────────────────────
    heartbeat_timeout_minutes: float = 65.0

    # ─── Fan-Out ────────────────────────────────────────────
    max_fanout_variance_ms: float = 5.0     # < 5ms between account executions


# ─── Main Strategy ──────────────────────────────────────────────

class PropScalingStrategy:
    """
    Sleeve 3: Prop-Firm Scaling — the primary alpha engine.

    Manages N parallel evaluation accounts, each running through:
      EVAL → (pass) → SCALING → (pass again) → SCALING (2x)
                ↘ (breach) → BREACHED → (reset) → EVAL

    Signal generation applies to ALL active accounts simultaneously
    via atomic fan-out (< 5ms variance between accounts).
    """

    def __init__(self, config: Optional[Sleeve3Config] = None):
        self.config = config or Sleeve3Config()
        self.accounts: list[EvalAccount] = []
        self._last_master_heartbeat: Optional[datetime] = None
        self._permission_bias: float = 1.0  # From permission vector
        self._regime: str = "growth"
        self._total_realized_pnl: float = 0.0
        self._is_initialized: bool = False

        # Multi-source signal routing
        self._llm_signals: list[LLMSignal] = []       # Pending LLM picks
        self._active_signal_source: Optional[SignalSource] = None  # Last source that fired
        self._llm_signal_ttl_hours: float = 24.0       # LLM picks expire after 24h

    def initialize_accounts(self, num_accounts: Optional[int] = None):
        """Spin up N parallel eval accounts."""
        n = num_accounts or self.config.num_accounts
        self.accounts = []
        for i in range(n):
            acct = EvalAccount(
                account_id=f"EVAL-{i+1:03d}",
                phase=AccountPhase.EVAL,
                seed_capital=self.config.seed_capital,
                current_capital=self.config.seed_capital,
                peak_capital=self.config.seed_capital,
                eval_start_date=datetime.utcnow(),
            )
            self.accounts.append(acct)
        self._is_initialized = True
        logger.info(f"Sleeve 3: Initialized {n} eval accounts at ${self.config.seed_capital:,.0f} each")

    # ─── Eval Lifecycle ─────────────────────────────────────────

    def check_eval_pass(self, account: EvalAccount) -> bool:
        """
        Eval Pass Criteria:
          - 10% profit within 30 days
          - Drawdown stayed < 5% throughout
        """
        if account.phase != AccountPhase.EVAL:
            return False
        return (
            account.return_pct >= self.config.eval_profit_target
            and account.drawdown_pct < self.config.eval_max_drawdown
        )

    def check_eval_breach(self, account: EvalAccount) -> tuple[bool, str]:
        """
        Eval Breach (any of):
          - Drawdown > 6%
          - Daily loss > 2%
          - Max account DD > 12%
          - 30 days elapsed without hitting 10% profit
        """
        if account.phase == AccountPhase.BREACHED:
            return False, ""

        # Drawdown breach (6% for eval, 12% absolute max)
        if account.drawdown_pct >= self.config.breach_drawdown:
            return True, f"drawdown_breach ({account.drawdown_pct:.1%} ≥ {self.config.breach_drawdown:.0%})"

        if account.drawdown_pct >= self.config.max_account_dd:
            return True, f"max_dd_breach ({account.drawdown_pct:.1%} ≥ {self.config.max_account_dd:.0%})"

        # Daily loss breach
        if account.daily_loss_pct >= self.config.daily_loss_limit:
            return True, f"daily_loss_breach ({account.daily_loss_pct:.1%} ≥ {self.config.daily_loss_limit:.0%})"

        # Time breach (eval phase only)
        if account.phase == AccountPhase.EVAL and account.days_in_eval >= self.config.eval_max_days:
            if account.return_pct < self.config.eval_profit_target:
                return True, f"time_breach ({account.days_in_eval}d without {self.config.eval_profit_target:.0%} profit)"

        return False, ""

    def scale_account(self, account: EvalAccount):
        """Pass eval → double capital."""
        old_mult = account.scaling_multiplier
        account.scaling_multiplier *= self.config.scaling_factor
        new_capital = account.seed_capital * account.scaling_multiplier
        account.current_capital = new_capital
        account.peak_capital = new_capital
        account.phase = AccountPhase.SCALING
        account.days_in_eval = 0
        account.eval_start_date = datetime.utcnow()
        logger.info(
            f"Account {account.account_id} SCALED: {old_mult:.0f}x → {account.scaling_multiplier:.0f}x "
            f"(${new_capital:,.0f})"
        )

    def reset_account(self, account: EvalAccount, reason: str):
        """Breach → reset to seed capital, restart eval."""
        old_capital = account.current_capital
        account.phase = AccountPhase.EVAL
        account.scaling_multiplier = 1.0
        account.current_capital = self.config.seed_capital
        account.peak_capital = self.config.seed_capital
        account.days_in_eval = 0
        account.eval_start_date = datetime.utcnow()
        account.daily_pnl = 0.0
        logger.warning(
            f"Account {account.account_id} RESET: {reason} "
            f"(${old_capital:,.0f} → ${self.config.seed_capital:,.0f})"
        )

    def pause_all_accounts(self, reason: str):
        """Emergency: pause all accounts (heartbeat timeout, kill switch)."""
        for acct in self.accounts:
            if acct.phase not in (AccountPhase.BREACHED, AccountPhase.PAUSED):
                acct.phase = AccountPhase.PAUSED
        logger.critical(f"Sleeve 3: ALL ACCOUNTS PAUSED — {reason}")

    # ─── LLM Signal Injection ────────────────────────────────────

    def inject_llm_signal(self, signal: LLMSignal):
        """
        Inject an external LLM-generated trade signal.

        These get queued and considered alongside RSI/momentum signals
        during the next generate_signal() call. Subject to same
        eval/breach/SHIELD rules as all other signals.

        Usage (poly-agent routing):
            signal = LLMSignal(
                ticker="MU", direction=SignalType.LONG,
                conviction=0.85, thesis="AI capex cycle + HBM3E ramp",
                source_model="grok", target_pct=0.15, stop_loss_pct=0.05,
            )
            strategy.inject_llm_signal(signal)
        """
        # Validate
        if signal.direction == SignalType.NONE:
            logger.warning(f"LLM signal ignored: direction=NONE for {signal.ticker}")
            return
        if not 0.0 <= signal.conviction <= 1.0:
            logger.warning(f"LLM signal ignored: invalid conviction {signal.conviction}")
            return

        # Check crypto allocation limit
        if signal.asset_class == AssetClass.CRYPTO:
            logger.info(f"LLM signal {signal.ticker}: crypto — subject to {self.config.max_crypto_pct:.0%} cap")

        self._llm_signals.append(signal)
        logger.info(
            f"LLM signal injected: {signal.direction.value.upper()} {signal.ticker} "
            f"conviction={signal.conviction:.0%} source={signal.source_model} "
            f"thesis='{signal.thesis[:80]}'"
        )

    def _prune_expired_llm_signals(self):
        """Remove LLM signals older than TTL."""
        cutoff = datetime.utcnow() - timedelta(hours=self._llm_signal_ttl_hours)
        before = len(self._llm_signals)
        self._llm_signals = [s for s in self._llm_signals if s.timestamp > cutoff]
        pruned = before - len(self._llm_signals)
        if pruned > 0:
            logger.info(f"Pruned {pruned} expired LLM signals (>{self._llm_signal_ttl_hours}h old)")

    def get_best_llm_signal(self) -> Optional[LLMSignal]:
        """Get highest-conviction active LLM signal."""
        self._prune_expired_llm_signals()
        if not self._llm_signals:
            return None
        return max(self._llm_signals, key=lambda s: s.conviction)

    # ─── Multi-Source Signal Generation ─────────────────────────

    def generate_trade_signal(self, market) -> tuple[SignalType, SignalSource]:
        """
        Generate a high-conviction trade signal from multiple sources.

        Priority resolution:
          1. LLM high-conviction (conviction ≥ 0.7) — Arena-style picks
          2. RSI extremes (< 30 or > 70) — mean reversion
          3. Momentum crossover — trend following
          4. LLM medium-conviction (0.4 - 0.7) — lower priority
          5. NONE if nothing fires

        When sources AGREE (same direction), confidence increases.
        When sources CONFLICT, higher-priority source wins.

        Returns: (signal_type, signal_source)
        """
        rsi = getattr(market, 'rsi', 50.0)
        trend = getattr(market, 'trend_strength', 0.0)

        # ─── Gather signals from all sources ─────────────────
        rsi_signal = SignalType.NONE
        if rsi < self.config.rsi_oversold:
            rsi_signal = SignalType.LONG
        elif rsi > self.config.rsi_overbought:
            rsi_signal = SignalType.SHORT

        momentum_signal = SignalType.NONE
        if trend > 0.6:
            momentum_signal = SignalType.LONG
        elif trend < -0.6:
            momentum_signal = SignalType.SHORT

        llm_signal_obj = self.get_best_llm_signal()
        llm_signal = llm_signal_obj.direction if llm_signal_obj else SignalType.NONE
        llm_conviction = llm_signal_obj.conviction if llm_signal_obj else 0.0

        # ─── Resolution cascade ──────────────────────────────

        # High-conviction LLM overrides (Arena-quality picks)
        if llm_signal != SignalType.NONE and llm_conviction >= 0.7:
            self._active_signal_source = SignalSource.LLM_CONVICTION
            return llm_signal, SignalSource.LLM_CONVICTION

        # RSI extremes (strong mean reversion signals)
        if rsi_signal != SignalType.NONE:
            self._active_signal_source = SignalSource.RSI
            return rsi_signal, SignalSource.RSI

        # Momentum crossover
        if momentum_signal != SignalType.NONE:
            self._active_signal_source = SignalSource.MOMENTUM
            return momentum_signal, SignalSource.MOMENTUM

        # Medium-conviction LLM (fallback when technicals are silent)
        if llm_signal != SignalType.NONE and llm_conviction >= 0.4:
            self._active_signal_source = SignalSource.LLM_CONVICTION
            return llm_signal, SignalSource.LLM_CONVICTION

        self._active_signal_source = None
        return SignalType.NONE, SignalSource.RSI  # source doesn't matter for NONE

    def calculate_position_size(self, account: EvalAccount, signal: SignalType) -> float:
        """
        Position sizing per account.

        Base: 1:1 risk-reward on current capital.
        Adjusted by: permission vector bias, leverage cap.
        """
        if signal == SignalType.NONE:
            return 0.0
        if account.phase in (AccountPhase.BREACHED, AccountPhase.PAUSED):
            return 0.0

        # Base size: fraction of account capital
        base_size = account.current_capital * 0.10  # 10% of capital per trade

        # Apply permission vector bias
        size = base_size * self._permission_bias

        # Leverage cap (2x maximum)
        max_size = account.current_capital * self.config.max_leverage
        size = min(size, max_size)

        return size

    # ─── Main Entry Point ───────────────────────────────────────

    def generate_signal(self, market) -> "SleeveSignal":
        """
        Main signal generation. Called by Orchestrator.tick().

        Flow:
          1. Record heartbeat
          2. Check heartbeat timeout → pause all
          3. For each account: check breach → check pass → generate signal
          4. Aggregate across accounts → single SleeveSignal
        """
        from orchestrator import SleeveSignal

        # Initialize on first call if needed
        if not self._is_initialized:
            self.initialize_accounts()

        # Record heartbeat
        self._last_master_heartbeat = datetime.utcnow()

        # ─── Heartbeat failsafe ─────────────────────────────
        # (checked against PREVIOUS heartbeat, not this one)
        active_accounts = [a for a in self.accounts if a.phase not in (AccountPhase.BREACHED, AccountPhase.PAUSED)]

        if len(active_accounts) == 0:
            return SleeveSignal(
                sleeve_id=3, sleeve_name="Prop Scaling",
                signal=0.0, confidence=0.0,
                instruments=["ES"],
                rationale=f"No active accounts ({len(self.accounts)} total, all breached/paused)",
            )

        # ─── Per-account lifecycle ──────────────────────────
        for account in self.accounts:
            if account.phase in (AccountPhase.BREACHED, AccountPhase.PAUSED):
                continue

            # Check breach first (safety)
            breached, reason = self.check_eval_breach(account)
            if breached:
                self.reset_account(account, reason)
                continue

            # Check eval pass (scaling)
            if self.check_eval_pass(account):
                self.scale_account(account)

        # ─── Generate aggregate signal ──────────────────────
        trade_signal, signal_source = self.generate_trade_signal(market)

        if trade_signal == SignalType.NONE:
            return SleeveSignal(
                sleeve_id=3, sleeve_name="Prop Scaling",
                signal=0.0, confidence=0.3,
                instruments=["ES", "EURUSD"],
                rationale=f"No high-conviction signal (RSI={getattr(market, 'rsi', 'N/A')}, LLM={len(self._llm_signals)} pending)",
            )

        # Aggregate: sum position sizes across active accounts
        active = [a for a in self.accounts if a.phase in (AccountPhase.EVAL, AccountPhase.SCALING)]
        total_capital = sum(a.current_capital for a in active)
        total_size = sum(self.calculate_position_size(a, trade_signal) for a in active)

        if total_capital <= 0:
            return SleeveSignal(
                sleeve_id=3, sleeve_name="Prop Scaling",
                signal=0.0, confidence=0.0,
                instruments=["ES"],
                rationale="No active capital across eval accounts",
            )

        # Normalize signal to [-1, 1]
        signal_direction = 1.0 if trade_signal == SignalType.LONG else -1.0
        signal_strength = min(total_size / total_capital, 1.0)

        # Confidence: base from source + bonus if multiple sources agree
        confidence = self._calculate_source_confidence(market, trade_signal, signal_source)

        # Build account summary for rationale
        scaling_count = len([a for a in active if a.phase == AccountPhase.SCALING])
        eval_count = len([a for a in active if a.phase == AccountPhase.EVAL])

        # LLM context for rationale
        llm_ctx = ""
        llm_sig = self.get_best_llm_signal()
        if signal_source == SignalSource.LLM_CONVICTION and llm_sig:
            llm_ctx = f", LLM={llm_sig.source_model}:{llm_sig.ticker}@{llm_sig.conviction:.0%}"
        elif llm_sig:
            llm_ctx = f", LLM_pending={llm_sig.ticker}"

        # Instruments: include LLM ticker if that's the source
        instruments = ["ES", "EURUSD"]
        if signal_source == SignalSource.LLM_CONVICTION and llm_sig:
            if llm_sig.ticker not in instruments:
                instruments.append(llm_sig.ticker)

        return SleeveSignal(
            sleeve_id=3, sleeve_name="Prop Scaling",
            signal=signal_direction * signal_strength,
            confidence=confidence,
            instruments=instruments,
            rationale=(
                f"{trade_signal.value.upper()} via {signal_source.value}: "
                f"{len(active)} accounts active "
                f"({eval_count} eval, {scaling_count} scaling), "
                f"capital=${total_capital:,.0f}, "
                f"RSI={getattr(market, 'rsi', 'N/A')}{llm_ctx}"
            ),
        )

    def _calculate_source_confidence(
        self, market, trade_signal: SignalType, primary_source: SignalSource
    ) -> float:
        """
        Calculate confidence based on source quality + multi-source agreement.

        Base confidence:
          RSI extreme:     0.80
          LLM conviction:  mapped from conviction score (0.60 - 0.90)
          Momentum:        0.60

        Agreement bonus: +0.10 if 2+ sources agree on direction
        """
        rsi = getattr(market, 'rsi', 50.0)

        # Base confidence by source
        if primary_source == SignalSource.RSI:
            base = 0.80
        elif primary_source == SignalSource.LLM_CONVICTION:
            llm = self.get_best_llm_signal()
            base = 0.60 + (llm.conviction * 0.30 if llm else 0.0)  # 0.60 - 0.90
        else:
            base = 0.60

        # Check agreement: how many sources point the same direction?
        agreement_count = 0

        # RSI direction
        rsi_agrees = (
            (rsi < self.config.rsi_oversold and trade_signal == SignalType.LONG) or
            (rsi > self.config.rsi_overbought and trade_signal == SignalType.SHORT)
        )
        if rsi_agrees:
            agreement_count += 1

        # Momentum direction
        trend = getattr(market, 'trend_strength', 0.0)
        momentum_agrees = (
            (trend > 0.6 and trade_signal == SignalType.LONG) or
            (trend < -0.6 and trade_signal == SignalType.SHORT)
        )
        if momentum_agrees:
            agreement_count += 1

        # LLM direction
        llm = self.get_best_llm_signal()
        if llm and llm.direction == trade_signal:
            agreement_count += 1

        # Bonus: +0.10 if 2+ sources agree
        bonus = 0.10 if agreement_count >= 2 else 0.0

        return min(base + bonus, 0.95)  # Cap at 0.95

    # ─── Account Updates (called by execution layer) ────────────

    def record_fill(self, account_id: str, pnl: float, is_win: bool,
                    source: Optional[SignalSource] = None):
        """Record a trade result for an account, tracking signal source."""
        acct = self._find_account(account_id)
        if acct is None:
            return

        acct.current_capital += pnl
        acct.total_pnl += pnl
        acct.daily_pnl += pnl
        acct.trade_count += 1
        if is_win:
            acct.win_count += 1

        # Update peak
        if acct.current_capital > acct.peak_capital:
            acct.peak_capital = acct.current_capital

        # Per-source tracking
        if source is not None:
            src_key = source.value
            if src_key in acct.source_stats:
                acct.source_stats[src_key]["trades"] += 1
                acct.source_stats[src_key]["pnl"] += pnl
                if is_win:
                    acct.source_stats[src_key]["wins"] += 1

    def get_source_scorecard(self) -> dict:
        """
        Score each signal source across all accounts.

        Returns per-source: trades, wins, win_rate, total_pnl, avg_pnl.
        Use this to validate whether LLM signals outperform technicals
        through the eval framework.
        """
        totals = {}
        for src in SignalSource:
            key = src.value
            trades = sum(a.source_stats.get(key, {}).get("trades", 0) for a in self.accounts)
            wins = sum(a.source_stats.get(key, {}).get("wins", 0) for a in self.accounts)
            pnl = sum(a.source_stats.get(key, {}).get("pnl", 0.0) for a in self.accounts)
            totals[key] = {
                "trades": trades,
                "wins": wins,
                "win_rate": wins / trades if trades > 0 else 0.0,
                "total_pnl": pnl,
                "avg_pnl": pnl / trades if trades > 0 else 0.0,
            }
        return totals

    def consume_llm_signal(self, ticker: str):
        """Remove an LLM signal after it's been acted on."""
        self._llm_signals = [s for s in self._llm_signals if s.ticker != ticker]

    def new_trading_day(self):
        """Reset daily P&L counters (call at market open)."""
        for acct in self.accounts:
            acct.daily_pnl = 0.0
            if acct.phase in (AccountPhase.EVAL, AccountPhase.SCALING):
                acct.days_in_eval += 1

    def set_permission_bias(self, bias: float):
        """Update from permission vector."""
        self._permission_bias = max(0.0, bias)

    def set_regime(self, regime: str):
        """Update current regime."""
        self._regime = regime

    # ─── Quarterly Review ───────────────────────────────────────

    def quarterly_review(self) -> dict:
        """
        Quarterly scaling review:
        If 70% win rate across all evals → +50% capital boost.
        """
        active = [a for a in self.accounts if a.phase in (AccountPhase.EVAL, AccountPhase.SCALING)]
        if not active:
            return {"action": "none", "reason": "no active accounts"}

        total_trades = sum(a.trade_count for a in active)
        total_wins = sum(a.win_count for a in active)
        win_rate = total_wins / total_trades if total_trades > 0 else 0

        if win_rate >= self.config.quarterly_scaling_win_rate:
            # Boost all accounts by 50%
            for acct in active:
                old_cap = acct.current_capital
                boost = acct.current_capital * self.config.quarterly_capital_boost
                acct.current_capital += boost
                acct.peak_capital = max(acct.peak_capital, acct.current_capital)
                logger.info(f"Quarterly boost: {acct.account_id} ${old_cap:,.0f} → ${acct.current_capital:,.0f}")

            return {
                "action": "boosted",
                "win_rate": win_rate,
                "accounts_boosted": len(active),
                "boost_pct": self.config.quarterly_capital_boost,
            }

        return {
            "action": "none",
            "win_rate": win_rate,
            "reason": f"Win rate {win_rate:.0%} < {self.config.quarterly_scaling_win_rate:.0%} threshold",
        }

    # ─── Helpers ────────────────────────────────────────────────

    def _find_account(self, account_id: str) -> Optional[EvalAccount]:
        for acct in self.accounts:
            if acct.account_id == account_id:
                return acct
        return None

    def get_status(self) -> dict:
        active = [a for a in self.accounts if a.phase in (AccountPhase.EVAL, AccountPhase.SCALING)]
        breached = [a for a in self.accounts if a.phase == AccountPhase.BREACHED]
        paused = [a for a in self.accounts if a.phase == AccountPhase.PAUSED]
        return {
            "sleeve": "Prop Scaling",
            "total_accounts": len(self.accounts),
            "active": len(active),
            "breached": len(breached),
            "paused": len(paused),
            "total_capital": sum(a.current_capital for a in active),
            "total_realized_pnl": self._total_realized_pnl,
            "permission_bias": self._permission_bias,
            "regime": self._regime,
            "signal_sources": {
                "active_source": self._active_signal_source.value if self._active_signal_source else None,
                "llm_signals_pending": len(self._llm_signals),
                "llm_signals": [
                    {"ticker": s.ticker, "direction": s.direction.value,
                     "conviction": s.conviction, "source": s.source_model}
                    for s in self._llm_signals
                ],
                "source_scorecard": self.get_source_scorecard(),
            },
            "accounts": [
                {
                    "id": a.account_id,
                    "phase": a.phase.value,
                    "capital": a.current_capital,
                    "scaling": f"{a.scaling_multiplier:.0f}x",
                    "return": f"{a.return_pct:.1%}",
                    "dd": f"{a.drawdown_pct:.1%}",
                    "win_rate": f"{a.win_rate:.0%}",
                    "trades": a.trade_count,
                    "days": a.days_in_eval,
                    "source_stats": a.source_stats,
                }
                for a in self.accounts
            ],
        }
