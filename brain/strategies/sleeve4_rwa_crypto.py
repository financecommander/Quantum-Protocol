"""
MATRIX PROTOCOL v1.0 — Sleeve 4: RWA/Crypto Arbitrage

Cross-venue spot-futures arbitrage on crypto pairs.
Detects spread dislocations and signals directional trades.

CORE LOGIC: Spot-Futures Basis Arbitrage
  Monitor spot vs perpetual/quarterly futures prices for BTC, ETH, SOL.
  When spread > min_spread_bps + fee_bps -> opportunity detected.
  Rank by profit_potential * confidence (volume-weighted).

ENTRY:  abs(spread) > 5bps + 2bps fees = 7bps minimum
EXIT:   Spread converges below fee threshold, or stale timeout
CRISIS: VIX > 35 reduce 50%, VIX > 45 flatten
INSTRUMENTS: BTC, ETH, SOL (spot + futures pairs)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("matrix.strategies.sleeve4")


@dataclass
class ArbitrageOpportunity:
    """A detected spot-futures spread opportunity."""
    symbol: str
    spot_price: float
    futures_price: float
    spread_bps: float
    profit_potential_bps: float
    confidence: float
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Sleeve4Config:
    """Hard-coded parameters from strategy spec."""

    # Spread thresholds
    min_spread_bps: float = 5.0
    fee_bps: float = 2.0

    # Position limits
    max_position_usd: float = 50_000.0

    # Symbols
    symbols: list = field(default_factory=lambda: ["BTC", "ETH", "SOL"])

    # Opportunity management
    stale_timeout_seconds: float = 30.0
    max_opportunities: int = 10

    # Crisis thresholds
    crisis_vix_reduce: float = 35.0
    crisis_vix_flatten: float = 45.0

    # Heartbeat
    heartbeat_timeout_minutes: float = 65.0

    # Synthetic spread parameters (v1.0)
    base_spread_bps: float = 3.0
    vix_spread_multiplier: float = 0.5
    spx_momentum_factor: float = 0.02


class RwaCryptoStrategy:
    """
    Sleeve 4: Cross-venue crypto spot-futures arbitrage.

    v1.0: Synthetic spreads derived from market conditions.
    v1.5: Real exchange feeds from Coinbase/Kraken/Bybit.
    """

    def __init__(self, config: Optional[Sleeve4Config] = None):
        self.config = config or Sleeve4Config()
        self._opportunities: list[ArbitrageOpportunity] = []
        self._last_master_heartbeat: Optional[datetime] = None
        self._permission_bias: float = 1.0
        self._regime: str = "growth"
        self._trade_count: int = 0
        self._total_profit_bps: float = 0.0
        self._is_crisis_reduced: bool = False

    # ─── Spread Estimation ────────────────────────────────────────

    def _estimate_crypto_spreads(self, market) -> dict[str, float]:
        """
        v1.0: Estimate crypto spot-futures spreads from market conditions.
        Higher VIX -> wider crypto spreads (correlation spike).
        SPX momentum -> directional basis (risk-on/off flows).
        """
        vix = market.vix
        spx = market.spx

        spreads = {}
        for i, symbol in enumerate(self.config.symbols):
            base = self.config.base_spread_bps
            vix_component = max(0, (vix - 15.0)) * self.config.vix_spread_multiplier

            spx_ref = 5000.0
            spx_deviation = (spx - spx_ref) / spx_ref
            momentum_component = spx_deviation * 100 * self.config.spx_momentum_factor

            # Per-symbol variation (BTC tighter, SOL wider)
            symbol_factor = 1.0 + (i * 0.15)

            spread = (base + vix_component + momentum_component) * symbol_factor

            if self._regime == "stress":
                spread *= 1.5
            elif self._regime == "crisis":
                spread *= 2.5

            spreads[symbol] = spread

        return spreads

    # ─── Opportunity Detection ────────────────────────────────────

    def _scan_opportunities(self, market) -> list[ArbitrageOpportunity]:
        """Scan for arbitrage opportunities from current spreads."""
        spreads = self._estimate_crypto_spreads(market)
        threshold = self.config.min_spread_bps + self.config.fee_bps
        opportunities = []

        for symbol, spread_bps in spreads.items():
            if abs(spread_bps) > threshold:
                profit_potential = abs(spread_bps) - self.config.fee_bps

                volume_scores = {"BTC": 0.9, "ETH": 0.7, "SOL": 0.5}
                volume_score = volume_scores.get(symbol, 0.4)
                spread_confidence = min(1.0, abs(spread_bps) / 20.0)
                confidence = (volume_score + spread_confidence) / 2.0

                opp = ArbitrageOpportunity(
                    symbol=symbol,
                    spot_price=0.0,
                    futures_price=0.0,
                    spread_bps=spread_bps,
                    profit_potential_bps=profit_potential,
                    confidence=confidence,
                )
                opportunities.append(opp)

        return opportunities

    def _clear_stale_opportunities(self):
        """Remove opportunities older than timeout."""
        now = datetime.now(timezone.utc)
        cutoff = self.config.stale_timeout_seconds
        self._opportunities = [
            o for o in self._opportunities
            if (now - o.detected_at).total_seconds() < cutoff
        ]

    def _get_best_opportunity(self) -> Optional[ArbitrageOpportunity]:
        """Get highest risk-adjusted opportunity."""
        if not self._opportunities:
            return None
        return max(self._opportunities, key=lambda o: o.profit_potential_bps * o.confidence)

    # ─── Crisis Check ─────────────────────────────────────────────

    def _crisis_multiplier(self, vix: float) -> float:
        """Crypto correlates with equities in crisis. Reduce exposure."""
        if vix >= self.config.crisis_vix_flatten:
            return 0.0
        elif vix >= self.config.crisis_vix_reduce:
            return 0.5
        return 1.0

    # ─── Heartbeat ────────────────────────────────────────────────

    def check_heartbeat_timeout(self) -> bool:
        """Master heartbeat silent > 65 minutes -> auto-liquidate."""
        if self._last_master_heartbeat is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._last_master_heartbeat).total_seconds() / 60
        return elapsed > self.config.heartbeat_timeout_minutes

    # ─── Main Signal Generation ───────────────────────────────────

    def generate_signal(self, market) -> "SleeveSignal":
        """
        Main entry point. Called by Orchestrator.tick().

        Signal semantics:
          signal > 0: Long basis (buy spot, short futures)
          signal < 0: Short basis (short spot, buy futures)
          signal = 0: No opportunity or crisis-reduced
        """
        from orchestrator import SleeveSignal

        vix = market.vix

        # Priority 1: Heartbeat timeout (check BEFORE updating)
        if self.check_heartbeat_timeout():
            return SleeveSignal(
                sleeve_id=4, sleeve_name="RWA/Crypto",
                signal=0.0, confidence=1.0,
                instruments=self.config.symbols,
                rationale="LIQUIDATE: heartbeat timeout",
            )

        # Record heartbeat (after timeout check)
        self._last_master_heartbeat = datetime.now(timezone.utc)

        # Priority 2: Crisis check
        crisis_mult = self._crisis_multiplier(vix)
        self._is_crisis_reduced = crisis_mult < 1.0

        if crisis_mult == 0.0:
            return SleeveSignal(
                sleeve_id=4, sleeve_name="RWA/Crypto",
                signal=0.0, confidence=0.95,
                instruments=self.config.symbols,
                rationale=f"CRISIS FLATTEN: VIX={vix:.1f} > {self.config.crisis_vix_flatten}",
            )

        # Scan for opportunities
        new_opps = self._scan_opportunities(market)
        self._opportunities.extend(new_opps)
        self._clear_stale_opportunities()

        if len(self._opportunities) > self.config.max_opportunities:
            self._opportunities = sorted(
                self._opportunities,
                key=lambda o: o.profit_potential_bps * o.confidence,
                reverse=True
            )[:self.config.max_opportunities]

        best = self._get_best_opportunity()

        if best is None:
            return SleeveSignal(
                sleeve_id=4, sleeve_name="RWA/Crypto",
                signal=0.0, confidence=0.3,
                instruments=self.config.symbols,
                rationale=f"No arb opportunity (threshold={self.config.min_spread_bps + self.config.fee_bps:.0f}bps)",
            )

        # Generate signal from best opportunity
        signal_strength = min(best.profit_potential_bps / 20.0, 1.0)
        signal_direction = 1.0 if best.spread_bps > 0 else -1.0
        signal = signal_direction * signal_strength * crisis_mult * self._permission_bias
        signal = max(-1.0, min(1.0, signal))

        self._trade_count += 1
        crisis_note = f" (crisis-reduced {crisis_mult:.0%})" if crisis_mult < 1.0 else ""

        return SleeveSignal(
            sleeve_id=4, sleeve_name="RWA/Crypto",
            signal=signal,
            confidence=best.confidence,
            instruments=[best.symbol],
            rationale=(
                f"ARB: {best.symbol} spread={best.spread_bps:+.1f}bps, "
                f"profit={best.profit_potential_bps:.1f}bps, "
                f"conf={best.confidence:.0%}{crisis_note}"
            ),
        )

    # ─── State Management ─────────────────────────────────────────

    def set_permission_bias(self, bias: float):
        self._permission_bias = max(0.0, bias)

    def set_regime(self, regime: str):
        self._regime = regime

    def new_trading_day(self):
        self._opportunities.clear()

    def get_status(self) -> dict:
        return {
            "sleeve": "RWA/Crypto",
            "active_opportunities": len(self._opportunities),
            "trade_count": self._trade_count,
            "total_profit_bps": self._total_profit_bps,
            "permission_bias": self._permission_bias,
            "regime": self._regime,
            "is_crisis_reduced": self._is_crisis_reduced,
            "symbols": self.config.symbols,
        }
