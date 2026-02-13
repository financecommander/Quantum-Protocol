//! RWA/Crypto HFT Integration Module
//!
//! Integrates the RWA/Crypto HFT engine with the main trading loop.

use crate::rwa_crypto_hft::{ArbitrageOpportunity, CryptoPair, RwaCryptoEngine};
use crate::{AuditEventType, AuditRecord, AuditRing, MarketPacket, SharedConfig};

/// Update RWA/Crypto engine with market data
pub fn update_rwa_crypto_from_market(
    engine: &mut RwaCryptoEngine,
    packet: &MarketPacket,
    audit: &mut AuditRing,
) {
    // Interpret market packet as crypto pair data
    // In production, this would come from multiple venue feeds
    let pair = CryptoPair {
        symbol_id: packet.symbol_id,
        spot_price: packet.bid,
        futures_price: packet.ask,
        funding_rate: (packet.ask - packet.bid) / packet.bid,
        volume_24h: packet.volume as f64,
        last_update_ns: packet.timestamp_ns,
    };

    engine.update_pair(pair);

    // Scan for opportunities
    let found = engine.scan_opportunities(packet.timestamp_ns);

    if found > 0 {
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::SleeveSignal,
            sleeve_id: 4,
            signal_value: found as f64,
            position_delta: 0.0,
            risk_flag: 0,
        });
    }
}

/// Process arbitrage opportunities and execute trades
pub fn process_rwa_crypto_opportunities(
    engine: &mut RwaCryptoEngine,
    packet: &MarketPacket,
    config: &SharedConfig,
    audit: &mut AuditRing,
) {
    // Check circuit breaker
    if !config.circuit_breaker_enabled {
        return;
    }

    // Clear stale opportunities (older than 1ms)
    engine.clear_stale_opportunities(packet.timestamp_ns, 1_000_000);

    // Execute best opportunity if available
    if let Some(opp) = engine.execute_best_opportunity() {
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::SleeveSignal,
            sleeve_id: 4,
            signal_value: opp.spread_bps,
            position_delta: opp.profit_potential,
            risk_flag: if opp.confidence > 0.8 { 0 } else { 1 },
        });
    }
}

/// Generate performance report for RWA/Crypto sleeve
pub fn report_rwa_crypto_performance(
    engine: &RwaCryptoEngine,
    packet: &MarketPacket,
    audit: &mut AuditRing,
) {
    let stats = engine.get_stats();

    if stats.total_executions > 0 {
        audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::Heartbeat,
            sleeve_id: 4,
            signal_value: stats.total_executions as f64,
            position_delta: stats.total_profit,
            risk_flag: if stats.avg_profit_per_trade > 0.0 {
                0
            } else {
                1
            },
        });
    }
}

// ---------------------------------------------------------------------------
// Integration Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_packet(symbol_id: u32, bid: f64, ask: f64, volume: u64) -> MarketPacket {
        MarketPacket {
            symbol_id,
            bid,
            ask,
            last: (bid + ask) / 2.0,
            volume,
            timestamp_ns: 1_000_000,
            vix: 20.0,
            depeg_pct: 0.0,
        }
    }

    #[test]
    fn test_update_rwa_crypto_from_market() {
        let mut engine = RwaCryptoEngine::new();
        let mut audit = AuditRing::new();
        let packet = make_packet(1, 50000.0, 50100.0, 1_000_000);

        update_rwa_crypto_from_market(&mut engine, &packet, &mut audit);

        assert_eq!(engine.num_pairs, 1);
        assert_eq!(engine.pairs[0].symbol_id, 1);
    }

    #[test]
    fn test_update_with_arbitrage_opportunity() {
        let mut engine = RwaCryptoEngine::new();
        let mut audit = AuditRing::new();

        // Large spread should trigger opportunity
        let packet = make_packet(1, 50000.0, 50500.0, 1_000_000);

        update_rwa_crypto_from_market(&mut engine, &packet, &mut audit);

        // Should find opportunities
        assert!(engine.num_opportunities > 0);
        // Should log to audit
        assert_eq!(audit.count(), 1);
    }

    #[test]
    fn test_process_rwa_crypto_opportunities() {
        let mut engine = RwaCryptoEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();
        let packet = make_packet(1, 50000.0, 50500.0, 1_000_000);

        // Add an opportunity manually
        engine.opportunities[0] = ArbitrageOpportunity {
            timestamp_ns: packet.timestamp_ns,
            symbol_id: 1,
            venue_a_price: 50000.0,
            venue_b_price: 50500.0,
            spread_bps: 100.0,
            profit_potential: 98.0,
            confidence: 0.9,
        };
        engine.num_opportunities = 1;

        process_rwa_crypto_opportunities(&mut engine, &packet, &config, &mut audit);

        // Should execute the opportunity
        assert_eq!(engine.total_executions, 1);
        assert_eq!(audit.count(), 1);
    }

    #[test]
    fn test_process_with_circuit_breaker_disabled() {
        let mut engine = RwaCryptoEngine::new();
        let mut audit = AuditRing::new();
        let mut config = SharedConfig::default();
        config.circuit_breaker_enabled = false;
        let packet = make_packet(1, 50000.0, 50500.0, 1_000_000);

        // Add an opportunity
        engine.opportunities[0] = ArbitrageOpportunity {
            timestamp_ns: packet.timestamp_ns,
            symbol_id: 1,
            venue_a_price: 50000.0,
            venue_b_price: 50500.0,
            spread_bps: 100.0,
            profit_potential: 98.0,
            confidence: 0.9,
        };
        engine.num_opportunities = 1;

        process_rwa_crypto_opportunities(&mut engine, &packet, &config, &mut audit);

        // Should NOT execute due to circuit breaker
        assert_eq!(engine.total_executions, 0);
        assert_eq!(audit.count(), 0);
    }

    #[test]
    fn test_report_rwa_crypto_performance() {
        let mut engine = RwaCryptoEngine::new();
        let mut audit = AuditRing::new();
        let packet = make_packet(1, 50000.0, 50100.0, 1_000_000);

        // Simulate some executions
        engine.total_executions = 10;
        engine.total_profit = 150.0;

        report_rwa_crypto_performance(&engine, &packet, &mut audit);

        assert_eq!(audit.count(), 1);
        let rec = audit.last().unwrap();
        assert_eq!(rec.event_type, AuditEventType::Heartbeat);
        assert_eq!(rec.sleeve_id, 4);
    }

    #[test]
    fn test_full_integration_flow() {
        let mut engine = RwaCryptoEngine::new();
        let mut audit = AuditRing::new();
        let config = SharedConfig::default();

        // Simulate multiple market updates
        for i in 0..5 {
            let packet = make_packet(
                i + 1,
                50000.0 + (i as f64 * 100.0),
                50400.0 + (i as f64 * 100.0),
                1_000_000,
            );

            update_rwa_crypto_from_market(&mut engine, &packet, &mut audit);
            process_rwa_crypto_opportunities(&mut engine, &packet, &config, &mut audit);
        }

        // Should have multiple pairs
        assert_eq!(engine.num_pairs, 5);

        // Should have executed some trades
        assert!(engine.total_executions > 0);

        // Report performance
        let packet = make_packet(1, 50000.0, 50100.0, 1_000_000);
        report_rwa_crypto_performance(&engine, &packet, &mut audit);

        // Should have audit records
        assert!(audit.count() > 0);
    }
}
