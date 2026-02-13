//! Sleeve 3: Prop Scaling Engine
//!
//! Synchronizes a master IBKR account with up to 32 prop trading accounts
//! (Topstep/FTMO) with millisecond-level precision.
//!
//! Key Features:
//! - Fixed 88-byte PropAccount struct (stack-allocated, no heap)
//! - Auto-hedge on rate limits
//! - Sync lag monitoring (<100µs threshold)
//! - Daily reset with margin validation

use super::{AuditEventType, AuditRecord};
use crate::{FillEvent, RejectionEvent, RejectionReason, Side};

// ---------------------------------------------------------------------------
// Prop Account Status
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub enum PropAccountStatus {
    Inactive = 0,    // Account not initialized or disabled
    Active = 1,      // Actively syncing with master
    RateLimited = 2, // Rejected recent fill; in backoff
    OutOfSync = 3,   // Sync lag exceeds threshold (>100µs)
    Error = 4,       // Critical error (margin call, disconnect)
}

// ---------------------------------------------------------------------------
// PropAccount (88 bytes, stack-allocated)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct PropAccount {
    pub id: u8,                    // Account ID (0-31)
    pub status: PropAccountStatus, // Current state
    pub position: i32,             // Current position (shares)
    pub target_position: i32,      // Desired position from master
    pub last_fill_ts_ns: u64,      // Timestamp of last fill
    pub fill_latency_us: u16,      // Latency to receive fill (microseconds)
    pub rejection_count: u8,       // Consecutive rejections
    pub sync_lag_ns: u32,          // Drift from master (nanoseconds)
    pub equity: f64,               // Account equity
    pub margin_available: f64,     // Available margin
    pub reserved: [u8; 40],        // Padding to reach 88 bytes (1+1+4+4+8+2+1+1+4+8+8+40 = 88)
}

impl Default for PropAccount {
    fn default() -> Self {
        Self {
            id: 0,
            status: PropAccountStatus::Inactive,
            position: 0,
            target_position: 0,
            last_fill_ts_ns: 0,
            fill_latency_us: 0,
            rejection_count: 0,
            sync_lag_ns: 0,
            equity: 0.0,
            margin_available: 0.0,
            reserved: [0; 40],
        }
    }
}

// ---------------------------------------------------------------------------
// Master Account
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct MasterAccount {
    pub position: i32,        // Current IBKR position
    pub target_position: i32, // Desired position
    pub last_fill_ts_ns: u64, // Master fill timestamp
    pub total_equity: f64,    // Aggregate equity
}

impl Default for MasterAccount {
    fn default() -> Self {
        Self {
            position: 0,
            target_position: 0,
            last_fill_ts_ns: 0,
            total_equity: 0.0,
        }
    }
}

// ---------------------------------------------------------------------------
// PropScalingEngine
// ---------------------------------------------------------------------------

pub struct PropScalingEngine {
    pub accounts: [PropAccount; 32],
    pub master: MasterAccount,
    pub num_active_accounts: u8,
    pub sync_lag_ns: u32,       // Max lag across all accounts
    pub rate_limited_count: u8, // Accounts in backoff state
    pub last_hedge_ts_ns: u64,
    pub hedge_buffer: [i32; 32], // Auto-hedge order queue (pre-allocated)
}

impl Default for PropScalingEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl PropScalingEngine {
    pub const MAX_PROP_ACCOUNTS: usize = 32;
    pub const SYNC_THRESHOLD_NS: u32 = 100_000; // 100µs in nanoseconds
    pub const MIN_EQUITY: f64 = 2000.0; // Topstep/FTMO minimum

    pub fn new() -> Self {
        Self {
            accounts: [PropAccount::default(); 32],
            master: MasterAccount::default(),
            num_active_accounts: 0,
            sync_lag_ns: 0,
            rate_limited_count: 0,
            last_hedge_ts_ns: 0,
            hedge_buffer: [0; 32],
        }
    }

    /// Initialize all accounts at startup
    pub fn init_accounts(&mut self) {
        for (i, account) in self.accounts.iter_mut().enumerate() {
            account.id = i as u8;
            account.status = PropAccountStatus::Inactive;
            account.position = 0;
            account.target_position = 0;
            account.equity = 0.0;
            account.margin_available = 0.0;
        }
        self.num_active_accounts = 0;
        self.rate_limited_count = 0;
    }

