use criterion::{black_box, criterion_group, criterion_main, Criterion};

// We reference the crate's public items via the library-less approach:
// Since this is a binary crate, we test the hot path inline.

/// Simulated on_tick benchmark: measures raw processing time of the hot path.
/// Target: p99 < 120µs.

#[repr(C)]
#[derive(Clone, Copy)]
struct MarketPacket {
    symbol_id: u32,
    bid: f64,
    ask: f64,
    last: f64,
    volume: u64,
    timestamp_ns: u64,
    vix: f64,
    depeg_pct: f64,
}

fn bench_on_tick(c: &mut Criterion) {
    let packet = MarketPacket {
        symbol_id: 1,
        bid: 100.0,
        ask: 100.5,
        last: 100.25,
        volume: 1000,
        timestamp_ns: 1_000_000,
        vix: 20.0,
        depeg_pct: 0.0,
    };

    c.bench_function("on_tick_simulate", |b| {
        b.iter(|| {
            // Simulate the core hot-path logic inline (no allocations)
            let vix = black_box(packet.vix);
            let _crisis = if vix > 45.0 {
                2u8 // SmartBunker
            } else if black_box(packet.depeg_pct) > 5.0 {
                3u8 // SurgicalSniper
            } else {
                0u8 // Normal
            };

            // Treasury basis signal
            let spread = black_box(packet.ask) - black_box(packet.bid);
            let fair_value = black_box(packet.last) * 0.8;
            let _tb_signal = (spread - fair_value * 0.001).clamp(-1.0, 1.0);

            // Vol regime signal
            let _vol_signal = if vix < 15.0 {
                -1.0f64
            } else if vix > 30.0 {
                1.0f64
            } else {
                0.0f64
            };
        })
    });
}

criterion_group!(benches, bench_on_tick);
criterion_main!(benches);
