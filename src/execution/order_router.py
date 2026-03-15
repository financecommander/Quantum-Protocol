from typing import Dict, List, Optional
import asyncio

class OrderRouter:
    def __init__(self, venues: List[str], slippage_threshold: float = 0.001):
        self.venues = venues
        self.slippage_threshold = slippage_threshold
        self.venue_latency = {venue: 0.1 for venue in venues}  # Mock latency in seconds
        self.venue_costs = {venue: 0.0002 for venue in venues}  # Mock fee rate

    async def route_order(self, symbol: str, quantity: float, side: str) -> Dict:
        """Route order to the best venue based on latency, cost, and slippage."""
        best_venue = self._select_best_venue(symbol)
        if not best_venue:
            return {"status": "failed", "reason": "No suitable venue", "venue": None}

        # Simulate order execution with slippage check
        slippage = await self._estimate_slippage(best_venue, symbol, quantity)
        if slippage > self.slippage_threshold:
            return {"status": "rejected", "reason": "High slippage", "venue": best_venue, "slippage": slippage}

        # TODO: Integrate with actual venue API for order placement
        return {
            "status": "executed",
            "venue": best_venue,
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "slippage": slippage
        }

    def _select_best_venue(self, symbol: str) -> Optional[str]:
        """Select venue with lowest combined latency and cost score."""
        scores = {v: self.venue_latency[v] * 0.6 + self.venue_costs[v] * 0.4 for v in self.venues}
        return min(scores, key=scores.get) if scores else None

    async def _estimate_slippage(self, venue: str, symbol: str, quantity: float) -> float:
        """Mock slippage estimation based on quantity and venue."""
        await asyncio.sleep(0.01)  # Simulate async API call
        return quantity * 0.0001  # Linear mock slippage
