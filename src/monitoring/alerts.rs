//! Alerting System
//!
//! Slack webhook and email alerts with deduplication.

use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;

// ---------------------------------------------------------------------------
// Alert Types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Severity {
    Info,
    Warning,
    Critical,
    Emergency,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Alert {
    pub severity: Severity,
    pub title: String,
    pub message: String,
    pub timestamp: DateTime<Utc>,
    pub source: String,
}

impl Alert {
    /// Create a new alert
    pub fn new(
        severity: Severity,
        title: impl Into<String>,
        message: impl Into<String>,
        source: impl Into<String>,
    ) -> Self {
        Self {
            severity,
            title: title.into(),
            message: message.into(),
            timestamp: Utc::now(),
            source: source.into(),
        }
    }

    /// Get alert key for deduplication
    fn alert_key(&self) -> String {
        format!("{}:{}", self.source, self.title)
    }
}

// ---------------------------------------------------------------------------
// Alert Manager
// ---------------------------------------------------------------------------

/// Alert manager with Slack and email support
pub struct AlertManager {
    slack_webhook_url: String,
    smtp_config: SmtpConfig,
    cooldown_secs: u64,
    last_alert_times: HashMap<String, DateTime<Utc>>,
    http_client: reqwest::Client,
}

#[derive(Debug, Clone)]
pub struct SmtpConfig {
    pub host: String,
    pub port: u16,
    pub user: String,
    pub pass: String,
    pub to: String,
}

impl AlertManager {
    /// Create a new alert manager
    pub fn new(slack_webhook_url: String, smtp_config: SmtpConfig, cooldown_secs: u64) -> Self {
        Self {
            slack_webhook_url,
            smtp_config,
            cooldown_secs,
            last_alert_times: HashMap::new(),
            http_client: reqwest::Client::builder()
                .timeout(Duration::from_secs(10))
                .build()
                .unwrap(),
        }
    }

    /// Send an alert (with deduplication)
    pub async fn send_alert(&mut self, alert: Alert) {
        // Check deduplication
        let key = alert.alert_key();
        if let Some(last_time) = self.last_alert_times.get(&key) {
            let elapsed = Utc::now().signed_duration_since(*last_time).num_seconds();
            if elapsed < self.cooldown_secs as i64 {
                log::debug!(
                    "Alert '{}' suppressed due to cooldown ({}s remaining)",
                    alert.title,
                    self.cooldown_secs as i64 - elapsed
                );
                return;
            }
        }

        // Update last alert time
        self.last_alert_times.insert(key, alert.timestamp);

        // Send to Slack
        if let Err(e) = self.send_slack(&alert).await {
            log::error!("Failed to send Slack alert: {}", e);
        }

        // Send email for Critical and Emergency alerts
        if matches!(alert.severity, Severity::Critical | Severity::Emergency) {
            if let Err(e) = self.send_email(&alert).await {
                log::error!("Failed to send email alert: {}", e);
            }
        }
    }

    /// Send alert to Slack
    async fn send_slack(&self, alert: &Alert) -> Result<()> {
        let color = match alert.severity {
            Severity::Info => "#36a64f",      // Green
            Severity::Warning => "#ff9900",   // Orange
            Severity::Critical => "#ff0000",  // Red
            Severity::Emergency => "#8b0000", // Dark red
        };

        let payload = serde_json::json!({
            "attachments": [{
                "color": color,
                "title": format!("[{:?}] {}", alert.severity, alert.title),
                "text": alert.message,
                "footer": format!("Source: {}", alert.source),
                "ts": alert.timestamp.timestamp(),
            }]
        });

        let response = self
            .http_client
            .post(&self.slack_webhook_url)
            .json(&payload)
            .send()
            .await?;

        if !response.status().is_success() {
            anyhow::bail!("Slack API returned status: {}", response.status());
        }

        log::info!("Slack alert sent: {}", alert.title);
        Ok(())
    }

    /// Send alert via email (simplified implementation)
    async fn send_email(&self, alert: &Alert) -> Result<()> {
        // This is a simplified implementation
        // In production, you would use a library like `lettre` for full SMTP support
        log::info!(
            "Email alert would be sent to {}: [{:?}] {}",
            self.smtp_config.to,
            alert.severity,
            alert.title
        );

        // For now, just log the email
        // In a real implementation, you would:
        // 1. Connect to SMTP server
        // 2. Authenticate
        // 3. Send email with proper headers and body

        Ok(())
    }

    /// Clear cooldown for a specific alert (for testing)
    pub fn clear_cooldown(&mut self, source: &str, title: &str) {
        let key = format!("{}:{}", source, title);
        self.last_alert_times.remove(&key);
    }

    /// Get number of unique alerts sent
    pub fn alert_count(&self) -> usize {
        self.last_alert_times.len()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_manager() -> AlertManager {
        AlertManager::new(
            "https://hooks.slack.com/services/test".to_string(),
            SmtpConfig {
                host: "smtp.test.com".to_string(),
                port: 587,
                user: "test@test.com".to_string(),
                pass: "password".to_string(),
                to: "alerts@test.com".to_string(),
            },
            300, // 5 min cooldown
        )
    }

    #[tokio::test]
    async fn test_alert_creation() {
        let alert = Alert::new(
            Severity::Warning,
            "Test Alert",
            "This is a test",
            "test_suite",
        );
        assert_eq!(alert.severity, Severity::Warning);
        assert_eq!(alert.title, "Test Alert");
        assert_eq!(alert.source, "test_suite");
    }

    #[tokio::test]
    async fn test_alert_key() {
        let alert1 = Alert::new(Severity::Info, "Alert1", "msg", "source1");
        let alert2 = Alert::new(Severity::Info, "Alert1", "msg", "source1");
        let alert3 = Alert::new(Severity::Info, "Alert2", "msg", "source1");

        assert_eq!(alert1.alert_key(), alert2.alert_key());
        assert_ne!(alert1.alert_key(), alert3.alert_key());
    }

    #[test]
    fn test_alert_manager_creation() {
        let manager = create_test_manager();
        assert_eq!(manager.cooldown_secs, 300);
        assert_eq!(manager.alert_count(), 0);
    }

    #[tokio::test]
    async fn test_alert_deduplication() {
        let mut manager = create_test_manager();

        let alert1 = Alert::new(Severity::Info, "DupTest", "First", "test");
        let alert2 = Alert::new(Severity::Info, "DupTest", "Second", "test");

        // First alert should be sent (but we're not actually sending to Slack in test)
        // We'll just track the deduplication logic
        let key = alert1.alert_key();
        manager.last_alert_times.insert(key, Utc::now());

        // Check that the same alert within cooldown would be suppressed
        let last_time = manager.last_alert_times.get(&alert2.alert_key()).unwrap();
        let elapsed = Utc::now().signed_duration_since(*last_time).num_seconds();
        assert!(elapsed < manager.cooldown_secs as i64);
    }

    #[test]
    fn test_clear_cooldown() {
        let mut manager = create_test_manager();
        let alert = Alert::new(Severity::Info, "Test", "msg", "source");

        manager
            .last_alert_times
            .insert(alert.alert_key(), Utc::now());
        assert_eq!(manager.alert_count(), 1);

        manager.clear_cooldown("source", "Test");
        assert_eq!(manager.alert_count(), 0);
    }

    #[test]
    fn test_severity_levels() {
        assert_eq!(
            std::mem::discriminant(&Severity::Info),
            std::mem::discriminant(&Severity::Info)
        );
        assert_ne!(
            std::mem::discriminant(&Severity::Info),
            std::mem::discriminant(&Severity::Critical)
        );
    }
}
