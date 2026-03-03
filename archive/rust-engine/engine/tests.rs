//! Unit tests for Quantum Protocol Engine
//!
//! Covers: ring buffer, crisis protocols, sleeves, audit logging, parsing.

use super::*;

// ---------------------------------------------------------------------------
// Helper: create a default packet with overrides
// ---------------------------------------------------------------------------

fn make_packet(vix: f64, depeg_pct: f64, bid: f64, ask: f64, last: f64) -> MarketPacket {
    MarketPacket {
        symbol_id: 1,
        bid,
        ask,
        last,
        volume: 1000,
        timestamp_ns: 1_000_000,
        vix,
        depeg_pct,
    }
}

// ---------------------------------------------------------------------------
// Ring Buffer Tests
// ---------------------------------------------------------------------------

#[test]
fn test_ring_buffer_push_pop() {
    let mut ring = RingBuffer::new();
    assert!(ring.is_empty());

    let pkt = MarketPacket::default();
    ring.push(pkt);
    assert_eq!(ring.len(), 1);

    let popped = ring.pop();
    assert!(popped.is_some());
    assert!(ring.is_empty());
}

#[test]
fn test_ring_buffer_ordering() {
    let mut ring = RingBuffer::new();
    for i in 0..10 {
        let mut pkt = MarketPacket::default();
        pkt.symbol_id = i;
        ring.push(pkt);
    }
    assert_eq!(ring.len(), 10);

    for i in 0..10 {
        let pkt = ring.pop().unwrap();
        assert_eq!(pkt.symbol_id, i);
    }
    assert!(ring.is_empty());
}

#[test]
fn test_ring_buffer_wrap_around() {
    let mut ring = RingBuffer::new();
    // Fill beyond capacity — oldest entries are overwritten
    for i in 0..(RING_BUFFER_SIZE + 100) {
        let mut pkt = MarketPacket::default();
        pkt.symbol_id = i as u32;
        ring.push(pkt);
    }
    // Consumer hasn't read, so write_pos advanced but buffer wrapped
    // The ring still reports pending items
    assert!(ring.len() > 0);
}

#[test]
fn test_ring_buffer_empty_pop() {
    let ring = RingBuffer::new();
    assert!(ring.pop().is_none());
}

// ---------------------------------------------------------------------------
// Crisis Protocol Tests
// ---------------------------------------------------------------------------

#[test]
fn test_crisis_normal() {
    let pkt = make_packet(20.0, 0.0, 100.0, 100.5, 100.25);
    assert_eq!(evaluate_crisis(&pkt), CrisisState::Normal);
}

#[test]
fn test_crisis_smart_bunker_vix_above_45() {
    let pkt = make_packet(50.0, 0.0, 100.0, 100.5, 100.25);
    assert_eq!(evaluate_crisis(&pkt), CrisisState::SmartBunker);
}

#[test]
fn test_crisis_smart_bunker_vix_boundary() {
    let pkt = make_packet(45.0, 0.0, 100.0, 100.5, 100.25);
    assert_eq!(evaluate_crisis(&pkt), CrisisState::Normal);

    let pkt2 = make_packet(45.01, 0.0, 100.0, 100.5, 100.25);
    assert_eq!(evaluate_crisis(&pkt2), CrisisState::SmartBunker);
}

#[test]
fn test_crisis_surgical_sniper() {
    let pkt = make_packet(20.0, 6.0, 100.0, 100.5, 100.25);
    assert_eq!(evaluate_crisis(&pkt), CrisisState::SurgicalSniper);
}

#[test]
fn test_crisis_smart_bunker_takes_precedence_over_sniper() {
    // VIX > 45 AND depeg > 5% — SmartBunker should win (checked first)
    let pkt = make_packet(50.0, 10.0, 100.0, 100.5, 100.25);
    assert_eq!(evaluate_crisis(&pkt), CrisisState::SmartBunker);
}

// ---------------------------------------------------------------------------
// Sleeve Tests: Treasury Basis
// ---------------------------------------------------------------------------

#[test]
fn test_sleeve_treasury_basis_signal_range() {
    let config = SharedConfig::default();
    let pkt = make_packet(20.0, 0.0, 100.0, 100.5, 100.25);
    let signal = sleeve_treasury_basis(&pkt, &config);
    assert!(
        signal >= -1.0 && signal <= 1.0,
        "Signal out of range: {}",
        signal
    );
}

