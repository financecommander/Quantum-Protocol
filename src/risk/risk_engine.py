from typing import Dict, List
import pandas as pd
import numpy as np

class RiskEngine:
    def __init__(self, var_confidence: float = 0.95, max_drawdown: float = 0.1):
        self.var_confidence = var_confidence
        self.max_drawdown = max_drawdown
        self.returns_history: List[float] = []

    def calculate_var(self) -> float:
        """Calculate Value at Risk (VaR) using historical simulation."""
        if len(self.returns_history) < 100:
            return 0.0  # Not enough data
        returns = np.array(self.returns_history)
        return -np.percentile(returns, (1 - self.var_confidence) * 100)

    def check_drawdown(self, current_pnl: float, peak_pnl: float) -> bool:
        """Check if current drawdown exceeds limit."""
        drawdown = (peak_pnl - current_pnl) / peak_pnl if peak_pnl > 0 else 0.0
        return drawdown <= self.max_drawdown

    def update_returns(self, daily_return: float):
        """Update returns history for risk metrics."""
        self.returns_history.append(daily_return)
        if len(self.returns_history) > 1000:
            self.returns_history.pop(0)

    def calculate_position_size(self, symbol: str, capital: float) -> float:
        """Calculate position size based on risk metrics."""
        var = self.calculate_var()
        if var == 0:
            return capital * 0.01  # Default sizing
        return capital * 0.02 / var  # Risk-adjusted sizing
