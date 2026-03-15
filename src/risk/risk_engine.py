from typing import Dict, List
import pandas as pd
import numpy as np
from dataclasses import dataclass

@dataclass
class RiskMetrics:
    var_95: float  # Value at Risk at 95% confidence
    max_drawdown: float
    current_exposure: float

class RiskEngine:
    def __init__(self, historical_returns: pd.Series, max_var: float = 0.05, max_drawdown: float = 0.1):
        self.historical_returns = historical_returns
        self.max_var = max_var
        self.max_drawdown = max_drawdown

    def calculate_var(self, confidence: float = 0.95) -> float:
        """Calculate Value at Risk for given confidence level."""
        if len(self.historical_returns) == 0:
            return 0.0
        return float(np.percentile(self.historical_returns, (1 - confidence) * 100))

    def calculate_drawdown(self) -> float:
        """Calculate current drawdown from peak."""
        if len(self.historical_returns) == 0:
            return 0.0
        cumulative = (1 + self.historical_returns).cumprod()
        peak = cumulative.cummax()
        drawdown = (cumulative - peak) / peak
        return float(drawdown.min())

    def position_sizing(self, signal_strength: float, current_exposure: float) -> float:
        """Adjust position size based on risk metrics."""
        var = self.calculate_var()
        if var < -self.max_var:
            return 0.0  # No position if VaR exceeds limit
        risk_adjusted_size = signal_strength * (1 - abs(var) / self.max_var)
        return min(risk_adjusted_size, 1.0 - current_exposure)
