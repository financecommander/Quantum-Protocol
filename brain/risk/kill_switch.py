"""
MATRIX PROTOCOL™ v1.0 — Kill Switch

Direct port from Rust KillSwitch implementation.
4 trigger conditions, latching behavior, manual reset only.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.risk.kill_switch")


class KillReason(Enum):
    PNL_LOSS = "pnl_loss"
    POSITION_BREACH = "position_breach"
    CONSECUTIVE_REJECTIONS = "consecutive_rejections"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    MANUAL = "manual"


@dataclass
class KillSwitchConfig:
    max_daily_loss_pct: float = 0.02
    max_position_pct: float = 0.25
    max_consecutive_rejections: int = 5
    heartbeat_timeout_seconds: int = 30


class KillSwitch:
    """Latching kill switch. Once triggered, stays active until manual reset."""

    def __init__(self, config: Optional[KillSwitchConfig] = None):
        self.config = config or KillSwitchConfig()
        self.is_killed = False
        self.kill_reason: Optional[KillReason] = None
        self.kill_time: Optional[datetime] = None
        self.consecutive_rejections = 0
        self.last_heartbeat: Optional[datetime] = None
        self.daily_pnl = 0.0
        self.portfolio_value = 0.0

    def check_pnl(self, daily_pnl: float, portfolio_value: float) -> bool:
        self.daily_pnl = daily_pnl
        self.portfolio_value = portfolio_value
        if portfolio_value <= 0:
            return False
        loss_pct = abs(daily_pnl) / portfolio_value if daily_pnl < 0 else 0
        if loss_pct >= self.config.max_daily_loss_pct:
            self._trigger(KillReason.PNL_LOSS)
            return True
        return False

    def check_position(self, position_value: float, portfolio_value: float) -> bool:
        if portfolio_value <= 0:
            return False
        concentration = abs(position_value) / portfolio_value
        if concentration >= self.config.max_position_pct:
            self._trigger(KillReason.POSITION_BREACH)
            return True
        return False

    def record_rejection(self):
        self.consecutive_rejections += 1
        if self.consecutive_rejections >= self.config.max_consecutive_rejections:
            self._trigger(KillReason.CONSECUTIVE_REJECTIONS)

    def record_fill(self):
        self.consecutive_rejections = 0

    def heartbeat(self):
        self.last_heartbeat = datetime.now(timezone.utc)

    def check_heartbeat(self) -> bool:
        if self.last_heartbeat is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        if elapsed > self.config.heartbeat_timeout_seconds:
            self._trigger(KillReason.HEARTBEAT_TIMEOUT)
            return True
        return False

    def _trigger(self, reason: KillReason):
        if self.is_killed:
            return
        self.is_killed = True
        self.kill_reason = reason
        self.kill_time = datetime.now(timezone.utc)
        logger.critical(f"KILL SWITCH ACTIVATED: {reason.value} at {self.kill_time.isoformat()}")

    def manual_kill(self):
        self._trigger(KillReason.MANUAL)

    def reset(self, operator: str):
        if not self.is_killed:
            return
        logger.warning(f"KILL SWITCH RESET by {operator} | Was killed for {self.kill_reason.value}")
        self.is_killed = False
        self.kill_reason = None
        self.kill_time = None
        self.consecutive_rejections = 0

    def is_active(self) -> bool:
        return self.is_killed

    def status(self) -> dict:
        return {
            "is_killed": self.is_killed,
            "kill_reason": self.kill_reason.value if self.kill_reason else None,
            "kill_time": self.kill_time.isoformat() if self.kill_time else None,
            "consecutive_rejections": self.consecutive_rejections,
            "daily_pnl": self.daily_pnl,
            "portfolio_value": self.portfolio_value,
        }
