"""
MATRIX PROTOCOL™ v1.0 — Portfolio Orchestrator

Manages sleeve allocation, rebalancing, and signal aggregation.
Connects strategy modules → risk checks → execution layer.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.orchestrator")


class CrisisLevel(Enum):
    """Ported from Rust: evaluate_crisis() state machine."""
    NORMAL = "Normal"
    ELEVATED = "Elevated"
    SEVERE = "Severe"
    SMART_BUNKER = "SmartBunker"
    SURGICAL_SNIPER = "SurgicalSniper"


@dataclass
class SleeveAllocation:
    """Portfolio weights per sleeve. Must sum to 1.0."""
    treasury_yield: float = 0.10       # Sleeve 1
    compression_curve: float = 0.15    # Sleeve 2
    prop_scaling: float = 0.45         # Sleeve 3 (primary alpha)
    rwa_infrastructure: float = 0.00   # Sleeve 4 (deferred to v1.5)
    convexity_shield: float = 0.10     # Sleeve 5 (redesigned)
    cash: float = 0.20                 # Reserve / unallocated

    def __post_init__(self):
        total = (self.treasury_yield + self.compression_curve +
                 self.prop_scaling + self.rwa_infrastructure +
                 self.convexity_shield + self.cash)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Allocations must sum to 1.0, got {total:.4f}")


@dataclass
class MarketState:
    """Current market data snapshot."""
    timestamp: datetime
    vix: float
    spx: float
    tnx: float  # 10-year yield
    dxy: float  # Dollar index
    es_price: float  # E-mini S&P
    zn_price: float  # 10-year Treasury futures
    zf_price: float  # 5-year Treasury futures


@dataclass
class SleeveSignal:
    """Output from a sleeve strategy module."""
    sleeve_id: int
    sleeve_name: str
    signal: float  # -1.0 (max short) to +1.0 (max long)
    confidence: float  # 0.0 to 1.0
    instruments: list[str] = field(default_factory=list)
    rationale: str = ""


class Orchestrator:
    """
    Core portfolio orchestrator.
    
    Flow: Market Data → Regime → Permission Vector → Sleeve Signals → Risk Check → Execution
    """

    def __init__(
        self,
        allocation: Optional[SleeveAllocation] = None,
        portfolio_value: float = 50_000.0,
    ):
        self.allocation = allocation or SleeveAllocation()
        self.base_allocation = SleeveAllocation(
            **{k: v for k, v in self.allocation.__dict__.items()}
        )  # Snapshot of original allocation for regime adjustments
        self.portfolio_value = portfolio_value
        self.crisis_level = CrisisLevel.NORMAL
        self.is_killed = False
        self.signals: list[SleeveSignal] = []
        
        # SERAPH AI regime detector
        self._seraph = None
        self._init_seraph()

        # Permission vector (Master → Sleeve broadcast)
        self._current_vector = None
        self._previous_vector = None
        self._human_approval_pending = False
        self._init_permission_vector()

        # Import sleeve strategies (lazy — not all may be available)
        self._sleeves = {}
        self._init_sleeves()

    def _init_seraph(self):
        """Initialize SERAPH AI regime detector."""
        try:
            from strategies.seraph_ai import SeraphAI
            self._seraph = SeraphAI()
            logger.info("SERAPH AI™ regime detector initialized")
        except ImportError:
            logger.warning("SERAPH AI not available — running without regime detection")

    def _init_permission_vector(self):
        """Initialize permission vector system."""
        try:
            from risk.permission_vector import generate_permission_vector, REGIME_VECTORS
            self._generate_vector = generate_permission_vector
            self._regime_vectors = REGIME_VECTORS
            logger.info("Permission vector system initialized")
        except ImportError:
            self._generate_vector = None
            self._regime_vectors = None
            logger.warning("Permission vector not available — sleeves run unbiased")

    def _init_sleeves(self):
        """Initialize available sleeve strategy modules."""
        try:
            from strategies.sleeve1_treasury_yield import TreasuryYieldStrategy
            self._sleeves[1] = TreasuryYieldStrategy()
        except ImportError:
            logger.warning("Sleeve 1 (Treasury Yield) not available")

        try:
            from strategies.sleeve2_compression_curve import CompressionCurveStrategy
            self._sleeves[2] = CompressionCurveStrategy()
        except ImportError:
            logger.warning("Sleeve 2 (Compression & Curve) not available")

        try:
            from strategies.sleeve3_prop_scaling import PropScalingStrategy
            self._sleeves[3] = PropScalingStrategy()
        except ImportError:
            logger.warning("Sleeve 3 (Prop Scaling) not available")

        # Sleeve 4 deferred to v1.5
        logger.info("Sleeve 4 (RWA + Infrastructure) deferred to v1.5")

        try:
            from strategies.sleeve5_convexity_shield import ConvexityShieldStrategy
            self._sleeves[5] = ConvexityShieldStrategy()
        except ImportError:
            logger.warning("Sleeve 5 (Convexity Shield) not available")

    def evaluate_crisis(self, market: MarketState) -> CrisisLevel:
        """
        Ported from Rust: evaluate_crisis()
        Determines portfolio-wide crisis level from market data.
        
        Precedence: SmartBunker > SurgicalSniper > Severe > Elevated > Normal
        """
        vix = market.vix

        if vix > 45.0:
            self.crisis_level = CrisisLevel.SMART_BUNKER
        elif vix > 35.0:
            self.crisis_level = CrisisLevel.SURGICAL_SNIPER
        elif vix > 28.0:
            self.crisis_level = CrisisLevel.SEVERE
        elif vix > 20.0:
            self.crisis_level = CrisisLevel.ELEVATED
        else:
            self.crisis_level = CrisisLevel.NORMAL

        if self.crisis_level != CrisisLevel.NORMAL:
            logger.warning(f"Crisis level: {self.crisis_level.value} (VIX={vix:.1f})")

        return self.crisis_level

    def generate_signals(self, market: MarketState) -> list[SleeveSignal]:
        """Generate signals from all active sleeves."""
        self.signals = []
        
        for sleeve_id, strategy in self._sleeves.items():
            try:
                signal = strategy.generate_signal(market)
                self.signals.append(signal)
            except Exception as e:
                logger.error(f"Sleeve {sleeve_id} signal generation failed: {e}")
        
        return self.signals

    def apply_risk_overlay(self, signals: list[SleeveSignal]) -> list[SleeveSignal]:
        """
        Apply crisis-level risk adjustments to signals.
        Ported from Rust kill switch + crisis protocol logic.
        """
        if self.is_killed:
            logger.critical("KILL SWITCH ACTIVE — all signals zeroed")
            return [SleeveSignal(s.sleeve_id, s.sleeve_name, 0.0, 0.0, 
                                rationale="KILLED") for s in signals]

        adjusted = []
        for signal in signals:
            if self.crisis_level == CrisisLevel.SMART_BUNKER:
                # SmartBunker: flatten everything except tail hedge
                if signal.sleeve_id == 5:
                    adjusted.append(signal)  # Convexity shield stays active
                else:
                    adjusted.append(SleeveSignal(
                        signal.sleeve_id, signal.sleeve_name, 0.0, 0.0,
                        rationale="SmartBunker: flattened"
                    ))

            elif self.crisis_level == CrisisLevel.SURGICAL_SNIPER:
                # SurgicalSniper: reduce size by 50%, keep direction
                adjusted.append(SleeveSignal(
                    signal.sleeve_id, signal.sleeve_name,
                    signal.signal * 0.5, signal.confidence,
                    signal.instruments,
                    f"SurgicalSniper: reduced 50% | {signal.rationale}"
                ))

            elif self.crisis_level == CrisisLevel.SEVERE:
                # Severe: reduce size by 25%
                adjusted.append(SleeveSignal(
                    signal.sleeve_id, signal.sleeve_name,
                    signal.signal * 0.75, signal.confidence,
                    signal.instruments,
                    f"Severe: reduced 25% | {signal.rationale}"
                ))

            else:
                adjusted.append(signal)

        return adjusted

    def calculate_positions(self, signals: list[SleeveSignal]) -> dict:
        """
        Convert signals + allocations into dollar positions.
        """
        positions = {}
        alloc_map = {
            1: self.allocation.treasury_yield,
            2: self.allocation.compression_curve,
            3: self.allocation.prop_scaling,
            4: self.allocation.rwa_infrastructure,
            5: self.allocation.convexity_shield,
        }

        for signal in signals:
            sleeve_capital = self.portfolio_value * alloc_map.get(signal.sleeve_id, 0)
            position_size = sleeve_capital * signal.signal * signal.confidence
            
            positions[signal.sleeve_name] = {
                "sleeve_id": signal.sleeve_id,
                "signal": signal.signal,
                "confidence": signal.confidence,
                "allocated_capital": sleeve_capital,
                "target_position": position_size,
                "instruments": signal.instruments,
                "rationale": signal.rationale,
            }

        return positions

    def _broadcast_permission_vector(self, regime_name: str):
        """
        Generate and broadcast permission vector to all sleeves.

        This is the Master → Slave gating mechanism from the thesis.
        Each sleeve receives a bias multiplier:
          > 1.0 = regime favors this sleeve (increase sizing)
          < 1.0 = regime disfavors (reduce sizing)
          = 0.0 = sleeve blocked (do not trade)
        """
        if self._generate_vector is None:
            return

        self._previous_vector = self._current_vector
        self._current_vector = self._generate_vector(
            regime_name, previous_vector=self._previous_vector
        )

        # Check human approval gate (Feature 7: >20% shift)
        if self._current_vector.requires_human_approval:
            self._human_approval_pending = True
            logger.warning(
                f"HUMAN APPROVAL REQUIRED: {self._current_vector.approval_reason}"
            )
            # v1.0: log and continue (dashboard alert in v1.5)
            # v1.5: block execution until approved

        # Broadcast bias to each sleeve
        sleeve_bias_map = {
            1: self._current_vector.get_sleeve_bias(1),  # Treasury
            2: self._current_vector.get_sleeve_bias(2),  # Curve
            3: self._current_vector.get_sleeve_bias(3),  # Prop
            5: self._current_vector.get_sleeve_bias(5),  # Tail
        }

        for sleeve_id, bias in sleeve_bias_map.items():
            if sleeve_id in self._sleeves:
                strategy = self._sleeves[sleeve_id]
                if hasattr(strategy, 'set_permission_bias'):
                    strategy.set_permission_bias(bias)
                if hasattr(strategy, 'set_regime'):
                    strategy.set_regime(regime_name)

        logger.info(
            f"Permission vector broadcast: regime={regime_name} | "
            f"biases=[T:{sleeve_bias_map[1]:.2f} C:{sleeve_bias_map[2]:.2f} "
            f"P:{sleeve_bias_map[3]:.2f} H:{sleeve_bias_map[5]:.2f}]"
        )

    def tick(self, market: MarketState) -> dict:
        """
        Main tick loop. Called on each market data update.
        
        Flow:
          0. SERAPH AI regime detection + allocation adjustment
          1. Permission vector broadcast (Master → Sleeve gating)
          2. Evaluate crisis level
          3. Generate signals from all sleeves (biased by permission vector)
          4. Apply risk overlay
          5. Calculate target positions
        
        Returns dict of target positions per sleeve.
        """
        # 0. SERAPH AI regime detection + allocation adjustment
        regime_name = "compression"  # Default
        if self._seraph:
            self._seraph.classify_regime(market.vix, market.spx)
            
            if self._seraph.state:
                regime_name = self._seraph.state.regime.value.lower()
            
            # Quarterly rebalancing: adjust allocations based on regime
            if self._seraph.is_rebalance_due(market.timestamp):
                adj = self._seraph.get_allocation_adjustment()
                self.allocation = SleeveAllocation(
                    treasury_yield=max(0, min(0.30, self.base_allocation.treasury_yield + adj.sleeve1_delta)),
                    compression_curve=max(0, min(0.30, self.base_allocation.compression_curve + adj.sleeve2_delta)),
                    prop_scaling=max(0.20, min(0.65, self.base_allocation.prop_scaling + adj.sleeve3_delta)),
                    rwa_infrastructure=0.00,  # Deferred
                    convexity_shield=max(0.05, min(0.20, self.base_allocation.convexity_shield + adj.sleeve5_delta)),
                    cash=max(0.05, min(0.40, self.base_allocation.cash + adj.cash_delta)),
                )
                self._seraph.mark_rebalanced()
                logger.info(f"SERAPH rebalance: {adj.rationale}")

        # 1. Permission vector broadcast
        self._broadcast_permission_vector(regime_name)

        # 2. Evaluate crisis level
        self.evaluate_crisis(market)

        # 2. Generate signals from all sleeves
        signals = self.generate_signals(market)

        # 3. Apply risk overlay
        adjusted_signals = self.apply_risk_overlay(signals)

        # 4. Calculate target positions
        positions = self.calculate_positions(adjusted_signals)

        # 5. Log for audit trail
        pv_info = f"Vector: {regime_name}" if self._current_vector else "Vector: N/A"
        logger.info(
            f"Tick: {market.timestamp.isoformat()} | "
            f"Crisis: {self.crisis_level.value} | "
            f"Regime: {self._seraph.state.regime.value if self._seraph and self._seraph.state else 'N/A'} | "
            f"{pv_info} | "
            f"Signals: {len(signals)} | "
            f"VIX: {market.vix:.1f}"
        )

        return positions
