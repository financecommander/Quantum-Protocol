//! Benchmark for RWA/Crypto HFT Engine
//!
//! Self-contained benchmark that doesn't import from the main crate.
//! Measures performance of arbitrage scanning and execution.

use criterion::{black_box, criterion_group, criterion_main, Criterion};

// ---------------------------------------------------------------------------
// Local test structs (self-contained)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
#[repr(C)]
struct CryptoPair {
    symbol_id: u32,
    spot_price: f64,
    futures_price: f64,
    funding_rate: f64,
    volume_24h: f64,
    last_update_ns: u64,
}

impl Default for CryptoPair {
    fn default() -> Self {
        Self {
            symbol_id: 0,
            spot_price: 0.0,
            futures_price: 0.0,
            funding_rate: 0.0,
            volume_24h: 0.0,
            last_update_ns: 0,
        }
    }
}

#[derive(Clone, Copy, Debug)]
#[repr(C)]
struct ArbitrageOpportunity {
    timestamp_ns: u64,
    symbol_id: u32,
    venue_a_price: f64,
    venue_b_price: f64,
    spread_bps: f64,
    profit_potential: f64,
    confidence: f64,
}

impl Default for ArbitrageOpportunity {
    fn default() -> Self {
        Self {
            timestamp_ns: 0,
            symbol_id: 0,
            venue_a_price: 0.0,
            venue_b_price: 0.0,
            spread_bps: 0.0,
            profit_potential: 0.0,
            confidence: 0.0,
        }
    }
}

struct RwaCryptoEngine {
    pairs: [CryptoPair; 16],
    opportunities: [ArbitrageOpportunity; 32],
    num_pairs: usize,
    num_opportunities: usize,
    total_executions: u64,
    total_profit: f64,
}

impl RwaCryptoEngine {
    const MIN_SPREAD_BPS: f64 = 5.0;
    const FEE_BPS: f64 = 2.0;

    fn new() -> Self {
        Self {
            pairs: [CryptoPair::default(); 16],
            opportunities: [ArbitrageOpportunity::default(); 32],
            num_pairs: 0,
            num_opportunities: 0,
            total_executions: 0,
            total_profit: 0.0,
        }
    }

    fn update_pair(&mut self, pair: CryptoPair) {
        let mut found = false;
        for i in 0..self.num_pairs {
            if self.pairs[i].symbol_id == pair.symbol_id {
                self.pairs[i] = pair;
                found = true;
                break;
            }
        }
        if !found && self.num_pairs < 16 {
            self.pairs[self.num_pairs] = pair;
            self.num_pairs += 1;
        }
    }

    fn scan_opportunities(&mut self, current_time_ns: u64) -> usize {
        let mut found_count = 0;

        for i in 0..self.num_pairs {
            let pair = &self.pairs[i];

            if pair.spot_price > 0.0 && pair.futures_price > 0.0 {
                let spread_pct = ((pair.futures_price - pair.spot_price) / pair.spot_price) * 100.0;
                let spread_bps = spread_pct * 100.0;

                if spread_bps.abs() > Self::MIN_SPREAD_BPS + Self::FEE_BPS {
                    let profit_potential = spread_bps.abs() - Self::FEE_BPS;

                    let age_penalty = if current_time_ns > pair.last_update_ns {
                        let age_ms = (current_time_ns - pair.last_update_ns) / 1_000_000;
                        (1.0 - (age_ms as f64 / 1000.0)).max(0.0)
                    } else {
                        1.0
                    };
                    let volume_score = (pair.volume_24h / 1_000_000.0).min(1.0);
                    let confidence = (age_penalty + volume_score) / 2.0;

                    if self.num_opportunities < 32 {
                        self.opportunities[self.num_opportunities] = ArbitrageOpportunity {
                            timestamp_ns: current_time_ns,
                            symbol_id: pair.symbol_id,
                            venue_a_price: pair.spot_price,
                            venue_b_price: pair.futures_price,
                            spread_bps,
                            profit_potential,
                            confidence,
                        };
                        self.num_opportunities += 1;
                        found_count += 1;
                    }
                }
            }
        }

        found_count
    }

