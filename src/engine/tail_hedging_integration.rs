//! Tail Hedging Integration Module
//!
//! Integrates the Tail Hedging engine with the main trading loop.

use crate::tail_hedging::{HedgeInstrument, TailHedgingEngine, TailRiskLevel};
use crate::{AuditEventType, AuditRecord, AuditRing, MarketPacket, SharedConfig};

/// Update tail hedging engine with market data
pub fn update_tail_hedging_from_market(
    engine: &mut TailHedgingEngine,
    packet: &MarketPacket,
    audit: &mut AuditRing,
) {
    // Update VIX and detect tail events
    if let Some(event) = engine.update_vix(packet.vix, packet.timestamp_ns) {
        // Log tail event to audit
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::CrisisProtocol,
            sleeve_id: 5,
            signal_value: event.vix_level,
            position_delta: event.vix_change_pct,
            risk_flag: event.risk_level as u8,
        });
    }
}

/// Process tail hedging and rebalance if needed
pub fn process_tail_hedging_rebalance(
    engine: &mut TailHedgingEngine,
    packet: &MarketPacket,
    config: &SharedConfig,
    audit: &mut AuditRing,
) {
    // Calculate portfolio value from max_position (simplified)
    let portfolio_value = config.max_position;

    // Remove expired hedges
    let expired = engine.remove_expired_hedges();
    if expired > 0 {
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::ConfigUpdate,
            sleeve_id: 5,
            signal_value: expired as f64,
            position_delta: expired as f64, // Track number of hedges removed
            risk_flag: 0,
        });
    }

    // Rebalance hedges based on risk level
    let actions = engine.rebalance_hedges(portfolio_value);

    for action in actions {
        // In production, would execute hedge orders
        // For now, just log to audit
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::SleeveSignal,
            sleeve_id: 5,
            signal_value: action.notional,
            position_delta: action.delta,
            risk_flag: match action.instrument {
                HedgeInstrument::VixCall => 1,
                HedgeInstrument::SpxPut => 2,
                HedgeInstrument::TailFund => 3,
                HedgeInstrument::Treasury => 4,
            },
        });

        // Add the hedge position
        engine.add_hedge(action);
    }
}

/// Generate performance report for tail hedging
pub fn report_tail_hedging_performance(
    engine: &TailHedgingEngine,
    packet: &MarketPacket,
    audit: &mut AuditRing,
) {
    let stats = engine.get_stats();

    audit.push(AuditRecord {
        timestamp_ns: packet.timestamp_ns,
        event_type: AuditEventType::Heartbeat,
        sleeve_id: 5,
        signal_value: stats.total_delta,
        position_delta: stats.total_vega,
        risk_flag: stats.current_risk_level as u8,
    });
}

/// Check if tail hedging requires crisis protocol activation
pub fn check_tail_crisis_threshold(engine: &TailHedgingEngine, packet: &MarketPacket) -> bool {
    // Activate crisis if VIX is critical or we have a significant VIX spike
    engine.current_risk_level == TailRiskLevel::Critical || packet.vix > 45.0
}