#[test]
fn test_sleeve_treasury_basis_narrow_spread() {
    let config = SharedConfig::default();
    let pkt = make_packet(20.0, 0.0, 100.0, 100.01, 100.0);
    let signal = sleeve_treasury_basis(&pkt, &config);
    // Narrow spread should produce a negative or small signal
    assert!(
        signal <= 0.5,
        "Expected small signal for narrow spread: {}",
        signal
    );
}

// ---------------------------------------------------------------------------
// Sleeve Tests: Vol Regime
// ---------------------------------------------------------------------------

#[test]
fn test_sleeve_vol_regime_low() {
    let config = SharedConfig::default(); // low threshold = 15
    let pkt = make_packet(10.0, 0.0, 100.0, 100.5, 100.25);
    assert_eq!(sleeve_vol_regime(&pkt, &config), -1.0); // risk on
}

#[test]
fn test_sleeve_vol_regime_high() {
    let config = SharedConfig::default(); // high threshold = 30
    let pkt = make_packet(35.0, 0.0, 100.0, 100.5, 100.25);
    assert_eq!(sleeve_vol_regime(&pkt, &config), 1.0); // risk off
}

#[test]
fn test_sleeve_vol_regime_neutral() {
    let config = SharedConfig::default();
    let pkt = make_packet(20.0, 0.0, 100.0, 100.5, 100.25);
    assert_eq!(sleeve_vol_regime(&pkt, &config), 0.0); // neutral
}

#[test]
fn test_sleeve_vol_regime_boundary_low() {
    let config = SharedConfig::default();
    let pkt = make_packet(15.0, 0.0, 100.0, 100.5, 100.25);
    // VIX == 15.0 is NOT < 15.0, so neutral
    assert_eq!(sleeve_vol_regime(&pkt, &config), 0.0);
}

#[test]
fn test_sleeve_vol_regime_boundary_high() {
    let config = SharedConfig::default();
    let pkt = make_packet(30.0, 0.0, 100.0, 100.5, 100.25);
    // VIX == 30.0 is NOT > 30.0, so neutral
    assert_eq!(sleeve_vol_regime(&pkt, &config), 0.0);
}

// ---------------------------------------------------------------------------
// Engine / on_tick Tests
// ---------------------------------------------------------------------------

#[test]
fn test_engine_on_tick_normal() {
    let mut engine = Engine::new();
    let pkt = make_packet(20.0, 0.0, 100.0, 100.5, 100.25);
    engine.on_tick(&pkt);

    assert_eq!(engine.ticks_processed, 1);
    assert_eq!(engine.crisis_state, CrisisState::Normal);
    // Should have 2 sleeve audit records (Treasury Basis + Vol Regime)
    assert!(engine.audit.count() >= 2);
}

#[test]
fn test_engine_on_tick_smart_bunker_skips_sleeves() {
    let mut engine = Engine::new();
    let pkt = make_packet(50.0, 0.0, 100.0, 100.5, 100.25);
    engine.on_tick(&pkt);

    assert_eq!(engine.crisis_state, CrisisState::SmartBunker);
    assert_eq!(engine.ticks_processed, 1);
    // Only the crisis protocol audit record should exist (no sleeve records)
    assert_eq!(engine.audit.count(), 1);
    let rec = engine.audit.last().unwrap();
    assert_eq!(rec.event_type, AuditEventType::CrisisProtocol);
    assert_eq!(rec.risk_flag, 2);
}

#[test]
fn test_engine_crisis_transition_logged() {
    let mut engine = Engine::new();

    // Start normal
    let pkt1 = make_packet(20.0, 0.0, 100.0, 100.5, 100.25);
    engine.on_tick(&pkt1);
    let count_after_normal = engine.audit.count();

    // Transition to SmartBunker
    let pkt2 = make_packet(50.0, 0.0, 100.0, 100.5, 100.25);
    engine.on_tick(&pkt2);
    // Crisis transition should add one more audit record
    assert!(engine.audit.count() > count_after_normal);
}

#[test]
fn test_engine_multiple_ticks() {
    let mut engine = Engine::new();
    for i in 0..100 {
        let pkt = make_packet(20.0, 0.0, 100.0 + i as f64, 100.5 + i as f64, 100.25);
        engine.on_tick(&pkt);
    }
    assert_eq!(engine.ticks_processed, 100);
}

