from typing import Dict, List
import pandas as pd
from dataclasses import dataclass

@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    current_price: float = 0.0

class PositionManager:
    def __init__(self, position_limit: float = 1000000.0):
        self.positions: Dict[str, Position] = {}
        self.position_limit = position_limit

    def update_position(self, symbol: str, quantity: float, price: float) -> None:
        """Update or create a position for a symbol."""
        if symbol in self.positions:
            pos = self.positions[symbol]
            avg_price = (pos.quantity * pos.entry_price + quantity * price) / (pos.quantity + quantity)
            pos.quantity += quantity
            pos.entry_price = avg_price
            if pos.quantity == 0:
                del self.positions[symbol]
        else:
            self.positions[symbol] = Position(symbol=symbol, quantity=quantity, entry_price=price)

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update current market price for P&L calculation."""
        if symbol in self.positions:
            self.positions[symbol].current_price = price

    def get_pnl(self) -> float:
        """Calculate unrealized P&L across all positions."""
        total_pnl = 0.0
        for pos in self.positions.values():
            total_pnl += pos.quantity * (pos.current_price - pos.entry_price)
        return total_pnl

    def check_position_limits(self) -> bool:
        """Check if total position value exceeds risk limits."""
        total_value = sum(abs(pos.quantity * pos.current_price) for pos in self.positions.values())
        return total_value <= self.position_limit
