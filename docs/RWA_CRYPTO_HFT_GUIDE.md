# Sleeve 4: RWA/Crypto HFT Guide

## Overview

The RWA/Crypto HFT module executes cross-venue arbitrage on tokenized real-world assets and cryptocurrency spot/futures spreads with sub-100µs latency.

## Architecture

### Core Components

1. **RwaCryptoEngine** - Arbitrage detection and execution engine
2. **CryptoPair** - Market data for spot/futures pairs
3. **ArbitrageOpportunity** - Detected trading opportunities
4. **Integration Module** - Main loop integration

### Data Structures

```rust
struct CryptoPair {
    symbol_id: u32,
    spot_price: f64,
    futures_price: f64,
    funding_rate: f64,
    volume_24h: f64,
    last_update_ns: u64,
}

struct ArbitrageOpportunity {
    timestamp_ns: u64,
    symbol_id: u32,
    venue_a_price: f64,
    venue_b_price: f64,
    spread_bps: f64,          // Spread in basis points
    profit_potential: f64,     // After fees
    confidence: f64,           // 0.0-1.0 score
}
```

## Key Features

### 1. Spread Monitoring

Continuously monitors spot-futures spread:

```
spread_pct = ((futures_price - spot_price) / spot_price) × 100
spread_bps = spread_pct × 100
```

### 2. Opportunity Detection

Criteria for valid arbitrage:
- `|spread_bps| > MIN_SPREAD_BPS + FEE_BPS`
- `MIN_SPREAD_BPS = 5.0` (minimum 5bp spread)
- `FEE_BPS = 2.0` (assume 2bp total fees)

### 3. Confidence Scoring

```rust
age_penalty = max(0, 1.0 - (age_ms / 1000))
volume_score = min(1.0, volume_24h / 1_000_000)
confidence = (age_penalty + volume_score) / 2.0
```

### 4. Best Execution

Risk-adjusted selection:
```
score = profit_potential × confidence
execute(best_by_score)
```

## Supported Pairs

Current capacity: **16 pairs**

Common pairs:
- BTC/USD (spot vs futures)
- ETH/USD (spot vs futures)
- Tokenized treasuries (on-chain vs OTC)
- Tokenized commodities (PAXG, etc.)

## Usage Example

```rust
use quantum_protocol::rwa_crypto_hft::*;

// Initialize engine
let mut engine = RwaCryptoEngine::new();

// Update pair data
let pair = CryptoPair {
    symbol_id: 1,
    spot_price: 50000.0,
    futures_price: 50400.0,  // 80bp spread
    funding_rate: 0.01,
    volume_24h: 1_000_000_000.0,
    last_update_ns: 1000,
};
engine.update_pair(pair);

// Scan for opportunities
let found = engine.scan_opportunities(1000);
println!("Found {} opportunities", found);

// Execute best
if let Some(opp) = engine.execute_best_opportunity() {
    println!("Executed: {:.2} bps profit", opp.profit_potential);
}
```

## Integration

### With Main Engine

```rust
use quantum_protocol::rwa_crypto_integration::*;

// In on_tick() loop
update_rwa_crypto_from_market(&mut rwa_engine, packet, &mut audit);
process_rwa_crypto_opportunities(&mut rwa_engine, packet, config, &mut audit);

// Periodic performance reports
report_rwa_crypto_performance(&rwa_engine, packet, &mut audit);
```

### Market Data Ingestion

The engine expects high-frequency market data:
- **Spot prices**: Direct from exchanges (Coinbase, Binance, etc.)
- **Futures prices**: Perpetuals from CME, Deribit, etc.
- **Update frequency**: 10ms or faster
- **Format**: MarketPacket with symbol_id, bid, ask, volume

## Performance Characteristics

- **Update Pair**: ~50ns
- **Scan Opportunities**: ~2µs (16 pairs)
- **Execute Opportunity**: ~100ns
- **Full Cycle**: ~3µs (update + scan + execute)

### Latency Budget

Total wire-to-wire: <100µs
- Network ingress: 20µs
- Data validation: 5µs
- Opportunity scan: 2µs
- Execution decision: 1µs
- Order routing: 40µs
- Network egress: 30µs

## Trading Strategy

### 1. Cash-and-Carry Arbitrage

