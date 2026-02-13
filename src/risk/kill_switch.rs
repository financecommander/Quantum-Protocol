//! Kill Switch
//!
//! Multiple trigger types: P&L loss, position breach, consecutive rejections,
//! heartbeat timeout. State persistence for recovery.

use crate::engine::common::now_ns;
use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Kill Switch
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq)]
pub enum KillSwitchStatus {
    Armed,
    Triggered(KillSwitchReason),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum KillSwitchReason {
    PnlLoss { loss: f64, limit: f64 },
    PositionBreach { position: f64, limit: f64 },
    ConsecutiveRejections { count: u32, limit: u32 },
    HeartbeatTimeout { elapsed_ms: u64, limit_ms: u64 },
    Manual { reason: String },
}

pub struct KillSwitch {
    pub status: KillSwitchStatus,
    pub max_daily_loss: f64,
    pub max_portfolio_position: f64,
    pub max_consecutive_rejections: u32,
    pub heartbeat_timeout_ms: u64,
    pub current_pnl: f64,
    pub current_position: f64,
    pub consecutive_rejections: u32,
    pub last_heartbeat_ns: u64,
    pub triggered_at_ns: u64,
}

impl KillSwitch {
    pub fn new(
        max_daily_loss: f64,
        max_portfolio_position: f64,
        max_consecutive_rejections: u32,
        heartbeat_timeout_ms: u64,
    ) -> Self {
        Self {
            status: KillSwitchStatus::Armed,
            max_daily_loss,
            max_portfolio_position,
            max_consecutive_rejections,
            heartbeat_timeout_ms,
            current_pnl: 0.0,
            current_position: 0.0,
            consecutive_rejections: 0,
            last_heartbeat_ns: now_ns(),
            triggered_at_ns: 0,
        }
    }

    /// Check all kill switch conditions. Returns current status.
    pub fn check(&mut self) -> &KillSwitchStatus {
        if self.status != KillSwitchStatus::Armed {
            return &self.status;
        }

        // Check P&L loss
        if self.current_pnl < -self.max_daily_loss {
            self.trigger(KillSwitchReason::PnlLoss {
                loss: self.current_pnl,
                limit: self.max_daily_loss,
            });
            return &self.status;
        }

        // Check position breach
        if self.current_position > self.max_portfolio_position {
            self.trigger(KillSwitchReason::PositionBreach {
                position: self.current_position,
                limit: self.max_portfolio_position,
            });
            return &self.status;
        }

        // Check consecutive rejections
        if self.consecutive_rejections >= self.max_consecutive_rejections {
            self.trigger(KillSwitchReason::ConsecutiveRejections {
                count: self.consecutive_rejections,
                limit: self.max_consecutive_rejections,
            });
            return &self.status;
        }

        // Check heartbeat timeout
        if self.last_heartbeat_ns > 0 {
            let elapsed_ms = (now_ns() - self.last_heartbeat_ns) / 1_000_000;
            if elapsed_ms > self.heartbeat_timeout_ms {
                self.trigger(KillSwitchReason::HeartbeatTimeout {
                    elapsed_ms,
                    limit_ms: self.heartbeat_timeout_ms,
                });
                return &self.status;
            }
        }

        &self.status
    }

    /// Manually trigger the kill switch.
    pub fn trigger_manual(&mut self, reason: &str) {
        self.trigger(KillSwitchReason::Manual {
            reason: reason.to_string(),
        });
    }

    /// Update P&L.
    pub fn update_pnl(&mut self, pnl: f64) {
        self.current_pnl = pnl;
    }

    /// Update aggregate position.
    pub fn update_position(&mut self, position: f64) {
        self.current_position = position;
    }

    /// Record a rejection.
    pub fn record_rejection(&mut self) {
        self.consecutive_rejections += 1;
    }

    /// Record a fill (resets rejection counter).
    pub fn record_fill(&mut self) {
        self.consecutive_rejections = 0;
    }

    /// Record a heartbeat.
    pub fn record_heartbeat(&mut self) {
        self.last_heartbeat_ns = now_ns();
    }

    /// Reset (re-arm) the kill switch for a new trading day.
    pub fn reset(&mut self) {
        self.status = KillSwitchStatus::Armed;
        self.current_pnl = 0.0;
        self.current_position = 0.0;
        self.consecutive_rejections = 0;
        self.last_heartbeat_ns = now_ns();
        self.triggered_at_ns = 0;
    }

    /// Check if the kill switch is currently triggered.
    pub fn is_triggered(&self) -> bool {
        matches!(self.status, KillSwitchStatus::Triggered(_))
    }

    /// Serialize state for persistence/recovery.
    pub fn persist_state(&self) -> Option<String> {
        if let KillSwitchStatus::Triggered(ref reason) = self.status {
            serde_json::to_string(reason).ok()
        } else {
            None
        }
    }

