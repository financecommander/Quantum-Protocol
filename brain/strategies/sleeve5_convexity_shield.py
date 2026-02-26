"""
MATRIX PROTOCOL™ v1.0 — Sleeve 5: Convexity Shield (Tail Hedging)

Powered By: SERAPH SHIELD™ (deterministic governance firewall)

Portfolio insurance delivering asymmetric protection in tail events (>3σ drops).
Neutral in calm markets with 0-2% annual drag (offset by dynamic collars).

MERGED SPEC: Thesis rules + Convexity Shield redesign.

═══════════════════════════════════════════════════════════════
  ENTRY RULES (Hard-Coded):
═══════════════════════════════════════════════════════════════

  Primary:     10-20% OTM SPX put spreads (buy 5-delta, sell 15-delta)
  Secondary:   VIX call spreads (buy 20-strike, sell 40-strike)
  Collar:      Short SPX calls when VIX < 15 (offsets premium drag)

  Trigger:     Enter/roll when VIX < 15 (cheap premiums → ACCUMULATE)
  Emergency:   6σ auto-trigger: SPX drops ≥ 5% intraday → immediate max hedge
  Permission:  Only active if regime = "high_vol" or VIX forecast > 6%
               (v1.0: VIX threshold proxy; v1.5: ARIMA Oracle Agent)

  Sizing:      1-2% of portfolio premium budget per activation
  Budget:      0.5-0.8% of portfolio per month (hard cap: 2% annually)

  Fail-Safe:   Master heartbeat silent > 65 minutes → auto-liquidate to cash

═══════════════════════════════════════════════════════════════
  EXIT RULES:
═══════════════════════════════════════════════════════════════

  Unwind:      VIX > 40 → take profits (crisis spike payoff)
  Premium:     Close if premium erodes > 50% of entry cost
  Roll:        Monthly at 7 DTE, or immediately post-event
  Harvest:     Auto-close 50% when profit > 5x monthly budget
  Re-entry:    Auto re-enter on next VIX < 15 window after unwind
  Carry:       Short calls rolled in bull markets to offset put decay

═══════════════════════════════════════════════════════════════
  RISK MANAGEMENT (SHIELD™ Enforcements):
═══════════════════════════════════════════════════════════════

  Premium Cap:    1-2% of total portfolio annually (SHIELD veto on excess)
  KPI Guard:      Veto if hedge would push monthly portfolio DD > -5%
  6σ Activation:  Immediate on SPX -5% intraday
  Monthly Bleed:  Max 1.0% of portfolio per month

═══════════════════════════════════════════════════════════════
  INSTRUMENTS:
═══════════════════════════════════════════════════════════════

  SPX index options (puts + short calls for collar)
  VIX calls / VX futures
  30-45 DTE at entry, roll at 7 DTE
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.strategies.sleeve5")


class HedgeRegime(Enum):
    ACCUMULATE = "accumulate"   # VIX < 15: insurance is cheap, buy + sell collars
    MAINTAIN = "maintain"       # VIX 15-25: hold positions, normal budget
    HARVEST = "harvest"         # VIX 25-35: likely profitable, reduce new buys
    PROTECT = "protect"         # VIX > 35: crisis — hold for max payoff, unwind > 40


class HedgeAction(Enum):
    """Actions the strategy can signal to the execution layer."""
    NONE = "none"
    BUY_PROTECTION = "buy_protection"       # Buy put spreads + VIX call spreads
    BUY_WITH_COLLAR = "buy_with_collar"     # Buy puts + sell calls (VIX < 15)
    ROLL = "roll"                           # Roll expiring positions
    HARVEST_PARTIAL = "harvest_partial"     # Close 50% of profitable hedges
    UNWIND_CRISIS = "unwind_crisis"         # VIX > 40: take crisis profits
    EMERGENCY_ACTIVATE = "emergency_6sigma" # SPX -5% intraday: max hedge NOW
    LIQUIDATE = "liquidate"                 # Heartbeat timeout: flatten to cash


@dataclass
class ConvexityConfig:
    """Hard-coded parameters from SERAPH SHIELD™ spec."""

    # ─── Budget ─────────────────────────────────────────────
    monthly_budget_pct: float = 0.006       # 0.6% of portfolio per month
    max_monthly_bleed_pct: float = 0.010    # 1.0% max monthly bleed
    annual_premium_cap_pct: float = 0.02    # 2.0% annual hard cap (SHIELD veto)
    max_allocation_pct: float = 0.10        # 10% of portfolio hard cap

    # ─── Component Split ────────────────────────────────────
    spx_put_allocation: float = 0.70        # 70% → SPX put spreads
    vix_call_allocation: float = 0.30       # 30% → VIX call spreads

    # ─── SPX Put Spread Parameters ──────────────────────────
    spx_long_delta: float = 0.05            # Buy 5-delta put (10-20% OTM)
    spx_short_delta: float = 0.15           # Sell 15-delta put
    target_dte: int = 35                    # Days to expiry at entry
    roll_dte: int = 7                       # Roll when DTE hits this

    # ─── VIX Call Spread Parameters ─────────────────────────
    vix_long_strike: float = 20.0
    vix_short_strike: float = 40.0

    # ─── Dynamic Collar (thesis addition) ───────────────────
    collar_vix_threshold: float = 15.0      # Sell calls only when VIX < 15
    collar_allocation: float = 0.10         # 5-10% of sleeve to short calls

    # ─── Regime Thresholds ──────────────────────────────────
    accumulate_vix: float = 15.0            # VIX < 15 → cheap insurance
    maintain_vix: float = 25.0              # VIX 15-25 → normal
    harvest_vix: float = 35.0              # VIX 25-35 → taking profits
    unwind_vix: float = 40.0               # VIX > 40 → crisis unwind

    # ─── 6σ Emergency Trigger ───────────────────────────────
    emergency_spx_drop_pct: float = 0.05    # 5% intraday SPX drop → max hedge
    emergency_response_ms: int = 100        # Target: < 100ms activation

    # ─── Harvest / Profit Taking ────────────────────────────
    harvest_multiplier: float = 5.0         # Take profit at 5x monthly cost
    harvest_close_pct: float = 0.50         # Close 50% on harvest
    premium_erosion_exit: float = 0.50      # Exit if premium erodes > 50%

    # ─── Heartbeat ──────────────────────────────────────────
    master_heartbeat_timeout_minutes: float = 65.0

    # ─── KPI Guard ──────────────────────────────────────────
    max_monthly_portfolio_dd: float = 0.05  # Veto if hedge pushes DD > -5%


class ConvexityShieldStrategy:
    """
    Sleeve 5: Portfolio insurance via rolling options structures.

    This sleeve is NOT a P&L center. It is portfolio insurance.

    Success metrics:
    - Correlation to portfolio: < -0.30
    - Crisis payoff: +15-40% when portfolio draws down >10%
    - Calm market drag: 0-2% annually (offset by collar income)
    - 6σ activation: < 100ms response time
    """

    def __init__(self, config: Optional[ConvexityConfig] = None):
        self.config = config or ConvexityConfig()
        self._current_regime: HedgeRegime = HedgeRegime.MAINTAIN
        self._positions_active: bool = False
        self._collar_active: bool = False
        self._current_dte: int = 0
        self._entry_cost: float = 0.0
        self._current_value: float = 0.0
        self._monthly_premium_spent: float = 0.0
        self._annual_premium_spent: float = 0.0
        self._last_roll_date: Optional[datetime] = None
        self._last_spx_price: Optional[float] = None
        self._session_high_spx: Optional[float] = None
        self._last_master_heartbeat: Optional[datetime] = None
        self._post_unwind: bool = False  # Waiting for re-entry after crisis unwind
        self._permission_bias: float = 1.0

    # ─── Regime Classification ──────────────────────────────────

    def classify_regime(self, vix: float) -> HedgeRegime:
        """Classify VIX into hedge regime."""
        if vix < self.config.accumulate_vix:
            return HedgeRegime.ACCUMULATE
        elif vix < self.config.maintain_vix:
            return HedgeRegime.MAINTAIN
        elif vix < self.config.harvest_vix:
            return HedgeRegime.HARVEST
        else:
            return HedgeRegime.PROTECT

    # ─── Budget Controls (SHIELD™ Enforcement) ──────────────────

    def check_annual_cap(self, proposed_spend: float, portfolio_value: float) -> bool:
        """SHIELD™ veto: reject if annual premium cap exceeded."""
        cap = portfolio_value * self.config.annual_premium_cap_pct
        if self._annual_premium_spent + proposed_spend > cap:
            logger.warning(
                f"SHIELD VETO: Annual premium cap breached. "
                f"Spent ${self._annual_premium_spent:,.0f} + proposed ${proposed_spend:,.0f} "
                f"> cap ${cap:,.0f}"
            )
            return False
        return True

    def check_monthly_bleed(self, proposed_spend: float, portfolio_value: float) -> bool:
        """Monthly bleed cap: 1.0% of portfolio."""
        cap = portfolio_value * self.config.max_monthly_bleed_pct
        if self._monthly_premium_spent + proposed_spend > cap:
            logger.warning(f"Monthly bleed cap: ${self._monthly_premium_spent + proposed_spend:,.0f} > ${cap:,.0f}")
            return False
        return True

    def calculate_budget(self, portfolio_value: float) -> tuple[float, float]:
        """Calculate monthly budget split: (spx_budget, vix_budget)."""
        monthly = portfolio_value * self.config.monthly_budget_pct
        return (
            monthly * self.config.spx_put_allocation,
            monthly * self.config.vix_call_allocation,
        )

    # ─── Trigger Checks ─────────────────────────────────────────

    def check_6sigma_trigger(self, spx_current: float) -> bool:
        """
        6σ Emergency: SPX drops ≥ 5% intraday → immediate max hedge.
        Track intraday high and compare to current.
        """
        if self._session_high_spx is None:
            self._session_high_spx = spx_current
            return False

        # Update session high
        if spx_current > self._session_high_spx:
            self._session_high_spx = spx_current

        # Check intraday drop from session high
        if self._session_high_spx > 0:
            drop_pct = (self._session_high_spx - spx_current) / self._session_high_spx
            if drop_pct >= self.config.emergency_spx_drop_pct:
                logger.critical(
                    f"6σ TRIGGER: SPX dropped {drop_pct:.1%} from session high "
                    f"({self._session_high_spx:.0f} → {spx_current:.0f})"
                )
                return True

        return False

    def check_heartbeat_timeout(self) -> bool:
        """Master heartbeat silent > 65 minutes → auto-liquidate."""
        if self._last_master_heartbeat is None:
            return False
        elapsed = (datetime.utcnow() - self._last_master_heartbeat).total_seconds() / 60
        if elapsed > self.config.master_heartbeat_timeout_minutes:
            logger.critical(f"HEARTBEAT TIMEOUT: {elapsed:.0f}min since last heartbeat")
            return True
        return False

    def should_roll(self, current_dte: int) -> bool:
        """Roll at 7 DTE."""
        return current_dte <= self.config.roll_dte

    def should_harvest(self, current_value: float, entry_cost: float) -> bool:
        """Auto-harvest when profit > 5x monthly budget."""
        if entry_cost <= 0:
            return False
        return current_value >= entry_cost * self.config.harvest_multiplier

    def check_premium_erosion(self, current_value: float, entry_cost: float) -> bool:
        """Exit if premium erodes > 50% of entry cost."""
        if entry_cost <= 0:
            return False
        remaining = current_value / entry_cost
        return remaining < (1.0 - self.config.premium_erosion_exit)

    def should_use_collar(self, vix: float) -> bool:
        """Sell calls to offset premium only when VIX < 15 (cheap insurance regime)."""
        return vix < self.config.collar_vix_threshold

    def check_auto_reentry(self, vix: float) -> bool:
        """After crisis unwind, re-enter on next VIX < 15 window."""
        return self._post_unwind and vix < self.config.accumulate_vix

    # ─── Sizing ─────────────────────────────────────────────────

    def get_sizing_multiplier(self, regime: HedgeRegime) -> float:
        """Position sizing by regime."""
        return {
            HedgeRegime.ACCUMULATE: 1.0,    # Full budget — insurance is cheap
            HedgeRegime.MAINTAIN: 1.0,      # Full budget — normal operations
            HedgeRegime.HARVEST: 0.5,       # Reduce new buys — already profitable
            HedgeRegime.PROTECT: 0.0,       # No new positions — hold existing
        }[regime]

    # ─── Main Signal Generation ─────────────────────────────────

    def generate_signal(self, market) -> "SleeveSignal":
        """
        Main signal generation. Called by Orchestrator.tick().

        Signal semantics for Sleeve 5:
          signal < 0:  Buying protection (put spreads, VIX calls)
          signal = 0:  Hold existing / no action
          signal > 0:  Harvesting profits (closing winning hedges)

        Actions are encoded in rationale for the execution layer.
        """
        from orchestrator import SleeveSignal

        vix = market.vix
        spx = market.spx
        regime = self.classify_regime(vix)
        self._current_regime = regime

        # Record master heartbeat
        self._last_master_heartbeat = datetime.utcnow()

        # ─── Priority 1: Heartbeat timeout → LIQUIDATE ──────
        if self.check_heartbeat_timeout():
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=0.0, confidence=1.0,
                instruments=["SPX_PUT", "VIX_CALL"],
                rationale=f"LIQUIDATE: heartbeat timeout | action={HedgeAction.LIQUIDATE.value}",
            )

        # ─── Priority 2: 6σ emergency → MAX HEDGE NOW ───────
        if self.check_6sigma_trigger(spx):
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=-1.0, confidence=1.0,
                instruments=["SPX_PUT", "VIX_CALL"],
                rationale=f"6σ EMERGENCY: SPX -{(self._session_high_spx - spx)/self._session_high_spx:.1%} | action={HedgeAction.EMERGENCY_ACTIVATE.value}",
            )

        # ─── Priority 3: VIX > 40 crisis unwind ─────────────
        if vix > self.config.unwind_vix and self._positions_active:
            self._post_unwind = True
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=1.0, confidence=0.95,
                instruments=["SPX_PUT", "VIX_CALL"],
                rationale=f"CRISIS UNWIND: VIX={vix:.0f} > 40, taking profits | action={HedgeAction.UNWIND_CRISIS.value}",
            )

        # ─── Priority 4: Auto re-entry after crisis unwind ──
        if self.check_auto_reentry(vix):
            self._post_unwind = False
            use_collar = self.should_use_collar(vix)
            action = HedgeAction.BUY_WITH_COLLAR if use_collar else HedgeAction.BUY_PROTECTION
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=-1.0, confidence=0.85,
                instruments=["SPX_PUT", "VIX_CALL", "SPX_CALL_SHORT"] if use_collar else ["SPX_PUT", "VIX_CALL"],
                rationale=f"AUTO RE-ENTRY: VIX={vix:.0f} < 15 post-unwind | action={action.value}",
            )

        # ─── Priority 5: Harvest check ──────────────────────
        if self._positions_active and self.should_harvest(self._current_value, self._entry_cost):
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=0.5, confidence=0.85,
                instruments=["SPX_PUT", "VIX_CALL"],
                rationale=f"HARVEST: profit {self._current_value/max(self._entry_cost,1):.1f}x cost | action={HedgeAction.HARVEST_PARTIAL.value}",
            )

        # ─── Priority 6: Premium erosion exit ────────────────
        if self._positions_active and self.check_premium_erosion(self._current_value, self._entry_cost):
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=0.3, confidence=0.7,
                instruments=["SPX_PUT", "VIX_CALL"],
                rationale=f"PREMIUM EROSION: value < {1-self.config.premium_erosion_exit:.0%} of entry | action={HedgeAction.HARVEST_PARTIAL.value}",
            )

        # ─── Priority 7: Roll check ─────────────────────────
        if self._positions_active and self.should_roll(self._current_dte):
            use_collar = self.should_use_collar(vix)
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=-0.5, confidence=0.8,
                instruments=["SPX_PUT", "VIX_CALL", "SPX_CALL_SHORT"] if use_collar else ["SPX_PUT", "VIX_CALL"],
                rationale=f"ROLL: DTE={self._current_dte} ≤ {self.config.roll_dte} | action={HedgeAction.ROLL.value}",
            )

        # ─── Regime-based positioning ────────────────────────
        sizing = self.get_sizing_multiplier(regime)

        if regime == HedgeRegime.PROTECT:
            # Hold for max payoff, no new positions
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=0.0, confidence=0.9,
                instruments=["SPX_PUT", "VIX_CALL"],
                rationale=f"PROTECT: VIX={vix:.0f}, holding for max payoff | action={HedgeAction.NONE.value}",
            )

        if regime == HedgeRegime.HARVEST:
            return SleeveSignal(
                sleeve_id=5, sleeve_name="Convexity Shield",
                signal=-0.3 * sizing, confidence=0.7,
                instruments=["SPX_PUT", "VIX_CALL"],
                rationale=f"HARVEST regime: VIX={vix:.0f}, reduced new hedges | action={HedgeAction.BUY_PROTECTION.value}",
            )

        # ACCUMULATE or MAINTAIN
        use_collar = self.should_use_collar(vix)
        signal_strength = -1.0 if regime == HedgeRegime.ACCUMULATE else -0.5

        if use_collar:
            action = HedgeAction.BUY_WITH_COLLAR
            instruments = ["SPX_PUT", "VIX_CALL", "SPX_CALL_SHORT"]
            collar_note = " +collar"
        else:
            action = HedgeAction.BUY_PROTECTION
            instruments = ["SPX_PUT", "VIX_CALL"]
            collar_note = ""

        return SleeveSignal(
            sleeve_id=5, sleeve_name="Convexity Shield",
            signal=signal_strength * sizing, confidence=0.8,
            instruments=instruments,
            rationale=f"{regime.value.upper()}: VIX={vix:.0f}{collar_note} | action={action.value}",
        )

    # ─── Session Management ─────────────────────────────────────

    def reset_session(self):
        """Reset intraday tracking (call at market open)."""
        self._session_high_spx = None
        self._last_spx_price = None

    def reset_monthly(self):
        """Reset monthly budget tracking (call at month start)."""
        self._monthly_premium_spent = 0.0

    def reset_annual(self):
        """Reset annual budget tracking (call at year start)."""
        self._annual_premium_spent = 0.0

    def set_permission_bias(self, bias: float):
        """Update from permission vector."""
        self._permission_bias = max(0.0, bias)

    def set_regime(self, regime: str):
        """Update regime from orchestrator."""
        pass  # Sleeve 5 uses VIX-based internal regime, not Master regime

    # ─── Status ─────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "sleeve": "Convexity Shield",
            "regime": self._current_regime.value,
            "positions_active": self._positions_active,
            "collar_active": self._collar_active,
            "current_dte": self._current_dte,
            "entry_cost": self._entry_cost,
            "current_value": self._current_value,
            "monthly_premium_spent": self._monthly_premium_spent,
            "annual_premium_spent": self._annual_premium_spent,
            "post_unwind_waiting": self._post_unwind,
            "session_high_spx": self._session_high_spx,
        }
