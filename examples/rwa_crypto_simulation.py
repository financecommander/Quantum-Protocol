#!/usr/bin/env python3
"""
RWA/Crypto HFT Simulation

Simulates cross-venue arbitrage detection and execution for crypto pairs.
Demonstrates:
- Spread monitoring across venues
- Arbitrage opportunity detection
- Execution with fees
- Profit tracking
"""

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class CryptoPair:
    symbol_id: int
    symbol: str
    spot_price: float
    futures_price: float
    funding_rate: float
    volume_24h: float
    last_update_ts: float

@dataclass
class ArbitrageOpportunity:
    timestamp: float
    symbol_id: int
    venue_a_price: float
    venue_b_price: float
    spread_bps: float
    profit_potential: float
    confidence: float

class RwaCryptoSimulation:
    def __init__(self):
        self.pairs = {
            'BTC': CryptoPair(1, 'BTC', 50000.0, 50000.0, 0.01, 1e9, 0.0),
            'ETH': CryptoPair(2, 'ETH', 3000.0, 3000.0, 0.01, 5e8, 0.0),
            'SOL': CryptoPair(3, 'SOL', 100.0, 100.0, 0.01, 1e8, 0.0),
        }
        self.opportunities = []
        self.executions = []
        self.total_profit = 0.0
        
        self.MIN_SPREAD_BPS = 5.0
        self.FEE_BPS = 2.0
    
    def update_prices(self, timestamp: float, volatility=0.001):
        """Update prices with random walk"""
        for symbol, pair in self.pairs.items():
            # Spot price random walk
            spot_change = np.random.normal(0, volatility * pair.spot_price)
            pair.spot_price += spot_change
            
            # Futures with occasional divergence
            futures_change = spot_change + np.random.normal(0, volatility * pair.spot_price * 0.5)
            pair.futures_price += futures_change
            
            # Ensure positive prices
            pair.spot_price = max(100.0, pair.spot_price)
            pair.futures_price = max(100.0, pair.futures_price)
            
            pair.last_update_ts = timestamp
    
    def scan_opportunities(self, timestamp: float) -> int:
        """Scan for arbitrage opportunities"""
        found = 0
        
        for symbol, pair in self.pairs.items():
            spread_pct = ((pair.futures_price - pair.spot_price) / pair.spot_price) * 100.0
            spread_bps = spread_pct * 100.0
            
            # Check if spread exceeds minimum + fees
            if abs(spread_bps) > self.MIN_SPREAD_BPS + self.FEE_BPS:
                profit_potential = abs(spread_bps) - self.FEE_BPS
                
                # Calculate confidence (simplified)
                age_penalty = 1.0  # All recent in simulation
                volume_score = min(1.0, pair.volume_24h / 1e9)
                confidence = (age_penalty + volume_score) / 2.0
                
                opportunity = ArbitrageOpportunity(
                    timestamp=timestamp,
                    symbol_id=pair.symbol_id,
                    venue_a_price=pair.spot_price,
                    venue_b_price=pair.futures_price,
                    spread_bps=spread_bps,
                    profit_potential=profit_potential,
                    confidence=confidence
                )
                
                self.opportunities.append(opportunity)
                found += 1
        
        return found
    
    def execute_best_opportunity(self, timestamp: float) -> Optional[float]:
        """Execute the best opportunity if available"""
        if not self.opportunities:
            return None
        
        # Find best risk-adjusted opportunity
        best = max(self.opportunities, key=lambda o: o.profit_potential * o.confidence)
        
        # Execute
        profit = best.profit_potential
        self.total_profit += profit
        self.executions.append((timestamp, best.symbol_id, profit))
        
        # Remove executed opportunity
        self.opportunities = [o for o in self.opportunities if o != best]
        
        return profit
    
    def clear_stale_opportunities(self, timestamp: float, max_age_ms=10.0):
        """Remove stale opportunities"""
        cutoff = timestamp - max_age_ms * 1e6  # Convert ms to ns
        self.opportunities = [o for o in self.opportunities if o.timestamp > cutoff]
    
    def run(self, num_ticks=1000, tick_interval_ms=1.0):
        """Run the simulation"""
        timestamps = []
        spreads_btc = []
        spreads_eth = []
        spreads_sol = []
        opportunity_counts = []
        cumulative_profit = []
        
        current_profit = 0.0
        
        for tick in range(num_ticks):
            timestamp = tick * tick_interval_ms * 1e6  # Convert ms to ns
            
            # Update prices
            self.update_prices(timestamp)
            
            # Scan for opportunities
            found = self.scan_opportunities(timestamp)
            
            # Execute if profitable
            profit = self.execute_best_opportunity(timestamp)
            if profit:
                current_profit += profit
            
            # Clear stale opportunities
            self.clear_stale_opportunities(timestamp)
            
            # Record metrics
            timestamps.append(tick * tick_interval_ms)
            btc_spread = ((self.pairs['BTC'].futures_price - self.pairs['BTC'].spot_price) 
                         / self.pairs['BTC'].spot_price) * 10000  # bps
            eth_spread = ((self.pairs['ETH'].futures_price - self.pairs['ETH'].spot_price) 
                         / self.pairs['ETH'].spot_price) * 10000
            sol_spread = ((self.pairs['SOL'].futures_price - self.pairs['SOL'].spot_price) 
                         / self.pairs['SOL'].spot_price) * 10000
            
            spreads_btc.append(btc_spread)
            spreads_eth.append(eth_spread)
            spreads_sol.append(sol_spread)
            opportunity_counts.append(len(self.opportunities))
            cumulative_profit.append(current_profit)
        
        return timestamps, spreads_btc, spreads_eth, spreads_sol, opportunity_counts, cumulative_profit

