//! Configuration System
//!
//! TOML-based configuration with hot reload, schema validation, and environment variable substitution.

use anyhow::{Context, Result};
use notify::{Event, RecommendedWatcher, RecursiveMode, Watcher};
use serde::Deserialize;
use std::path::Path;
use std::sync::Arc;
use tokio::sync::watch;

// ---------------------------------------------------------------------------
// Configuration Structures
// ---------------------------------------------------------------------------

/// Main configuration structure for the Quantum Protocol engine
#[derive(Debug, Clone, Deserialize)]
pub struct QuantumConfig {
    pub engine: EngineConfig,
    pub sleeves: SleeveConfigs,
    pub risk: RiskConfig,
    pub monitoring: MonitoringConfig,
    pub feeds: FeedsConfig,
    pub alerts: AlertsConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EngineConfig {
    pub udp_addr: String,
    pub metrics_port: u16,
    pub graceful_shutdown_timeout_secs: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SleeveConfigs {
    pub treasury_basis: TreasuryBasisConfig,
    pub vol_regime: VolRegimeConfig,
    pub prop_scaling: PropScalingConfig,
    pub rwa_crypto: RwaCryptoConfig,
    pub tail_hedging: TailHedgingConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TreasuryBasisConfig {
    pub enabled: bool,
    pub hedge_ratio: f64,
    pub max_position: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct VolRegimeConfig {
    pub enabled: bool,
    pub threshold_low: f64,
    pub threshold_high: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PropScalingConfig {
    pub enabled: bool,
    pub master_account_id: u8,
    pub satellite_account_ids: Vec<u8>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RwaCryptoConfig {
    pub enabled: bool,
    pub depeg_threshold: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TailHedgingConfig {
    pub enabled: bool,
    pub vix_call_strike_offset: f64,
    pub put_strike_offset: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RiskConfig {
    pub max_position_size: i64,
    pub max_notional: f64,
    pub max_daily_loss: f64,
    pub kill_switch_consecutive_rejections: u32,
    pub kill_switch_heartbeat_timeout_ms: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct MonitoringConfig {
    pub audit_log_dir: String,
    pub audit_retention_days: u32,
    pub metrics_enabled: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FeedsConfig {
    pub market_data_ws_url: String,
    pub market_data_api_key: String,
    pub symbols: Vec<String>,
    pub heartbeat_interval_ms: u64,
    pub reconnect_max_delay_secs: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AlertsConfig {
    pub slack_webhook_url: String,
    pub smtp_host: String,
    pub smtp_port: u16,
    pub smtp_user: String,
    pub smtp_pass: String,
    pub alert_email_to: String,
    pub alert_cooldown_secs: u64,
}

// ---------------------------------------------------------------------------
// Configuration Loading
// ---------------------------------------------------------------------------

/// Load configuration from a TOML file with environment variable substitution
pub fn load_config(path: &str) -> Result<QuantumConfig> {
    let content = std::fs::read_to_string(path)
        .with_context(|| format!("Failed to read config file: {}", path))?;

    // Perform environment variable substitution
    let content = substitute_env_vars(&content);

    let config: QuantumConfig = toml::from_str(&content)
        .with_context(|| format!("Failed to parse config file: {}", path))?;

    // Validate the configuration
    validate_config(&config)?;

    Ok(config)
}

/// Substitute environment variables in the format ${ENV_VAR}
fn substitute_env_vars(content: &str) -> String {
    let mut result = content.to_string();
    let re = regex::Regex::new(r"\$\{([A-Z_][A-Z0-9_]*)\}").unwrap();

    for cap in re.captures_iter(content) {
        let env_var = &cap[1];
        if let Ok(value) = std::env::var(env_var) {
            result = result.replace(&cap[0], &value);
        }
    }

    result
}

/// Validate configuration values
fn validate_config(config: &QuantumConfig) -> Result<()> {
    // Validate risk config
    if config.risk.max_position_size <= 0 {
        anyhow::bail!("risk.max_position_size must be positive");
    }
    if config.risk.max_notional <= 0.0 {
        anyhow::bail!("risk.max_notional must be positive");
    }
    if config.risk.max_daily_loss >= 0.0 {
        anyhow::bail!("risk.max_daily_loss must be negative");
    }

    // Validate sleeve configs
    if config.sleeves.treasury_basis.enabled
        && (config.sleeves.treasury_basis.hedge_ratio <= 0.0
            || config.sleeves.treasury_basis.hedge_ratio > 1.0)
    {
        anyhow::bail!("treasury_basis.hedge_ratio must be in (0, 1]");
    }

    if config.sleeves.vol_regime.enabled
        && config.sleeves.vol_regime.threshold_low >= config.sleeves.vol_regime.threshold_high
    {
        anyhow::bail!("vol_regime.threshold_low must be less than threshold_high");
    }

    // Validate feeds config
    if config.feeds.symbols.is_empty() {
        anyhow::bail!("feeds.symbols cannot be empty");
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Hot Reload
// ---------------------------------------------------------------------------

/// Watch configuration file for changes and send updates through the channel
pub async fn watch_config(path: String, tx: watch::Sender<QuantumConfig>) -> Result<()> {
    let path_arc = Arc::new(path.clone());
    let tx_arc = Arc::new(tx);

    let (event_tx, mut event_rx) = tokio::sync::mpsc::channel(100);

    // Create watcher
    let mut watcher: RecommendedWatcher =
        notify::recommended_watcher(move |res: Result<Event, notify::Error>| {
            if let Ok(event) = res {
                if matches!(
                    event.kind,
                    notify::EventKind::Modify(_) | notify::EventKind::Create(_)
                ) {
                    let _ = event_tx.blocking_send(());
                }
            }
        })?;

    watcher.watch(Path::new(&path), RecursiveMode::NonRecursive)?;

    log::info!("Watching config file for changes: {}", path);

    // Keep watcher alive and process events
    loop {
        tokio::select! {
            Some(_) = event_rx.recv() => {
                log::info!("Config file changed, reloading...");
                match load_config(&path_arc) {
                    Ok(new_config) => {
                        if let Err(e) = tx_arc.send(new_config) {
                            log::error!("Failed to send config update: {}", e);
                        } else {
                            log::info!("Config reloaded successfully");
                        }
                    }
                    Err(e) => {
                        log::error!("Failed to reload config: {}", e);
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_load_valid_config() {
        let toml_content = r#"
[engine]
udp_addr = "0.0.0.0:9999"
metrics_port = 9090
graceful_shutdown_timeout_secs = 30

[sleeves.treasury_basis]
enabled = true
hedge_ratio = 0.8
max_position = 1000000.0

[sleeves.vol_regime]
enabled = true
threshold_low = 15.0
threshold_high = 30.0

[sleeves.prop_scaling]
enabled = true
master_account_id = 1
satellite_account_ids = [2, 3, 4]

[sleeves.rwa_crypto]
enabled = true
depeg_threshold = 5.0

[sleeves.tail_hedging]
enabled = true
vix_call_strike_offset = 10.0
put_strike_offset = 5.0

[risk]
max_position_size = 10000
max_notional = 1000000.0
max_daily_loss = -50000.0
kill_switch_consecutive_rejections = 10
kill_switch_heartbeat_timeout_ms = 5000

[monitoring]
audit_log_dir = "/var/log/quantum"
audit_retention_days = 2555
metrics_enabled = true

[feeds]
market_data_ws_url = "wss://stream.data.alpaca.markets/v2/iex"
market_data_api_key = "test_key"
symbols = ["SPY", "QQQ", "UVXY"]
heartbeat_interval_ms = 30000
reconnect_max_delay_secs = 60

[alerts]
slack_webhook_url = "https://hooks.slack.com/services/xxx"
smtp_host = "smtp.gmail.com"
smtp_port = 587
smtp_user = "alerts@example.com"
smtp_pass = "password"
alert_email_to = "team@example.com"
alert_cooldown_secs = 300
"#;

        let mut temp_file = NamedTempFile::new().unwrap();
        temp_file.write_all(toml_content.as_bytes()).unwrap();
        temp_file.flush().unwrap();

        let config = load_config(temp_file.path().to_str().unwrap()).unwrap();
        assert_eq!(config.engine.metrics_port, 9090);
        assert_eq!(config.sleeves.treasury_basis.hedge_ratio, 0.8);
        assert_eq!(config.feeds.symbols.len(), 3);
    }

    #[test]
    fn test_env_var_substitution() {
        std::env::set_var("TEST_API_KEY", "secret123");
        let content = "api_key = \"${TEST_API_KEY}\"";
        let result = substitute_env_vars(content);
        assert!(result.contains("secret123"));
        std::env::remove_var("TEST_API_KEY");
    }

    #[test]
    fn test_validation_invalid_hedge_ratio() {
        let mut config = create_test_config();
        config.sleeves.treasury_basis.hedge_ratio = 1.5;
        assert!(validate_config(&config).is_err());
    }

    #[test]
    fn test_validation_invalid_thresholds() {
        let mut config = create_test_config();
        config.sleeves.vol_regime.threshold_low = 40.0;
        config.sleeves.vol_regime.threshold_high = 30.0;
        assert!(validate_config(&config).is_err());
    }

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
                    enabled: true,
                    master_account_id: 1,
                    satellite_account_ids: vec![2, 3, 4],
                },
                rwa_crypto: RwaCryptoConfig {
                    enabled: true,
                    depeg_threshold: 5.0,
                },
                tail_hedging: TailHedgingConfig {
                    enabled: true,
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
                audit_log_dir: "/var/log/quantum".to_string(),
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
}
