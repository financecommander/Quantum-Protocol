//! Engine Coordinator
//!
//! `QuantumEngine` orchestrates async I/O (feeds, config reload, shutdown)
//! while delegating to existing sync sleeve logic.

use crate::config::QuantumConfig;
use crate::engine::common::MarketPacket;
use crate::engine::common::{AuditEventType, AuditRecord};
use crate::engine::{CrisisState, Engine};
use crate::monitoring::metrics::MetricsCollector;
use crate::risk::kill_switch::{KillSwitch, KillSwitchStatus};

// ---------------------------------------------------------------------------
// Quantum Engine Coordinator
// ---------------------------------------------------------------------------

pub struct QuantumEngine {
    pub engine: Engine,
    pub kill_switch: KillSwitch,
    pub metrics: MetricsCollector,
    pub ticks_since_last_report: u64,
}

impl QuantumEngine {
    pub fn new(config: &QuantumConfig) -> Self {
        let mut engine = Engine::new();
        engine.config = crate::config::to_shared_config(config);

        let kill_switch = KillSwitch::new(
            config.risk.max_daily_loss,
            config.risk.max_portfolio_position,
            config.risk.max_consecutive_rejections,
            config.risk.heartbeat_timeout_ms,
        );

        Self {
            engine,
            kill_switch,
            metrics: MetricsCollector::new(),
            ticks_since_last_report: 0,
        }
    }

    /// Process a single market tick. Hot path — delegates to existing sleeve logic.
    pub fn process_tick(&mut self, packet: &MarketPacket) {
        // Check kill switch
        if self.kill_switch.is_triggered() {
            return;
        }

        // Record heartbeat
        self.kill_switch.record_heartbeat();

        // Delegate to existing engine on_tick
        self.engine.on_tick(packet);

        // Record metrics
        self.metrics.inc_ticks();
        self.ticks_since_last_report += 1;
    }

    /// Apply a new configuration.
    pub fn apply_config(&mut self, config: &QuantumConfig) {
        self.engine.config = crate::config::to_shared_config(config);

        self.engine.audit.push(AuditRecord {
            timestamp_ns: crate::engine::common::now_ns(),
            event_type: AuditEventType::ConfigUpdate,
            sleeve_id: 0,
            signal_value: 0.0,
            position_delta: 0.0,
            risk_flag: 0,
        });

        log::info!("Configuration updated");
    }

    /// Check the kill switch and return its status.
    pub fn check_kill_switch(&mut self) -> &KillSwitchStatus {
        self.kill_switch.check()
    }

    /// Get current engine stats.
    pub fn stats(&self) -> EngineStats {
        EngineStats {
            ticks_processed: self.engine.ticks_processed,
            crisis_state: self.engine.crisis_state,
            kill_switch_triggered: self.kill_switch.is_triggered(),
            avg_latency_ns: self.metrics.avg_latency_ns(),
        }
    }

    /// Run the async event loop.
    pub async fn run(
        &mut self,
        mut market_data_rx: tokio::sync::mpsc::Receiver<MarketPacket>,
        mut config_rx: tokio::sync::watch::Receiver<QuantumConfig>,
        mut shutdown_rx: tokio::sync::broadcast::Receiver<()>,
    ) {
        log::info!("QuantumEngine coordinator starting");

        loop {
            tokio::select! {
                Some(packet) = market_data_rx.recv() => {
                    self.process_tick(&packet);
                }
                Ok(()) = config_rx.changed() => {
                    let new_config = config_rx.borrow().clone();
                    self.apply_config(&new_config);
                }
                _ = shutdown_rx.recv() => {
                    log::info!("Shutdown signal received");
                    break;
                }
            }

            if let KillSwitchStatus::Triggered(ref reason) = self.kill_switch.check().clone() {
                log::error!("Kill switch triggered: {:?}", reason);
                self.metrics.inc_kill_switch();
                break;
            }
        }

        log::info!(
            "QuantumEngine stopped. Ticks processed: {}",
            self.engine.ticks_processed
        );
    }
}