def main():
    """Run simulation and plot results"""
    print("Running RWA/Crypto HFT Simulation...")
    sim = RwaCryptoSimulation()
    timestamps, btc, eth, sol, opps, profit = sim.run(num_ticks=1000)
    
    # Create plots
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    
    # Plot 1: Spreads
    axes[0].plot(timestamps, btc, label='BTC', linewidth=0.5, alpha=0.7)
    axes[0].plot(timestamps, eth, label='ETH', linewidth=0.5, alpha=0.7)
    axes[0].plot(timestamps, sol, label='SOL', linewidth=0.5, alpha=0.7)
    axes[0].axhline(y=7, color='g', linestyle='--', label='Min Spread + Fees (7bp)')
    axes[0].axhline(y=-7, color='g', linestyle='--')
    axes[0].set_ylabel('Spread (bps)')
    axes[0].set_title('RWA/Crypto HFT: Spot-Futures Spread')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # Plot 2: Pending Opportunities
    axes[1].plot(timestamps, opps, drawstyle='steps-post', color='orange')
    axes[1].set_ylabel('Pending Opportunities')
    axes[1].set_title('RWA/Crypto HFT: Active Opportunities')
    axes[1].grid(True, alpha=0.3)
    
    # Plot 3: Cumulative Profit
    axes[2].plot(timestamps, profit, color='green', linewidth=1.5)
    axes[2].set_xlabel('Time (ms)')
    axes[2].set_ylabel('Cumulative Profit (bps)')
    axes[2].set_title('RWA/Crypto HFT: Cumulative Profit')
    axes[2].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('rwa_crypto_simulation.png', dpi=150)
    print(f"✓ Simulation complete. Plots saved to rwa_crypto_simulation.png")
    
    # Print statistics
    print(f"\n=== Simulation Statistics ===")
    print(f"Total ticks: {len(timestamps)}")
    print(f"Total executions: {len(sim.executions)}")
    print(f"Total profit: {sim.total_profit:.2f} bps")
    print(f"Avg profit per trade: {sim.total_profit / max(1, len(sim.executions)):.2f} bps")
    print(f"Max pending opportunities: {max(opps)}")

if __name__ == "__main__":
    main()
