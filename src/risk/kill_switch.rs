//! Kill Switch - Emergency Shutdown
//!
//! Monitors multiple trigger conditions and initiates graceful shutdown.

use crate::engine::now_ns;
use anyhow::Result;
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use thiserror::Error;

// ---------------------------------------------------------------------------
// Kill Switch Status
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub enum KillSwitchStatus {
    /// Kill switch is armed and monitoring
    Armed,
    /// Kill switch has been triggered
    Triggered(TriggerReason),
    /// Kill switch is disarmed (for testing or recovery)
    Disarmed,
}

#[derive(Debug, Clone, PartialEq)]
pub enum TriggerReason {
    DailyLossExceeded,
    PositionBreach,
    ManualTrigger,
    ConsecutiveRejections,
    HeartbeatTimeout,
}

// ---------------------------------------------------------------------------
// Kill Switch State (for persistence)
// ---------------------------------------------------------------------------

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct KillSwitchState {
    triggered: bool,
    trigger_reason: Option<String>,
    trigger_timestamp_ns: u64,
    daily_pnl: f64,
    consecutive_rejections: u32,
}

// ---------------------------------------------------------------------------
// Kill Switch
// ---------------------------------------------------------------------------

/// Emergency kill switch with multiple trigger conditions
pub struct KillSwitch {
    // Atomic flags for thread-safe access
    is_armed: Arc<AtomicBool>,
    is_triggered: Arc<AtomicBool>,
    manual_trigger: Arc<AtomicBool>,

    // Monitoring state
    daily_pnl: f64,
    max_daily_loss: f64,
    consecutive_rejections: u32,
    max_consecutive_rejections: u32,
    last_heartbeat_ns: Arc<AtomicU64>,
    heartbeat_timeout_ms: u64,

    // Position tracking
    max_position_size: i64,

    // Trigger state
    trigger_reason: Option<TriggerReason>,

    // State file for persistence
    state_file: Option<String>,
}

impl KillSwitch {
    /// Create a new kill switch
    pub fn new(
        max_daily_loss: f64,
        max_consecutive_rejections: u32,
        heartbeat_timeout_ms: u64,
        max_position_size: i64,
    ) -> Self {
        Self {
            is_armed: Arc::new(AtomicBool::new(true)),
            is_triggered: Arc::new(AtomicBool::new(false)),
            manual_trigger: Arc::new(AtomicBool::new(false)),
            daily_pnl: 0.0,
            max_daily_loss,
            consecutive_rejections: 0,
            max_consecutive_rejections,
            last_heartbeat_ns: Arc::new(AtomicU64::new(now_ns())),
            heartbeat_timeout_ms,
            max_position_size,
            trigger_reason: None,
            state_file: None,
        }
    }

    /// Set the state file path for persistence
    pub fn with_state_file(mut self, path: String) -> Self {
        self.state_file = Some(path);
        self
    }

    /// Arm the kill switch
    pub fn arm(&mut self) {
        self.is_armed.store(true, Ordering::SeqCst);
        log::info!("Kill switch armed");
    }

    /// Disarm the kill switch (for testing or recovery)
    pub fn disarm(&mut self) {
        self.is_armed.store(false, Ordering::SeqCst);
        log::warn!("Kill switch disarmed");
    }

    /// Trigger the kill switch manually
    pub fn trigger_manual(&mut self) {
        self.manual_trigger.store(true, Ordering::SeqCst);
        log::error!("Kill switch triggered manually");
    }

    /// Check kill switch status and trigger if conditions are met
    pub fn check(&mut self) -> KillSwitchStatus {
        if !self.is_armed.load(Ordering::SeqCst) {
            return KillSwitchStatus::Disarmed;
        }

        if self.is_triggered.load(Ordering::SeqCst) {
            return KillSwitchStatus::Triggered(
                self.trigger_reason.clone().unwrap_or(TriggerReason::ManualTrigger),
            );
        }

        // Check manual trigger
        if self.manual_trigger.load(Ordering::SeqCst) {
            return self.trigger(TriggerReason::ManualTrigger);
        }

        // Check daily P&L loss
        if self.daily_pnl < self.max_daily_loss {
            log::error!(
                "Daily P&L {} below threshold {}",
                self.daily_pnl,
                self.max_daily_loss
            );
            return self.trigger(TriggerReason::DailyLossExceeded);
        }

        // Check consecutive rejections
        if self.consecutive_rejections >= self.max_consecutive_rejections {
            log::error!(
                "Consecutive rejections {} exceeds threshold {}",
                self.consecutive_rejections,
                self.max_consecutive_rejections
            );
            return self.trigger(TriggerReason::ConsecutiveRejections);
        }

        // Check heartbeat timeout
        let last_hb = self.last_heartbeat_ns.load(Ordering::SeqCst);
        let elapsed_ms = (now_ns() - last_hb) / 1_000_000;
        if elapsed_ms > self.heartbeat_timeout_ms {
            log::error!(
                "Heartbeat timeout: {}ms elapsed, threshold {}ms",
                elapsed_ms,
                self.heartbeat_timeout_ms
            );
            return self.trigger(TriggerReason::HeartbeatTimeout);
        }

        KillSwitchStatus::Armed
    }

    /// Trigger the kill switch with a specific reason
    fn trigger(&mut self, reason: TriggerReason) -> KillSwitchStatus {
        log::error!("KILL SWITCH TRIGGERED: {:?}", reason);
        self.is_triggered.store(true, Ordering::SeqCst);
        self.trigger_reason = Some(reason.clone());

        // Persist state
        if let Err(e) = self.save_state() {
            log::error!("Failed to save kill switch state: {}", e);
        }

        KillSwitchStatus::Triggered(reason)
    }

