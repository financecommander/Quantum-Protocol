//! Benchmark for Tail Hedging Engine
//!
//! Self-contained benchmark that doesn't import from the main crate.
//! Measures performance of VIX monitoring and hedge rebalancing.

use criterion::{black_box, criterion_group, criterion_main, Criterion};

// ---------------------------------------------------------------------------
// Local test structs (self-contained)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
enum TailRiskLevel {
    Normal = 0,
    Elevated = 1,
    High = 2,
    Critical = 3,
}

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
enum HedgeInstrument {
    VixCall = 1,
    SpxPut = 2,
    TailFund = 3,
    Treasury = 4,
}

#[derive(Clone, Copy, Debug)]
#[repr(C)]
struct HedgePosition {
    instrument: HedgeInstrument,
    notional: f64,
    strike: f64,
    expiry_days: u16,
    cost_bps: f64,
    delta: f64,
    vega: f64,
}

impl Default for HedgePosition {
    fn default() -> Self {
        Self {
            instrument: HedgeInstrument::SpxPut,
            notional: 0.0,
            strike: 0.0,
            expiry_days: 0,
            cost_bps: 0.0,
            delta: 0.0,
            vega: 0.0,
        }
    }
}

struct TailHedgingEngine {
    positions: [HedgePosition; 8],
    num_positions: usize,
    current_risk_level: TailRiskLevel,
    total_hedge_cost: f64,
    vix_ema: f64,
    last_vix: f64,
}

impl TailHedgingEngine {
    const VIX_THRESHOLD_ELEVATED: f64 = 20.0;
    const VIX_THRESHOLD_HIGH: f64 = 30.0;
    const VIX_THRESHOLD_CRITICAL: f64 = 45.0;
    const EMA_ALPHA: f64 = 0.1;

    fn new() -> Self {
        Self {
            positions: [HedgePosition::default(); 8],
            num_positions: 0,
            current_risk_level: TailRiskLevel::Normal,
            total_hedge_cost: 0.0,
            vix_ema: 15.0,
            last_vix: 15.0,
        }
    }

    fn update_vix(&mut self, vix: f64) -> bool {
        // Update EMA
        self.vix_ema = Self::EMA_ALPHA * vix + (1.0 - Self::EMA_ALPHA) * self.vix_ema;

        // Classify risk
        let risk_level = self.classify_risk(vix);
        let changed = risk_level as u8 > self.current_risk_level as u8;
        self.current_risk_level = risk_level;
        self.last_vix = vix;

        changed
    }

    fn classify_risk(&self, vix: f64) -> TailRiskLevel {
        if vix >= Self::VIX_THRESHOLD_CRITICAL {
            TailRiskLevel::Critical
        } else if vix >= Self::VIX_THRESHOLD_HIGH {
            TailRiskLevel::High
        } else if vix >= Self::VIX_THRESHOLD_ELEVATED {
            TailRiskLevel::Elevated
        } else {
            TailRiskLevel::Normal
        }
    }

    fn add_hedge(&mut self, position: HedgePosition) -> bool {
        if self.num_positions >= 8 {
            return false;
        }
        self.positions[self.num_positions] = position;
        self.num_positions += 1;
        self.total_hedge_cost += position.cost_bps;
        true
    }

    fn recommended_hedge_notional(&self, portfolio_value: f64) -> f64 {
        let hedge_pct = match self.current_risk_level {
            TailRiskLevel::Normal => 0.01,
            TailRiskLevel::Elevated => 0.03,
            TailRiskLevel::High => 0.05,
            TailRiskLevel::Critical => 0.10,
        };
        portfolio_value * hedge_pct
    }

    fn total_delta(&self) -> f64 {
        let mut delta = 0.0;
        for i in 0..self.num_positions {
            delta += self.positions[i].delta;
        }
        delta
    }

    fn total_vega(&self) -> f64 {
        let mut vega = 0.0;
        for i in 0..self.num_positions {
            vega += self.positions[i].vega;
        }
        vega
    }

