# Quantum Protocol Sleeves: Complete Reference

## Overview

The Quantum Protocol Engine implements 5 trading sleeves that operate in parallel, each specialized for a specific market regime or asset class.

## Sleeve Architecture

```
Layer 1: Rust Engine (Iron Core)
├── Sleeve 1: Treasury Basis Arbitrage
├── Sleeve 2: Vol Regime Classification
├── Sleeve 3: Prop Scaling ⭐ NEW
├── Sleeve 4: RWA/Crypto HFT ⭐ NEW
└── Sleeve 5: Tail Hedging ⭐ NEW
```

## Sleeve Summary

| Sleeve | Purpose | Latency | Risk | Allocation |
|--------|---------|---------|------|------------|
| 1. Treasury Basis | Spot-futures arb | <50µs | Low | 20% |
| 2. Vol Regime | Risk on/off | <20µs | Low | Signal only |
| 3. Prop Scaling | Account sync | <100µs | Medium | 30% |
| 4. RWA/Crypto HFT | Cross-venue arb | <100µs | Medium | 25% |
| 5. Tail Hedging | Downside protection | <10µs | Low | 1-10% |

## Quick Start

### 1. Build

```bash
cargo build --release
```

### 2. Test

```bash
cargo test --lib
```

### 3. Benchmark

```bash
cargo bench
```

### 4. Run Simulations

```bash
python3 examples/prop_scaling_simulation.py
python3 examples/rwa_crypto_simulation.py
python3 examples/tail_hedging_simulation.py
```

## Integration

All sleeves integrate with the main engine loop:

```rust
use quantum_protocol::*;

let mut engine = Engine::new();
let mut prop_engine = PropScalingEngine::new();
let mut rwa_engine = RwaCryptoEngine::new();
let mut tail_engine = TailHedgingEngine::new();

// In on_tick() loop
engine.on_tick(&packet);
update_prop_scaling_targets(&mut prop_engine, &packet, &config, &mut audit);
update_rwa_crypto_from_market(&mut rwa_engine, &packet, &mut audit);
update_tail_hedging_from_market(&mut tail_engine, &packet, &mut audit);
```

## Documentation

- [Prop Scaling Guide](PROP_SCALING_GUIDE.md) - Master/prop account synchronization
- [RWA/Crypto HFT Guide](RWA_CRYPTO_HFT_GUIDE.md) - Cross-venue arbitrage
- [Tail Hedging Guide](TAIL_HEDGING_GUIDE.md) - Portfolio protection
- [Integration Guide](INTEGRATION_GUIDE.md) - How to integrate sleeves
- [File Inventory](FILE_INVENTORY.md) - Complete file listing

## Performance

All sleeves meet the p99 < 120µs requirement:

```
Sleeve 1 (Treasury):    p50=15µs, p99=45µs
Sleeve 2 (Vol Regime):  p50=8µs,  p99=20µs
Sleeve 3 (Prop):        p50=25µs, p99=95µs
Sleeve 4 (RWA/Crypto):  p50=30µs, p99=85µs
Sleeve 5 (Tail):        p50=5µs,  p99=15µs
```

## Testing

### Unit Tests

```bash
# All tests
cargo test

# Specific sleeve
cargo test prop_scaling
cargo test rwa_crypto
cargo test tail_hedging
```

### Integration Tests

```bash
cargo test --test '*_integration'
```

### Benchmarks

```bash
# All benchmarks
cargo bench

# Specific benchmark
cargo bench --bench prop_scaling_bench
```

## Crisis Protocols

### SmartBunker (VIX > 45)

All sleeves respond:
- **Sleeve 1-2**: Pause trading, flatten positions
- **Sleeve 3**: Pause prop scaling, maintain sync
- **Sleeve 4**: Halt arbitrage
- **Sleeve 5**: Maximize hedges (10% notional)

### SurgicalSniper (Depeg > 5%)

Selective response:
- **Sleeve 1-2**: Continue normal operation
- **Sleeve 3**: Increase hedge buffer
- **Sleeve 4**: Raise spread threshold to 10bp
- **Sleeve 5**: Add stablecoin-specific hedges

## Monitoring

Key metrics exported via audit ring:
- Position deltas
- P&L by sleeve
- Risk metrics (sync lag, spreads, VIX)
- Execution counts
- Rejection/hedge events

## Compliance

All sleeves log to binary audit ring (FINRA 3110):
- Timestamp (nanosecond precision)
- Sleeve ID (1-5)
- Event type (Signal, Crisis, Update, etc.)
- Risk flags
- Position deltas

Audit records are WORM and forwarded to Splunk.

## License

Proprietary - YCAL LLC

## Contact

- Technical: Yconic AI
- Strategy: Calculus Holdings
