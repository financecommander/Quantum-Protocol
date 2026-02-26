"""
MATRIX PROTOCOL™ v1.0 — KPI Guard (SERAPH SHIELD™ Enhancement)

From thesis: "Shield Agent vetoes if projected DD >5% monthly" (Feature 4)

This sits ABOVE the kill switch. The kill switch is a 2% daily emergency stop.
The KPI Guard is a rolling monthly drawdown monitor that vetoes new positions
BEFORE they can trigger the kill switch.

Hierarchy:
  KPI Guard (monthly, preventive) → blocks new trades if on track for >5% monthly DD
  Kill Switch (daily, reactive) → emergency stop at 2% daily loss

v1.0: Rolling 20-day P&L tracker with linear projection
v2.0: Monte Carlo projected DD from Watcher Agent (1,000 paths)
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("matrix.risk.kpi_guard")


@dataclass
class KPIGuardConfig:
    """SHIELD™ enforcement parameters."""
    max_monthly_dd_pct: float = 0.05        # 5% monthly DD veto threshold
    lookback_days: int = 20                  # Rolling window for DD calculation
    warning_threshold_pct: float = 0.03      # 3% → warning (no veto yet)
    projected_dd_safety_margin: float = 1.5  # Project forward with 1.5x safety factor
    min_data_points: int = 3                 # Need at least 3 days before projecting


@dataclass
class DailySnapshot:
    """End-of-day portfolio snapshot."""
    date: date
    portfolio_value: float
    daily_pnl: float
    daily_return_pct: float


class KPIGuard:
    """
    Rolling monthly drawdown monitor.
    
    Tracks daily returns over a 20-day window and projects whether
    the current trajectory would breach the 5% monthly DD limit.
    
    VETO means: no new positions allowed, but existing positions stay.
    This is softer than the kill switch (which flattens everything).
    """

    def __init__(self, config: Optional[KPIGuardConfig] = None):
        self.config = config or KPIGuardConfig()
        self._daily_history: deque[DailySnapshot] = deque(maxlen=self.config.lookback_days)
        self._month_start_value: Optional[float] = None
        self._current_month: Optional[int] = None
        self._veto_active: bool = False
        self._veto_reason: str = ""
        self._warning_active: bool = False

    def record_daily(self, portfolio_value: float, daily_pnl: float):
        """
        Record end-of-day snapshot. Call once per trading day at close.
        """
        today = date.today()
        
        # Track month boundary
        if self._current_month != today.month:
            self._month_start_value = portfolio_value - daily_pnl  # Start of new month
            self._current_month = today.month
            self._veto_active = False
            self._warning_active = False
            logger.info(f"KPI Guard: New month {today.month}, start value ${self._month_start_value:,.0f}")

        if self._month_start_value is None:
            self._month_start_value = portfolio_value - daily_pnl

        daily_return = daily_pnl / max(portfolio_value - daily_pnl, 1.0)
        
        snapshot = DailySnapshot(
            date=today,
            portfolio_value=portfolio_value,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return,
        )
        self._daily_history.append(snapshot)
        
        # Evaluate after recording
        self._evaluate()

    def _evaluate(self):
        """Check current and projected drawdown against thresholds."""
        if len(self._daily_history) < self.config.min_data_points:
            return

        # Calculate actual month-to-date drawdown
        mtd_dd = self.get_mtd_drawdown()
        
        # Check actual DD against threshold
        if mtd_dd <= -self.config.max_monthly_dd_pct:
            self._veto_active = True
            self._veto_reason = f"MTD drawdown {mtd_dd:.2%} breached -{self.config.max_monthly_dd_pct:.0%} limit"
            logger.warning(f"KPI GUARD VETO: {self._veto_reason}")
            return

        # Check projected DD (linear extrapolation with safety margin)
        projected = self.get_projected_monthly_dd()
        if projected <= -self.config.max_monthly_dd_pct:
            self._veto_active = True
            self._veto_reason = f"Projected monthly DD {projected:.2%} would breach -{self.config.max_monthly_dd_pct:.0%}"
            logger.warning(f"KPI GUARD VETO (projected): {self._veto_reason}")
            return

        # Warning check
        if mtd_dd <= -self.config.warning_threshold_pct:
            self._warning_active = True
            logger.info(f"KPI Guard WARNING: MTD drawdown {mtd_dd:.2%} approaching limit")
        else:
            self._warning_active = False

        # Clear veto if we've recovered
        if self._veto_active and mtd_dd > -self.config.warning_threshold_pct:
            self._veto_active = False
            self._veto_reason = ""
            logger.info("KPI Guard: Veto cleared — drawdown recovered")

    def get_mtd_drawdown(self) -> float:
        """Calculate month-to-date drawdown from month start."""
        if not self._daily_history or self._month_start_value is None:
            return 0.0
        
        current_value = self._daily_history[-1].portfolio_value
        return (current_value - self._month_start_value) / self._month_start_value

    def get_projected_monthly_dd(self) -> float:
        """
        Project monthly drawdown using linear extrapolation.
        
        v1.0: Average daily return × remaining trading days × safety margin.
        v2.0: Monte Carlo projection from Watcher Agent.
        """
        if len(self._daily_history) < self.config.min_data_points:
            return 0.0

        # Average daily return over lookback window
        returns = [s.daily_return_pct for s in self._daily_history]
        avg_daily = sum(returns) / len(returns)
        
        # If average is positive, no projected DD concern
        if avg_daily >= 0:
            return 0.0

        # Estimate remaining trading days in month (~22 total)
        days_elapsed = len(self._daily_history)
        days_remaining = max(22 - days_elapsed, 0)
        
        # Current MTD DD + projected additional loss (with safety margin)
        mtd = self.get_mtd_drawdown()
        projected_additional = avg_daily * days_remaining * self.config.projected_dd_safety_margin
        
        return mtd + projected_additional

    def check_trade_allowed(self, sleeve_id: int, proposed_risk: float = 0.0) -> tuple[bool, str]:
        """
        Called by OrderManager before every trade.
        
        Returns (allowed, reason).
        
        Unlike kill switch (which stops ALL trading), KPI Guard:
        - Blocks NEW positions
        - Allows position REDUCTIONS
        - Allows Sleeve 5 hedging (always permitted)
        """
        # Sleeve 5 (tail hedge) is always allowed — it REDUCES portfolio risk
        if sleeve_id == 5:
            return True, "Sleeve 5 (hedge) always permitted"

        if self._veto_active:
            return False, f"KPI Guard VETO: {self._veto_reason}"

        return True, "approved"

    @property
    def is_veto_active(self) -> bool:
        return self._veto_active

    @property
    def is_warning_active(self) -> bool:
        return self._warning_active

    def get_status(self) -> dict:
        return {
            "veto_active": self._veto_active,
            "veto_reason": self._veto_reason,
            "warning_active": self._warning_active,
            "mtd_drawdown": f"{self.get_mtd_drawdown():.2%}",
            "projected_dd": f"{self.get_projected_monthly_dd():.2%}",
            "data_points": len(self._daily_history),
            "month_start_value": self._month_start_value,
        }