    fn execute_best_opportunity(&mut self) -> Option<ArbitrageOpportunity> {
        if self.num_opportunities == 0 {
            return None;
        }

        let mut best_idx = 0;
        let mut best_score = 0.0;

        for i in 0..self.num_opportunities {
            let opp = &self.opportunities[i];
            let score = opp.profit_potential * opp.confidence;
            if score > best_score {
                best_score = score;
                best_idx = i;
            }
        }

        let best = self.opportunities[best_idx];
        self.total_executions += 1;
        self.total_profit += best.profit_potential;

        // Remove executed
        for i in best_idx..self.num_opportunities - 1 {
            self.opportunities[i] = self.opportunities[i + 1];
        }
        self.num_opportunities -= 1;

        Some(best)
    }
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

fn bench_update_pair(c: &mut Criterion) {
    let mut engine = RwaCryptoEngine::new();

    c.bench_function("rwa_crypto_update_pair", |b| {
        let mut price = 50000.0;
        b.iter(|| {
            price += 1.0;
            let pair = CryptoPair {
                symbol_id: 1,
                spot_price: price,
                futures_price: price + 100.0,
                funding_rate: 0.01,
                volume_24h: 1_000_000.0,
                last_update_ns: 1000,
            };
            engine.update_pair(black_box(pair));
            black_box(&engine);
        });
    });
}

fn bench_scan_opportunities(c: &mut Criterion) {
    let mut engine = RwaCryptoEngine::new();

    // Add pairs with varying spreads
    for i in 0..16 {
        let pair = CryptoPair {
            symbol_id: i,
            spot_price: 50000.0 + (i as f64 * 1000.0),
            futures_price: 50400.0 + (i as f64 * 1000.0), // 8bp spread
            funding_rate: 0.01,
            volume_24h: 1_000_000.0,
            last_update_ns: 1000,
        };
        engine.update_pair(pair);
    }

    c.bench_function("rwa_crypto_scan_opportunities", |b| {
        let mut ts = 1000u64;
        b.iter(|| {
            ts += 1000;
            engine.num_opportunities = 0; // Reset
            let found = engine.scan_opportunities(black_box(ts));
            black_box(found);
        });
    });
}

fn bench_execute_opportunity(c: &mut Criterion) {
    c.bench_function("rwa_crypto_execute_opportunity", |b| {
        b.iter(|| {
            let mut engine = RwaCryptoEngine::new();

            // Add opportunity
            engine.opportunities[0] = ArbitrageOpportunity {
                timestamp_ns: 1000,
                symbol_id: 1,
                venue_a_price: 50000.0,
                venue_b_price: 50400.0,
                spread_bps: 80.0,
                profit_potential: 78.0,
                confidence: 0.9,
            };
            engine.num_opportunities = 1;

            let result = engine.execute_best_opportunity();
            black_box(result);
        });
    });
}

fn bench_full_cycle(c: &mut Criterion) {
    c.bench_function("rwa_crypto_full_cycle", |b| {
        let mut ts = 1000u64;
        b.iter(|| {
            let mut engine = RwaCryptoEngine::new();

            // Update multiple pairs
            for i in 0..10 {
                ts += 100;
                let pair = CryptoPair {
                    symbol_id: i,
                    spot_price: 50000.0 + (i as f64 * 1000.0),
                    futures_price: 50400.0 + (i as f64 * 1000.0),
                    funding_rate: 0.01,
                    volume_24h: 1_000_000.0,
                    last_update_ns: ts,
                };
                engine.update_pair(pair);
            }

            // Scan for opportunities
            ts += 100;
            let found = engine.scan_opportunities(ts);

            // Execute if found
            if found > 0 {
                engine.execute_best_opportunity();
            }

            black_box(&engine);
        });
    });
}

criterion_group!(
    benches,
    bench_update_pair,
    bench_scan_opportunities,
    bench_execute_opportunity,
    bench_full_cycle
);
criterion_main!(benches);