    /// Restore from persisted state.
    pub fn restore_state(json: &str) -> Option<KillSwitchReason> {
        serde_json::from_str(json).ok()
    }

    fn trigger(&mut self, reason: KillSwitchReason) {
        self.status = KillSwitchStatus::Triggered(reason);
        self.triggered_at_ns = now_ns();
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_kill_switch() -> KillSwitch {
        KillSwitch::new(50_000.0, 5_000_000.0, 10, 5000)
    }

    #[test]
    fn test_armed_by_default() {
        let mut ks = make_kill_switch();
        assert_eq!(*ks.check(), KillSwitchStatus::Armed);
        assert!(!ks.is_triggered());
    }

    #[test]
    fn test_pnl_loss_trigger() {
        let mut ks = make_kill_switch();
        ks.update_pnl(-60_000.0);
        ks.check();
        assert!(ks.is_triggered());
        match &ks.status {
            KillSwitchStatus::Triggered(KillSwitchReason::PnlLoss { loss, limit }) => {
                assert_eq!(*loss, -60_000.0);
                assert_eq!(*limit, 50_000.0);
            }
            _ => panic!("Expected PnlLoss"),
        }
    }

    #[test]
    fn test_position_breach_trigger() {
        let mut ks = make_kill_switch();
        ks.update_position(6_000_000.0);
        ks.check();
        assert!(ks.is_triggered());
        match &ks.status {
            KillSwitchStatus::Triggered(KillSwitchReason::PositionBreach { .. }) => {}
            _ => panic!("Expected PositionBreach"),
        }
    }

    #[test]
    fn test_consecutive_rejections_trigger() {
        let mut ks = make_kill_switch();
        for _ in 0..10 {
            ks.record_rejection();
        }
        ks.check();
        assert!(ks.is_triggered());
        match &ks.status {
            KillSwitchStatus::Triggered(KillSwitchReason::ConsecutiveRejections {
                count,
                limit,
            }) => {
                assert_eq!(*count, 10);
                assert_eq!(*limit, 10);
            }
            _ => panic!("Expected ConsecutiveRejections"),
        }
    }

    #[test]
    fn test_fill_resets_rejections() {
        let mut ks = make_kill_switch();
        for _ in 0..5 {
            ks.record_rejection();
        }
        assert_eq!(ks.consecutive_rejections, 5);
        ks.record_fill();
        assert_eq!(ks.consecutive_rejections, 0);
    }

    #[test]
    fn test_manual_trigger() {
        let mut ks = make_kill_switch();
        ks.trigger_manual("operator intervention");
        assert!(ks.is_triggered());
        match &ks.status {
            KillSwitchStatus::Triggered(KillSwitchReason::Manual { reason }) => {
                assert_eq!(reason, "operator intervention");
            }
            _ => panic!("Expected Manual"),
        }
    }

    #[test]
    fn test_reset() {
        let mut ks = make_kill_switch();
        ks.trigger_manual("test");
        assert!(ks.is_triggered());
        ks.reset();
        assert!(!ks.is_triggered());
        assert_eq!(ks.current_pnl, 0.0);
    }

    #[test]
    fn test_persist_and_restore() {
        let mut ks = make_kill_switch();
        ks.trigger_manual("test persist");

        let json = ks.persist_state().unwrap();
        let restored = KillSwitch::restore_state(&json).unwrap();
        match restored {
            KillSwitchReason::Manual { reason } => assert_eq!(reason, "test persist"),
            _ => panic!("Expected Manual"),
        }
    }

    #[test]
    fn test_persist_armed_returns_none() {
        let ks = make_kill_switch();
        assert!(ks.persist_state().is_none());
    }

    #[test]
    fn test_restore_invalid_json() {
        assert!(KillSwitch::restore_state("invalid").is_none());
    }

    #[test]
    fn test_stays_triggered() {
        let mut ks = make_kill_switch();
        ks.trigger_manual("test");
        ks.update_pnl(100.0); // Even with positive PnL
        ks.check();
        assert!(ks.is_triggered());
    }

    #[test]
    fn test_pnl_within_limit() {
        let mut ks = make_kill_switch();
        ks.update_pnl(-40_000.0);
        ks.check();
        assert!(!ks.is_triggered());
    }

    #[test]
    fn test_position_within_limit() {
        let mut ks = make_kill_switch();
        ks.update_position(4_000_000.0);
        ks.check();
        assert!(!ks.is_triggered());
    }

    #[test]
    fn test_rejections_below_limit() {
        let mut ks = make_kill_switch();
        for _ in 0..9 {
            ks.record_rejection();
        }
        ks.check();
        assert!(!ks.is_triggered());
    }

    #[test]
    fn test_record_heartbeat() {
        let mut ks = make_kill_switch();
        let before = ks.last_heartbeat_ns;
        std::thread::sleep(std::time::Duration::from_millis(1));
        ks.record_heartbeat();
        assert!(ks.last_heartbeat_ns >= before);
    }
}