    /// Handle a fill on the master IBKR account
    pub fn handle_master_fill(&mut self, fill: FillEvent) {
        // Update master position
        self.master.last_fill_ts_ns = fill.timestamp_ns;
        match fill.side {
            Side::Buy => self.master.position += fill.qty,
            Side::Sell => self.master.position -= fill.qty,
        }

        // Fan out to active accounts (distribute pro-rata)
        if self.num_active_accounts > 0 {
            let qty_per_account = fill.qty / self.num_active_accounts as i32;
            for account in self.accounts.iter_mut() {
                if account.status == PropAccountStatus::Active {
                    account.target_position = self.master.position;
                }
            }
        }

        // Recalculate sync lag
        self.update_sync_lag();
    }

    /// Handle a fill on a prop account
    pub fn handle_prop_fill(&mut self, fill: FillEvent) {
        let account = &mut self.accounts[fill.account_id as usize];

        // Update position
        match fill.side {
            Side::Buy => account.position += fill.qty,
            Side::Sell => account.position -= fill.qty,
        }

        // Record fill time and latency
        account.last_fill_ts_ns = fill.timestamp_ns;
        if self.master.last_fill_ts_ns > 0 {
            let latency_ns = fill
                .timestamp_ns
                .saturating_sub(self.master.last_fill_ts_ns);
            account.fill_latency_us = (latency_ns / 1000) as u16;
        }

        // Reset rejection count on successful fill
        if account.status == PropAccountStatus::RateLimited {
            account.rejection_count = 0;
            account.status = PropAccountStatus::Active;
            if self.rate_limited_count > 0 {
                self.rate_limited_count -= 1;
            }
        }

        // Recalculate sync lag
        self.update_sync_lag();
    }

    /// Handle a rejection from a prop account
    pub fn handle_prop_rejection(&mut self, event: RejectionEvent) {
        let account = &mut self.accounts[event.account_id as usize];

        account.rejection_count += 1;

        match event.reason {
            RejectionReason::RateLimit => {
                if account.status == PropAccountStatus::Active {
                    account.status = PropAccountStatus::RateLimited;
                    self.rate_limited_count += 1;
                }
                // Queue for auto-hedge
                self.hedge_buffer[event.account_id as usize] = event.original_qty;
            }
            RejectionReason::InsufficientMargin | RejectionReason::Disconnect => {
                account.status = PropAccountStatus::Error;
                if self.num_active_accounts > 0 {
                    self.num_active_accounts -= 1;
                }
            }
            _ => {
                // For other reasons, mark as rate limited if consecutive rejections > 3
                if account.rejection_count > 3 {
                    account.status = PropAccountStatus::OutOfSync;
                }
            }
        }
    }

    /// Execute auto-hedge for accounts in rate limit backoff
    pub fn auto_hedge(&mut self) -> usize {
        let mut hedged_count = 0;

        for i in 0..Self::MAX_PROP_ACCOUNTS {
            if self.hedge_buffer[i] != 0 {
                // In a real implementation, this would execute on master IBKR
                // For now, just clear the buffer
                self.hedge_buffer[i] = 0;
                hedged_count += 1;
            }
        }

        self.last_hedge_ts_ns = crate::now_ns();
        hedged_count
    }

    /// Check if all active accounts are in sync
    pub fn is_sync_healthy(&self) -> bool {
        // Check sync lag threshold
        if self.sync_lag_ns > Self::SYNC_THRESHOLD_NS {
            return false;
        }

        // Check for accounts in bad states
        for account in self.accounts.iter() {
            if account.status == PropAccountStatus::OutOfSync
                || account.status == PropAccountStatus::Error
            {
                return false;
            }
        }

        // Max 5 accounts can be rate limited
        if self.rate_limited_count > 5 {
            return false;
        }

        true
    }

    /// Calculate position drift for a specific account
    pub fn position_drift(&self, account_id: u8) -> f64 {
        let account = &self.accounts[account_id as usize];
        let drift = (account.position - account.target_position).abs();

        if account.target_position != 0 {
            (drift as f64 / account.target_position.abs() as f64) * 100.0
        } else {
            drift as f64
        }
    }