// ---------------------------------------------------------------------------
// Integration Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tail_hedging::HedgePosition;

    fn make_packet(vix: f64) -> MarketPacket {
        MarketPacket {
            symbol_id: 1,
            bid: 100.0,
            ask: 100.5,
            last: 100.25,
            volume: 1000,
            timestamp_ns: 1_000_000,
            vix,
            depeg_pct: 0.0,
        }
    }

    #[test]
    fn test_update_tail_hedging_normal() {
        let mut engine = TailHedgingEngine::new();
        let mut audit = AuditRing::new();
        let packet = make_packet(18.0);

        update_tail_hedging_from_market(&mut engine, &packet, &mut audit);

        // No event expected for normal VIX
        assert_eq!(audit.count(), 0);
    }

    #[test]
    fn test_update_tail_hedging_spike() {
        let mut engine = TailHedgingEngine::new();
        let mut audit = AuditRing::new();

        engine.last_vix = 15.0;
        let packet = make_packet(50.0); // Large spike

        update_tail_hedging_from_market(&mut engine, &packet, &mut audit);

        // Should log crisis event
        assert_eq!(audit.count(), 1);
        let rec = audit.last().unwrap();
        assert_eq!(rec.event_type, AuditEventType::CrisisProtocol);
        assert_eq!(rec.sleeve_id, 5);
    }

    #[test]
    fn test_process_tail_hedging_rebalance() {
        let mut engine = TailHedgingEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();
        let packet = make_packet(35.0); // High VIX

        // Set high risk to trigger rebalance
        engine.current_risk_level = TailRiskLevel::High;

        process_tail_hedging_rebalance(&mut engine, &packet, &config, &mut audit);

        // Should generate rebalance actions
        assert!(engine.num_positions > 0);
    }

    #[test]
    fn test_process_tail_hedging_expired() {
        let mut engine = TailHedgingEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();
        let packet = make_packet(20.0);

        // Add expired position
        let expired = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 100_000.0,
            strike: 4000.0,
            expiry_days: 0, // Expired
            cost_bps: 50.0,
            delta: -0.3,
            vega: 0.5,
        };
        engine.add_hedge(expired);

        let initial_count = engine.num_positions;
        assert_eq!(initial_count, 1);

        process_tail_hedging_rebalance(&mut engine, &packet, &config, &mut audit);

        // Should log removal
        assert!(audit.count() > 0);
    }

    #[test]
    fn test_report_tail_hedging_performance() {
        let mut engine = TailHedgingEngine::new();
        let mut audit = AuditRing::new();
        let packet = make_packet(20.0);

        // Add some positions
        let position = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 100_000.0,
            strike: 4000.0,
            expiry_days: 30,
            cost_bps: 50.0,
            delta: -0.3,
            vega: 0.5,
        };
        engine.add_hedge(position);

        report_tail_hedging_performance(&engine, &packet, &mut audit);

        assert_eq!(audit.count(), 1);
        let rec = audit.last().unwrap();
        assert_eq!(rec.event_type, AuditEventType::Heartbeat);
        assert_eq!(rec.sleeve_id, 5);
    }

    #[test]
    fn test_check_tail_crisis_threshold_normal() {
        let engine = TailHedgingEngine::new();
        let packet = make_packet(20.0);

        assert!(!check_tail_crisis_threshold(&engine, &packet));
    }

    #[test]
    fn test_check_tail_crisis_threshold_critical_vix() {
        let engine = TailHedgingEngine::new();
        let packet = make_packet(50.0);

        assert!(check_tail_crisis_threshold(&engine, &packet));
    }

    #[test]
    fn test_check_tail_crisis_threshold_critical_level() {
        let mut engine = TailHedgingEngine::new();
        engine.current_risk_level = TailRiskLevel::Critical;
        let packet = make_packet(20.0);

        assert!(check_tail_crisis_threshold(&engine, &packet));
    }

    #[test]
    fn test_full_integration_flow() {
        let mut engine = TailHedgingEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();

        // Start with normal VIX
        let packet1 = make_packet(18.0);
        update_tail_hedging_from_market(&mut engine, &packet1, &mut audit);
        process_tail_hedging_rebalance(&mut engine, &packet1, &config, &mut audit);

        // VIX spike to critical level
        let packet2 = make_packet(50.0); // Critical level to trigger crisis
        update_tail_hedging_from_market(&mut engine, &packet2, &mut audit);
        process_tail_hedging_rebalance(&mut engine, &packet2, &config, &mut audit);

        // Should have crisis event and hedges
        assert!(audit.count() > 0);
        assert!(engine.num_positions > 0);

        // Report performance
        report_tail_hedging_performance(&engine, &packet2, &mut audit);

        // Verify crisis threshold
        assert!(check_tail_crisis_threshold(&engine, &packet2));
    }
}
