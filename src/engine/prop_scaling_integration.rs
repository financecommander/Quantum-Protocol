//! Prop Scaling Integration Module
//!
//! Integrates the PropScalingEngine with the main trading engine loop.
//! Handles market data updates, fill/rejection events, and audit logging.

#[cfg(test)]
use crate::prop_scaling::PropAccountStatus;
use crate::prop_scaling::PropScalingEngine;
use crate::{AuditEventType, AuditRecord, AuditRing, FillEvent, MarketPacket, SharedConfig, Side};

/// Update prop scaling targets based on market conditions
pub fn update_prop_scaling_targets(
    engine: &mut PropScalingEngine,
    packet: &MarketPacket,
    config: &SharedConfig,
    audit: &mut AuditRing,
) {
    // Use VIX as a risk metric to adjust position sizing
    let risk_factor = if packet.vix < config.vol_regime_threshold_low {
        1.0 // Low vol - full size
    } else if packet.vix > config.vol_regime_threshold_high {
        0.5 // High vol - reduce size
    } else {
        0.75 // Medium vol
    };

    // Calculate target position from spread signal
    let spread = packet.ask - packet.bid;
    let target_signal = (spread / packet.last).clamp(-1.0, 1.0);
    let base_position = (target_signal * config.max_position) as i32;
    let adjusted_position = (base_position as f64 * risk_factor) as i32;

    // Update master target
    engine.master.target_position = adjusted_position;

    // Audit the signal
    audit.push(AuditRecord {
        timestamp_ns: packet.timestamp_ns,
        event_type: AuditEventType::SleeveSignal,
        sleeve_id: 3,
        signal_value: target_signal,
        position_delta: adjusted_position as f64,
        risk_flag: if !engine.is_sync_healthy() { 1 } else { 0 },
    });
}

/// Process prop scaling engine state and generate audit records
pub fn process_prop_scaling_state(
    engine: &PropScalingEngine,
    packet: &MarketPacket,
    audit: &mut AuditRing,
) {
    // Check sync health and log if degraded
    if !engine.is_sync_healthy() {
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::CircuitBreaker,
            sleeve_id: 3,
            signal_value: engine.sync_lag_ns as f64,
            position_delta: 0.0,
            risk_flag: 2, // Degraded sync
        });
    }

    // Log hedging operations
    if engine.hedge_buffer.iter().any(|&qty| qty != 0) {
        let total_hedge_qty: i32 = engine.hedge_buffer.iter().sum();
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::SleeveSignal,
            sleeve_id: 3,
            signal_value: total_hedge_qty as f64,
            position_delta: total_hedge_qty as f64,
            risk_flag: 3, // Auto-hedge flag
        });
    }
}

/// Simulate a master fill event for testing
pub fn simulate_master_fill(
    engine: &mut PropScalingEngine,
    timestamp_ns: u64,
    qty: i32,
    price: f64,
) {
    let fill = FillEvent {
        timestamp_ns,
        account_id: 0,
        side: if qty > 0 { Side::Buy } else { Side::Sell },
        qty: qty.abs(),
        price,
        is_master: true,
    };

    engine.handle_master_fill(fill);
}

/// Simulate a prop account fill event for testing
pub fn simulate_prop_fill(
    engine: &mut PropScalingEngine,
    account_id: u8,
    timestamp_ns: u64,
    qty: i32,
    price: f64,
) {
    let fill = FillEvent {
        timestamp_ns,
        account_id,
        side: if qty > 0 { Side::Buy } else { Side::Sell },
        qty: qty.abs(),
        price,
        is_master: false,
    };

    engine.handle_prop_fill(fill);
}

