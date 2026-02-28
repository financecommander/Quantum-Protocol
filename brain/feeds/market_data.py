"""
MATRIX PROTOCOL™ v1.0 — Async Market Data Feed

Replaces Rust UDP listener with async REST/WebSocket market data.

v1.0: REST polling (Alpaca free tier, Yahoo Finance fallback)
v1.5: WebSocket streaming for lower latency
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("matrix.feeds.market_data")


class MarketDataFeed(ABC):
    """
    Abstract async market data feed.
    Subclass for specific providers (Alpaca, Yahoo, Mock).
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to data source. Returns True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from data source."""
        ...

    @abstractmethod
    async def get_market_state(self):
        """Fetch current market snapshot. Returns orchestrator.MarketState."""
        ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to symbols for streaming updates."""
        ...


class MockMarketDataFeed(MarketDataFeed):
    """
    Mock feed for testing. Returns configurable market data.
    """

    def __init__(self, default_vix: float = 18.0, default_spx: float = 5000.0):
        self._connected = False
        self._default_vix = default_vix
        self._default_spx = default_spx
        self._tick_count = 0
        self._override_vix: Optional[float] = None
        self._override_depeg: Optional[float] = None
        self._scenario: list[dict] = []
        self._scenario_index = 0

    async def connect(self) -> bool:
        self._connected = True
        logger.info("MockMarketDataFeed connected")
        return True

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("MockMarketDataFeed disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        logger.info(f"MockMarketDataFeed subscribed to {symbols}")

    def set_scenario(self, scenario: list[dict]):
        """
        Set a sequence of market states to replay.
        Each dict can have: vix, spx, depeg_pct, tnx, dxy, es_price, zn_price, zf_price
        """
        self._scenario = scenario
        self._scenario_index = 0

    def set_vix(self, vix: float):
        self._override_vix = vix

    def set_depeg(self, depeg_pct: float):
        self._override_depeg = depeg_pct

    async def get_market_state(self):
        from orchestrator import MarketState

        if not self._connected:
            raise ConnectionError("Feed not connected")

        self._tick_count += 1

        # Use scenario if available
        if self._scenario and self._scenario_index < len(self._scenario):
            data = self._scenario[self._scenario_index]
            self._scenario_index += 1
            return MarketState(
                timestamp=datetime.now(timezone.utc),
                vix=data.get("vix", self._default_vix),
                spx=data.get("spx", self._default_spx),
                tnx=data.get("tnx", 40.0),
                dxy=data.get("dxy", 104.0),
                es_price=data.get("es_price", self._default_spx),
                zn_price=data.get("zn_price", 110.0),
                zf_price=data.get("zf_price", 108.0),
                depeg_pct=data.get("depeg_pct", 0.0),
            )

        # Use overrides or defaults
        return MarketState(
            timestamp=datetime.now(timezone.utc),
            vix=self._override_vix if self._override_vix is not None else self._default_vix,
            spx=self._default_spx,
            tnx=40.0,
            dxy=104.0,
            es_price=self._default_spx,
            zn_price=110.0,
            zf_price=108.0,
            depeg_pct=self._override_depeg if self._override_depeg is not None else 0.0,
        )


class AlpacaMarketDataFeed(MarketDataFeed):
    """
    Alpaca REST API feed (v1.0: polling, v1.5: WebSocket).

    Requires ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.
    Free tier: 200 req/min, delayed data.
    """

    BASE_URL = "https://data.alpaca.markets/v2"
    VIX_SYMBOL = "VIXY"  # VIX proxy ETF (free tier doesn't have $VIX.X)

    def __init__(self, api_key: str = "", secret_key: str = ""):
        import os
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self._connected = False
        self._symbols = ["SPY", "TLT", "IEF", "UUP"]
        self._last_prices: dict[str, float] = {}

    async def connect(self) -> bool:
        if not self._api_key:
            logger.warning("No Alpaca API key — feed will use fallback prices")
            self._connected = True
            return True

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.alpaca.markets/v2/account",
                    headers={
                        "APCA-API-KEY-ID": self._api_key,
                        "APCA-API-SECRET-KEY": self._secret_key,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    self._connected = True
                    logger.info("Alpaca feed connected")
                    return True
                else:
                    logger.error(f"Alpaca auth failed: {resp.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Alpaca connection failed: {e}")
            self._connected = True  # Allow fallback mode
            return True

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("Alpaca feed disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = symbols

    async def get_market_state(self):
        from orchestrator import MarketState

        prices = await self._fetch_prices()

        # Estimate VIX from VIXY price (rough proxy)
        vixy = prices.get("VIXY", 15.0)
        vix_estimate = vixy * 1.2  # Rough scaling

        spy = prices.get("SPY", 500.0)
        spx_estimate = spy * 10  # SPY ~ SPX / 10

        tlt = prices.get("TLT", 90.0)
        tnx_estimate = max(1.0, (100 - tlt) * 0.1 + 3.5)  # Rough inverse

        uup = prices.get("UUP", 26.0)
        dxy_estimate = uup * 4.0  # Rough scaling

        return MarketState(
            timestamp=datetime.now(timezone.utc),
            vix=vix_estimate,
            spx=spx_estimate,
            tnx=tnx_estimate,
            dxy=dxy_estimate,
            es_price=spx_estimate,
            zn_price=110.0,
            zf_price=108.0,
            depeg_pct=0.0,
        )

    async def _fetch_prices(self) -> dict[str, float]:
        """Fetch latest prices for subscribed symbols."""
        if not self._api_key:
            return self._last_prices

        try:
            import httpx
            symbols_str = ",".join(self._symbols + [self.VIX_SYMBOL])
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}/stocks/trades/latest",
                    params={"symbols": symbols_str},
                    headers={
                        "APCA-API-KEY-ID": self._api_key,
                        "APCA-API-SECRET-KEY": self._secret_key,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for sym, trade in data.get("trades", {}).items():
                        self._last_prices[sym] = trade.get("p", 0.0)
        except Exception as e:
            logger.warning(f"Price fetch failed, using last known: {e}")

        return self._last_prices