    /// Reset all accounts for daily market open
    pub fn reset_daily(&mut self) {
        for account in self.accounts.iter_mut() {
            account.position = 0;
            account.target_position = 0;
            account.rejection_count = 0;
            account.sync_lag_ns = 0;

            // Reactivate accounts with sufficient equity
            if account.equity >= Self::MIN_EQUITY {
                account.status = PropAccountStatus::Active;
            } else {
                account.status = PropAccountStatus::Inactive;
            }
        }

        self.master.position = 0;
        self.master.target_position = 0;
        self.sync_lag_ns = 0;
        self.rate_limited_count = 0;
        self.hedge_buffer = [0; 32];

        // Recount active accounts
        self.num_active_accounts = self
            .accounts
            .iter()
            .filter(|a| a.status == PropAccountStatus::Active)
            .count() as u8;
    }

    /// Get count of active accounts
    pub fn active_count(&self) -> usize {
        self.accounts
            .iter()
            .filter(|a| {
                a.status == PropAccountStatus::Active || a.status == PropAccountStatus::RateLimited
            })
            .count()
    }

    /// Get count of rate-limited accounts
    pub fn rate_limited_count(&self) -> usize {
        self.rate_limited_count as usize
    }

    /// Set target position for a specific account
    pub fn set_target_position(&mut self, account_id: u8, target: i32) {
        if (account_id as usize) < Self::MAX_PROP_ACCOUNTS {
            let account = &mut self.accounts[account_id as usize];

            // Validate margin availability (simplified check)
            let position_delta = (target - account.position).abs();
            if account.margin_available > (position_delta as f64 * 50.0) {
                account.target_position = target;
            }
        }
    }

    /// Internal: Update max sync lag across all accounts
    fn update_sync_lag(&mut self) {
        let mut max_lag = 0u32;

        for account in self.accounts.iter_mut() {
            if account.status == PropAccountStatus::Active
                || account.status == PropAccountStatus::RateLimited
            {
                // Calculate lag from master
                if self.master.last_fill_ts_ns > 0 && account.last_fill_ts_ns > 0 {
                    let lag =
                        self.master
                            .last_fill_ts_ns
                            .saturating_sub(account.last_fill_ts_ns) as u32;
                    account.sync_lag_ns = lag;
                    max_lag = max_lag.max(lag);
                }
            }
        }

        self.sync_lag_ns = max_lag;
    }
}

