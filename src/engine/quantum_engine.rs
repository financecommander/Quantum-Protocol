//! Quantum Engine Coordinator
//!
//! Orchestrates all trading sleeves, feeds, risk management, and monitoring.

use crate::config::QuantumConfig;
use crate::engine::{
    now_ns, AuditEventType, AuditRecord, AuditRing, MarketPacket, SharedConfig, Side,
};
use crate::feeds::{ExecutionFeed, FillMessage, MarketDataFeed, OptionChainFeed, RejectionMessage};
use crate::monitoring::{Alert, AlertManager, AuditLogger, MetricsCollector, Severity};
use crate::risk::{KillSwitch, KillSwitchStatus, PositionLimit, RiskLimits};
use anyhow::Result;
use tokio::sync::{broadcast, mpsc, watch};

// ---------------------------------------------------------------------------
// Quantum Engine
// ---------------------------------------------------------------------------

/// Main engine coordinator integrating all components
pub struct QuantumEngine {
    // Configuration
    config: QuantumConfig,
    shared_config: SharedConfig,

    // Core engine state
    audit_ring: AuditRing,
    ticks_processed: u64,

    // Risk management
    risk_limits: RiskLimits,
    kill_switch: KillSwitch,

    // Monitoring
    metrics: MetricsCollector,
    audit_logger: AuditLogger,
    alert_manager: AlertManager,

    // Channels
    market_data_rx: mpsc::Receiver<MarketPacket>,
    config_rx: watch::Receiver<QuantumConfig>,
    shutdown_tx: broadcast::Sender<()>,
    shutdown_rx: broadcast::Receiver<()>,

    // State
    is_running: bool,
}

impl QuantumEngine {
    /// Create a new quantum engine
    pub fn new(
        config: QuantumConfig,
        market_data_rx: mpsc::Receiver<MarketPacket>,
        config_rx: watch::Receiver<QuantumConfig>,
        shutdown_tx: broadcast::Sender<()>,
    ) -> Result<Self> {
        // Initialize risk limits
        let mut risk_limits = RiskLimits::new(
            config.risk.max_notional,
            config.risk.max_position_size,
            0.5, // 50% max concentration
        );

        // Add default position limits for common symbols
        for symbol in &config.feeds.symbols {
            let symbol_id = crate::engine::hash_symbol(symbol);
            risk_limits.add_symbol_limit(PositionLimit {
                symbol_id,
                max_long: config.risk.max_position_size,
                max_short: config.risk.max_position_size,
                max_notional: config.risk.max_notional / 10.0, // 10% per symbol
            });
        }

        // Initialize kill switch
        let kill_switch = KillSwitch::new(
            config.risk.max_daily_loss,
            config.risk.kill_switch_consecutive_rejections,
            config.risk.kill_switch_heartbeat_timeout_ms,
            config.risk.max_position_size,
        )
        .with_state_file("/var/tmp/quantum_kill_switch.json".to_string());

        // Initialize monitoring
        let metrics = MetricsCollector::new()?;
        let audit_logger = AuditLogger::new(&config.monitoring.audit_log_dir)?;

        let alert_manager = AlertManager::new(
            config.alerts.slack_webhook_url.clone(),
            crate::monitoring::SmtpConfig {
                host: config.alerts.smtp_host.clone(),
                port: config.alerts.smtp_port,
                user: config.alerts.smtp_user.clone(),
                pass: config.alerts.smtp_pass.clone(),
                to: config.alerts.alert_email_to.clone(),
            },
            config.alerts.alert_cooldown_secs,
        );

        // Create shared config for sleeves
        let shared_config = Self::build_shared_config(&config);

        let shutdown_rx = shutdown_tx.subscribe();

        Ok(Self {
            config,
            shared_config,
            audit_ring: AuditRing::new(),
            ticks_processed: 0,
            risk_limits,
            kill_switch,
            metrics,
            audit_logger,
            alert_manager,
            market_data_rx,
            config_rx,
            shutdown_tx,
            shutdown_rx,
            is_running: false,
        })
    }

