"""
MATRIX PROTOCOL -- Mock Trading Runner

Runs the full orchestrator pipeline against simulated market data.
No IBKR connection required. Simulates order fills, tracks PnL,
and produces the GO/NO-GO report.

Usage:
    python brain/mock_trading_runner.py
    python brain/mock_trading_runner.py --days 20
    python brain/mock_trading_runner.py --crisis    (inject a VIX spike)
    python brain/mock_trading_runner.py --fast      (1-tick-per-second)
"""

import asyncio
import json
import logging
import math
import random
import sys
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from orchestrator import Orchestrator, MarketState, SleeveSignal
from paper_trading_runner import (
    PaperTradingConfig,
    SessionMetrics,
    signal_to_orders,
    INSTRUMENT_MAP,
)

logger = logging.getLogger("matrix.mock_runner")


# ─── Market Scenario Generator ─────────────────────────────────

@dataclass
class MarketScenarioConfig:
    """Controls for the simulated market."""
    base_vix: float = 18.0
    base_spx: float = 5200.0
    base_tnx: float = 42.0        # 10Y yield × 10
    base_dxy: float = 104.0
    base_zn: float = 110.0
    base_zf: float = 108.0
    vix_volatility: float = 0.08   # VIX daily vol (% of level)
    spx_volatility: float = 0.01   # SPX daily vol
    ticks_per_day: int = 39        # ~10s ticks in 6.5hr trading day
    inject_crisis: bool = False    # Force a VIX spike mid-simulation
    crisis_day: int = 5            # Which day the crisis hits
    crisis_vix: float = 48.0       # Peak VIX during crisis
    seed: Optional[int] = None     # For reproducibility


class MarketScenarioGenerator:
    """Generates realistic multi-day market data with mean-reverting VIX."""

    def __init__(self, config: Optional[MarketScenarioConfig] = None):
        self.config = config or MarketScenarioConfig()
        self._rng = random.Random(self.config.seed)
        self._vix = self.config.base_vix
        self._spx = self.config.base_spx
        self._tnx = self.config.base_tnx
        self._dxy = self.config.base_dxy
        self._zn = self.config.base_zn
        self._zf = self.config.base_zf
        self._tick = 0
        self._day = 0

    def next_tick(self) -> MarketState:
        """Generate next market state with mean-reverting dynamics."""
        self._tick += 1
        intraday_tick = self._tick % self.config.ticks_per_day
        if intraday_tick == 1 and self._tick > 1:
            self._day += 1

        # Check for crisis injection
        in_crisis = (
            self.config.inject_crisis
            and self._day >= self.config.crisis_day
            and self._day <= self.config.crisis_day + 2
        )

        # VIX: mean-reverting with occasional jumps
        vix_target = self.config.crisis_vix if in_crisis else self.config.base_vix
        mean_revert_speed = 0.15 if not in_crisis else 0.4
        vix_shock = self._rng.gauss(0, self._vix * self.config.vix_volatility / math.sqrt(self.config.ticks_per_day))
        self._vix += mean_revert_speed * (vix_target - self._vix) / self.config.ticks_per_day + vix_shock
        self._vix = max(9.0, min(80.0, self._vix))

        # SPX: inversely correlated with VIX changes
        vix_impact = -0.002 * (self._vix - self.config.base_vix) / self.config.base_vix
        spx_shock = self._rng.gauss(0, self._spx * self.config.spx_volatility / math.sqrt(self.config.ticks_per_day))
        self._spx += vix_impact * self._spx + spx_shock
        self._spx = max(3000.0, self._spx)

        # Rates: slow drift
        rate_shock = self._rng.gauss(0, 0.02)
        self._tnx += rate_shock
        self._tnx = max(10.0, min(60.0, self._tnx))

        # Futures track underlying
        self._zn = 110.0 + (self._tnx - 42.0) * -0.5
        self._zf = 108.0 + (self._tnx - 42.0) * -0.3

        return MarketState(
            timestamp=datetime.now(timezone.utc),
            vix=round(self._vix, 2),
            spx=round(self._spx, 2),
            tnx=round(self._tnx / 10, 3),  # Convert to yield
            dxy=round(self._dxy + self._rng.gauss(0, 0.05), 2),
            es_price=round(self._spx, 2),
            zn_price=round(self._zn, 3),
            zf_price=round(self._zf, 3),
        )

    @property
    def current_day(self) -> int:
        return self._day


