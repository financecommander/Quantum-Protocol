from typing import Dict, List, Optional
import asyncio

class OrderRouter:
    def __init__(self, venues: List[str], slippage_threshold: float = 0.001):
        self.venues = venues
        self.slippage_threshold = slippage_threshold
        self.venue_latency = {venue: 0.1 for venue in venues}  # Mock latency in seconds
        self.venue_costs = {venue: 0.0002 for venue in venues}  # Mock fee rate

    async def route_order(self, symbol: str, qty: float, side: str) -> Dict:
        """
        Route order to the best venue based on latency, cost, and slippage.
        """
        best_venue = self._select_best_venue(symbol)
        if not best_venue:
            raise ValueError(f"No suitable venue found for {symbol}")

        # Simulate order execution with slippage check
        slippage = self._estimate_slippage(symbol, qty, best_venue)
        if slippage > self.slippage_threshold:
            raise ValueError(f"Slippage {slippage} exceeds threshold {self.slippage_threshold}")

        return {
            "venue": best_venue,
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "status": "routed",
            "slippage": slippage
        }

    def _select_best_venue(self, symbol: str) -> Optional[str]:
        # Simple selection based on lowest combined latency and cost
        scores = {v: self.venue_latency[v] * 0.6 + self.venue_costs[v] * 0.4 for v in self.venues}
        return min(scores, key=scores.get) if scores else None

    def _estimate_slippage(self, symbol: str, qty: float, venue: str) -> float:
        # Mock slippage estimation based on qty and venue
        base_slippage = 0.0005
        qty_factor = qty / 10000  # Arbitrary scaling
        return base_slippage + qty_factor * 0.0001
