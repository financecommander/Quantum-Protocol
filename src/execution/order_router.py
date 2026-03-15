from typing import Dict, List, Optional
import asyncio
from dataclasses import dataclass

@dataclass
class Order:
    symbol: str
    quantity: float
    side: str  # 'buy' or 'sell'
    venue: Optional[str] = None
    price: Optional[float] = None

class OrderRouter:
    def __init__(self, venues: List[str]):
        self.venues = venues
        self.venue_latency = {venue: 0.1 for venue in venues}  # Mock latency
        self.venue_liquidity = {venue: 1.0 for venue in venues}  # Mock liquidity

    async def route_order(self, order: Order) -> Dict[str, any]:
        """Smart route order to best venue based on latency and liquidity."""
        if order.venue:
            selected_venue = order.venue
        else:
            selected_venue = self._select_best_venue(order.symbol)

        # Simulate slippage based on venue liquidity
        slippage = self._calculate_slippage(order.quantity, selected_venue)
        execution_price = order.price * (1 + slippage) if order.price else None

        # TODO: Connect to actual venue API for order submission
        await asyncio.sleep(0.1)  # Simulate async network delay

        return {
            "order_id": f"mock_{id(order)}",
            "symbol": order.symbol,
            "quantity": order.quantity,
            "side": order.side,
            "venue": selected_venue,
            "execution_price": execution_price
        }

    def _select_best_venue(self, symbol: str) -> str:
        """Select venue with best liquidity and lowest latency."""
        scores = {
            venue: (1 / self.venue_latency[venue]) * self.venue_liquidity[venue]
            for venue in self.venues
        }
        return max(scores, key=scores.get)

    def _calculate_slippage(self, quantity: float, venue: str) -> float:
        """Calculate slippage based on quantity and venue liquidity."""
        liquidity = self.venue_liquidity[venue]
        return 0.001 * (quantity / liquidity)  # Simplified slippage model
