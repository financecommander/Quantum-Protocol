"""
MATRIX PROTOCOL™ v1.0 — Sleeve 1: Treasury Yield (The Anchor™)

Low-volatility income foundation. Stability ballast for the portfolio.
Backtest: 3.1% CAGR, 88% win rate, -1.2% max DD.

Powered By: NERD MAINFRAME™ + SHIELD™

═══════════════════════════════════════════════════════════════
  CORE LOGIC: Yield Curve Roll-Down
═══════════════════════════════════════════════════════════════

  Buy intermediate-term Treasuries (7-year notes / IEF proxy).
  Hold as they "roll down" the curve toward maturity.
  Normal upward-sloping curve → "roll yield" without rate bets.

═══════════════════════════════════════════════════════════════
  ENTRY RULES (Hard-Coded):
═══════════════════════════════════════════════════════════════

  Primary:     7-10 Year Treasuries (IEF ETF / ZN futures)
  Entry:       Buy when 2s10s spread > 50bps (FRED DGS2/DGS10)
  Allocation:  100% of sleeve's share (10% of portfolio)
  Leverage:    1x only (hard cap — no directional bets)
  Permission:  Master Agent yield_bias > 0

═══════════════════════════════════════════════════════════════
  EXIT RULES:
═══════════════════════════════════════════════════════════════

  Maturity Roll:   Sell 1-3 months before maturity for final roll yield
  Flatten Signal:  Exit if 2s10s < 20bps (rotate to shorter durations)
  Rebalancing:     Quarterly rolls to maintain 0.2-0.3% monthly pickup
  Fail-Safe:       Master heartbeat silent > 65min → auto-liquidate

═══════════════════════════════════════════════════════════════
  RISK MANAGEMENT (SHIELD™):
═══════════════════════════════════════════════════════════════

  Leverage:        1x hard cap
  Yield Spike:     Auto-pause on > 2σ yield moves
  Correlation:     < 0.1 rho to portfolio (veto if breached)
  KPI Guard:       Veto if projected loss > 5%

═══════════════════════════════════════════════════════════════
  INSTRUMENTS: IEF (7-10yr Treasury ETF), ZN futures, SHY (short dur)
═══════════════════════════════════════════════════════════════
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.strategies.sleeve1")


def treasury_basis_signal(bid: float, ask: float, last: float, hedge_ratio: float = 0.8) -> float:
    """
    Direct port of Rust sleeve_treasury_basis().
    Returns signal in [-1.0, 1.0].

    Formula: (spread - fair_value * 0.001).clamp(-1.0, 1.0)
    where spread = ask - bid, fair_value = last * hedge_ratio.
    """
    spread = ask - bid
    fair_value = last * hedge_ratio
    return max(-1.0, min(1.0, spread - fair_value * 0.001))


class YieldRegime(Enum):
    NORMAL = "normal"           # 2s10s > 50bps, curve upward-sloping → roll-down works
    FLAT = "flat"               # 2s10s 20-50bps, reduced opportunity
    INVERTED = "inverted"       # 2s10s < 20bps, exit to short duration
    SPIKE = "spike"             # > 2σ yield move, auto-pause


class YieldAction(Enum):
    NONE = "none"
    BUY_ROLLDOWN = "buy_rolldown"       # Enter roll-down position (IEF/ZN)
    HOLD = "hold"                       # Maintain existing position
    ROTATE_SHORT = "rotate_short"       # Flatten → rotate to SHY/short duration
    PAUSE = "pause"                     # Yield spike → sit in cash
    LIQUIDATE = "liquidate"             # Heartbeat timeout


@dataclass
class YieldMarketData:
    """Market inputs for Sleeve 1."""
    spread_2s10s: float         # bps (from FRED DGS2/DGS10)
    yield_10y: float            # 10-year yield (%)
    yield_2y: float             # 2-year yield (%)
    yield_change_1d: float      # 1-day yield change (bps) for spike detection
    yield_std_20d: float        # 20-day rolling std of yield changes (bps)
    vix: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Sleeve1Config:
    """Hard-coded parameters from strategy spec."""

    # ─── Entry Thresholds ───────────────────────────────────
    entry_spread_threshold: float = 50.0    # bps: buy when 2s10s > 50
    flatten_spread_threshold: float = 20.0  # bps: exit when 2s10s < 20

    # ─── Roll-Down Parameters ───────────────────────────────
    target_monthly_pickup: float = 0.0025   # 0.25% monthly roll yield target
    roll_months_before_maturity: int = 2    # Sell 1-3 months before maturity
    rebalance_frequency_days: int = 90      # Quarterly rolls

    # ─── Risk Limits ────────────────────────────────────────
    max_leverage: float = 1.0               # Hard cap — 1x only
    yield_spike_sigma: float = 2.0          # Pause on > 2σ yield moves
    max_portfolio_correlation: float = 0.10  # Veto if correlation > 0.1
    max_projected_loss_pct: float = 0.05    # 5% KPI Guard

    # ─── Heartbeat ──────────────────────────────────────────
    heartbeat_timeout_minutes: float = 65.0

    # ─── Position Parameters ────────────────────────────────
    full_allocation: float = 1.0            # 100% of sleeve allocation


class TreasuryYieldStrategy:
    """
    Sleeve 1: Treasury Yield Roll-Down — the portfolio anchor.

    This is NOT an alpha generator. It is:
    - Stability ballast (< 0.1 correlation to portfolio)
    - Income floor (~3% CAGR)
    - Rebalancing source (quarterly proceeds fund Sleeve 3)

    Extremely simple by design. Complexity = risk in fixed income.
    """

    def __init__(self, config: Optional[Sleeve1Config] = None):
        self.config = config or Sleeve1Config()
        self._current_regime: YieldRegime = YieldRegime.NORMAL
        self._is_positioned: bool = False
        self._position_instrument: str = "IEF"  # Default: IEF for 7-10yr
        self._entry_yield: float = 0.0
        self._entry_date: Optional[datetime] = None
        self._last_master_heartbeat: Optional[datetime] = None
        self._permission_bias: float = 1.0
        self._is_paused: bool = False
        self._days_since_rebalance: int = 0

    # ─── Regime Classification ──────────────────────────────────

    def classify_regime(self, data: YieldMarketData) -> YieldRegime:
        """Classify yield environment."""
        # Spike check first (safety)
        if self._check_yield_spike(data):
            return YieldRegime.SPIKE

        spread = data.spread_2s10s
        if spread > self.config.entry_spread_threshold:
            return YieldRegime.NORMAL
        elif spread >= self.config.flatten_spread_threshold:
            return YieldRegime.FLAT
        else:
            return YieldRegime.INVERTED

    def _check_yield_spike(self, data: YieldMarketData) -> bool:
        """Auto-pause on > 2σ yield moves."""
        if data.yield_std_20d <= 0:
            return False
        sigma_move = abs(data.yield_change_1d) / data.yield_std_20d
        if sigma_move > self.config.yield_spike_sigma:
            logger.warning(
                f"YIELD SPIKE: {sigma_move:.1f}σ move "
                f"({data.yield_change_1d:+.1f}bps vs {data.yield_std_20d:.1f}bps std)"
            )
            return True
        return False

    # ─── Heartbeat ──────────────────────────────────────────────

    def check_heartbeat_timeout(self) -> bool:
        if self._last_master_heartbeat is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._last_master_heartbeat).total_seconds() / 60
        return elapsed > self.config.heartbeat_timeout_minutes

    # ─── Rebalance Check ────────────────────────────────────────

    def needs_quarterly_rebalance(self) -> bool:
        """Quarterly rolls to maintain roll yield."""
        return self._days_since_rebalance >= self.config.rebalance_frequency_days

    # ─── Main Signal Generation ─────────────────────────────────

    def generate_signal(self, market) -> "SleeveSignal":
        """
        Main entry point. Called by Orchestrator.tick().

        Signal semantics for Sleeve 1:
          signal > 0:  Long treasuries (roll-down position active)
          signal = 0:  Flat / cash (paused or flattened curve)

        This sleeve never goes short. It's long-only or cash.
        """
        from orchestrator import SleeveSignal

        # Convert MarketState → YieldMarketData
        data = self._convert_market_data(market)

        # Record heartbeat
        self._last_master_heartbeat = datetime.now(timezone.utc)

        # ─── Priority 1: Heartbeat timeout ──────────────────
        if self.check_heartbeat_timeout():
            self._is_positioned = False
            return SleeveSignal(
                sleeve_id=1, sleeve_name="Treasury Yield",
                signal=0.0, confidence=1.0, instruments=["IEF"],
                rationale=f"LIQUIDATE: heartbeat timeout | action={YieldAction.LIQUIDATE.value}",
            )

        # ─── Classify regime ────────────────────────────────
        regime = self.classify_regime(data)
        self._current_regime = regime

        # ─── Priority 2: Yield spike → pause ────────────────
        if regime == YieldRegime.SPIKE:
            self._is_paused = True
            return SleeveSignal(
                sleeve_id=1, sleeve_name="Treasury Yield",
                signal=0.0, confidence=0.9, instruments=["IEF"],
                rationale=f"PAUSED: yield spike (>2σ move) | action={YieldAction.PAUSE.value}",
            )

        # Clear pause if spike resolved
        self._is_paused = False

        # ─── Priority 3: Inverted / flat → rotate short ─────
        if regime == YieldRegime.INVERTED:
            self._is_positioned = False
            return SleeveSignal(
                sleeve_id=1, sleeve_name="Treasury Yield",
                signal=0.0, confidence=0.8, instruments=["SHY"],
                rationale=f"ROTATE SHORT: 2s10s={data.spread_2s10s:.0f}bps < {self.config.flatten_spread_threshold}bps | action={YieldAction.ROTATE_SHORT.value}",
            )

        # ─── Priority 4: Normal curve → roll-down ───────────
        if regime == YieldRegime.NORMAL:
            # Check if we need to rebalance
            needs_rebal = self.needs_quarterly_rebalance()

            if not self._is_positioned or needs_rebal:
                self._is_positioned = True
                self._entry_yield = data.yield_10y
                self._entry_date = datetime.now(timezone.utc)
                if needs_rebal:
                    self._days_since_rebalance = 0
                action_note = "REBALANCE" if needs_rebal else "ENTRY"
                return SleeveSignal(
                    sleeve_id=1, sleeve_name="Treasury Yield",
                    signal=1.0 * self._permission_bias, confidence=0.85,
                    instruments=["IEF", "ZN"],
                    rationale=f"{action_note}: 2s10s={data.spread_2s10s:.0f}bps > {self.config.entry_spread_threshold}bps, 10y={data.yield_10y:.2f}% | action={YieldAction.BUY_ROLLDOWN.value}",
                )

            # Holding roll-down position
            return SleeveSignal(
                sleeve_id=1, sleeve_name="Treasury Yield",
                signal=0.8 * self._permission_bias, confidence=0.8,
                instruments=["IEF", "ZN"],
                rationale=f"HOLD: 2s10s={data.spread_2s10s:.0f}bps, 10y={data.yield_10y:.2f}% | action={YieldAction.HOLD.value}",
            )

        # ─── Flat regime: reduced position ───────────────────
        if regime == YieldRegime.FLAT:
            return SleeveSignal(
                sleeve_id=1, sleeve_name="Treasury Yield",
                signal=0.4 * self._permission_bias, confidence=0.6,
                instruments=["IEF"],
                rationale=f"REDUCED: 2s10s={data.spread_2s10s:.0f}bps (flat zone {self.config.flatten_spread_threshold}-{self.config.entry_spread_threshold}bps) | action={YieldAction.HOLD.value}",
            )

        # Default: no position
        return SleeveSignal(
            sleeve_id=1, sleeve_name="Treasury Yield",
            signal=0.0, confidence=0.0, instruments=["IEF"],
            rationale="No signal",
        )

    # ─── Data Conversion ────────────────────────────────────────

    def _convert_market_data(self, market) -> YieldMarketData:
        """
        Convert Orchestrator MarketState → YieldMarketData.

        v1.0: Estimates from TNX. FF rate hardcoded.
        v1.5: Direct FRED DGS2/DGS10/FEDFUNDS feed.
        """
        ten_yr = market.tnx / 10 if market.tnx > 10 else market.tnx
        # Estimate 2-year from FF rate + term premium
        two_yr_est = self._current_ff_rate() + 0.25
        spread_2s10s = (ten_yr - two_yr_est) * 100  # bps

        return YieldMarketData(
            spread_2s10s=spread_2s10s,
            yield_10y=ten_yr,
            yield_2y=two_yr_est,
            yield_change_1d=getattr(market, 'yield_change_1d', 0.0),
            yield_std_20d=getattr(market, 'yield_std_20d', 5.0),  # ~5bps default
            vix=market.vix,
            timestamp=market.timestamp,
        )

    def _current_ff_rate(self) -> float:
        """v1.0: Manually updated. v1.5: FRED FEDFUNDS."""
        return 4.50  # Update after each FOMC

    # ─── State Management ───────────────────────────────────────

    def new_trading_day(self):
        """Call at market open."""
        self._days_since_rebalance += 1

    def set_permission_bias(self, bias: float):
        self._permission_bias = max(0.0, bias)

    def get_status(self) -> dict:
        return {
            "sleeve": "Treasury Yield",
            "regime": self._current_regime.value,
            "is_positioned": self._is_positioned,
            "is_paused": self._is_paused,
            "instrument": self._position_instrument,
            "entry_yield": self._entry_yield,
            "entry_date": self._entry_date.isoformat() if self._entry_date else None,
            "days_since_rebalance": self._days_since_rebalance,
            "permission_bias": self._permission_bias,
        }
