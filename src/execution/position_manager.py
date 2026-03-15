from typing import Dict, List
import pandas as pd

class PositionManager:
    def __init__(self, max_position_size: float = 1000000.0, max_risk_per_trade: float = 0.02):
        self.positions: Dict[str, Dict] = {}
        self.max_position_size = max_position_size
        self.max_risk_per_trade = max_risk_per_trade
        self.pnl_history = pd.DataFrame(columns=["timestamp", "symbol", "pnl"])

    def update_position(self, symbol: str, qty: float, price: float, side: str) -> bool:
        if not self._check_risk_limits(symbol, qty, price):
            return False

        if symbol not in self.positions:
            self.positions[symbol] = {"qty": 0.0, "avg_price": 0.0, "entry_value": 0.0}

        pos = self.positions[symbol]
        if side == "buy":
            new_qty = pos["qty"] + qty
            new_value = pos["entry_value"] + (qty * price)
            pos["avg_price"] = new_value / new_qty if new_qty != 0 else 0
            pos["qty"] = new_qty
            pos["entry_value"] = new_value
        else:  # sell
            pos["qty"] -= qty
            if pos["qty"] == 0:
                pos["avg_price"] = 0
                pos["entry_value"] = 0
        return True

    def calculate_pnl(self, symbol: str, current_price: float) -> float:
        if symbol not in self.positions or self.positions[symbol]["qty"] == 0:
            return 0.0
        pos = self.positions[symbol]
        return pos["qty"] * (current_price - pos["avg_price"])

    def _check_risk_limits(self, symbol: str, qty: float, price: float) -> bool:
        trade_value = qty * price
        if trade_value > self.max_position_size:
            return False
        if trade_value > self.max_risk_per_trade * self.max_position_size:
            return False
        return True
