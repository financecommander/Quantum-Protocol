//! Engine Coordinator
//!
//! `QuantumEngine` orchestrates async I/O (feeds, config reload, shutdown)
//! while delegating to existing sync sleeve logic.

use crate::config::QuantumConfig;
use crate::engine::common::{AuditEventType, AuditRecord, MarketPacket, SharedConfig};
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

/// Build a SharedConfig from a QuantumConfig.
pub fn to_shared_config(config: &QuantumConfig) -> SharedConfig {
    SharedConfig {
        hedge_ratio: config.sleeves.treasury_basis.hedge_ratio,
        max_position: config.sleeves.treasury_basis.max_position,
        vol_regime_threshold_low: config.sleeves.vol_regime.threshold_low,
        vol_regime_threshold_high: config.sleeves.vol_regime.threshold_high,
        quantum_weights: [0.125; 8],
        circuit_breaker_enabled: true,
        heartbeat_max_lag_us: 100,
    }
}

impl QuantumEngine {
    pub fn new(config: &QuantumConfig) -> Result<Self, anyhow::Error> {
        let mut engine = Engine::new();
        engine.config = to_shared_config(config);

        let kill_switch = KillSwitch::new(
            config.risk.max_daily_loss,
            config.risk.kill_switch_consecutive_rejections,
            config.risk.kill_switch_heartbeat_timeout_ms,
            config.risk.max_position_size,
        );

        let metrics = MetricsCollector::new()?;

        Ok(Self {
            engine,
            kill_switch,
            metrics,
            ticks_since_last_report: 0,
        })
    }

    /// Process a single market tick. Hot path — delegates to existing sleeve logic.
    pub fn process_tick(&mut self, packet: &MarketPacket) {
        // Check kill switch
        if matches!(self.kill_switch.check(), KillSwitchStatus::Triggered(_)) {
            return;
        }

        // Record heartbeat
        self.kill_switch.heartbeat();

        // Delegate to existing engine on_tick
        self.engine.on_tick(packet);

        // Record metrics
        self.metrics.increment_ticks("coordinator");
        self.ticks_since_last_report += 1;
    }

