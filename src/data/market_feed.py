import asyncio
from typing import Dict, Callable, Any
import websockets

class MarketFeed:
    def __init__(self, ws_url: str = "wss://stream.binance.com:9443/ws"):
        self.ws_url = ws_url
        self.subscriptions = set()
        self.handlers: Dict[str, Callable] = {}
        self.is_running = False

    async def connect(self):
        self.is_running = True
        async with websockets.connect(self.ws_url) as websocket:
            while self.is_running:
                data = await websocket.recv()
                await self._process_data(data)

    async def subscribe(self, symbol: str, handler: Callable[[Any], None]):
        self.subscriptions.add(symbol)
        self.handlers[symbol] = handler
        # TODO: Send subscription message to WebSocket

    async def _process_data(self, data: Any):
        # Parse incoming data (mocked for now)
        symbol = "BTCUSDT"  # Extract from data in real implementation
        if symbol in self.handlers:
            await self.handlers[symbol](data)

    def stop(self):
        self.is_running = False