# ─── Mock Fill Simulator ──────────────────────────────────────

PRICE_MAP = {
    "ES": 5200, "IEF": 95, "SHY": 82, "ZN": 110, "ZF": 108,
    "SPY": 520, "EURUSD": 1.08, "MU": 100, "CRM": 250, "NOW": 900, "FSLR": 200,
}


def simulate_fill(order: dict, portfolio_value: float) -> dict:
    """
    Simulate an order fill with slippage.
    Returns fill dict with pnl impact estimate.
    """
    symbol = order["symbol"]
    qty = order["quantity"]
    side = order["side"]
    est_price = PRICE_MAP.get(symbol, 100)

    # Simulate slippage: 0.01-0.05% adverse
    slippage_bps = random.uniform(1, 5)
    slippage_mult = 1 + (slippage_bps / 10000) * (1 if side == "BUY" else -1)
    fill_price = est_price * slippage_mult

    # Estimate dollar impact (signal * confidence * allocation capital)
    signal_strength = order.get("signal_strength", 0)
    confidence = order.get("confidence", 0)
    notional = qty * fill_price

    return {
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "fill_price": round(fill_price, 4),
        "notional": round(notional, 2),
        "slippage_bps": round(slippage_bps, 1),
        "filled": True,
    }


# ─── Mock Trading Runner ──────────────────────────────────────

