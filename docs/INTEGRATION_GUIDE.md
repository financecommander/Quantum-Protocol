# Integration Guide: Adding Sleeves 3, 4, & 5 to Production

## Prerequisites

- Rust 1.70+ installed
- Python 3.9+ (for simulations)
- Access to production environment
- Testing environment with market data replay

## Step 1: Library Restructuring

The project has been restructured from binary-only to library + binary:

```
Before:
src/engine/main.rs (all-in-one)

After:
src/lib.rs                    → Library entry point
src/engine/mod.rs             → Module coordinator
src/engine/common.rs          → Shared types
src/engine/main.rs            → Thin binary
src/engine/prop_scaling.rs    → Sleeve 3
src/engine/rwa_crypto_hft.rs  → Sleeve 4
src/engine/tail_hedging.rs    → Sleeve 5
```

**Action Required**: None if using provided code. Existing tests continue to work.

## Step 2: Update Engine Initialization

Add sleeve engines to your main engine struct or initialization code:

```rust
use quantum_protocol::*;

// In your Engine struct or main()
let mut engine = Engine::new();
let mut prop_engine = prop_scaling::PropScalingEngine::new();
let mut rwa_engine = rwa_crypto_hft::RwaCryptoEngine::new();
let mut tail_engine = tail_hedging::TailHedgingEngine::new();

// Initialize prop accounts
prop_engine.init_accounts();
for i in 0..NUM_PROP_ACCOUNTS {
    prop_engine.accounts[i].status = PropAccountStatus::Active;
    prop_engine.accounts[i].equity = 5000.0;
    prop_engine.accounts[i].margin_available = 10000.0;
}
prop_engine.num_active_accounts = NUM_PROP_ACCOUNTS as u8;
```

## Step 3: Integrate into on_tick() Loop

Add sleeve updates to your hot path:

```rust
pub fn on_tick(&mut self, packet: &MarketPacket) {
    // Existing: Crisis evaluation and sleeves 1-2
    self.engine.on_tick(packet);
    
    // NEW: Sleeve 3 - Prop Scaling
    prop_scaling_integration::update_prop_scaling_targets(
        &mut self.prop_engine,
        packet,
        &self.config,
        &mut self.audit
    );
    
    // NEW: Sleeve 4 - RWA/Crypto HFT
    rwa_crypto_integration::update_rwa_crypto_from_market(
        &mut self.rwa_engine,
        packet,
        &mut self.audit
    );
    rwa_crypto_integration::process_rwa_crypto_opportunities(
        &mut self.rwa_engine,
        packet,
        &self.config,
        &mut self.audit
    );
    
    // NEW: Sleeve 5 - Tail Hedging
    tail_hedging_integration::update_tail_hedging_from_market(
        &mut self.tail_engine,
        packet,
        &mut self.audit
    );
}
```

## Step 4: Handle Fill/Rejection Events

Integrate order execution feedback:

```rust
pub fn on_fill(&mut self, fill: FillEvent) {
    if fill.is_master {
        self.prop_engine.handle_master_fill(fill);
    } else {
        self.prop_engine.handle_prop_fill(fill);
    }
}

pub fn on_rejection(&mut self, rejection: RejectionEvent) {
    self.prop_engine.handle_prop_rejection(rejection);
    
    // Auto-hedge if needed
    if self.prop_engine.hedge_buffer.iter().any(|&qty| qty != 0) {
        self.prop_engine.auto_hedge();
    }
}
```

## Step 5: Periodic Tasks

Add these to your event loop or timer:

```rust
// Every 100ms: Check sync health
if !prop_engine.is_sync_healthy() {
    log::warn!("Prop scaling sync unhealthy: lag={}µs", 
               prop_engine.sync_lag_ns / 1000);
}

// Every 1 second: Clear stale opportunities
rwa_engine.clear_stale_opportunities(now_ns(), 1_000_000);

// Every 5 minutes: Rebalance tail hedges
tail_hedging_integration::process_tail_hedging_rebalance(
    &mut tail_engine,
    &packet,
    &config,
    &mut audit
);

// Daily at market open: Reset all engines
prop_engine.reset_daily();
rwa_engine.reset_daily();
tail_engine.reset_daily();
```

## Step 6: Crisis Protocol Integration

Update crisis handlers to include new sleeves:

```rust
match self.crisis_state {
    CrisisState::SmartBunker => {
        // Existing: Skip sleeves 1-2
        
        // NEW: Pause prop scaling
        for account in prop_engine.accounts.iter_mut() {
            if account.status == PropAccountStatus::Active {
                account.status = PropAccountStatus::Inactive;
            }
        }
        
        // NEW: Halt RWA/crypto arbitrage
        rwa_engine.opportunities.clear();
        rwa_engine.num_opportunities = 0;
        
        // NEW: Maximize tail hedges
        tail_engine.current_risk_level = TailRiskLevel::Critical;
        let actions = tail_engine.rebalance_hedges(portfolio_value);
        // Execute hedge orders
    }
    CrisisState::SurgicalSniper => {
        // Adjust thresholds for depeg scenario
        // Prop scaling: increase hedge buffer
        // RWA/crypto: raise minimum spread to 10bp
    }
    _ => {}
}
```

