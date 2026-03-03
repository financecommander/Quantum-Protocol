"""
MATRIX PROTOCOL™ v1.0 — Quantum Engine (Pure Async Python)

Main entry point replacing Rust src/engine/main.rs + coordinator.rs.

Lifecycle:
  1. Load config from quantum_protocol.toml
  2. Connect to market data feed
  3. Run orchestrator tick loop
  4. Optionally connect to IBKR for execution
  5. Expose state for dashboards
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("matrix.engine")


class QuantumEngine:
    """
    Core engine — replaces Rust Engine + Coordinator.

    Wires together: feed → orchestrator → risk → execution → audit.
    """

    def __init__(
        self,
        config_path: str = "config/quantum_protocol.toml",
        portfolio_value: float = 50_000.0,
        tick_interval: float = 10.0,
    ):
        self.config_path = config_path
        self.portfolio_value = portfolio_value
        self.tick_interval = tick_interval
        self._running = False
        self._ticks_processed = 0
        self._start_time: Optional[float] = None
        self._last_tick_time: Optional[float] = None
        self._last_market = None

        # Core components (lazy init)
        self.orchestrator = None
        self.feed = None
        self.audit = None
        self.order_manager = None
        self._task: Optional[asyncio.Task] = None

        self._init_components()

    def _init_components(self):
        """Initialize core components."""
        from orchestrator import Orchestrator
        from compliance.audit_logger import AuditLogger

        self.orchestrator = Orchestrator(portfolio_value=self.portfolio_value)
        self.audit = AuditLogger()

        logger.info("QuantumEngine components initialized")

    def set_feed(self, feed):
        """Inject a market data feed (for testing or provider selection)."""
        self.feed = feed

    async def start(self) -> None:
        """Start the engine. Non-blocking — launches tick loop as async task."""
        if self._running:
            logger.warning("Engine already running")
            return

        if self.feed is None:
            from feeds.market_data import MockMarketDataFeed
            logger.warning("No feed configured — using MockMarketDataFeed")
            self.feed = MockMarketDataFeed()

        connected = await self.feed.connect()
        if not connected:
            raise ConnectionError("Failed to connect to market data feed")

        self._running = True
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._tick_loop())
        logger.info("QuantumEngine started")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self.feed:
            await self.feed.disconnect()

        logger.info(
            f"QuantumEngine stopped after {self._ticks_processed} ticks "
            f"({self.uptime_seconds:.1f}s uptime)"
        )

    async def _tick_loop(self) -> None:
        """Main loop: fetch data → orchestrate → log → (execute)."""
        while self._running:
            try:
                await self._process_tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tick error: {e}", exc_info=True)
                self.audit.log_risk_event(
                    "TICK_ERROR", signal_value=0.0, risk_flag=1,
                    error=str(e),
                )

            await asyncio.sleep(self.tick_interval)

    async def _process_tick(self) -> dict:
        """Process a single tick. Returns target positions."""
        t0 = time.perf_counter()

        # 1. Fetch market data
        market = await self.feed.get_market_state()
        t_feed = time.perf_counter()
        self._last_market = market

        # 2. Run orchestrator
        positions = self.orchestrator.tick(market)
        t_orch = time.perf_counter()

        # 3. Log crisis transitions
        crisis = self.orchestrator.crisis_level.value
        if self._ticks_processed == 0 or self._last_crisis != crisis:
            self.audit.log_risk_event(
                "CRISIS_TRANSITION",
                signal_value=market.vix,
                risk_flag={"Normal": 0, "SmartBunker": 2, "SurgicalSniper": 3}.get(crisis, 0),
                crisis_level=crisis,
                depeg_pct=market.depeg_pct,
            )
            self._last_crisis = crisis

        self._ticks_processed += 1
        self._last_tick_time = time.monotonic()
        t_total = time.perf_counter()

        # Latency instrumentation
        feed_ms = (t_feed - t0) * 1000
        orch_ms = (t_orch - t_feed) * 1000
        total_ms = (t_total - t0) * 1000
        self._last_tick_latency = {
            "feed_ms": round(feed_ms, 2),
            "orchestrator_ms": round(orch_ms, 2),
            "total_ms": round(total_ms, 2),
        }
        logger.info(
            f"Tick #{self._ticks_processed} latency: "
            f"feed={feed_ms:.1f}ms orch={orch_ms:.1f}ms total={total_ms:.1f}ms | "
            f"VIX={market.vix:.1f} crisis={crisis}"
        )

        return positions

    @property
    def _last_crisis(self) -> str:
        return getattr(self, "_last_crisis_val", "")

    @_last_crisis.setter
    def _last_crisis(self, value: str):
        self._last_crisis_val = value

    @property
    def uptime_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    def get_state(self) -> dict:
        """Full engine state for dashboards."""
        orch = self.orchestrator

        # SERAPH AI regime data
        seraph = {}
        if orch and orch._seraph and orch._seraph.state:
            s = orch._seraph.state
            seraph = {
                "regime": s.regime.value,
                "confidence": round(s.confidence, 2),
                "days_in_regime": s.days_in_regime,
                "previous_regime": s.previous_regime.value if s.previous_regime else None,
                "vix": round(s.signals.vix, 2),
                "adx": round(s.signals.adx, 1),
                "spx_20d_return": round(s.signals.spx_20d_return, 4),
            }

        # Latest market snapshot
        market = {}
        if hasattr(self, "_last_market") and self._last_market:
            m = self._last_market
            market = {
                "vix": m.vix,
                "spx": m.spx,
                "tnx": m.tnx,
                "dxy": m.dxy,
                "depeg_pct": m.depeg_pct,
                "timestamp": m.timestamp.isoformat(),
            }

        # Permission vector biases
        permission_vector = {}
        if orch and orch._current_vector:
            pv = orch._current_vector
            permission_vector = {
                "regime": pv.regime,
                "sleeve_biases": {
                    1: pv.get_sleeve_bias(1),
                    2: pv.get_sleeve_bias(2),
                    3: pv.get_sleeve_bias(3),
                    5: pv.get_sleeve_bias(5),
                },
                "requires_human_approval": pv.requires_human_approval,
            }

        return {
            "running": self._running,
            "ticks_processed": self._ticks_processed,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "crisis_level": orch.crisis_level.value if orch else "Unknown",
            "portfolio_value": self.portfolio_value,
            "signals": [
                {
                    "sleeve_id": s.sleeve_id,
                    "sleeve_name": s.sleeve_name,
                    "signal": s.signal,
                    "confidence": s.confidence,
                    "instruments": s.instruments,
                    "rationale": s.rationale,
                }
                for s in (orch.signals if orch else [])
            ],
            "allocation": {
                "treasury_yield": orch.allocation.treasury_yield,
                "compression_curve": orch.allocation.compression_curve,
                "prop_scaling": orch.allocation.prop_scaling,
                "convexity_shield": orch.allocation.convexity_shield,
                "cash": orch.allocation.cash,
            } if orch else {},
            "seraph": seraph,
            "market": market,
            "permission_vector": permission_vector,
            "kill_switch": orch.is_killed if orch else False,
            "human_approval_pending": orch._human_approval_pending if orch else False,
            "audit_summary": self.audit.get_compliance_summary() if self.audit else {},
            "tick_latency": getattr(self, "_last_tick_latency", {}),
        }


async def main():
    """CLI entry point: python -m brain.engine"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    engine = QuantumEngine()
    logger.info("Starting Quantum Protocol Engine...")

    try:
        await engine.start()
        # Run until interrupted
        while engine._running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