class MockTradingRunner:
    """
    Runs the full orchestrator pipeline against simulated market data.
    No IBKR required.
    """

    def __init__(
        self,
        trading_days: int = 10,
        inject_crisis: bool = False,
        tick_delay: float = 0.0,
        seed: Optional[int] = None,
    ):
        self.trading_days = trading_days
        self.tick_delay = tick_delay

        self.paper_config = PaperTradingConfig(validation_days=trading_days)
        self.orchestrator = Orchestrator(
            portfolio_value=self.paper_config.initial_portfolio_value,
        )
        self.metrics = SessionMetrics(
            peak_value=self.paper_config.initial_portfolio_value,
            trough_value=self.paper_config.initial_portfolio_value,
        )

        self.market_gen = MarketScenarioGenerator(MarketScenarioConfig(
            inject_crisis=inject_crisis,
            seed=seed,
            ticks_per_day=39,  # ~10s intervals across 6.5hr day
        ))

        self._portfolio_value = self.paper_config.initial_portfolio_value
        self._positions: dict[str, float] = {}  # symbol → notional
        self._running = False
        self._log_dir = Path("mock_trading_logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._last_day = -1
        self._daily_start_value = self._portfolio_value

    async def run(self):
        """Run the full mock trading simulation."""
        total_ticks = self.trading_days * self.market_gen.config.ticks_per_day
        self._running = True

        logger.info("=" * 60)
        logger.info("QUANTUM PROTOCOL -- Mock Trading Simulation")
        logger.info("=" * 60)
        logger.info(f"Portfolio: ${self._portfolio_value:,.0f}")
        logger.info(f"Duration: {self.trading_days} trading days ({total_ticks} ticks)")
        logger.info(f"Crisis injection: {self.market_gen.config.inject_crisis}")
        logger.info(f"Seed: {self.market_gen.config.seed}")
        logger.info("=" * 60)

        self.metrics.start_time = datetime.now(timezone.utc)

        for tick_num in range(total_ticks):
            if not self._running:
                break

            await self._tick(tick_num)

            if self.tick_delay > 0:
                await asyncio.sleep(self.tick_delay)

        # Final day close
        if self._last_day >= 0:
            self._on_new_trading_day()

        self._print_report()

    async def _tick(self, tick_num: int):
        """Process one tick."""
        t0 = time.perf_counter()

        # 1. Generate market data
        market = self.market_gen.next_tick()
        t_market = time.perf_counter()

        # 2. Day transition
        current_day = self.market_gen.current_day
        if current_day != self._last_day:
            if self._last_day >= 0:
                self._on_new_trading_day()
            self._last_day = current_day
            self._daily_start_value = self._portfolio_value

        # 3. Run orchestrator
        positions = self.orchestrator.tick(market)
        t_orch = time.perf_counter()

        self.metrics.tick_count += 1

        # 4. Count signals
        for sig in self.orchestrator.signals:
            self.metrics.signal_count += 1
            if sig.sleeve_id in self.metrics.sleeve_signals:
                self.metrics.sleeve_signals[sig.sleeve_id] += 1

        # 5. Generate orders
        alloc_map = {
            1: self.orchestrator.allocation.treasury_yield,
            2: self.orchestrator.allocation.compression_curve,
            3: self.orchestrator.allocation.prop_scaling,
            5: self.orchestrator.allocation.convexity_shield,
        }

        all_orders = []
        for sig in self.orchestrator.signals:
            alloc = alloc_map.get(sig.sleeve_id, 0)
            orders = signal_to_orders(sig, self._portfolio_value, alloc)
            all_orders.extend(orders)

        # 6. Simulate fills
        for order in all_orders:
            fill = simulate_fill(order, self._portfolio_value)
            if fill["filled"]:
                self.metrics.order_count += 1
                self.metrics.fill_count += 1

                # Track position
                sym = fill["symbol"]
                sign = 1 if fill["side"] == "BUY" else -1
                self._positions[sym] = self._positions.get(sym, 0) + sign * fill["notional"]

        # 7. Update portfolio value (mark to market with noise)
        position_pnl = sum(
            v * random.gauss(0, 0.0002)  # Per-tick P&L noise per position
            for v in self._positions.values()
        )
        self._portfolio_value += position_pnl
        self.orchestrator.portfolio_value = self._portfolio_value
        self.metrics.update_drawdown(self._portfolio_value)

        t_total = time.perf_counter()

        # 8. Check abort
        if self.metrics.max_drawdown >= self.paper_config.max_paper_dd_abort:
            logger.critical(
                f"ABORT: DD {self.metrics.max_drawdown:.1%} >= {self.paper_config.max_paper_dd_abort:.0%}"
            )
            self._running = False
            return

        # 9. Log periodically (every 39 ticks = 1 day)
        if tick_num % self.market_gen.config.ticks_per_day == 0 or tick_num < 5:
            feed_ms = (t_market - t0) * 1000
            orch_ms = (t_orch - t_market) * 1000
            total_ms = (t_total - t0) * 1000
            logger.info(
                f"Tick #{self.metrics.tick_count:>4d} | "
                f"Day {current_day:>2d} | "
                f"VIX={market.vix:5.1f} SPX={market.spx:7.1f} | "
                f"Crisis={self.orchestrator.crisis_level.value:<15s} | "
                f"Signals={len(self.orchestrator.signals)} Orders={len(all_orders)} | "
                f"Value=${self._portfolio_value:>10,.0f} DD={self.metrics.max_drawdown:.2%} | "
                f"{total_ms:.1f}ms"
            )

        # 10. Write tick log
        self._log_tick(market, all_orders)

    def _on_new_trading_day(self):
        """Handle day boundary."""
        self.metrics.trading_days += 1

        # Daily return
        if self._daily_start_value > 0:
            daily_return = (self._portfolio_value - self._daily_start_value) / self._daily_start_value
            self.metrics.daily_returns.append(daily_return)

        logger.info(
            f"  DAY {self.metrics.trading_days} CLOSE | "
            f"Value: ${self._portfolio_value:,.0f} | "
            f"DD: {self.metrics.max_drawdown:.2%} | "
            f"Sharpe: {self.metrics.sharpe_ratio:.2f} | "
            f"Positions: {len(self._positions)}"
        )

    def _log_tick(self, market: MarketState, orders: list):
        """Append tick to JSONL log."""
        entry = {
            "timestamp": market.timestamp.isoformat(),
            "tick": self.metrics.tick_count,
            "day": self.market_gen.current_day,
            "vix": market.vix,
            "spx": market.spx,
            "crisis": self.orchestrator.crisis_level.value,
            "portfolio_value": round(self._portfolio_value, 2),
            "max_dd": round(self.metrics.max_drawdown, 6),
            "signals": len(self.orchestrator.signals),
            "orders": len(orders),
        }
        log_file = self._log_dir / f"mock_ticks_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _print_report(self):
        """Print and save the GO/NO-GO report."""
        result = self.metrics.go_no_go(self.paper_config)

        logger.info("")
        logger.info("=" * 60)
        logger.info("GO / NO-GO EVALUATION (Mock Simulation)")
        logger.info("=" * 60)

        for check, passed in result.items():
            if check == "verdict":
                continue
            icon = "PASS" if passed else "FAIL"
            logger.info(f"  [{icon}] {check}: {passed}")

        verdict = result["verdict"]
        logger.info("")
        if verdict == "GO":
            logger.info("  >>> VERDICT: GO -- Pipeline validated")
        else:
            logger.info("  >>> VERDICT: NO-GO -- Review failures above")
        logger.info("")

        logger.info(f"  Total ticks:      {self.metrics.tick_count}")
        logger.info(f"  Trading days:     {self.metrics.trading_days}")
        logger.info(f"  Signals:          {self.metrics.signal_count}")
        logger.info(f"  Orders:           {self.metrics.order_count}")
        logger.info(f"  Fills:            {self.metrics.fill_count}")
        logger.info(f"  Max drawdown:     {self.metrics.max_drawdown:.2%}")
        logger.info(f"  Sharpe ratio:     {self.metrics.sharpe_ratio:.2f}")
        logger.info(f"  Final value:      ${self._portfolio_value:,.0f}")
        logger.info(f"  Return:           {(self._portfolio_value / self.paper_config.initial_portfolio_value - 1):.2%}")
        logger.info(f"  Sleeve signals:   {self.metrics.sleeve_signals}")
        logger.info(f"  Positions held:   {len(self._positions)}")
        logger.info("=" * 60)

        # Save report
        report_file = self._log_dir / "go_no_go_report.json"
        with open(report_file, "w") as f:
            json.dump({
                "mode": "mock_simulation",
                "verdict": verdict,
                "checks": result,
                "metrics": {
                    "tick_count": self.metrics.tick_count,
                    "trading_days": self.metrics.trading_days,
                    "signal_count": self.metrics.signal_count,
                    "order_count": self.metrics.order_count,
                    "fill_count": self.metrics.fill_count,
                    "max_drawdown": self.metrics.max_drawdown,
                    "sharpe_ratio": self.metrics.sharpe_ratio,
                    "final_value": round(self._portfolio_value, 2),
                    "sleeve_signals": self.metrics.sleeve_signals,
                },
                "config": {
                    "trading_days": self.trading_days,
                    "crisis_injected": self.market_gen.config.inject_crisis,
                    "seed": self.market_gen.config.seed,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2)

        logger.info(f"  Report: {report_file}")


# ─── Entry Point ────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    days = 10
    crisis = False
    fast = False
    seed = None

    for arg in sys.argv[1:]:
        if arg == "--crisis":
            crisis = True
        elif arg == "--fast":
            fast = True
        elif arg.startswith("--days"):
            days = int(arg.split("=")[1]) if "=" in arg else int(sys.argv[sys.argv.index(arg) + 1])
        elif arg.startswith("--seed"):
            seed = int(arg.split("=")[1]) if "=" in arg else int(sys.argv[sys.argv.index(arg) + 1])

    runner = MockTradingRunner(
        trading_days=days,
        inject_crisis=crisis,
        tick_delay=0.0 if fast else 0.01,
        seed=seed,
    )
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