## Step 7: Configuration

Update your `SharedConfig` or config file:

```rust
pub struct SharedConfig {
    // Existing fields
    pub hedge_ratio: f64,
    pub max_position: f64,
    pub vol_regime_threshold_low: f64,
    pub vol_regime_threshold_high: f64,
    pub quantum_weights: [f64; 8],
    pub circuit_breaker_enabled: bool,
    pub heartbeat_max_lag_us: u64,
    
    // NEW: Prop scaling config
    pub num_prop_accounts: u8,
    pub prop_sync_threshold_ns: u32,
    pub prop_max_rate_limited: u8,
    
    // NEW: RWA/crypto config
    pub rwa_min_spread_bps: f64,
    pub rwa_fee_bps: f64,
    pub rwa_max_stale_age_ms: u64,
    
    // NEW: Tail hedging config
    pub tail_vix_threshold_elevated: f64,
    pub tail_vix_threshold_high: f64,
    pub tail_vix_threshold_critical: f64,
    pub tail_base_hedge_pct: f64,
}
```

## Step 8: Monitoring Integration

Add metrics export:

```rust
// Prometheus/Grafana metrics
pub fn export_metrics(&self) {
    // Prop scaling
    gauge!("prop_scaling.sync_lag_us", prop_engine.sync_lag_ns / 1000);
    gauge!("prop_scaling.active_accounts", prop_engine.active_count());
    gauge!("prop_scaling.rate_limited", prop_engine.rate_limited_count());
    
    // RWA/crypto
    let rwa_stats = rwa_engine.get_stats();
    gauge!("rwa_crypto.active_pairs", rwa_stats.active_pairs);
    gauge!("rwa_crypto.pending_opps", rwa_stats.pending_opportunities);
    counter!("rwa_crypto.total_executions", rwa_stats.total_executions);
    gauge!("rwa_crypto.total_profit_bps", rwa_stats.total_profit);
    
    // Tail hedging
    let tail_stats = tail_engine.get_stats();
    gauge!("tail_hedging.num_positions", tail_stats.num_positions);
    gauge!("tail_hedging.hedge_cost_bps", tail_stats.total_hedge_cost);
    gauge!("tail_hedging.vix_ema", tail_stats.vix_ema);
    gauge!("tail_hedging.total_delta", tail_stats.total_delta);
    gauge!("tail_hedging.total_vega", tail_stats.total_vega);
}
```

## Step 9: Testing in Staging

Before production deployment:

```bash
# 1. Unit tests
cargo test --lib

# 2. Integration tests
cargo test --test '*'

# 3. Benchmarks (ensure p99 < 120µs)
cargo bench

# 4. Market data replay
./scripts/replay_market_data.sh --date 2022-05-09  # Terra Luna
./scripts/replay_market_data.sh --date 2020-03-16  # COVID crash

# 5. Stress test
./scripts/stress_test.sh --duration 1h --rate 10000pps

# 6. Python simulations
python3 examples/prop_scaling_simulation.py
python3 examples/rwa_crypto_simulation.py
python3 examples/tail_hedging_simulation.py
```

## Step 10: Production Deployment

### Pre-Deployment Checklist

- [ ] All tests passing (85+ tests)
- [ ] Benchmarks meet latency targets
- [ ] Audit logging verified
- [ ] Monitoring dashboards created
- [ ] Runbooks updated
- [ ] Compliance sign-off
- [ ] Staging validation complete

### Deployment Steps

1. **Deploy to shadow trading** (read-only mode)
   - Monitor for 24 hours
   - Verify audit logs
   - Check performance metrics

2. **Enable with 10% capital** (partial deployment)
   - Start with 3 prop accounts
   - Monitor sync health
   - Verify P&L attribution

3. **Scale to 100%** (full deployment)
   - Activate all 32 prop accounts
   - Enable all RWA/crypto pairs
   - Activate full tail hedge suite

### Rollback Plan

If issues detected:

```bash
# Disable new sleeves
sed -i 's/enable_prop_scaling=true/enable_prop_scaling=false/' config.toml
sed -i 's/enable_rwa_crypto=true/enable_rwa_crypto=false/' config.toml
sed -i 's/enable_tail_hedging=true/enable_tail_hedging=false/' config.toml

# Restart engine
systemctl restart quantum-engine

# Verify old behavior
./scripts/verify_sleeves_1_2_only.sh
```

## Troubleshooting

### Build Fails

```bash
# Clean and rebuild
cargo clean
cargo build --release

# Check for missing dependencies
cargo tree
```

### Tests Fail

```bash
# Run with verbose output
cargo test -- --nocapture

# Run specific test
cargo test test_prop_scaling_full_cycle -- --nocapture
```

### High Latency

```bash
# Profile with flamegraph
cargo flamegraph --bench prop_scaling_bench

# Check for memory allocations
RUST_LOG=trace cargo test
```

### Sync Issues

```bash
# Check network latency to prop brokers
ping prop-broker-1.example.com
ping prop-broker-2.example.com

# Monitor fill latencies
tail -f /var/log/quantum-engine/prop_fills.log
```

## Support

- **Documentation**: See individual sleeve guides
- **Issues**: GitHub Issues
- **Emergency**: On-call rotation
