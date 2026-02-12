#!/usr/bin/env python3
"""
Tail Hedging Simulation

Simulates VIX monitoring and dynamic hedge rebalancing.
Demonstrates:
- VIX regime classification
- Tail risk detection
- Hedge sizing based on risk level
- Portfolio protection during crisis
"""

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import List
from enum import Enum

class TailRiskLevel(Enum):
    NORMAL = 0
    ELEVATED = 1
    HIGH = 2
    CRITICAL = 3

class HedgeInstrument(Enum):
    VIX_CALL = 1
    SPX_PUT = 2
    TAIL_FUND = 3
    TREASURY = 4

@dataclass
class HedgePosition:
    instrument: HedgeInstrument
    notional: float
    strike: float
    expiry_days: int
    cost_bps: float
    delta: float
    vega: float

class TailHedgingSimulation:
    def __init__(self, portfolio_value=1_000_000.0):
        self.portfolio_value = portfolio_value
        self.positions: List[HedgePosition] = []
        self.risk_level = TailRiskLevel.NORMAL
        self.vix = 15.0
        self.vix_ema = 15.0
        self.total_hedge_cost = 0.0
        self.portfolio_returns = []
        self.hedge_pnl = []
        
        self.VIX_THRESHOLD_ELEVATED = 20.0
        self.VIX_THRESHOLD_HIGH = 30.0
        self.VIX_THRESHOLD_CRITICAL = 45.0
        self.EMA_ALPHA = 0.1
    
    def update_vix(self, new_vix: float) -> bool:
        """Update VIX and detect regime change"""
        old_level = self.risk_level
        
        # Update EMA
        self.vix_ema = self.EMA_ALPHA * new_vix + (1 - self.EMA_ALPHA) * self.vix_ema
        self.vix = new_vix
        
        # Classify risk
        if new_vix >= self.VIX_THRESHOLD_CRITICAL:
            self.risk_level = TailRiskLevel.CRITICAL
        elif new_vix >= self.VIX_THRESHOLD_HIGH:
            self.risk_level = TailRiskLevel.HIGH
        elif new_vix >= self.VIX_THRESHOLD_ELEVATED:
            self.risk_level = TailRiskLevel.ELEVATED
        else:
            self.risk_level = TailRiskLevel.NORMAL
        
        return self.risk_level != old_level
    
    def recommended_hedge_notional(self) -> float:
        """Calculate recommended hedge size"""
        hedge_pct = {
            TailRiskLevel.NORMAL: 0.01,
            TailRiskLevel.ELEVATED: 0.03,
            TailRiskLevel.HIGH: 0.05,
            TailRiskLevel.CRITICAL: 0.10,
        }
        return self.portfolio_value * hedge_pct[self.risk_level]
    
    def current_hedge_notional(self) -> float:
        """Calculate current hedge notional"""
        return sum(p.notional for p in self.positions)
    
    def total_delta(self) -> float:
        """Calculate portfolio delta from hedges"""
        return sum(p.delta for p in self.positions)
    
    def total_vega(self) -> float:
        """Calculate portfolio vega from hedges"""
        return sum(p.vega for p in self.positions)
    
    def rebalance_hedges(self):
        """Rebalance hedges to match recommended size"""
        recommended = self.recommended_hedge_notional()
        current = self.current_hedge_notional()
        
        # Remove expired hedges
        self.positions = [p for p in self.positions if p.expiry_days > 0]
        
        # Add hedges if under-hedged (>10% deviation)
        if current < recommended * 0.9:
            new_notional = recommended - current
            
            # Choose instrument based on risk level
            if self.risk_level == TailRiskLevel.CRITICAL:
                instrument = HedgeInstrument.VIX_CALL
                delta = 0.5
                vega = 0.8
                cost = 100.0
            elif self.risk_level == TailRiskLevel.HIGH:
                instrument = HedgeInstrument.SPX_PUT
                delta = -0.4
                vega = 0.6
                cost = 75.0
            else:
                instrument = HedgeInstrument.SPX_PUT
                delta = -0.2
                vega = 0.4
                cost = 50.0
            
            new_position = HedgePosition(
                instrument=instrument,
                notional=new_notional,
                strike=0.0,  # Simplified
                expiry_days=30,
                cost_bps=cost,
                delta=delta,
                vega=vega
            )
            
            self.positions.append(new_position)
            self.total_hedge_cost += cost * new_notional / 10000  # bps to dollars
    
    def calculate_hedge_pnl(self, market_return: float, vix_change: float) -> float:
        """Calculate P&L from hedges"""
        pnl = 0.0
        for pos in self.positions:
            # Simplified P&L: delta * market + vega * vix
            pnl += pos.notional * (pos.delta * market_return / 100 + pos.vega * vix_change / 100)
        return pnl
    
    def age_positions(self):
        """Age hedge positions by 1 day"""
        for pos in self.positions:
            pos.expiry_days = max(0, pos.expiry_days - 1)
    
    def simulate_market(self, day: int, crisis_day_start=500, crisis_day_duration=100) -> tuple:
        """Simulate market returns with crisis period"""
        # Normal volatility
        base_vol = 0.01
        
        # Crisis period
        if crisis_day_start <= day < crisis_day_start + crisis_day_duration:
            # VIX spike
            target_vix = 50.0 + np.random.normal(0, 5)
            vix_change = target_vix - self.vix
            self.update_vix(target_vix)
            
            # Market drop
            market_return = -np.random.exponential(2.0)
        else:
            # Normal regime
            vix_change = np.random.normal(0, 1.0)
            self.update_vix(max(10.0, self.vix + vix_change))
            market_return = np.random.normal(0.05, base_vol * 100)  # Daily return in %
        
        return market_return, vix_change
    
    def run(self, num_days=1000):
        """Run the simulation"""
        timestamps = []
        vix_history = []
        risk_levels = []
        hedge_notionals = []
        portfolio_values = []
        hedge_pnl_history = []
        total_deltas = []
        total_vegas = []
        
        for day in range(num_days):
            # Simulate market
            market_return, vix_change = self.simulate_market(day)
            
            # Rebalance hedges
            self.rebalance_hedges()
            
            # Calculate P&L
            hedge_pnl = self.calculate_hedge_pnl(market_return, vix_change)
            portfolio_pnl = self.portfolio_value * market_return / 100
            
            # Update portfolio value
            self.portfolio_value += portfolio_pnl + hedge_pnl
            
            # Age positions
            self.age_positions()
            
            # Record metrics
            timestamps.append(day)
            vix_history.append(self.vix)
            risk_levels.append(self.risk_level.value)
            hedge_notionals.append(self.current_hedge_notional())
            portfolio_values.append(self.portfolio_value)
            hedge_pnl_history.append(hedge_pnl)
            total_deltas.append(self.total_delta())
            total_vegas.append(self.total_vega())
        
        return (timestamps, vix_history, risk_levels, hedge_notionals, 
                portfolio_values, hedge_pnl_history, total_deltas, total_vegas)

