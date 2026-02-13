//! Benchmark for Prop Scaling Engine
//!
//! Self-contained benchmark that doesn't import from the main crate.
//! Measures performance of core prop scaling operations.

use criterion::{black_box, criterion_group, criterion_main, Criterion};

// ---------------------------------------------------------------------------
// Local test structs (self-contained)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
enum PropAccountStatus {
    Inactive = 0,
    Active = 1,
    RateLimited = 2,
    OutOfSync = 3,
    Error = 4,
}

#[derive(Clone, Copy, Debug)]
#[repr(C)]
struct PropAccount {
    id: u8,
    status: PropAccountStatus,
    position: i32,
    target_position: i32,
    last_fill_ts_ns: u64,
    fill_latency_us: u16,
    rejection_count: u8,
    sync_lag_ns: u32,
    equity: f64,
    margin_available: f64,
    reserved: [u8; 40],
}

impl Default for PropAccount {
    fn default() -> Self {
        Self {
            id: 0,
            status: PropAccountStatus::Inactive,
            position: 0,
            target_position: 0,
            last_fill_ts_ns: 0,
            fill_latency_us: 0,
            rejection_count: 0,
            sync_lag_ns: 0,
            equity: 0.0,
            margin_available: 0.0,
            reserved: [0; 40],
        }
    }
}

#[derive(Clone, Copy, Debug)]
#[repr(C)]
struct MasterAccount {
    position: i32,
    target_position: i32,
    last_fill_ts_ns: u64,
    total_equity: f64,
}

impl Default for MasterAccount {
    fn default() -> Self {
        Self {
            position: 0,
            target_position: 0,
            last_fill_ts_ns: 0,
            total_equity: 0.0,
        }
    }
}

struct PropScalingEngine {
    accounts: [PropAccount; 32],
    master: MasterAccount,
    num_active_accounts: u8,
    sync_lag_ns: u32,
    rate_limited_count: u8,
    last_hedge_ts_ns: u64,
    hedge_buffer: [i32; 32],
}

impl PropScalingEngine {
    fn new() -> Self {
        Self {
            accounts: [PropAccount::default(); 32],
            master: MasterAccount::default(),
            num_active_accounts: 0,
            sync_lag_ns: 0,
            rate_limited_count: 0,
            last_hedge_ts_ns: 0,
            hedge_buffer: [0; 32],
        }
    }

    fn init_accounts(&mut self) {
        for (i, account) in self.accounts.iter_mut().enumerate() {
            account.id = i as u8;
            account.status = PropAccountStatus::Active;
            account.equity = 5000.0;
            account.margin_available = 10000.0;
        }
        self.num_active_accounts = 32;
    }

    fn handle_master_fill(&mut self, qty: i32, timestamp_ns: u64) {
        self.master.position += qty;
        self.master.last_fill_ts_ns = timestamp_ns;

        // Fan out to active accounts
        if self.num_active_accounts > 0 {
            for account in self.accounts.iter_mut() {
                if account.status == PropAccountStatus::Active {
                    account.target_position = self.master.position;
                }
            }
        }

        self.update_sync_lag();
    }

    fn handle_prop_fill(&mut self, account_id: u8, qty: i32, timestamp_ns: u64) {
        let account = &mut self.accounts[account_id as usize];
        account.position += qty;
        account.last_fill_ts_ns = timestamp_ns;

        if self.master.last_fill_ts_ns > 0 {
            let latency_ns = timestamp_ns.saturating_sub(self.master.last_fill_ts_ns);
            account.fill_latency_us = (latency_ns / 1000) as u16;
        }

        self.update_sync_lag();
    }

    fn update_sync_lag(&mut self) {
        let mut max_lag = 0u32;
        for account in self.accounts.iter_mut() {
            if account.status == PropAccountStatus::Active
                && self.master.last_fill_ts_ns > 0
                && account.last_fill_ts_ns > 0
            {
                let lag = self
                    .master
                    .last_fill_ts_ns
                    .saturating_sub(account.last_fill_ts_ns) as u32;
                account.sync_lag_ns = lag;
                max_lag = max_lag.max(lag);
            }
        }
        self.sync_lag_ns = max_lag;
    }

    fn is_sync_healthy(&self) -> bool {
        self.sync_lag_ns < 100_000 && self.rate_limited_count <= 5
    }
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

fn bench_init_accounts(c: &mut Criterion) {
    c.bench_function("prop_scaling_init_accounts", |b| {
        let mut engine = PropScalingEngine::new();
        b.iter(|| {
            engine.init_accounts();
            black_box(&engine);
        });
    });
}

fn bench_master_fill(c: &mut Criterion) {
    let mut engine = PropScalingEngine::new();
    engine.init_accounts();

    c.bench_function("prop_scaling_master_fill", |b| {
        let mut ts = 1000u64;
        b.iter(|| {
            ts += 1000;
            engine.handle_master_fill(black_box(100), black_box(ts));
            black_box(&engine);
        });
    });
}

fn bench_prop_fill(c: &mut Criterion) {
    let mut engine = PropScalingEngine::new();
    engine.init_accounts();
    engine.handle_master_fill(100, 1000);

    c.bench_function("prop_scaling_prop_fill", |b| {
        let mut ts = 2000u64;
        b.iter(|| {
            ts += 100;
            engine.handle_prop_fill(black_box(0), black_box(10), black_box(ts));
            black_box(&engine);
        });
    });
}

fn bench_sync_check(c: &mut Criterion) {
    let mut engine = PropScalingEngine::new();
    engine.init_accounts();
    engine.handle_master_fill(100, 1000);

    c.bench_function("prop_scaling_sync_check", |b| {
        b.iter(|| {
            let result = engine.is_sync_healthy();
            black_box(result);
        });
    });
}

fn bench_full_cycle(c: &mut Criterion) {
    c.bench_function("prop_scaling_full_cycle", |b| {
        let mut ts = 1000u64;
        b.iter(|| {
            let mut engine = PropScalingEngine::new();
            engine.init_accounts();

            // Master fill
            ts += 1000;
            engine.handle_master_fill(100, ts);

            // Prop fills
            for i in 0..32 {
                ts += 50;
                engine.handle_prop_fill(i, 3, ts);
            }

            // Sync check
            let healthy = engine.is_sync_healthy();
            black_box(healthy);
        });
    });
}

criterion_group!(
    benches,
    bench_init_accounts,
    bench_master_fill,
    bench_prop_fill,
    bench_sync_check,
    bench_full_cycle
);
criterion_main!(benches);
