//! Configuration System for Quantum Protocol HFT Engine
//!
//! TOML-based configuration with:
//! - Hot reload via `notify` crate
//! - Environment variable substitution (`${ENV_VAR}` patterns)
//! - Schema validation at load time

use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use regex::Regex;
use serde::Deserialize;
use std::path::Path;

// ---------------------------------------------------------------------------
// Configuration Structs
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Deserialize)]
pub struct QuantumConfig {
    pub engine: EngineConfig,
    #[serde(default)]
    pub sleeves: SleevesConfig,
    #[serde(default)]
    pub risk: RiskConfig,
    #[serde(default)]
    pub monitoring: MonitoringConfig,
    #[serde(default)]
    pub feeds: FeedsConfig,
    #[serde(default)]
    pub alerts: AlertsConfig,
}

#[derive(Clone, Debug, Deserialize)]
pub struct EngineConfig {
    #[serde(default = "default_udp_addr")]
    pub udp_addr: String,
    #[serde(default = "default_max_position")]
    pub max_position: f64,
    #[serde(default = "default_hedge_ratio")]
    pub hedge_ratio: f64,
    #[serde(default = "default_true")]
    pub circuit_breaker_enabled: bool,
    #[serde(default = "default_heartbeat_max_lag_us")]
    pub heartbeat_max_lag_us: u64,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            udp_addr: default_udp_addr(),
            max_position: default_max_position(),
            hedge_ratio: default_hedge_ratio(),
            circuit_breaker_enabled: true,
            heartbeat_max_lag_us: default_heartbeat_max_lag_us(),
        }
    }
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct SleevesConfig {
    #[serde(default)]
    pub treasury_basis: TreasuryBasisConfig,
    #[serde(default)]
    pub vol_regime: VolRegimeConfig,
    #[serde(default)]
    pub prop_scaling: PropScalingConfig,
    #[serde(default)]
    pub rwa_crypto: RwaCryptoConfig,
    #[serde(default)]
    pub tail_hedging: TailHedgingConfig,
}

#[derive(Clone, Debug, Deserialize)]
pub struct TreasuryBasisConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_weight")]
    pub weight: f64,
}

impl Default for TreasuryBasisConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            weight: default_weight(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct VolRegimeConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_vol_threshold_low")]
    pub threshold_low: f64,
    #[serde(default = "default_vol_threshold_high")]
    pub threshold_high: f64,
}

impl Default for VolRegimeConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            threshold_low: default_vol_threshold_low(),
            threshold_high: default_vol_threshold_high(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct PropScalingConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_max_accounts")]
    pub max_accounts: usize,
    #[serde(default = "default_min_equity")]
    pub min_equity: f64,
}

impl Default for PropScalingConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            max_accounts: default_max_accounts(),
            min_equity: default_min_equity(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct RwaCryptoConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_min_spread_bps")]
    pub min_spread_bps: f64,
}

impl Default for RwaCryptoConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            min_spread_bps: default_min_spread_bps(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct TailHedgingConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_vix_critical")]
    pub vix_critical_threshold: f64,
}