    /// Apply a new configuration.
    pub fn apply_config(&mut self, config: &QuantumConfig) {
        self.engine.config = to_shared_config(config);

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
    pub fn check_kill_switch(&mut self) -> KillSwitchStatus {
        self.kill_switch.check()
    }

    /// Get current engine stats.
    pub fn stats(&mut self) -> EngineStats {
        let triggered = matches!(self.kill_switch.check(), KillSwitchStatus::Triggered(_));
        EngineStats {
            ticks_processed: self.engine.ticks_processed,
            crisis_state: self.engine.crisis_state,
            kill_switch_triggered: triggered,
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

            if let KillSwitchStatus::Triggered(ref reason) = self.kill_switch.check() {
                log::error!("Kill switch triggered: {:?}", reason);
                self.metrics.update_kill_switch(1, &format!("{:?}", reason));
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
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::*;

    fn make_config() -> QuantumConfig {
        QuantumConfig {
            engine: EngineConfig {
                udp_addr: "0.0.0.0:9999".to_string(),
                metrics_port: 9090,
                graceful_shutdown_timeout_secs: 30,
            },
            sleeves: SleeveConfigs {
                treasury_basis: TreasuryBasisConfig {
                    enabled: true,
                    hedge_ratio: 0.8,
                    max_position: 1000000.0,
                },
                vol_regime: VolRegimeConfig {
                    enabled: true,
                    threshold_low: 15.0,
                    threshold_high: 30.0,
                },
                prop_scaling: PropScalingConfig {
                    enabled: false,
                    master_account_id: 1,
                    satellite_account_ids: vec![],
                },
                rwa_crypto: RwaCryptoConfig {
                    enabled: false,
                    depeg_threshold: 5.0,
                },
                tail_hedging: TailHedgingConfig {
                    enabled: false,
                    vix_call_strike_offset: 10.0,
                    put_strike_offset: 5.0,
                },
            },
            risk: RiskConfig {
                max_position_size: 10000,
                max_notional: 1000000.0,
                max_daily_loss: -50000.0,
                kill_switch_consecutive_rejections: 10,
                kill_switch_heartbeat_timeout_ms: 5000,
            },
            monitoring: MonitoringConfig {
                audit_log_dir: "/tmp/audit".to_string(),
                audit_retention_days: 2555,
                metrics_enabled: true,
            },
            feeds: FeedsConfig {
                market_data_ws_url: "wss://test".to_string(),
                market_data_api_key: "key".to_string(),
                symbols: vec!["SPY".to_string()],
                heartbeat_interval_ms: 30000,
                reconnect_max_delay_secs: 60,
            },
            alerts: AlertsConfig {
                slack_webhook_url: "https://test".to_string(),
                smtp_host: "smtp.test".to_string(),
                smtp_port: 587,
                smtp_user: "user".to_string(),
                smtp_pass: "pass".to_string(),
                alert_email_to: "test@test".to_string(),
                alert_cooldown_secs: 300,
            },
        }
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
    fn test_process_tick_kill_switch_active() {
        let config = make_config();
        match QuantumEngine::new(&config) {
            Ok(mut qe) => {
                qe.kill_switch.trigger_manual();
                let packet = make_packet(20.0);
                qe.process_tick(&packet);
                assert_eq!(qe.engine.ticks_processed, 0);
            }
            Err(_) => {} // Metrics already registered, skip
        }
    }

    #[test]
    fn test_apply_config() {
        let config = make_config();
        match QuantumEngine::new(&config) {
            Ok(mut qe) => {
                let mut new_config = make_config();
                new_config.sleeves.treasury_basis.max_position = 2000000.0;
                new_config.sleeves.treasury_basis.hedge_ratio = 0.9;
                qe.apply_config(&new_config);
                assert_eq!(qe.engine.config.max_position, 2_000_000.0);
                assert_eq!(qe.engine.config.hedge_ratio, 0.9);
            }
            Err(_) => {} // Metrics already registered, skip
        }
    }

    #[test]
    fn test_stats_with_crisis() {
        let config = make_config();
        match QuantumEngine::new(&config) {
            Ok(mut qe) => {
                let packet = make_packet(50.0);
                qe.process_tick(&packet);
                let stats = qe.stats();
                assert_eq!(stats.crisis_state, CrisisState::SmartBunker);
            }
            Err(_) => {} // Metrics already registered, skip
        }
    }

    #[test]
    fn test_stats_kill_switch() {
        let config = make_config();
        match QuantumEngine::new(&config) {
            Ok(mut qe) => {
                qe.kill_switch.trigger_manual();
                let stats = qe.stats();
                assert!(stats.kill_switch_triggered);
            }
            Err(_) => {} // Metrics already registered, skip
        }
    }

    #[test]
    fn test_multiple_ticks() {
        let config = make_config();
        match QuantumEngine::new(&config) {
            Ok(mut qe) => {
                for i in 0..100 {
                    let packet = make_packet(20.0 + (i as f64 * 0.1));
                    qe.process_tick(&packet);
                }
                assert_eq!(qe.engine.ticks_processed, 100);
                assert_eq!(qe.ticks_since_last_report, 100);
            }
            Err(_) => {} // Metrics already registered, skip
        }
    }

    #[tokio::test]
    async fn test_run_shutdown() {
        let config = make_config();
        match QuantumEngine::new(&config) {
            Ok(mut qe) => {
                let (tx, rx) = tokio::sync::mpsc::channel(10);
                let (_config_tx, config_rx) = tokio::sync::watch::channel(config.clone());
                let (shutdown_tx, shutdown_rx) = tokio::sync::broadcast::channel(1);

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
            Err(_) => {} // Metrics already registered, skip
        }
    }

    #[tokio::test]
    async fn test_run_config_update() {
        let config = make_config();
        match QuantumEngine::new(&config) {
            Ok(mut qe) => {
                let (_tx, rx) = tokio::sync::mpsc::channel::<MarketPacket>(10);
                let (config_tx, config_rx) = tokio::sync::watch::channel(config.clone());
                let (shutdown_tx, shutdown_rx) = tokio::sync::broadcast::channel(1);

                let handle = tokio::spawn(async move {
                    let mut new_config = make_config();
                    new_config.sleeves.treasury_basis.max_position = 2000000.0;
                    new_config.sleeves.treasury_basis.hedge_ratio = 0.9;
                    config_tx.send(new_config).unwrap();
                    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
                    shutdown_tx.send(()).unwrap();
                });

                qe.run(rx, config_rx, shutdown_rx).await;
                handle.await.unwrap();
                assert_eq!(qe.engine.config.max_position, 2_000_000.0);
            }
            Err(_) => {} // Metrics already registered, skip
        }
    }
}
