import asyncio
from typing import Dict, Callable, Any
import json

class MarketFeed:
    def __init__(self, venues: list[str] = ["binance", "alpaca"]):
        self.venues = venues
        self.subscriptions: Dict[str, Callable] = {}
        self.is_running = False

    async def connect(self):
        """Simulate WebSocket connection to market data venues."""
        self.is_running = True
        print(f"Connected to {self.venues}")
        # TODO: Implement actual WebSocket connection for Binance/Alpaca
        while self.is_running:
            await asyncio.sleep(1)
            self._simulate_data_stream()

    def subscribe(self, symbol: str, callback: Callable[[Dict], None]):
        """Subscribe to market data for a symbol."""
        self.subscriptions[symbol] = callback

    def _simulate_data_stream(self):
        """Simulate incoming market data."""
        for symbol, callback in self.subscriptions.items():
            mock_data = {
                "symbol": symbol,
                "price": 100.0 + hash(symbol) % 10,
                "volume": 1000.0,
                "timestamp": "now"
            }
            callback(mock_data)

    async def disconnect(self):
        """Disconnect from market data feeds."""
        self.is_running = False
        print("Disconnected from market feeds")