impl Default for TailHedgingConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            vix_critical_threshold: default_vix_critical(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct RiskConfig {
    #[serde(default = "default_max_position_per_symbol")]
    pub max_position_per_symbol: f64,
    #[serde(default = "default_max_portfolio_position")]
    pub max_portfolio_position: f64,
    #[serde(default = "default_max_daily_loss")]
    pub max_daily_loss: f64,
    #[serde(default = "default_max_consecutive_rejections")]
    pub max_consecutive_rejections: u32,
    #[serde(default = "default_heartbeat_timeout_ms")]
    pub heartbeat_timeout_ms: u64,
}

impl Default for RiskConfig {
    fn default() -> Self {
        Self {
            max_position_per_symbol: default_max_position_per_symbol(),
            max_portfolio_position: default_max_portfolio_position(),
            max_daily_loss: default_max_daily_loss(),
            max_consecutive_rejections: default_max_consecutive_rejections(),
            heartbeat_timeout_ms: default_heartbeat_timeout_ms(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct MonitoringConfig {
    #[serde(default = "default_metrics_port")]
    pub metrics_port: u16,
    #[serde(default = "default_audit_dir")]
    pub audit_log_dir: String,
    #[serde(default = "default_audit_retention_days")]
    pub audit_retention_days: u32,
}

impl Default for MonitoringConfig {
    fn default() -> Self {
        Self {
            metrics_port: default_metrics_port(),
            audit_log_dir: default_audit_dir(),
            audit_retention_days: default_audit_retention_days(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct FeedsConfig {
    #[serde(default = "default_ws_url")]
    pub ws_url: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default)]
    pub symbols: Vec<String>,
    #[serde(default = "default_heartbeat_interval_ms")]
    pub heartbeat_interval_ms: u64,
    #[serde(default = "default_reconnect_max_delay_ms")]
    pub reconnect_max_delay_ms: u64,
}

impl Default for FeedsConfig {
    fn default() -> Self {
        Self {
            ws_url: default_ws_url(),
            api_key: String::new(),
            symbols: Vec::new(),
            heartbeat_interval_ms: default_heartbeat_interval_ms(),
            reconnect_max_delay_ms: default_reconnect_max_delay_ms(),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct AlertsConfig {
    #[serde(default)]
    pub slack_webhook_url: String,
    #[serde(default)]
    pub email_to: String,
    #[serde(default = "default_alert_cooldown_secs")]
    pub cooldown_secs: u64,
}

impl Default for AlertsConfig {
    fn default() -> Self {
        Self {
            slack_webhook_url: String::new(),
            email_to: String::new(),
            cooldown_secs: default_alert_cooldown_secs(),
        }
    }
}

// ---------------------------------------------------------------------------
// Default value functions
// ---------------------------------------------------------------------------

fn default_udp_addr() -> String {
    "0.0.0.0:9999".to_string()
}
fn default_max_position() -> f64 {
    1_000_000.0
}
fn default_hedge_ratio() -> f64 {
    0.8
}
fn default_true() -> bool {
    true
}
fn default_heartbeat_max_lag_us() -> u64 {
    100
}
fn default_weight() -> f64 {
    0.125
}
fn default_vol_threshold_low() -> f64 {
    15.0
}
fn default_vol_threshold_high() -> f64 {
    30.0
}
fn default_max_accounts() -> usize {
    32
}
fn default_min_equity() -> f64 {
    2000.0
}
fn default_min_spread_bps() -> f64 {
    5.0
}
fn default_vix_critical() -> f64 {
    45.0
}
fn default_max_position_per_symbol() -> f64 {
    100_000.0
}
fn default_max_portfolio_position() -> f64 {
    5_000_000.0
}
fn default_max_daily_loss() -> f64 {
    50_000.0
}
fn default_max_consecutive_rejections() -> u32 {
    10
}
fn default_heartbeat_timeout_ms() -> u64 {
    5000
}
fn default_metrics_port() -> u16 {
    9090
}
fn default_audit_dir() -> String {
    "/var/log/quantum".to_string()
}
fn default_audit_retention_days() -> u32 {
    2555
}
fn default_ws_url() -> String {
    "wss://feed.example.com/v1/market".to_string()
}
fn default_heartbeat_interval_ms() -> u64 {
    1000
}
fn default_reconnect_max_delay_ms() -> u64 {
    60000
}
fn default_alert_cooldown_secs() -> u64 {
    300
}

// ---------------------------------------------------------------------------
// Environment variable substitution
// ---------------------------------------------------------------------------

/// Replace `${ENV_VAR}` patterns in a string with actual env var values.
pub fn substitute_env_vars(input: &str) -> String {
    let re = Regex::new(r"\$\{([^}]+)\}").unwrap();
    re.replace_all(input, |caps: &regex::Captures| {
        let var_name = &caps[1];
        std::env::var(var_name).unwrap_or_default()
    })
    .to_string()
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/// Validate configuration values are within acceptable ranges.
pub fn validate_config(config: &QuantumConfig) -> Result<(), String> {
    if config.engine.max_position <= 0.0 {
        return Err("engine.max_position must be positive".to_string());
    }
    if config.engine.hedge_ratio <= 0.0 || config.engine.hedge_ratio > 1.0 {
        return Err("engine.hedge_ratio must be in (0.0, 1.0]".to_string());
    }
    if config.sleeves.vol_regime.threshold_low >= config.sleeves.vol_regime.threshold_high {
        return Err("vol_regime.threshold_low must be < threshold_high".to_string());
    }
    if config.risk.max_daily_loss <= 0.0 {
        return Err("risk.max_daily_loss must be positive".to_string());
    }
    if config.risk.max_position_per_symbol <= 0.0 {
        return Err("risk.max_position_per_symbol must be positive".to_string());
    }
    if config.risk.max_portfolio_position <= 0.0 {
        return Err("risk.max_portfolio_position must be positive".to_string());
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

/// Load and validate configuration from a TOML file.
pub fn load_config(path: &str) -> Result<QuantumConfig, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("read config: {e}"))?;
    let substituted = substitute_env_vars(&raw);
    let config: QuantumConfig =
        toml::from_str(&substituted).map_err(|e| format!("parse config: {e}"))?;
    validate_config(&config)?;
    Ok(config)
}

/// Convert a `QuantumConfig` to the engine's `SharedConfig`.
pub fn to_shared_config(qc: &QuantumConfig) -> crate::engine::common::SharedConfig {
    crate::engine::common::SharedConfig {
        hedge_ratio: qc.engine.hedge_ratio,
        max_position: qc.engine.max_position,
        vol_regime_threshold_low: qc.sleeves.vol_regime.threshold_low,
        vol_regime_threshold_high: qc.sleeves.vol_regime.threshold_high,
        quantum_weights: [0.125; 8],
        circuit_breaker_enabled: qc.engine.circuit_breaker_enabled,
        heartbeat_max_lag_us: qc.engine.heartbeat_max_lag_us,
    }
}

// ---------------------------------------------------------------------------
// Hot Reload
// ---------------------------------------------------------------------------

/// Watch a config file for changes and send updated configs through a channel.
pub fn watch_config(
    path: &str,
    tx: tokio::sync::watch::Sender<QuantumConfig>,
) -> Result<RecommendedWatcher, String> {
    let path_buf = std::path::PathBuf::from(path);
    let path_clone = path_buf.clone();

    let mut watcher = notify::recommended_watcher(move |res: Result<notify::Event, _>| {
        if let Ok(event) = res {
            if event.kind.is_modify() {
                if let Ok(config) = load_config(path_clone.to_str().unwrap_or_default()) {
                    let _ = tx.send(config);
                }
            }
        }
    })
    .map_err(|e| format!("create watcher: {e}"))?;

    let parent = path_buf.parent().unwrap_or_else(|| Path::new("."));
    watcher
        .watch(parent, RecursiveMode::NonRecursive)
        .map_err(|e| format!("watch config: {e}"))?;

    Ok(watcher)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn minimal_toml() -> &'static str {
        r#"
[engine]
udp_addr = "0.0.0.0:9999"
max_position = 1000000.0
hedge_ratio = 0.8
circuit_breaker_enabled = true
heartbeat_max_lag_us = 100
"#
    }

    #[test]
    fn test_parse_minimal_config() {
        let config: QuantumConfig = toml::from_str(minimal_toml()).unwrap();
        assert_eq!(config.engine.udp_addr, "0.0.0.0:9999");
        assert_eq!(config.engine.max_position, 1_000_000.0);
    }

    #[test]
    fn test_defaults() {
        let config: QuantumConfig = toml::from_str(minimal_toml()).unwrap();
        assert_eq!(config.risk.max_daily_loss, 50_000.0);
        assert_eq!(config.monitoring.metrics_port, 9090);
    }

    #[test]
    fn test_validate_valid() {
        let config: QuantumConfig = toml::from_str(minimal_toml()).unwrap();
        assert!(validate_config(&config).is_ok());
    }

    #[test]
    fn test_validate_bad_hedge_ratio() {
        let raw = r#"
[engine]
max_position = 1000000.0
hedge_ratio = 0.0
"#;
        let config: QuantumConfig = toml::from_str(raw).unwrap();
        assert!(validate_config(&config).is_err());
    }

    #[test]
    fn test_validate_bad_max_position() {
        let raw = r#"
[engine]
max_position = -1.0
hedge_ratio = 0.8
"#;
        let config: QuantumConfig = toml::from_str(raw).unwrap();
        assert!(validate_config(&config).is_err());
    }

    #[test]
    fn test_validate_bad_vol_thresholds() {
        let raw = r#"
[engine]
max_position = 1000000.0
hedge_ratio = 0.8

[sleeves.vol_regime]
threshold_low = 30.0
threshold_high = 15.0
"#;
        let config: QuantumConfig = toml::from_str(raw).unwrap();
        assert!(validate_config(&config).is_err());
    }

    #[test]
    fn test_env_var_substitution() {
        std::env::set_var("QP_TEST_VAR", "hello_world");
        let result = substitute_env_vars("prefix_${QP_TEST_VAR}_suffix");
        assert_eq!(result, "prefix_hello_world_suffix");
        std::env::remove_var("QP_TEST_VAR");
    }

    #[test]
    fn test_env_var_substitution_missing() {
        std::env::remove_var("QP_MISSING_VAR");
        let result = substitute_env_vars("${QP_MISSING_VAR}");
        assert_eq!(result, "");
    }

    #[test]
    fn test_env_var_substitution_no_vars() {
        let result = substitute_env_vars("no variables here");
        assert_eq!(result, "no variables here");
    }

    #[test]
    fn test_to_shared_config() {
        let config: QuantumConfig = toml::from_str(minimal_toml()).unwrap();
        let shared = to_shared_config(&config);
        assert_eq!(shared.hedge_ratio, 0.8);
        assert_eq!(shared.max_position, 1_000_000.0);
        assert!(shared.circuit_breaker_enabled);
    }

    #[test]
    fn test_load_config_file() {
        let dir = std::env::temp_dir().join("qp_config_test");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("test.toml");
        std::fs::write(&path, minimal_toml()).unwrap();

        let config = load_config(path.to_str().unwrap()).unwrap();
        assert_eq!(config.engine.max_position, 1_000_000.0);

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_load_config_missing_file() {
        assert!(load_config("/nonexistent/path.toml").is_err());
    }

    #[test]
    fn test_load_config_invalid_toml() {
        let dir = std::env::temp_dir().join("qp_config_bad");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("bad.toml");
        std::fs::write(&path, "this is not valid toml {{{}}}").unwrap();

        assert!(load_config(path.to_str().unwrap()).is_err());

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_full_config_parse() {
        let raw = r#"
[engine]
udp_addr = "0.0.0.0:9999"
max_position = 1000000.0
hedge_ratio = 0.8
circuit_breaker_enabled = true
heartbeat_max_lag_us = 100

[sleeves.treasury_basis]
enabled = true
weight = 0.2

[sleeves.vol_regime]
enabled = true
threshold_low = 15.0
threshold_high = 30.0

[sleeves.prop_scaling]
enabled = true
max_accounts = 32
min_equity = 2000.0

[sleeves.rwa_crypto]
enabled = true
min_spread_bps = 5.0

[sleeves.tail_hedging]
enabled = true
vix_critical_threshold = 45.0

[risk]
max_position_per_symbol = 100000.0
max_portfolio_position = 5000000.0
max_daily_loss = 50000.0
max_consecutive_rejections = 10
heartbeat_timeout_ms = 5000

[monitoring]
metrics_port = 9090
audit_log_dir = "/var/log/quantum"
audit_retention_days = 2555

[feeds]
ws_url = "wss://feed.example.com/v1/market"
api_key = ""
symbols = ["BTC-USD", "ETH-USD"]
heartbeat_interval_ms = 1000
reconnect_max_delay_ms = 60000

[alerts]
slack_webhook_url = ""
email_to = ""
cooldown_secs = 300
"#;
        let config: QuantumConfig = toml::from_str(raw).unwrap();
        assert!(validate_config(&config).is_ok());
        assert_eq!(config.feeds.symbols.len(), 2);
        assert_eq!(config.sleeves.treasury_basis.weight, 0.2);
        assert_eq!(config.monitoring.audit_retention_days, 2555);
    }

    #[test]
    fn test_env_var_in_config() {
        std::env::set_var("QP_TEST_API_KEY", "secret123");
        let raw = r#"
[engine]
max_position = 1000000.0
hedge_ratio = 0.8

[feeds]
api_key = "${QP_TEST_API_KEY}"
"#;
        let substituted = substitute_env_vars(raw);
        let config: QuantumConfig = toml::from_str(&substituted).unwrap();
        assert_eq!(config.feeds.api_key, "secret123");
        std::env::remove_var("QP_TEST_API_KEY");
    }
}
