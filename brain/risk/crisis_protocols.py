"""
MATRIX PROTOCOL™ v1.0 — Crisis Protocols

Direct port from Rust evaluate_crisis() + regime logic.
Deterministic state machine — auditable, reproducible, FINRA-compliant.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.risk.crisis")


def evaluate_crisis(vix: float, depeg_pct: float = 0.0) -> str:
    """
    Direct port of Rust evaluate_crisis().
    Returns "SmartBunker", "SurgicalSniper", or "Normal".

    SmartBunker takes precedence: VIX > 45 is checked before depeg.
    """
    if vix > 45.0:
        return "SmartBunker"
    elif depeg_pct > 5.0:
        return "SurgicalSniper"
    else:
        return "Normal"


class CrisisLevel(Enum):
    NORMAL = 0
    ELEVATED = 1
    SEVERE = 2
    SURGICAL_SNIPER = 3
    SMART_BUNKER = 4


@dataclass
class CrisisConfig:
    elevated_vix: float = 20.0
    severe_vix: float = 28.0
    sniper_vix: float = 35.0
    bunker_vix: float = 45.0
    elevated_multiplier: float = 1.0
    severe_multiplier: float = 0.75
    sniper_multiplier: float = 0.50
    bunker_multiplier: float = 0.0


@dataclass
class CrisisState:
    level: CrisisLevel
    entered_at: datetime
    vix_at_entry: float
    previous_level: Optional[CrisisLevel] = None


class CrisisProtocol:
    """
    Deterministic crisis state machine.
    Escalation: immediate. De-escalation: 5 consecutive ticks below threshold.
    """

    def __init__(self, config: Optional[CrisisConfig] = None):
        self.config = config or CrisisConfig()
        self.state = CrisisState(
            level=CrisisLevel.NORMAL,
            entered_at=datetime.utcnow(),
            vix_at_entry=15.0,
        )
        self.deescalation_counter = 0
        self.deescalation_threshold = 5

    def evaluate(self, vix: float) -> CrisisLevel:
        new_level = self._classify_vix(vix)

        if new_level.value > self.state.level.value:
            self._transition(new_level, vix)
            self.deescalation_counter = 0
        elif new_level.value < self.state.level.value:
            self.deescalation_counter += 1
            if self.deescalation_counter >= self.deescalation_threshold:
                self._transition(new_level, vix)
                self.deescalation_counter = 0
        else:
            self.deescalation_counter = 0

        return self.state.level

    def _classify_vix(self, vix: float) -> CrisisLevel:
        if vix > self.config.bunker_vix:
            return CrisisLevel.SMART_BUNKER
        elif vix > self.config.sniper_vix:
            return CrisisLevel.SURGICAL_SNIPER
        elif vix > self.config.severe_vix:
            return CrisisLevel.SEVERE
        elif vix > self.config.elevated_vix:
            return CrisisLevel.ELEVATED
        else:
            return CrisisLevel.NORMAL

    def _transition(self, new_level: CrisisLevel, vix: float):
        old_level = self.state.level
        self.state = CrisisState(
            level=new_level,
            entered_at=datetime.utcnow(),
            vix_at_entry=vix,
            previous_level=old_level,
        )
        if new_level.value > old_level.value:
            logger.warning(f"CRISIS ESCALATION: {old_level.name} → {new_level.name} (VIX={vix:.1f})")
        else:
            logger.info(f"Crisis de-escalation: {old_level.name} → {new_level.name} (VIX={vix:.1f})")

    def get_position_multiplier(self) -> float:
        multipliers = {
            CrisisLevel.NORMAL: 1.0,
            CrisisLevel.ELEVATED: self.config.elevated_multiplier,
            CrisisLevel.SEVERE: self.config.severe_multiplier,
            CrisisLevel.SURGICAL_SNIPER: self.config.sniper_multiplier,
            CrisisLevel.SMART_BUNKER: self.config.bunker_multiplier,
        }
        return multipliers[self.state.level]

    def should_flatten_sleeve(self, sleeve_id: int) -> bool:
        if self.state.level == CrisisLevel.SMART_BUNKER:
            return sleeve_id != 5
        return False
