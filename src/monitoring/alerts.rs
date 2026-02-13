//! Alert Manager
//!
//! Slack/email alerts with cooldown-based deduplication.

use crate::engine::common::now_ns;
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Alert Types
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Severity {
    Info,
    Warning,
    Critical,
    Emergency,
}

#[derive(Clone, Debug)]
pub struct Alert {
    pub severity: Severity,
    pub title: String,
    pub message: String,
    pub timestamp_ns: u64,
}

impl Alert {
    pub fn new(severity: Severity, title: &str, message: &str) -> Self {
        Self {
            severity,
            title: title.to_string(),
            message: message.to_string(),
            timestamp_ns: now_ns(),
        }
    }
}

// ---------------------------------------------------------------------------
// Alert Manager
// ---------------------------------------------------------------------------

pub struct AlertManager {
    pub slack_webhook_url: String,
    pub email_to: String,
    pub cooldown_ns: u64,
    last_alert_times: HashMap<String, u64>,
    pub alerts_sent: u64,
    pub alerts_suppressed: u64,
}

impl AlertManager {
    pub fn new(slack_webhook_url: &str, email_to: &str, cooldown_secs: u64) -> Self {
        Self {
            slack_webhook_url: slack_webhook_url.to_string(),
            email_to: email_to.to_string(),
            cooldown_ns: cooldown_secs * 1_000_000_000,
            last_alert_times: HashMap::new(),
            alerts_sent: 0,
            alerts_suppressed: 0,
        }
    }

    /// Check if an alert should be sent (cooldown deduplication).
    pub fn should_send(&self, alert: &Alert) -> bool {
        let key = self.dedup_key(alert);
        match self.last_alert_times.get(&key) {
            Some(&last_time) => {
                let elapsed = alert.timestamp_ns.saturating_sub(last_time);
                elapsed >= self.cooldown_ns
            }
            None => true,
        }
    }

    /// Send an alert (checks cooldown first).
    /// Returns true if the alert was sent, false if suppressed.
    pub fn send_alert(&mut self, alert: &Alert) -> bool {
        if !self.should_send(alert) {
            self.alerts_suppressed += 1;
            return false;
        }

        let key = self.dedup_key(alert);
        self.last_alert_times.insert(key, alert.timestamp_ns);
        self.alerts_sent += 1;

        log::warn!(
            "[ALERT {:?}] {}: {}",
            alert.severity,
            alert.title,
            alert.message
        );

        true
    }

    /// Format alert for Slack webhook payload.
    pub fn format_slack_payload(&self, alert: &Alert) -> String {
        let emoji = match alert.severity {
            Severity::Info => ":information_source:",
            Severity::Warning => ":warning:",
            Severity::Critical => ":rotating_light:",
            Severity::Emergency => ":sos:",
        };

        serde_json::json!({
            "text": format!("{} *{}*\n{}", emoji, alert.title, alert.message),
            "attachments": [{
                "color": match alert.severity {
                    Severity::Info => "#36a64f",
                    Severity::Warning => "#daa038",
                    Severity::Critical => "#cc0000",
                    Severity::Emergency => "#ff0000",
                },
                "fields": [{
                    "title": "Severity",
                    "value": format!("{:?}", alert.severity),
                    "short": true
                }]
            }]
        })
        .to_string()
    }

    /// Reset alert history (e.g., daily reset).
    pub fn reset(&mut self) {
        self.last_alert_times.clear();
    }

    fn dedup_key(&self, alert: &Alert) -> String {
        format!("{:?}:{}", alert.severity, alert.title)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_alert_manager() -> AlertManager {
        AlertManager::new("", "", 300)
    }

    #[test]
    fn test_send_alert_first_time() {
        let mut mgr = make_alert_manager();
        let alert = Alert::new(Severity::Warning, "Test", "message");
        assert!(mgr.send_alert(&alert));
        assert_eq!(mgr.alerts_sent, 1);
    }

    #[test]
    fn test_cooldown_suppression() {
        let mut mgr = make_alert_manager();
        let alert1 = Alert::new(Severity::Warning, "Test", "message");
        assert!(mgr.send_alert(&alert1));

        // Same alert immediately should be suppressed
        let alert2 = Alert {
            severity: Severity::Warning,
            title: "Test".to_string(),
            message: "message again".to_string(),
            timestamp_ns: alert1.timestamp_ns + 1_000, // 1µs later
        };
        assert!(!mgr.send_alert(&alert2));
        assert_eq!(mgr.alerts_suppressed, 1);
    }

    #[test]
    fn test_cooldown_expired() {
        let mut mgr = make_alert_manager();
        let alert1 = Alert {
            severity: Severity::Warning,
            title: "Test".to_string(),
            message: "message".to_string(),
            timestamp_ns: 1_000_000_000,
        };
        assert!(mgr.send_alert(&alert1));

        // Same alert after cooldown should send
        let alert2 = Alert {
            severity: Severity::Warning,
            title: "Test".to_string(),
            message: "message".to_string(),
            timestamp_ns: 1_000_000_000 + 300 * 1_000_000_000 + 1, // >300s later
        };
        assert!(mgr.send_alert(&alert2));
        assert_eq!(mgr.alerts_sent, 2);
    }

    #[test]
    fn test_different_alerts_not_suppressed() {
        let mut mgr = make_alert_manager();
        let alert1 = Alert::new(Severity::Warning, "Alert A", "message");
        let alert2 = Alert::new(Severity::Warning, "Alert B", "message");
        assert!(mgr.send_alert(&alert1));
        assert!(mgr.send_alert(&alert2));
        assert_eq!(mgr.alerts_sent, 2);
    }

    #[test]
    fn test_different_severity_not_suppressed() {
        let mut mgr = make_alert_manager();
        let alert1 = Alert::new(Severity::Warning, "Test", "message");
        let alert2 = Alert::new(Severity::Critical, "Test", "message");
        assert!(mgr.send_alert(&alert1));
        assert!(mgr.send_alert(&alert2));
        assert_eq!(mgr.alerts_sent, 2);
    }

    #[test]
    fn test_format_slack_payload() {
        let mgr = make_alert_manager();
        let alert = Alert::new(
            Severity::Critical,
            "Kill Switch",
            "Triggered due to P&L loss",
        );
        let payload = mgr.format_slack_payload(&alert);
        assert!(payload.contains("Kill Switch"));
        assert!(payload.contains("rotating_light"));
        assert!(payload.contains("#cc0000"));
    }

    #[test]
    fn test_format_slack_emergency() {
        let mgr = make_alert_manager();
        let alert = Alert::new(Severity::Emergency, "System Down", "Engine stopped");
        let payload = mgr.format_slack_payload(&alert);
        assert!(payload.contains("sos"));
        assert!(payload.contains("#ff0000"));
    }

    #[test]
    fn test_reset() {
        let mut mgr = make_alert_manager();
        let alert = Alert::new(Severity::Warning, "Test", "message");
        mgr.send_alert(&alert);
        mgr.reset();

        // After reset, same alert should send again
        let alert2 = Alert::new(Severity::Warning, "Test", "message");
        assert!(mgr.send_alert(&alert2));
    }

    #[test]
    fn test_should_send_no_history() {
        let mgr = make_alert_manager();
        let alert = Alert::new(Severity::Info, "New Alert", "test");
        assert!(mgr.should_send(&alert));
    }

    #[test]
    fn test_severity_values() {
        assert_ne!(Severity::Info, Severity::Warning);
        assert_ne!(Severity::Warning, Severity::Critical);
        assert_ne!(Severity::Critical, Severity::Emergency);
    }
}