#[derive(Debug)]
pub struct EngineStats {
    pub ticks_processed: u64,
    pub crisis_state: CrisisState,
    pub kill_switch_triggered: bool,
    pub avg_latency_ns: u64,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_config() -> QuantumConfig {
        toml::from_str(
            r#"
[engine]
max_position = 1000000.0
hedge_ratio = 0.8
"#,
        )
        .unwrap()
    }

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
    fn test_new_quantum_engine() {
        let config = make_config();
        let qe = QuantumEngine::new(&config);
        assert_eq!(qe.engine.config.max_position, 1_000_000.0);
        assert!(!qe.kill_switch.is_triggered());
    }

    #[test]
    fn test_process_tick() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);
        let packet = make_packet(20.0);
        qe.process_tick(&packet);
        assert_eq!(qe.engine.ticks_processed, 1);
        assert_eq!(qe.ticks_since_last_report, 1);
    }

    #[test]
    fn test_process_tick_kill_switch_active() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);
        qe.kill_switch.trigger_manual("test");

        let packet = make_packet(20.0);
        qe.process_tick(&packet);
        // Tick should be skipped
        assert_eq!(qe.engine.ticks_processed, 0);
    }

    #[test]
    fn test_apply_config() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);

        let new_config: QuantumConfig = toml::from_str(
            r#"
[engine]
max_position = 2000000.0
hedge_ratio = 0.9
"#,
        )
        .unwrap();

        qe.apply_config(&new_config);
        assert_eq!(qe.engine.config.max_position, 2_000_000.0);
        assert_eq!(qe.engine.config.hedge_ratio, 0.9);
    }

    #[test]
    fn test_stats() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);

        let packet = make_packet(20.0);
        qe.process_tick(&packet);

        let stats = qe.stats();
        assert_eq!(stats.ticks_processed, 1);
        assert_eq!(stats.crisis_state, CrisisState::Normal);
        assert!(!stats.kill_switch_triggered);
    }

    #[test]
    fn test_stats_with_crisis() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);

        let packet = make_packet(50.0); // VIX > 45 => SmartBunker
        qe.process_tick(&packet);

        let stats = qe.stats();
        assert_eq!(stats.crisis_state, CrisisState::SmartBunker);
    }

    #[test]
    fn test_stats_kill_switch() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);
        qe.kill_switch.trigger_manual("test");

        let stats = qe.stats();
        assert!(stats.kill_switch_triggered);
    }

    #[test]
    fn test_multiple_ticks() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);

        for i in 0..100 {
            let packet = make_packet(20.0 + (i as f64 * 0.1));
            qe.process_tick(&packet);
        }
        assert_eq!(qe.engine.ticks_processed, 100);
        assert_eq!(qe.ticks_since_last_report, 100);
    }

    #[tokio::test]
    async fn test_run_shutdown() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);

        let (tx, rx) = tokio::sync::mpsc::channel(10);
        let (config_tx, config_rx) = tokio::sync::watch::channel(config.clone());
        let (shutdown_tx, shutdown_rx) = tokio::sync::broadcast::channel(1);

        // Send some ticks then shutdown
        let handle = tokio::spawn(async move {
            for _ in 0..5 {
                let packet = make_packet(20.0);
                tx.send(packet).await.unwrap();
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            shutdown_tx.send(()).unwrap();
        });

        qe.run(rx, config_rx, shutdown_rx).await;
        handle.await.unwrap();

        assert_eq!(qe.engine.ticks_processed, 5);
    }

    #[tokio::test]
    async fn test_run_config_update() {
        let config = make_config();
        let mut qe = QuantumEngine::new(&config);

        let (_tx, rx) = tokio::sync::mpsc::channel::<MarketPacket>(10);
        let (config_tx, config_rx) = tokio::sync::watch::channel(config.clone());
        let (shutdown_tx, shutdown_rx) = tokio::sync::broadcast::channel(1);

        let handle = tokio::spawn(async move {
            let new_config: QuantumConfig = toml::from_str(
                r#"
[engine]
max_position = 2000000.0
hedge_ratio = 0.9
"#,
            )
            .unwrap();
            config_tx.send(new_config).unwrap();
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            shutdown_tx.send(()).unwrap();
        });

        qe.run(rx, config_rx, shutdown_rx).await;
        handle.await.unwrap();

        assert_eq!(qe.engine.config.max_position, 2_000_000.0);
    }
}