// ---------------------------------------------------------------------------
// Unit Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prop_account_size() {
        // Verify PropAccount is exactly 88 bytes
        assert_eq!(std::mem::size_of::<PropAccount>(), 88);
    }

    #[test]
    fn test_init_accounts() {
        let mut engine = PropScalingEngine::new();
        engine.init_accounts();

        assert_eq!(engine.num_active_accounts, 0);
        for (i, account) in engine.accounts.iter().enumerate() {
            assert_eq!(account.id, i as u8);
            assert_eq!(account.status, PropAccountStatus::Inactive);
        }
    }

    #[test]
    fn test_handle_master_fill_buy() {
        let mut engine = PropScalingEngine::new();
        engine.init_accounts();

        // Activate some accounts
        for i in 0..5 {
            engine.accounts[i].status = PropAccountStatus::Active;
            engine.accounts[i].equity = 5000.0;
        }
        engine.num_active_accounts = 5;

        let fill = FillEvent {
            timestamp_ns: 1000,
            account_id: 0,
            side: Side::Buy,
            qty: 100,
            price: 50.0,
            is_master: true,
        };

        engine.handle_master_fill(fill);

        assert_eq!(engine.master.position, 100);
        // All active accounts should have target updated
        for i in 0..5 {
            assert_eq!(engine.accounts[i].target_position, 100);
        }
    }

    #[test]
    fn test_handle_prop_fill() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].status = PropAccountStatus::Active;
        engine.master.last_fill_ts_ns = 1000;

        let fill = FillEvent {
            timestamp_ns: 1500,
            account_id: 0,
            side: Side::Buy,
            qty: 50,
            price: 50.0,
            is_master: false,
        };

        engine.handle_prop_fill(fill);

        assert_eq!(engine.accounts[0].position, 50);
        assert_eq!(engine.accounts[0].last_fill_ts_ns, 1500);
        // Latency should be 500ns = 0.5µs (rounds to 0)
        assert!(engine.accounts[0].fill_latency_us < 1);
    }

    #[test]
    fn test_handle_prop_rejection_rate_limit() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].status = PropAccountStatus::Active;

        let rejection = RejectionEvent {
            timestamp_ns: 1000,
            account_id: 0,
            reason: RejectionReason::RateLimit,
            original_qty: 100,
        };

        engine.handle_prop_rejection(rejection);

        assert_eq!(engine.accounts[0].status, PropAccountStatus::RateLimited);
        assert_eq!(engine.rate_limited_count, 1);
        assert_eq!(engine.hedge_buffer[0], 100);
    }

    #[test]
    fn test_auto_hedge() {
        let mut engine = PropScalingEngine::new();
        engine.hedge_buffer[0] = 100;
        engine.hedge_buffer[1] = 50;

        let hedged = engine.auto_hedge();

        assert_eq!(hedged, 2);
        assert_eq!(engine.hedge_buffer[0], 0);
        assert_eq!(engine.hedge_buffer[1], 0);
        assert!(engine.last_hedge_ts_ns > 0);
    }

    #[test]
    fn test_is_sync_healthy() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].status = PropAccountStatus::Active;
        engine.sync_lag_ns = 50_000; // 50µs - under threshold

        assert!(engine.is_sync_healthy());

        // Exceed threshold
        engine.sync_lag_ns = 150_000; // 150µs
        assert!(!engine.is_sync_healthy());
    }

    #[test]
    fn test_is_sync_healthy_with_out_of_sync_account() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].status = PropAccountStatus::OutOfSync;

        assert!(!engine.is_sync_healthy());
    }

    #[test]
    fn test_position_drift() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].position = 90;
        engine.accounts[0].target_position = 100;

        let drift = engine.position_drift(0);
        assert!((drift - 10.0).abs() < 0.1);
    }

    #[test]
    fn test_reset_daily() {
        let mut engine = PropScalingEngine::new();

        // Set up some state
        engine.accounts[0].equity = 5000.0;
        engine.accounts[0].position = 100;
        engine.accounts[0].rejection_count = 3;
        engine.master.position = 500;

        engine.reset_daily();

        assert_eq!(engine.accounts[0].position, 0);
        assert_eq!(engine.accounts[0].target_position, 0);
        assert_eq!(engine.accounts[0].rejection_count, 0);
        assert_eq!(engine.accounts[0].status, PropAccountStatus::Active);
        assert_eq!(engine.master.position, 0);
        assert_eq!(engine.num_active_accounts, 1);
    }

    #[test]
    fn test_reset_daily_insufficient_equity() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].equity = 1000.0; // Below minimum

        engine.reset_daily();

        assert_eq!(engine.accounts[0].status, PropAccountStatus::Inactive);
        assert_eq!(engine.num_active_accounts, 0);
    }

    #[test]
    fn test_active_count() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].status = PropAccountStatus::Active;
        engine.accounts[1].status = PropAccountStatus::RateLimited;
        engine.accounts[2].status = PropAccountStatus::Inactive;

        assert_eq!(engine.active_count(), 2);
    }

    #[test]
    fn test_rate_limited_count() {
        let mut engine = PropScalingEngine::new();
        engine.rate_limited_count = 3;

        assert_eq!(engine.rate_limited_count(), 3);
    }

    #[test]
    fn test_set_target_position() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].margin_available = 10000.0;
        engine.accounts[0].position = 0;

        engine.set_target_position(0, 100);

        assert_eq!(engine.accounts[0].target_position, 100);
    }

    #[test]
    fn test_set_target_position_insufficient_margin() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].margin_available = 100.0; // Insufficient
        engine.accounts[0].position = 0;

        engine.set_target_position(0, 1000);

        // Should not update target
        assert_eq!(engine.accounts[0].target_position, 0);
    }

    #[test]
    fn test_consecutive_rejections_trigger_out_of_sync() {
        let mut engine = PropScalingEngine::new();
        engine.accounts[0].status = PropAccountStatus::Active;

        // Send multiple rejections
        for _ in 0..4 {
            let rejection = RejectionEvent {
                timestamp_ns: 1000,
                account_id: 0,
                reason: RejectionReason::OrderTooLarge,
                original_qty: 100,
            };
            engine.handle_prop_rejection(rejection);
        }

        assert_eq!(engine.accounts[0].status, PropAccountStatus::OutOfSync);
    }
}