Buy spot, sell futures (or vice versa):
- **Entry**: When spread > MIN_SPREAD + FEES
- **Hold**: Until convergence or funding payment
- **Exit**: Spread normalizes or funding turns negative

### 2. Cross-Venue Arbitrage

Buy on cheaper venue, sell on expensive:
- **Venues**: Coinbase vs Binance vs Kraken
- **Constraints**: Withdrawal times, transfer fees
- **Risk**: Price moves before arbitrage completes

### 3. RWA Tokenization Spread

On-chain tokenized assets vs off-chain equivalents:
- **Example**: PAXG (on-chain gold) vs GLD ETF
- **Opportunity**: Minting/redemption fees create spread
- **Execution**: Atomic swaps or DEX trades

## Risk Management

### Position Limits

```rust
// In SharedConfig
max_position: 1_000_000.0,  // Max notional per pair
```

### Circuit Breaker

Execution halted if:
- `config.circuit_breaker_enabled == false`
- Spread changes >20% mid-execution
- Volume drops below threshold

### Stale Data Protection

```rust
engine.clear_stale_opportunities(current_time_ns, 1_000_000); // 1ms max age
```

## Monitoring

### Key Metrics

```rust
let stats = engine.get_stats();
println!("Active pairs: {}", stats.active_pairs);
println!("Pending opportunities: {}", stats.pending_opportunities);
println!("Total executions: {}", stats.total_executions);
println!("Total profit: {:.2} bps", stats.total_profit);
println!("Avg profit/trade: {:.2} bps", stats.avg_profit_per_trade);
```

### Alerts

Set up monitoring for:
- Execution rate drops below 10/sec
- Avg profit/trade < 3bp
- Stale opportunities accumulate (>10 pending)
- No opportunities found for >10 seconds

## Testing

```bash
# Unit tests
cargo test rwa_crypto_hft

# Integration tests
cargo test rwa_crypto_integration

# Benchmarks
cargo bench --bench rwa_crypto_bench

# Simulation
python3 examples/rwa_crypto_simulation.py
```

## Crisis Protocol Integration

### SmartBunker (VIX > 45)

- **Action**: Halt all crypto arbitrage
- **Reason**: Extreme volatility invalidates spreads
- **Recovery**: Resume when VIX < 40 for 5 minutes

### SurgicalSniper (Depeg > 5%)

- **Action**: Increase opportunity threshold to 10bp
- **Reason**: Stablecoin volatility increases execution risk
- **Focus**: Only high-confidence, high-spread trades

## Fee Structure

### Exchange Fees

- Coinbase Pro: 0.5bp maker, 5bp taker
- Binance: 1bp maker, 4bp taker
- Deribit: 2bp maker, 7.5bp taker

### Network Fees

- Ethereum: Variable (10-200 gwei)
- Arbitrum: ~0.1 gwei
- Solana: ~0.000005 SOL per tx

### Optimization

Minimize taker fees:
- Post limit orders when possible
- Use maker rebates
- Batch small trades

## Troubleshooting

### No Opportunities Found

**Causes:**
- Market spreads compressed
- Data feeds stale
- Threshold too high

**Solutions:**
- Verify data feed latency
- Lower MIN_SPREAD_BPS (carefully)
- Add more pairs

### High Slippage

**Causes:**
- Low liquidity
- Large order size
- Network congestion

**Solutions:**
- Reduce position size
- Use limit orders
- Split across venues

### Failed Executions

**Causes:**
- Rate limits
- Insufficient balance
- API errors

**Solutions:**
- Implement retry logic
- Monitor account balances
- Add error recovery

## Best Practices

1. **Latency**: Co-locate servers with exchanges
2. **Data Quality**: Validate timestamps, detect gaps
3. **Risk Limits**: Never exceed configured max_position
4. **Diversification**: Trade multiple uncorrelated pairs
5. **Monitoring**: Real-time P&L tracking
6. **Backtesting**: Replay production data before deployment

## Compliance

All opportunity scans and executions logged with `sleeve_id=4`:
- **SleeveSignal**: Opportunity detected/executed
- **Heartbeat**: Performance statistics
- **Risk Flag**: 0=normal, 1=low confidence, 2=high spread

Audit records include:
- Timestamp (nanosecond precision)
- Symbol ID
- Spread (bps)
- Profit potential
- Confidence score

FINRA 3110 compliant via binary audit logging to Splunk.