    /// Update daily P&L
    pub fn update_pnl(&mut self, pnl: f64) {
        self.daily_pnl = pnl;
    }

    /// Record a rejection
    pub fn record_rejection(&mut self) {
        self.consecutive_rejections += 1;
        log::debug!(
            "Rejection recorded: {} consecutive",
            self.consecutive_rejections
        );
    }

    /// Record a successful trade (resets rejection counter)
    pub fn record_success(&mut self) {
        self.consecutive_rejections = 0;
    }

    /// Update heartbeat
    pub fn heartbeat(&mut self) {
        self.last_heartbeat_ns.store(now_ns(), Ordering::SeqCst);
    }

    /// Check if a position size would breach limits
    pub fn check_position(&self, position_size: i64) -> Result<(), String> {
        if position_size.abs() > self.max_position_size {
            Err(format!(
                "Position size {} exceeds max {}",
                position_size.abs(),
                self.max_position_size
            ))
        } else {
            Ok(())
        }
    }

    /// Save kill switch state to disk
    fn save_state(&self) -> Result<()> {
        if let Some(path) = &self.state_file {
            let state = KillSwitchState {
                triggered: self.is_triggered.load(Ordering::SeqCst),
                trigger_reason: self.trigger_reason.as_ref().map(|r| format!("{:?}", r)),
                trigger_timestamp_ns: now_ns(),
                daily_pnl: self.daily_pnl,
                consecutive_rejections: self.consecutive_rejections,
            };

            let json = serde_json::to_string_pretty(&state)?;
            std::fs::write(path, json)?;
            log::info!("Kill switch state saved to {}", path);
        }
        Ok(())
    }

    /// Load kill switch state from disk
    pub fn load_state(&mut self) -> Result<()> {
        if let Some(path) = &self.state_file {
            if Path::new(path).exists() {
                let json = std::fs::read_to_string(path)?;
                let state: KillSwitchState = serde_json::from_str(&json)?;

                if state.triggered {
                    log::warn!("Loaded kill switch state: previously triggered");
                    self.is_triggered.store(true, Ordering::SeqCst);
                    // Don't automatically trigger again, but log the previous state
                }

                self.daily_pnl = state.daily_pnl;
                self.consecutive_rejections = state.consecutive_rejections;

                log::info!("Kill switch state loaded from {}", path);
            }
        }
        Ok(())
    }

    /// Reset the kill switch (for new trading day or recovery)
    pub fn reset(&mut self) {
        self.is_triggered.store(false, Ordering::SeqCst);
        self.manual_trigger.store(false, Ordering::SeqCst);
        self.daily_pnl = 0.0;
        self.consecutive_rejections = 0;
        self.trigger_reason = None;
        self.last_heartbeat_ns.store(now_ns(), Ordering::SeqCst);
        log::info!("Kill switch reset");
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread::sleep;
    use std::time::Duration;

    #[test]
    fn test_kill_switch_armed() {
        let mut ks = KillSwitch::new(-50000.0, 10, 5000, 10000);
        assert_eq!(ks.check(), KillSwitchStatus::Armed);
    }

    #[test]
    fn test_kill_switch_disarmed() {
        let mut ks = KillSwitch::new(-50000.0, 10, 5000, 10000);
        ks.disarm();
        assert_eq!(ks.check(), KillSwitchStatus::Disarmed);
    }

    #[test]
    fn test_manual_trigger() {
        let mut ks = KillSwitch::new(-50000.0, 10, 5000, 10000);
        ks.trigger_manual();
        let status = ks.check();
        assert!(matches!(
            status,
            KillSwitchStatus::Triggered(TriggerReason::ManualTrigger)
        ));
    }

    #[test]
    fn test_daily_loss_trigger() {
        let mut ks = KillSwitch::new(-50000.0, 10, 5000, 10000);
        ks.update_pnl(-60000.0); // Exceeds threshold
        let status = ks.check();
        assert!(matches!(
            status,
            KillSwitchStatus::Triggered(TriggerReason::DailyLossExceeded)
        ));
    }

    #[test]
    fn test_consecutive_rejections_trigger() {
        let mut ks = KillSwitch::new(-50000.0, 5, 5000, 10000);
        for _ in 0..5 {
            ks.record_rejection();
        }
        let status = ks.check();
        assert!(matches!(
            status,
            KillSwitchStatus::Triggered(TriggerReason::ConsecutiveRejections)
        ));
    }

    #[test]
    fn test_rejection_reset_on_success() {
        let mut ks = KillSwitch::new(-50000.0, 10, 5000, 10000);
        ks.record_rejection();
        ks.record_rejection();
        assert_eq!(ks.consecutive_rejections, 2);

        ks.record_success();
        assert_eq!(ks.consecutive_rejections, 0);
    }

    #[test]
    fn test_position_check() {
        let ks = KillSwitch::new(-50000.0, 10, 5000, 1000);
        assert!(ks.check_position(500).is_ok());
        assert!(ks.check_position(1001).is_err());
        assert!(ks.check_position(-1001).is_err());
    }

    #[test]
    fn test_heartbeat_timeout() {
        let mut ks = KillSwitch::new(-50000.0, 10, 10, 10000); // 10ms timeout
        sleep(Duration::from_millis(20)); // Wait longer than timeout
        let status = ks.check();
        assert!(matches!(
            status,
            KillSwitchStatus::Triggered(TriggerReason::HeartbeatTimeout)
        ));
    }

    #[test]
    fn test_reset() {
        let mut ks = KillSwitch::new(-50000.0, 10, 5000, 10000);
        ks.update_pnl(-60000.0);
        ks.check(); // Triggers

        ks.reset();
        assert_eq!(ks.daily_pnl, 0.0);
        assert!(!ks.is_triggered.load(Ordering::SeqCst));
    }
}