    fn remove_expired_hedges(&mut self) -> usize {
        let mut write_idx = 0;
        let mut removed = 0;

        for read_idx in 0..self.num_positions {
            let pos = &self.positions[read_idx];
            if pos.expiry_days > 0 {
                if write_idx != read_idx {
                    self.positions[write_idx] = *pos;
                }
                write_idx += 1;
            } else {
                removed += 1;
            }
        }

        self.num_positions = write_idx;
        removed
    }
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

fn bench_update_vix(c: &mut Criterion) {
    let mut engine = TailHedgingEngine::new();

    c.bench_function("tail_hedging_update_vix", |b| {
        let mut vix = 15.0;
        b.iter(|| {
            vix += 0.1;
            let changed = engine.update_vix(black_box(vix));
            black_box(changed);
        });
    });
}

fn bench_classify_risk(c: &mut Criterion) {
    let engine = TailHedgingEngine::new();

    c.bench_function("tail_hedging_classify_risk", |b| {
        let mut vix = 15.0;
        b.iter(|| {
            vix += 1.0;
            if vix > 60.0 {
                vix = 15.0;
            }
            let risk = engine.classify_risk(black_box(vix));
            black_box(risk);
        });
    });
}

fn bench_add_hedge(c: &mut Criterion) {
    c.bench_function("tail_hedging_add_hedge", |b| {
        b.iter(|| {
            let mut engine = TailHedgingEngine::new();

            for i in 0..8 {
                let position = HedgePosition {
                    instrument: HedgeInstrument::SpxPut,
                    notional: 100_000.0,
                    strike: 4000.0 - (i as f64 * 50.0),
                    expiry_days: 30,
                    cost_bps: 50.0,
                    delta: -0.3,
                    vega: 0.5,
                };
                engine.add_hedge(position);
            }

            black_box(&engine);
        });
    });
}

fn bench_calculate_greeks(c: &mut Criterion) {
    let mut engine = TailHedgingEngine::new();

    // Add positions
    for i in 0..8 {
        let position = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 100_000.0,
            strike: 4000.0 - (i as f64 * 50.0),
            expiry_days: 30,
            cost_bps: 50.0,
            delta: -0.3 + (i as f64 * 0.05),
            vega: 0.5 + (i as f64 * 0.1),
        };
        engine.add_hedge(position);
    }

    c.bench_function("tail_hedging_calculate_greeks", |b| {
        b.iter(|| {
            let delta = engine.total_delta();
            let vega = engine.total_vega();
            black_box((delta, vega));
        });
    });
}

fn bench_recommended_hedge(c: &mut Criterion) {
    let mut engine = TailHedgingEngine::new();
    engine.current_risk_level = TailRiskLevel::High;

    c.bench_function("tail_hedging_recommended_hedge", |b| {
        b.iter(|| {
            let notional = engine.recommended_hedge_notional(black_box(1_000_000.0));
            black_box(notional);
        });
    });
}

fn bench_remove_expired(c: &mut Criterion) {
    c.bench_function("tail_hedging_remove_expired", |b| {
        b.iter(|| {
            let mut engine = TailHedgingEngine::new();

            // Add mix of active and expired
            for i in 0..8 {
                let position = HedgePosition {
                    instrument: HedgeInstrument::SpxPut,
                    notional: 100_000.0,
                    strike: 4000.0,
                    expiry_days: if i % 2 == 0 { 30 } else { 0 },
                    cost_bps: 50.0,
                    delta: -0.3,
                    vega: 0.5,
                };
                engine.add_hedge(position);
            }

            let removed = engine.remove_expired_hedges();
            black_box(removed);
        });
    });
}

fn bench_full_cycle(c: &mut Criterion) {
    c.bench_function("tail_hedging_full_cycle", |b| {
        let mut vix = 15.0;
        b.iter(|| {
            let mut engine = TailHedgingEngine::new();

            // VIX updates
            for _ in 0..10 {
                vix += 2.0;
                engine.update_vix(vix);
            }

            // Add hedges based on risk
            let notional = engine.recommended_hedge_notional(1_000_000.0);
            if notional > 0.0 {
                let position = HedgePosition {
                    instrument: HedgeInstrument::SpxPut,
                    notional,
                    strike: 4000.0,
                    expiry_days: 30,
                    cost_bps: 50.0,
                    delta: -0.3,
                    vega: 0.5,
                };
                engine.add_hedge(position);
            }

            // Calculate greeks
            let delta = engine.total_delta();
            let vega = engine.total_vega();

            black_box((delta, vega));
        });
    });
}

criterion_group!(
    benches,
    bench_update_vix,
    bench_classify_risk,
    bench_add_hedge,
    bench_calculate_greeks,
    bench_recommended_hedge,
    bench_remove_expired,
    bench_full_cycle
);
criterion_main!(benches);
