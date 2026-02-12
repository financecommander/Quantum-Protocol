//! Execution Feed
//!
//! Monitors order fills and rejections from broker connections.

use crate::engine::{now_ns, FillEvent, RejectionEvent, RejectionReason, Side};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tokio::sync::mpsc;

// ---------------------------------------------------------------------------
// Execution Message Types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct FillMessage {
    pub account_id: u8,
    pub symbol: String,
    pub side: String, // "buy" or "sell"
    pub qty: i32,
    pub price: f64,
    pub timestamp: u64,
    pub is_master: bool,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct RejectionMessage {
    pub account_id: u8,
    pub symbol: String,
    pub reason: String,
    pub qty: i32,
    pub timestamp: u64,
}

// ---------------------------------------------------------------------------
// Execution Feed
// ---------------------------------------------------------------------------

/// Execution feed for monitoring fills and rejections
pub struct ExecutionFeed {
    fill_tx: mpsc::Sender<FillEvent>,
    rejection_tx: mpsc::Sender<RejectionEvent>,
    account_fill_counts: HashMap<u8, u64>,
    account_rejection_counts: HashMap<u8, u64>,
}

impl ExecutionFeed {
    /// Create a new execution feed
    pub fn new(
        fill_tx: mpsc::Sender<FillEvent>,
        rejection_tx: mpsc::Sender<RejectionEvent>,
    ) -> Self {
        Self {
            fill_tx,
            rejection_tx,
            account_fill_counts: HashMap::new(),
            account_rejection_counts: HashMap::new(),
        }
    }

    /// Process a fill message
    pub async fn handle_fill(&mut self, msg: FillMessage) -> Result<()> {
        let side = match msg.side.to_lowercase().as_str() {
            "buy" => Side::Buy,
            "sell" => Side::Sell,
            _ => {
                log::warn!("Unknown side: {}", msg.side);
                return Ok(());
            }
        };

        let fill = FillEvent {
            timestamp_ns: msg.timestamp,
            account_id: msg.account_id,
            side,
            qty: msg.qty,
            price: msg.price,
            is_master: msg.is_master,
        };

        // Track account-level fill counts
        *self.account_fill_counts.entry(msg.account_id).or_insert(0) += 1;

        self.fill_tx.send(fill).await?;

        log::debug!(
            "Fill processed: account={}, side={:?}, qty={}, price={}",
            msg.account_id,
            side,
            msg.qty,
            msg.price
        );

        Ok(())
    }

    /// Process a rejection message
    pub async fn handle_rejection(&mut self, msg: RejectionMessage) -> Result<()> {
        let reason = parse_rejection_reason(&msg.reason);

        let rejection = RejectionEvent {
            timestamp_ns: msg.timestamp,
            account_id: msg.account_id,
            reason,
            original_qty: msg.qty,
        };

        // Track account-level rejection counts
        *self
            .account_rejection_counts
            .entry(msg.account_id)
            .or_insert(0) += 1;

        self.rejection_tx.send(rejection).await?;

        log::warn!(
            "Rejection processed: account={}, reason={:?}, qty={}",
            msg.account_id,
            reason,
            msg.qty
        );

        Ok(())
    }

    /// Get fill count for an account
    pub fn get_fill_count(&self, account_id: u8) -> u64 {
        *self.account_fill_counts.get(&account_id).unwrap_or(&0)
    }

    /// Get rejection count for an account
    pub fn get_rejection_count(&self, account_id: u8) -> u64 {
        *self.account_rejection_counts.get(&account_id).unwrap_or(&0)
    }

    /// Get total fill count across all accounts
    pub fn get_total_fills(&self) -> u64 {
        self.account_fill_counts.values().sum()
    }

    /// Get total rejection count across all accounts
    pub fn get_total_rejections(&self) -> u64 {
        self.account_rejection_counts.values().sum()
    }
}

/// Parse rejection reason string to enum
fn parse_rejection_reason(reason: &str) -> RejectionReason {
    match reason.to_lowercase().as_str() {
        s if s.contains("rate") || s.contains("limit") => RejectionReason::RateLimit,
        s if s.contains("margin") => RejectionReason::InsufficientMargin,
        s if s.contains("too large") || s.contains("size") => RejectionReason::OrderTooLarge,
        s if s.contains("disconnect") || s.contains("connection") => RejectionReason::Disconnect,
        _ => RejectionReason::Other,
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_fill_processing() {
        let (fill_tx, mut fill_rx) = mpsc::channel(10);
        let (rejection_tx, _rejection_rx) = mpsc::channel(10);

        let mut feed = ExecutionFeed::new(fill_tx, rejection_tx);

        let fill_msg = FillMessage {
            account_id: 1,
            symbol: "SPY".to_string(),
            side: "buy".to_string(),
            qty: 100,
            price: 450.0,
            timestamp: now_ns(),
            is_master: true,
        };

        feed.handle_fill(fill_msg).await.unwrap();

        let received = fill_rx.recv().await.unwrap();
        assert_eq!(received.account_id, 1);
        assert_eq!(received.qty, 100);
        assert_eq!(received.price, 450.0);
        assert_eq!(feed.get_fill_count(1), 1);
    }

    #[tokio::test]
    async fn test_rejection_processing() {
        let (fill_tx, _fill_rx) = mpsc::channel(10);
        let (rejection_tx, mut rejection_rx) = mpsc::channel(10);

        let mut feed = ExecutionFeed::new(fill_tx, rejection_tx);

        let rejection_msg = RejectionMessage {
            account_id: 2,
            symbol: "QQQ".to_string(),
            reason: "rate limit exceeded".to_string(),
            qty: 50,
            timestamp: now_ns(),
        };

        feed.handle_rejection(rejection_msg).await.unwrap();

        let received = rejection_rx.recv().await.unwrap();
        assert_eq!(received.account_id, 2);
        assert_eq!(received.original_qty, 50);
        assert_eq!(received.reason, RejectionReason::RateLimit);
        assert_eq!(feed.get_rejection_count(2), 1);
    }

    #[test]
    fn test_parse_rejection_reason() {
        assert_eq!(
            parse_rejection_reason("rate limit exceeded"),
            RejectionReason::RateLimit
        );
        assert_eq!(
            parse_rejection_reason("insufficient margin"),
            RejectionReason::InsufficientMargin
        );
        assert_eq!(
            parse_rejection_reason("order too large"),
            RejectionReason::OrderTooLarge
        );
        assert_eq!(
            parse_rejection_reason("connection lost"),
            RejectionReason::Disconnect
        );
        assert_eq!(
            parse_rejection_reason("unknown error"),
            RejectionReason::Other
        );
    }
}
