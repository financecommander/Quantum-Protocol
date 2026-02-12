# Sleeve 3: Prop Scaling Guide

## Overview

The Prop Scaling module synchronizes a master IBKR institutional account with up to 32 proprietary trading accounts (Topstep/FTMO) with millisecond-level precision.

## Architecture

### Core Components

1. **PropScalingEngine** - Main synchronization engine
2. **PropAccount** - 88-byte fixed-size account struct (stack-allocated)
3. **MasterAccount** - IBKR master account state
4. **Integration Module** - Hooks into main engine loop

### Data Structures

```rust
struct PropAccount {
    id: u8,                    // Account ID (0-31)
    status: PropAccountStatus, // Current state
    position: i32,             // Current position
    target_position: i32,      // Desired position
    last_fill_ts_ns: u64,      // Last fill timestamp
    fill_latency_us: u16,      // Fill latency (microseconds)
    rejection_count: u8,       // Consecutive rejections
    sync_lag_ns: u32,          // Drift from master
    equity: f64,               // Account equity
    margin_available: f64,     // Available margin
    reserved: [u8; 40],        // Padding (total 88 bytes)
}
```

## Key Features

### 1. Pro-Rata Order Distribution

When master account fills, orders are distributed proportionally:

```
qty_per_account = master_fill_qty / num_active_accounts
```

### 2. Sync Lag Monitoring

- **Threshold**: 100µs maximum allowed lag
- **Calculation**: `master.last_fill_ts - account.last_fill_ts`
- **Action**: Circuit breaker triggers if exceeded

### 3. Auto-Hedge on Rate Limits

When a prop account rejects an order:
1. Mark account as `RateLimited`
2. Queue unfilled quantity to hedge buffer
3. Execute hedge on master IBKR account
4. Reactivate account after cooldown

### 4. Account Status States

- **Inactive** (0): Not initialized or disabled
- **Active** (1): Actively syncing with master
- **RateLimited** (2): In rate limit backoff
- **OutOfSync** (3): Sync lag exceeds threshold
- **Error** (4): Critical error (margin call, disconnect)

## Usage Example

```rust
use quantum_protocol::prop_scaling::*;

// Initialize engine
let mut engine = PropScalingEngine::new();
engine.init_accounts();

// Activate accounts with sufficient equity
for i in 0..5 {
    engine.accounts[i].status = PropAccountStatus::Active;
    engine.accounts[i].equity = 5000.0;
    engine.accounts[i].margin_available = 10000.0;
}
engine.num_active_accounts = 5;

// Handle master fill
let fill = FillEvent {
    timestamp_ns: 1000,
    account_id: 0,
    side: Side::Buy,
    qty: 100,
    price: 50.0,
    is_master: true,
};
engine.handle_master_fill(fill);

// Check sync health
if !engine.is_sync_healthy() {
    eprintln!("WARNING: Sync lag exceeds threshold!");
}
```

## Integration

### With Main Engine

```rust
use quantum_protocol::prop_scaling_integration::*;

// In on_tick() loop
update_prop_scaling_targets(&mut prop_engine, packet, config, &mut audit);
process_prop_scaling_state(&prop_engine, packet, &mut audit);
```

### Audit Logging

All events logged with `sleeve_id=3`:
- **SleeveSignal**: Position updates
- **CircuitBreaker**: Sync health degraded
- **ConfigUpdate**: Account state changes

## Performance Characteristics

- **Init**: ~1µs for all 32 accounts
- **Master Fill**: ~2µs (fan-out to 32 accounts)
- **Prop Fill**: ~200ns per account
- **Sync Check**: ~50ns
- **Memory**: 2,816 bytes (32 × 88) + overhead

## Crisis Protocol Integration

During **SmartBunker** (VIX > 45):
- Pause all prop trading
- Flatten positions on master and prop accounts
- Maintain sync monitoring

During **SurgicalSniper** (depeg > 5%):
- Continue normal operation
- Increase hedge buffer threshold
- Log all rejections with high priority

## Configuration

Key parameters in `SharedConfig`:
- `max_position`: Maximum position size
- `hedge_ratio`: Position hedge ratio
- `circuit_breaker_enabled`: Enable/disable sync checks

## Testing

Run prop scaling tests:
```bash
cargo test prop_scaling
```

Run prop scaling integration tests:
```bash
cargo test prop_scaling_integration
```

Run benchmarks:
```bash
cargo bench --bench prop_scaling_bench
```

Run Python simulation:
```bash
python3 examples/prop_scaling_simulation.py
```

## Monitoring

### Key Metrics

1. **Sync Lag**: `engine.sync_lag_ns / 1000` (convert to µs)
2. **Active Count**: `engine.active_count()`
3. **Rate Limited**: `engine.rate_limited_count()`
4. **Position Drift**: `engine.position_drift(account_id)`

### Health Checks

```rust
let healthy = engine.is_sync_healthy();
// Returns false if:
// - sync_lag_ns > 100,000
// - Any account in OutOfSync or Error state
// - rate_limited_count > 5
```

## Troubleshooting

### High Sync Lag

**Causes:**
- Network latency to prop brokers
- Slow prop account fills
- Rate limits on prop accounts

**Solutions:**
- Increase sync threshold (not recommended)
- Reduce position size
- Add more prop accounts to distribute load

### Frequent Rate Limits

**Causes:**
- Order size too large for account
- Too many orders in short time window
- Insufficient margin

**Solutions:**
- Reduce `max_position` in config
- Implement order batching
- Monitor account equity

### Position Drift

**Causes:**
- Rejections not hedged
- Partial fills
- Account offline

**Solutions:**
- Verify auto-hedge is enabled
- Check account status
- Rebalance manually if needed

## Best Practices

1. **Daily Reset**: Call `reset_daily()` at market open
2. **Margin Checks**: Validate margin before setting targets
3. **Monitoring**: Log sync_lag every 100ms
4. **Hedging**: Keep hedge_buffer clear (<5 pending)
5. **Testing**: Replay production data in dev environment

## Compliance

All fills, rejections, and hedges are logged to the audit ring with:
- **Timestamp**: Nanosecond precision
- **Sleeve ID**: 3 (Prop Scaling)
- **Event Type**: SleeveSignal, CircuitBreaker, etc.
- **Risk Flag**: 0=normal, 1=degraded, 2=critical, 3=hedge

Audit records are WORM (Write Once, Read Many) and forwarded to Splunk for FINRA 3110 compliance.
