"""
MATRIX PROTOCOL™ v1.0 — Sleeve 2: Compression & Curve Trading

Low-Vol Alpha sleeve targeting 5-7% CAGR with <5% annualized volatility.
Trades yield curve dynamics via ZN/ZF futures (flatteners/steepeners).

Strategy Rules (from Calculus Research / SERAPH AI™ spec):

ENTRY:
  Flattener: 2s10s > 100bps AND Fed dot median > current FF by ≥25bps
  Steepener: Inverted curve (2s10s < 0) AND VIX > 20

EXIT:
  Profit: 20bps convergence (50% of target)
  Stop: 20bps adverse move
  Failsafe: Master heartbeat silent >65min → auto-liquidate

SIZING: 1-2x leverage, delta-neutral, vol-targeted <5% ann.
RISK: Correlation cap 0.2, drift veto at 5% projected loss, 2x max leverage
INSTRUMENTS: ZN (10yr), ZF (5yr), ZT (2yr for butterfly in v1.5)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("matrix.strategies.sleeve2")


class CurveTradeType(Enum):
    NONE = "none"
    FLATTENER = "flattener"     # Short ZN, Long ZF — bet on convergence
    STEEPENER = "steepener"     # Long ZN, Short ZF — bet on divergence
    BUTTERFLY = "butterfly"     # Long wings, short belly — v1.5


class CurveRegime(Enum):
    NORMAL = "normal"           # 2s10s 0-100bps
    STEEP = "steep"             # 2s10s > 100bps → flattener
    INVERTED = "inverted"       # 2s10s < 0 → steepener
    FLAT = "flat"               # 2s10s < 20bps → butterfly territory


@dataclass
class CurveMarketData:
    """Market inputs for Sleeve 2."""
    spread_2s10s: float         # bps
    spread_2s5s: float          # bps
    spread_5s10s: float         # bps
    vix: float
    fed_funds_rate: float       # %
    fed_dot_median: float       # %
    zn_price: float
    zf_price: float
    zt_price: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Sleeve2Config:
    """Hard-coded thresholds from strategy spec."""
    # Entry
    flattener_spread_threshold: float = 100.0   # bps
    fed_hike_signal_bps: float = 25.0           # bps gap: dot - FF
    steepener_vix_threshold: float = 20.0

    # Exit
    profit_target_bps: float = 20.0
    stop_loss_bps: float = 20.0

    # Sizing
    max_leverage: float = 2.0
    base_leverage: float = 1.0
    vol_target: float = 0.05                    # 5% ann vol

    # Risk
    max_portfolio_correlation: float = 0.2
    max_projected_loss_pct: float = 0.05        # 5% KPI Guard

    # Regime
    butterfly_spread_threshold: float = 20.0    # bps

    # Heartbeat
    master_heartbeat_timeout_minutes: float = 65.0


class CompressionCurveStrategy:
    """
    Sleeve 2: Yield curve compression & spread trading.

    Mean-reversion on curve shape:
      Wide spread  → flattener (compression)
      Inverted     → steepener (recession → cuts)
      Flat (<20bp) → butterfly (v1.5)
    """

    def __init__(self, config: Optional[Sleeve2Config] = None):
        self.config = config or Sleeve2Config()
        self.current_trade: CurveTradeType = CurveTradeType.NONE
        self.entry_spread: float = 0.0
        self.entry_time: Optional[datetime] = None
        self.last_master_heartbeat: Optional[datetime] = None
        self._trade_count: int = 0
        self._permission_bias: float = 1.0
        self._regime: str = "compression"

    def classify_regime(self, data: CurveMarketData) -> CurveRegime:
        s = data.spread_2s10s
        if s < 0:
            return CurveRegime.INVERTED
        elif s < self.config.butterfly_spread_threshold:
            return CurveRegime.FLAT
        elif s > self.config.flattener_spread_threshold:
            return CurveRegime.STEEP
        else:
            return CurveRegime.NORMAL

    def check_flattener_entry(self, data: CurveMarketData) -> bool:
        """2s10s > 100bps AND dot median > FF by ≥25bps."""
        spread_wide = data.spread_2s10s > self.config.flattener_spread_threshold
        fed_hiking = (data.fed_dot_median - data.fed_funds_rate) * 100 >= self.config.fed_hike_signal_bps

        if spread_wide and fed_hiking:
            logger.info(
                f"Flattener signal: 2s10s={data.spread_2s10s:.1f}bps, "
                f"dot-FF gap={(data.fed_dot_median - data.fed_funds_rate)*100:.0f}bps"
            )
            return True
        return False

    def check_steepener_entry(self, data: CurveMarketData) -> bool:
        """Inverted curve AND VIX > 20."""
        inverted = data.spread_2s10s < 0
        vol_elevated = data.vix > self.config.steepener_vix_threshold

        if inverted and vol_elevated:
            logger.info(
                f"Steepener signal: 2s10s={data.spread_2s10s:.1f}bps, VIX={data.vix:.1f}"
            )
            return True
        return False

    def check_exit(self, data: CurveMarketData) -> tuple[bool, str]:
        """
        Exit checks (in priority order):
        1. Master heartbeat timeout (>65min) → emergency exit
        2. Stop loss (20bps against)
        3. Profit target (20bps in favor)
        """
        if self.current_trade == CurveTradeType.NONE:
            return False, ""

        # Heartbeat check first (safety)
        if self.last_master_heartbeat is not None:
            elapsed = (datetime.now(timezone.utc) - self.last_master_heartbeat).total_seconds() / 60
            if elapsed > self.config.master_heartbeat_timeout_minutes:
                return True, f"master_heartbeat_timeout ({elapsed:.0f}min)"

        # Calculate P&L in bps
        spread_change = data.spread_2s10s - self.entry_spread
        if self.current_trade == CurveTradeType.FLATTENER:
            pnl_bps = -spread_change    # Profit when spread narrows
        elif self.current_trade == CurveTradeType.STEEPENER:
            pnl_bps = spread_change     # Profit when spread widens
        else:
            pnl_bps = 0

        if pnl_bps >= self.config.profit_target_bps:
            return True, f"profit_target (+{pnl_bps:.1f}bps)"

        if pnl_bps <= -self.config.stop_loss_bps:
            return True, f"stop_loss ({pnl_bps:.1f}bps)"

        return False, ""

    def calculate_leverage(self, data: CurveMarketData) -> float:
        """
        Vol-targeted sizing: leverage = vol_target / estimated_trade_vol.
        Capped at 2x.
        """
        estimated_curve_vol = data.vix / 100 * 0.4
        if estimated_curve_vol <= 0:
            return self.config.base_leverage

        target_lev = self.config.vol_target / estimated_curve_vol
        return max(0.0, min(target_lev, self.config.max_leverage))

    def generate_signal(self, market) -> "SleeveSignal":
        """
        Main entry point. Called by Orchestrator.tick().
        Converts MarketState → CurveMarketData → signal.
        """
        from orchestrator import SleeveSignal

        data = self._convert_market_data(market)
        self.last_master_heartbeat = datetime.now(timezone.utc)

        # --- Check exit first ---
        should_exit, reason = self.check_exit(data)
        if should_exit:
            logger.info(f"Sleeve 2 EXIT: {self.current_trade.value} — {reason}")
            self._close_trade(reason)
            return SleeveSignal(
                sleeve_id=2, sleeve_name="Compression & Curve",
                signal=0.0, confidence=1.0,
                instruments=["ZN", "ZF"],
                rationale=f"Exit: {reason}",
            )

        # --- Check entry (if flat) ---
        if self.current_trade == CurveTradeType.NONE:
            regime = self.classify_regime(data)

            if regime == CurveRegime.STEEP and self.check_flattener_entry(data):
                self._open_trade(CurveTradeType.FLATTENER, data)
                lev = self.calculate_leverage(data)
                return SleeveSignal(
                    sleeve_id=2, sleeve_name="Compression & Curve",
                    signal=-1.0 * min(lev / self.config.max_leverage, 1.0),
                    confidence=0.8, instruments=["ZN", "ZF"],
                    rationale=f"Flattener: 2s10s={data.spread_2s10s:.0f}bps, lev={lev:.1f}x",
                )

            elif regime == CurveRegime.INVERTED and self.check_steepener_entry(data):
                self._open_trade(CurveTradeType.STEEPENER, data)
                lev = self.calculate_leverage(data)
                return SleeveSignal(
                    sleeve_id=2, sleeve_name="Compression & Curve",
                    signal=1.0 * min(lev / self.config.max_leverage, 1.0),
                    confidence=0.8, instruments=["ZN", "ZF"],
                    rationale=f"Steepener: 2s10s={data.spread_2s10s:.0f}bps, VIX={data.vix:.0f}",
                )

            elif regime == CurveRegime.FLAT:
                return SleeveSignal(
                    sleeve_id=2, sleeve_name="Compression & Curve",
                    signal=0.0, confidence=0.5,
                    instruments=["ZN", "ZF", "ZT"],
                    rationale=f"Flat regime ({data.spread_2s10s:.0f}bps) — butterfly deferred to v1.5",
                )

        # --- Holding existing position ---
        if self.current_trade == CurveTradeType.FLATTENER:
            return SleeveSignal(
                sleeve_id=2, sleeve_name="Compression & Curve",
                signal=-0.5, confidence=0.7, instruments=["ZN", "ZF"],
                rationale=f"Hold flattener: entry={self.entry_spread:.0f}, now={data.spread_2s10s:.0f}bps",
            )
        elif self.current_trade == CurveTradeType.STEEPENER:
            return SleeveSignal(
                sleeve_id=2, sleeve_name="Compression & Curve",
                signal=0.5, confidence=0.7, instruments=["ZN", "ZF"],
                rationale=f"Hold steepener: entry={self.entry_spread:.0f}, now={data.spread_2s10s:.0f}bps",
            )

        # Default: no signal
        return SleeveSignal(
            sleeve_id=2, sleeve_name="Compression & Curve",
            signal=0.0, confidence=0.0, instruments=[],
            rationale="No signal — waiting for regime conditions",
        )

    # ─── Internal helpers ───────────────────────────────────────────

    def _open_trade(self, trade_type: CurveTradeType, data: CurveMarketData):
        self.current_trade = trade_type
        self.entry_spread = data.spread_2s10s
        self.entry_time = datetime.now(timezone.utc)
        self._trade_count += 1
        logger.info(f"Sleeve 2 ENTRY: {trade_type.value} at {self.entry_spread:.1f}bps (#{self._trade_count})")

    def _close_trade(self, reason: str):
        logger.info(f"Sleeve 2 CLOSE: {self.current_trade.value} — {reason}")
        self.current_trade = CurveTradeType.NONE
        self.entry_spread = 0.0
        self.entry_time = None

    def _convert_market_data(self, market) -> CurveMarketData:
        """
        Convert Orchestrator MarketState → CurveMarketData.
        v1.0: Estimates spreads from TNX and known rates.
        v1.5: Direct FRED DGS2/DGS10 feed.
        """
        ten_yr = market.tnx / 10 if market.tnx > 10 else market.tnx
        ff_rate = self._current_ff_rate()
        two_yr_est = ff_rate + 0.25  # Rough: 2yr tracks FF + term premium

        spread_2s10s = (ten_yr - two_yr_est) * 100  # bps

        return CurveMarketData(
            spread_2s10s=spread_2s10s,
            spread_2s5s=spread_2s10s * 0.4,
            spread_5s10s=spread_2s10s * 0.6,
            vix=market.vix,
            fed_funds_rate=ff_rate,
            fed_dot_median=self._current_dot_median(),
            zn_price=market.zn_price,
            zf_price=market.zf_price,
            timestamp=market.timestamp,
        )

    def _current_ff_rate(self) -> float:
        """v1.0: Manually updated. v1.5: FRED FEDFUNDS."""
        return 4.50  # Update after each FOMC

    def _current_dot_median(self) -> float:
        """v1.0: Manually updated. v1.5: Automated from Fed releases."""
        return 4.00  # Update after each SEP

    def set_permission_bias(self, bias: float):
        """Update from permission vector."""
        self._permission_bias = max(0.0, bias)

    def set_regime(self, regime: str):
        """Update current regime."""
        self._regime = regime

    def get_status(self) -> dict:
        return {
            "sleeve": "Compression & Curve",
            "current_trade": self.current_trade.value,
            "entry_spread": self.entry_spread,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "trade_count": self._trade_count,
        }