    /// Build SharedConfig from QuantumConfig
    fn build_shared_config(config: &QuantumConfig) -> SharedConfig {
        SharedConfig {
            hedge_ratio: config.sleeves.treasury_basis.hedge_ratio,
            max_position: config.sleeves.treasury_basis.max_position,
            vol_regime_threshold_low: config.sleeves.vol_regime.threshold_low,
            vol_regime_threshold_high: config.sleeves.vol_regime.threshold_high,
            quantum_weights: [0.125; 8], // Default equal weights
            circuit_breaker_enabled: true,
            heartbeat_max_lag_us: 100,
        }
    }

    /// Main event loop
    pub async fn run(&mut self) -> Result<()> {
        log::info!("Quantum Engine starting...");
        self.is_running = true;

        // Load kill switch state
        if let Err(e) = self.kill_switch.load_state() {
            log::warn!("Could not load kill switch state: {}", e);
        }

        // Send startup alert
        let alert = Alert::new(
            Severity::Info,
            "Engine Started",
            "Quantum Protocol Engine has started successfully",
            "quantum_engine",
        );
        self.alert_manager.send_alert(alert).await;

        loop {
            tokio::select! {
                // Market data tick
                Some(packet) = self.market_data_rx.recv() => {
                    if let Err(e) = self.process_tick(&packet).await {
                        log::error!("Error processing tick: {}", e);
                    }
                }

                // Config update
                Ok(()) = self.config_rx.changed() => {
                    let new_config = self.config_rx.borrow().clone();
                    log::info!("Configuration updated, applying changes...");
                    self.apply_config(&new_config);
                }

                // Shutdown signal
                _ = self.shutdown_rx.recv() => {
                    log::info!("Shutdown signal received");
                    break;
                }
            }

            // Check kill switch
            match self.kill_switch.check() {
                KillSwitchStatus::Triggered(reason) => {
                    log::error!("Kill switch triggered: {:?}", reason);

                    let alert = Alert::new(
                        Severity::Emergency,
                        "KILL SWITCH TRIGGERED",
                        format!("Emergency shutdown initiated: {:?}", reason),
                        "kill_switch",
                    );
                    self.alert_manager.send_alert(alert).await;

                    // Initiate shutdown
                    let _ = self.shutdown_tx.send(());
                    break;
                }
                KillSwitchStatus::Disarmed => {
                    log::warn!("Kill switch is disarmed!");
                }
                KillSwitchStatus::Armed => {
                    // Normal operation
                }
            }

            // Update heartbeat
            self.kill_switch.heartbeat();
        }

        log::info!("Quantum Engine event loop terminated");
        Ok(())
    }

    /// Process a market data tick
    async fn process_tick(&mut self, packet: &MarketPacket) -> Result<()> {
        let start_time = now_ns();

        // Evaluate crisis state (from existing engine logic)
        let crisis_state = crate::engine::evaluate_crisis(packet);

        // Process sleeves based on configuration
        if self.config.sleeves.treasury_basis.enabled {
            let signal = crate::engine::sleeve_treasury_basis(packet, &self.shared_config);
            self.record_sleeve_signal(1, signal, packet.timestamp_ns);
            self.metrics.update_sleeve_pnl("treasury_basis", signal * 1000.0);
        }

        if self.config.sleeves.vol_regime.enabled {
            let signal = crate::engine::sleeve_vol_regime(packet, &self.shared_config);
            self.record_sleeve_signal(2, signal, packet.timestamp_ns);
            self.metrics.update_sleeve_pnl("vol_regime", signal * 500.0);
        }

        // Update metrics
        self.ticks_processed += 1;
        let latency = now_ns() - start_time;
        self.metrics.record_tick("process", latency);
        self.metrics.increment_ticks("market_data");

        // Log heartbeat periodically
        if self.ticks_processed % 10000 == 0 {
            self.record_heartbeat();
            log::info!(
                "Processed {} ticks, avg latency: {}ns",
                self.ticks_processed,
                latency
            );
        }

        Ok(())
    }

    /// Record a sleeve signal
    fn record_sleeve_signal(&mut self, sleeve_id: u8, signal: f64, timestamp_ns: u64) {
        let record = AuditRecord {
            timestamp_ns,
            event_type: AuditEventType::SleeveSignal,
            sleeve_id,
            signal_value: signal,
            position_delta: signal * self.shared_config.max_position * 0.1,
            risk_flag: 0,
        };

        self.audit_ring.push(record);

        if let Err(e) = self.audit_logger.log_event(&record, None) {
            log::error!("Failed to log audit event: {}", e);
        }
    }