// ---------------------------------------------------------------------------
// Integration Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_packet(vix: f64, bid: f64, ask: f64, last: f64) -> MarketPacket {
        MarketPacket {
            symbol_id: 1,
            bid,
            ask,
            last,
            volume: 1000,
            timestamp_ns: 1_000_000,
            vix,
            depeg_pct: 0.0,
        }
    }

    #[test]
    fn test_update_prop_scaling_targets_low_vol() {
        let mut engine = PropScalingEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();
        let packet = make_packet(10.0, 100.0, 100.5, 100.25);

        update_prop_scaling_targets(&mut engine, &packet, &config, &mut audit);

        // Low vol should use full risk factor (1.0)
        assert_ne!(engine.master.target_position, 0);
        assert_eq!(audit.count(), 1);
    }

    #[test]
    fn test_update_prop_scaling_targets_high_vol() {
        let mut engine = PropScalingEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();
        let packet = make_packet(35.0, 100.0, 100.5, 100.25);

        update_prop_scaling_targets(&mut engine, &packet, &config, &mut audit);

        // High vol should reduce position size
        // The actual target depends on spread calculation
        assert_eq!(audit.count(), 1);
    }

    #[test]
    fn test_process_prop_scaling_state_unhealthy() {
        let mut engine = PropScalingEngine::new();
        let mut audit = AuditRing::new();
        let packet = make_packet(20.0, 100.0, 100.5, 100.25);

        // Make sync unhealthy
        engine.sync_lag_ns = 200_000; // 200µs

        process_prop_scaling_state(&engine, &packet, &mut audit);

        // Should log circuit breaker event
        assert_eq!(audit.count(), 1);
        let rec = audit.last().unwrap();
        assert_eq!(rec.event_type, AuditEventType::CircuitBreaker);
        assert_eq!(rec.risk_flag, 2);
    }

    #[test]
    fn test_process_prop_scaling_state_hedge_pending() {
        let mut engine = PropScalingEngine::new();
        let mut audit = AuditRing::new();
        let packet = make_packet(20.0, 100.0, 100.5, 100.25);

        // Add pending hedge
        engine.hedge_buffer[0] = 100;

        process_prop_scaling_state(&engine, &packet, &mut audit);

        // Should log hedge event
        assert_eq!(audit.count(), 1);
        let rec = audit.last().unwrap();
        assert_eq!(rec.event_type, AuditEventType::SleeveSignal);
        assert_eq!(rec.risk_flag, 3);
    }

    #[test]
    fn test_simulate_master_fill_buy() {
        let mut engine = PropScalingEngine::new();

        simulate_master_fill(&mut engine, 1000, 100, 50.0);

        assert_eq!(engine.master.position, 100);
        assert_eq!(engine.master.last_fill_ts_ns, 1000);
    }

    #[test]
    fn test_simulate_master_fill_sell() {
        let mut engine = PropScalingEngine::new();
        engine.master.position = 100;

        simulate_master_fill(&mut engine, 1000, -50, 50.0);

        assert_eq!(engine.master.position, 50);
    }

    #[test]
    fn test_simulate_prop_fill() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].status = PropAccountStatus::Active;
        engine.master.last_fill_ts_ns = 1000;

        simulate_prop_fill(&mut engine, 0, 1500, 50, 50.0);

        assert_eq!(engine.accounts[0].position, 50);
        assert_eq!(engine.accounts[0].last_fill_ts_ns, 1500);
    }

    #[test]
    fn test_full_integration_flow() {
        let mut engine = PropScalingEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();

        // Initialize accounts
        engine.init_accounts();
        for i in 0..5 {
            engine.accounts[i].status = PropAccountStatus::Active;
            engine.accounts[i].equity = 5000.0;
            engine.accounts[i].margin_available = 10000.0;
        }
        engine.num_active_accounts = 5;

        // Receive market data
        let packet = make_packet(18.0, 100.0, 100.5, 100.25);
        update_prop_scaling_targets(&mut engine, &packet, &config, &mut audit);

        // Simulate master fill
        simulate_master_fill(&mut engine, 2000, 100, 100.25);

        // Simulate prop fills with some latency
        for i in 0..5 {
            simulate_prop_fill(&mut engine, i as u8, 2000 + (i * 100), 20, 100.25);
        }

        // Check state
        process_prop_scaling_state(&engine, &packet, &mut audit);

        // Verify master position
        assert_eq!(engine.master.position, 100);

        // Verify prop positions
        for i in 0..5 {
            assert_eq!(engine.accounts[i].position, 20);
        }

        // Audit should have multiple records
        assert!(audit.count() >= 1);
    }
}
