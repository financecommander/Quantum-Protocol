"""
MATRIX PROTOCOL™ v1.0 — Permission Vector

The thesis describes an hourly JSON broadcast from the Master Agent to all Sleeves:
  {"regime": "growth", "prop_bias": 1.15, "tail_bias": 0.9, "curve_bias": 1.0}

v1.0: Deterministic permission vector generated from SeraphAI regime classifier.
v2.0: MARL-trained permission vectors from full SERAPH AI hierarchy.

The Permission Vector GATES all sleeve execution:
- Sleeves check their bias value before generating signals
- Bias > 1.0 = regime favors this sleeve (increase confidence/size)
- Bias < 1.0 = regime disfavors (reduce confidence/size)
- Bias = 0.0 = sleeve blocked (do not trade)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("matrix.risk.permission_vector")


@dataclass
class PermissionVector:
    """
    Master Agent → Sleeve broadcast.
    
    Generated hourly (v1.0: on every tick from regime classifier).
    Every sleeve MUST check its bias before executing.
    """
    regime: str                         # "growth", "stress", "transition", "compression"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Per-sleeve bias multipliers (1.0 = neutral, >1 = favored, <1 = reduced, 0 = blocked)
    treasury_bias: float = 1.0          # Sleeve 1
    curve_bias: float = 1.0             # Sleeve 2
    prop_bias: float = 1.0              # Sleeve 3
    rwa_bias: float = 1.0               # Sleeve 4 (RWA/Crypto)
    tail_bias: float = 1.0              # Sleeve 5
    
    # Master heartbeat — sleeves use this for the 65-min failsafe
    heartbeat_alive: bool = True
    
    # Human override flag (Feature 7: >20% shift requires approval)
    requires_human_approval: bool = False
    approval_reason: str = ""

    def get_sleeve_bias(self, sleeve_id: int) -> float:
        """Get bias multiplier for a specific sleeve."""
        bias_map = {
            1: self.treasury_bias,
            2: self.curve_bias,
            3: self.prop_bias,
            4: self.rwa_bias,
            5: self.tail_bias,
        }
        return bias_map.get(sleeve_id, 0.0)

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "timestamp": self.timestamp.isoformat(),
            "biases": {
                "treasury": self.treasury_bias,
                "curve": self.curve_bias,
                "prop": self.prop_bias,
                "rwa": self.rwa_bias,
                "tail": self.tail_bias,
            },
            "heartbeat": self.heartbeat_alive,
            "requires_approval": self.requires_human_approval,
        }


# ─── Regime → Permission Vector Mapping ────────────────────────
# From thesis §3: specific allocation adjustments per regime

REGIME_VECTORS = {
    "growth": PermissionVector(
        regime="growth",
        treasury_bias=0.85,     # Reduce safe haven
        curve_bias=1.0,         # Neutral
        prop_bias=1.15,         # +15% to primary alpha
        rwa_bias=1.10,          # +10% crypto arb (calm markets = tighter spreads)
        tail_bias=0.90,         # Slightly reduce hedge cost
    ),
    "stress": PermissionVector(
        regime="stress",
        treasury_bias=1.12,     # +12% to safe haven
        curve_bias=0.80,        # Reduce curve trades (spreads widen unpredictably)
        prop_bias=0.70,         # -30% to prop (drawdown risk)
        rwa_bias=0.50,          # -50% crypto (correlates in stress)
        tail_bias=1.12,         # +12% to tail hedge
    ),
    "transition": PermissionVector(
        regime="transition",
        treasury_bias=1.0,      # Neutral
        curve_bias=1.10,        # +10% to curve (regime shifts = spread opportunities)
        prop_bias=0.95,         # Slightly reduced
        rwa_bias=0.90,          # Slightly reduced
        tail_bias=1.05,         # Slightly elevated hedge
    ),
    "compression": PermissionVector(
        regime="compression",
        treasury_bias=1.0,      # Neutral
        curve_bias=1.05,        # +5% (low vol = good for spreads)
        prop_bias=1.10,         # +10% (momentum works in calm markets)
        rwa_bias=1.15,          # +15% crypto arb (compression = good for basis trades)
        tail_bias=0.80,         # Reduce — insurance is a drag in calm markets
    ),
    "crisis": PermissionVector(
        regime="crisis",
        treasury_bias=1.20,     # Max safe haven
        curve_bias=0.0,         # Block — spreads blow out unpredictably
        prop_bias=0.0,          # Block — flatten prop accounts
        rwa_bias=0.0,           # Block — crypto correlates fully in crisis
        tail_bias=1.30,         # Max hedge activation
    ),
}


def generate_permission_vector(
    regime: str,
    previous_vector: Optional[PermissionVector] = None,
    human_approval_threshold: float = 0.20,
) -> PermissionVector:
    """
    Generate a permission vector for the current regime.
    
    If the shift from previous vector exceeds 20% on any sleeve,
    flag for human approval (Feature 7 from thesis).
    """
    template = REGIME_VECTORS.get(regime)
    if template is None:
        logger.warning(f"Unknown regime '{regime}', defaulting to compression")
        template = REGIME_VECTORS["compression"]
    
    # COPY — never mutate the shared template
    vector = PermissionVector(
        regime=template.regime,
        treasury_bias=template.treasury_bias,
        curve_bias=template.curve_bias,
        prop_bias=template.prop_bias,
        rwa_bias=template.rwa_bias,
        tail_bias=template.tail_bias,
    )
    vector.timestamp = datetime.now(timezone.utc)
    
    # Check for large shifts requiring human approval
    if previous_vector is not None:
        for sleeve_id in [1, 2, 3, 4, 5]:
            old_bias = previous_vector.get_sleeve_bias(sleeve_id)
            new_bias = vector.get_sleeve_bias(sleeve_id)
            
            if old_bias > 0:
                shift = abs(new_bias - old_bias) / old_bias
                if shift > human_approval_threshold:
                    vector.requires_human_approval = True
                    vector.approval_reason = (
                        f"Sleeve {sleeve_id} bias shift {old_bias:.2f} → {new_bias:.2f} "
                        f"({shift:.0%} > {human_approval_threshold:.0%} threshold)"
                    )
                    logger.warning(f"HUMAN APPROVAL REQUIRED: {vector.approval_reason}")
                    break
    
    logger.info(f"Permission vector: regime={regime}, biases={vector.to_dict()['biases']}")
    return vector