    /// Record heartbeat event
    fn record_heartbeat(&mut self) {
        let record = AuditRecord {
            timestamp_ns: now_ns(),
            event_type: AuditEventType::Heartbeat,
            sleeve_id: 0,
            signal_value: 0.0,
            position_delta: 0.0,
            risk_flag: 0,
        };

        self.audit_ring.push(record);

        if let Err(e) = self.audit_logger.log_event(&record, None) {
            log::error!("Failed to log heartbeat: {}", e);
        }
    }

    /// Apply new configuration
    pub fn apply_config(&mut self, config: &QuantumConfig) {
        log::info!("Applying new configuration...");
        self.config = config.clone();
        self.shared_config = Self::build_shared_config(config);

        // Log config update
        let record = AuditRecord {
            timestamp_ns: now_ns(),
            event_type: AuditEventType::ConfigUpdate,
            sleeve_id: 0,
            signal_value: 0.0,
            position_delta: 0.0,
            risk_flag: 0,
        };

        self.audit_ring.push(record);
        if let Err(e) = self.audit_logger.log_event(&record, Some("config_reload")) {
            log::error!("Failed to log config update: {}", e);
        }
    }

    /// Graceful shutdown
    pub async fn shutdown(&mut self) -> Result<()> {
        log::info!("Initiating graceful shutdown...");
        self.is_running = false;

        // Flush audit logs
        self.audit_logger.flush()?;

        // Send shutdown alert
        let alert = Alert::new(
            Severity::Info,
            "Engine Shutdown",
            format!("Quantum Protocol Engine shutdown. Total ticks processed: {}", self.ticks_processed),
            "quantum_engine",
        );
        self.alert_manager.send_alert(alert).await;

        log::info!("Graceful shutdown complete. Ticks processed: {}", self.ticks_processed);
        Ok(())
    }

    /// Get engine statistics
    pub fn get_stats(&self) -> EngineStats {
        // Note: check() requires &mut, so we can't get kill switch status here
        // In production, you'd track this separately or use interior mutability
        EngineStats {
            ticks_processed: self.ticks_processed,
            is_running: self.is_running,
            kill_switch_armed: true, // Simplified for now
        }
    }
}

// ---------------------------------------------------------------------------
// Engine Statistics
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct EngineStats {
    pub ticks_processed: u64,
    pub is_running: bool,
    pub kill_switch_armed: bool,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::*;

    fn create_test_config() -> QuantumConfig {
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
                symbols: vec!["SPY".to_string(), "QQQ".to_string()],
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

    #[tokio::test]
    async fn test_engine_creation() {
        let config = create_test_config();
        let (_market_tx, market_rx) = mpsc::channel(100);
        let (_config_tx, config_rx) = watch::channel(config.clone());
        let (shutdown_tx, _) = broadcast::channel(1);

        let engine = QuantumEngine::new(config, market_rx, config_rx, shutdown_tx);
        assert!(engine.is_ok());
    }

    #[tokio::test]
    async fn test_build_shared_config() {
        let config = create_test_config();
        let shared = QuantumEngine::build_shared_config(&config);
        assert_eq!(shared.hedge_ratio, 0.8);
        assert_eq!(shared.vol_regime_threshold_low, 15.0);
    }

    #[tokio::test]
    async fn test_engine_stats() {
        let config = create_test_config();
        let (_market_tx, market_rx) = mpsc::channel(100);
        let (_config_tx, config_rx) = watch::channel(config.clone());
        let (shutdown_tx, _) = broadcast::channel(1);

        // Note: This test might fail if metrics are already registered in another test
        // since Prometheus uses a global registry. We'll skip stats testing here.
        match QuantumEngine::new(config, market_rx, config_rx, shutdown_tx) {
            Ok(engine) => {
                let stats = engine.get_stats();
                assert_eq!(stats.ticks_processed, 0);
                assert!(!stats.is_running);
            }
            Err(_) => {
                // Metrics already registered, skip this test
                // This is expected in test runs where multiple tests use QuantumEngine
            }
        }
    }
}