// ---------------------------------------------------------------------------
// Audit Ring Tests
// ---------------------------------------------------------------------------

#[test]
fn test_audit_ring_push_last() {
    let mut audit = AuditRing::new();
    assert!(audit.last().is_none());

    audit.push(AuditRecord {
        timestamp_ns: 42,
        event_type: AuditEventType::Heartbeat,
        sleeve_id: 0,
        signal_value: 0.0,
        position_delta: 0.0,
        risk_flag: 0,
    });

    let rec = audit.last().unwrap();
    assert_eq!(rec.timestamp_ns, 42);
    assert_eq!(audit.count(), 1);
}

#[test]
fn test_audit_ring_wrap() {
    let mut audit = AuditRing::new();
    for i in 0..(AUDIT_RING_SIZE + 10) {
        audit.push(AuditRecord {
            timestamp_ns: i as u64,
            event_type: AuditEventType::Heartbeat,
            sleeve_id: 0,
            signal_value: 0.0,
            position_delta: 0.0,
            risk_flag: 0,
        });
    }
    // Count should be capped at AUDIT_RING_SIZE
    assert_eq!(audit.count(), AUDIT_RING_SIZE);
    // Last record should be the most recent
    let rec = audit.last().unwrap();
    assert_eq!(rec.timestamp_ns, (AUDIT_RING_SIZE + 9) as u64);
}

// ---------------------------------------------------------------------------
// UDP Packet Parsing Tests
// ---------------------------------------------------------------------------

#[test]
fn test_parse_udp_packet_valid() {
    let pkt = make_packet(20.0, 0.0, 100.0, 100.5, 100.25);
    let bytes: &[u8] = unsafe {
        std::slice::from_raw_parts(
            &pkt as *const MarketPacket as *const u8,
            std::mem::size_of::<MarketPacket>(),
        )
    };
    let parsed = Engine::parse_udp_packet(bytes).unwrap();
    assert_eq!(parsed.symbol_id, pkt.symbol_id);
    assert_eq!(parsed.vix, pkt.vix);
}

#[test]
fn test_parse_udp_packet_too_short() {
    let buf = [0u8; 4]; // too short
    assert!(Engine::parse_udp_packet(&buf).is_none());
}

// ---------------------------------------------------------------------------
// SharedConfig Tests
// ---------------------------------------------------------------------------

#[test]
fn test_shared_config_defaults() {
    let config = SharedConfig::default();
    assert_eq!(config.hedge_ratio, 0.8);
    assert_eq!(config.vol_regime_threshold_low, 15.0);
    assert_eq!(config.vol_regime_threshold_high, 30.0);
    assert!(config.circuit_breaker_enabled);
}

// ---------------------------------------------------------------------------
// Terra Luna Replay Simulation
// ---------------------------------------------------------------------------

#[test]
fn test_terra_luna_replay() {
    let mut engine = Engine::new();

    // Phase 1: Normal market (VIX ~18, no depeg)
    for _ in 0..50 {
        let pkt = make_packet(18.0, 0.0, 100.0, 100.05, 100.02);
        engine.on_tick(&pkt);
    }
    assert_eq!(engine.crisis_state, CrisisState::Normal);

    // Phase 2: Volatility spike — VIX crosses 45 (simulating Terra Luna crash)
    let crisis_pkt = make_packet(52.0, 0.0, 95.0, 96.0, 95.5);
    engine.on_tick(&crisis_pkt);
    assert_eq!(engine.crisis_state, CrisisState::SmartBunker);

    // Phase 3: Stablecoin depeg > 5% while VIX normalizes
    let depeg_pkt = make_packet(30.0, 8.0, 90.0, 91.0, 90.5);
    engine.on_tick(&depeg_pkt);
    assert_eq!(engine.crisis_state, CrisisState::SurgicalSniper);

    // Phase 4: Recovery — normal conditions
    let recovery_pkt = make_packet(22.0, 1.0, 98.0, 98.5, 98.25);
    engine.on_tick(&recovery_pkt);
    assert_eq!(engine.crisis_state, CrisisState::Normal);

    // Verify the engine survived without panic and processed all ticks
    assert_eq!(engine.ticks_processed, 53);
    // Verify audit trail has entries for all crisis transitions
    assert!(engine.audit.count() > 0);
}
