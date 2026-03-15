import pandas as pd
import numpy as np
from typing import Dict, Optional

class RiskEngine:
    def __init__(self, var_confidence: float = 0.95, max_drawdown: float = 0.1):
        self.var_confidence = var_confidence
        self.max_drawdown = max_drawdown
        self.returns_history = pd.Series(dtype=float)

    def calculate_var(self, portfolio_returns: pd.Series) -> float:
        """
        Calculate Value at Risk (VaR) for the portfolio.
        """
        if len(portfolio_returns) < 10:
            return 0.0
        return np.percentile(portfolio_returns, (1 - self.var_confidence) * 100)

    def check_drawdown(self, equity_curve: pd.Series) -> bool:
        """
        Check if current drawdown exceeds maximum allowed.
        """
        if len(equity_curve) < 2:
            return True
        peak = equity_curve.cummax()
        drawdown = (peak - equity_curve) / peak
        return drawdown.max() <= self.max_drawdown

    def position_size(self, symbol: str, signal_strength: float, volatility: float) -> float:
        """
        Calculate position size based on risk parameters and volatility.
        """
        risk_per_unit = volatility * signal_strength
        if risk_per_unit == 0:
            return 0.0
        target_risk = 0.01  # 1% portfolio risk per position
        return target_risk / risk_per_unit * 1000  # Scaled position size