def main():
    """Run simulation and plot results"""
    print("Running Tail Hedging Simulation...")
    sim = TailHedgingSimulation(portfolio_value=1_000_000.0)
    (timestamps, vix, risk, hedges, portfolio, hedge_pnl, 
     deltas, vegas) = sim.run(num_days=1000)
    
    # Create plots
    fig, axes = plt.subplots(4, 1, figsize=(12, 12))
    
    # Plot 1: VIX and Risk Level
    ax1 = axes[0]
    ax2 = ax1.twinx()
    
    ax1.plot(timestamps, vix, color='blue', linewidth=1, label='VIX')
    ax1.axhline(y=20, color='y', linestyle='--', alpha=0.5)
    ax1.axhline(y=30, color='orange', linestyle='--', alpha=0.5)
    ax1.axhline(y=45, color='r', linestyle='--', alpha=0.5)
    ax1.set_ylabel('VIX', color='blue')
    ax1.tick_params(axis='y', labelcolor='blue')
    
    ax2.plot(timestamps, risk, color='red', linewidth=0.5, alpha=0.7, drawstyle='steps-post')
    ax2.set_ylabel('Risk Level', color='red')
    ax2.tick_params(axis='y', labelcolor='red')
    ax2.set_ylim([-0.5, 3.5])
    
    axes[0].set_title('Tail Hedging: VIX and Risk Level')
    axes[0].grid(True, alpha=0.3)
    
    # Plot 2: Hedge Notional
    axes[1].plot(timestamps, np.array(hedges) / 1000, color='purple', linewidth=1)
    axes[1].set_ylabel('Hedge Notional ($k)')
    axes[1].set_title('Tail Hedging: Total Hedge Notional')
    axes[1].grid(True, alpha=0.3)
    
    # Plot 3: Portfolio Value
    axes[2].plot(timestamps, np.array(portfolio) / 1000, color='green', linewidth=1)
    axes[2].set_ylabel('Portfolio Value ($k)')
    axes[2].set_title('Tail Hedging: Protected Portfolio Value')
    axes[2].grid(True, alpha=0.3)
    
    # Plot 4: Greeks
    ax3 = axes[3]
    ax4 = ax3.twinx()
    
    ax3.plot(timestamps, deltas, color='blue', linewidth=1, label='Delta')
    ax3.set_ylabel('Delta', color='blue')
    ax3.tick_params(axis='y', labelcolor='blue')
    
    ax4.plot(timestamps, vegas, color='orange', linewidth=1, label='Vega')
    ax4.set_ylabel('Vega', color='orange')
    ax4.tick_params(axis='y', labelcolor='orange')
    
    axes[3].set_xlabel('Time (days)')
    axes[3].set_title('Tail Hedging: Portfolio Greeks')
    axes[3].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('tail_hedging_simulation.png', dpi=150)
    print(f"✓ Simulation complete. Plots saved to tail_hedging_simulation.png")
    
    # Print statistics
    print(f"\n=== Simulation Statistics ===")
    print(f"Total days: {len(timestamps)}")
    print(f"Starting portfolio: ${1_000_000:,.0f}")
    print(f"Ending portfolio: ${portfolio[-1]:,.0f}")
    print(f"Total return: {((portfolio[-1] / 1_000_000) - 1) * 100:.2f}%")
    print(f"Total hedge cost: ${sim.total_hedge_cost:,.0f}")
    print(f"Max VIX: {max(vix):.2f}")
    print(f"Avg hedge notional: ${np.mean(hedges):,.0f}")

if __name__ == "__main__":
    main()
