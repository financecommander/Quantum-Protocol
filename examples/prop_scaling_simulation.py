#!/usr/bin/env python3
"""
Prop Scaling Simulation

Simulates master IBKR account synchronization with 32 prop trading accounts.
Demonstrates:
- Fan-out order distribution
- Rate limit handling
- Auto-hedge on rejections
- Sync lag monitoring
"""

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import List
from enum import Enum

class PropAccountStatus(Enum):
    INACTIVE = 0
    ACTIVE = 1
    RATE_LIMITED = 2
    OUT_OF_SYNC = 3
    ERROR = 4

@dataclass
class PropAccount:
    id: int
    status: PropAccountStatus
    position: int = 0
    target_position: int = 0
    last_fill_ts: float = 0.0
    fill_latency_us: float = 0.0
    rejection_count: int = 0
    sync_lag_ns: float = 0.0
    equity: float = 5000.0
    margin_available: float = 10000.0

@dataclass
class MasterAccount:
    position: int = 0
    target_position: int = 0
    last_fill_ts: float = 0.0
    total_equity: float = 0.0

class PropScalingSimulation:
    def __init__(self, num_accounts=32):
        self.master = MasterAccount()
        self.accounts = [
            PropAccount(i, PropAccountStatus.ACTIVE) 
            for i in range(num_accounts)
        ]
        self.sync_lag_history = []
        self.rate_limited_history = []
        self.hedge_events = []
        
    def simulate_master_fill(self, qty: int, timestamp: float):
        """Simulate a master account fill and fan out to prop accounts"""
        self.master.position += qty
        self.master.last_fill_ts = timestamp
        
        # Distribute to active accounts
        active = [a for a in self.accounts if a.status == PropAccountStatus.ACTIVE]
        if active:
            qty_per_account = qty // len(active)
            for account in active:
                account.target_position = self.master.position
                
    def simulate_prop_fills(self, timestamp: float, base_latency_us=10.0, variance=5.0):
        """Simulate prop account fills with realistic latencies"""
        for account in self.accounts:
            if account.status != PropAccountStatus.ACTIVE:
                continue
                
            # Simulate fill with latency
            latency = max(0, np.random.normal(base_latency_us, variance))
            fill_ts = timestamp + latency * 1000  # Convert μs to ns
            
            # Simulate occasional rate limits (1% chance)
            if np.random.random() < 0.01:
                account.status = PropAccountStatus.RATE_LIMITED
                account.rejection_count += 1
                self.hedge_events.append((timestamp, account.id))
                continue
            
            # Execute fill
            delta = account.target_position - account.position
            if delta != 0:
                account.position += delta
                account.last_fill_ts = fill_ts
                account.fill_latency_us = latency
                account.sync_lag_ns = fill_ts - self.master.last_fill_ts
                
    def calculate_metrics(self):
        """Calculate current synchronization metrics"""
        active = [a for a in self.accounts if a.status == PropAccountStatus.ACTIVE]
        if not active:
            return 0, 0, 0
            
        max_lag = max(a.sync_lag_ns for a in active)
        rate_limited = sum(1 for a in self.accounts if a.status == PropAccountStatus.RATE_LIMITED)
        avg_drift = np.mean([abs(a.position - a.target_position) for a in active])
        
        return max_lag, rate_limited, avg_drift
    
    def recover_rate_limited(self):
        """Recover accounts from rate limited state"""
        for account in self.accounts:
            if account.status == PropAccountStatus.RATE_LIMITED:
                # 10% chance to recover each tick
                if np.random.random() < 0.1:
                    account.status = PropAccountStatus.ACTIVE
                    account.rejection_count = 0
    
    def run(self, num_ticks=1000):
        """Run the simulation for specified ticks"""
        timestamps = []
        max_lags = []
        rate_limited_counts = []
        drift_values = []
        
        for tick in range(num_ticks):
            timestamp = tick * 1000000.0  # 1ms per tick
            
            # Simulate master fills every 100 ticks
            if tick % 100 == 0:
                qty = np.random.randint(-50, 51)
                self.simulate_master_fill(qty, timestamp)
                self.simulate_prop_fills(timestamp)
            
            # Recover rate limited accounts
            self.recover_rate_limited()
            
            # Record metrics
            max_lag, rate_limited, drift = self.calculate_metrics()
            timestamps.append(tick)
            max_lags.append(max_lag / 1000)  # Convert to μs
            rate_limited_counts.append(rate_limited)
            drift_values.append(drift)
        
        return timestamps, max_lags, rate_limited_counts, drift_values

def main():
    """Run simulation and plot results"""
    print("Running Prop Scaling Simulation...")
    sim = PropScalingSimulation(num_accounts=32)
    timestamps, max_lags, rate_limited, drifts = sim.run(num_ticks=1000)
    
    # Create plots
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    
    # Plot 1: Sync Lag
    axes[0].plot(timestamps, max_lags, linewidth=0.5, alpha=0.7)
    axes[0].axhline(y=100, color='r', linestyle='--', label='Threshold (100μs)')
    axes[0].set_ylabel('Max Sync Lag (μs)')
    axes[0].set_title('Prop Scaling: Synchronization Lag')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # Plot 2: Rate Limited Accounts
    axes[1].plot(timestamps, rate_limited, drawstyle='steps-post', color='orange')
    axes[1].axhline(y=5, color='r', linestyle='--', label='Threshold (5 accounts)')
    axes[1].set_ylabel('Rate Limited Count')
    axes[1].set_title('Prop Scaling: Rate Limited Accounts')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    
    # Plot 3: Position Drift
    axes[2].plot(timestamps, drifts, linewidth=0.5, alpha=0.7, color='green')
    axes[2].set_xlabel('Time (ticks)')
    axes[2].set_ylabel('Avg Position Drift')
    axes[2].set_title('Prop Scaling: Position Drift')
    axes[2].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('prop_scaling_simulation.png', dpi=150)
    print(f"✓ Simulation complete. Plots saved to prop_scaling_simulation.png")
    
    # Print statistics
    print(f"\n=== Simulation Statistics ===")
    print(f"Total ticks: {len(timestamps)}")
    print(f"Hedge events: {len(sim.hedge_events)}")
    print(f"Avg sync lag: {np.mean(max_lags):.2f} μs")
    print(f"Max sync lag: {np.max(max_lags):.2f} μs")
    print(f"Avg rate limited: {np.mean(rate_limited):.2f}")
    print(f"Avg drift: {np.mean(drifts):.2f}")

if __name__ == "__main__":
    main()
