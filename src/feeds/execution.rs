//! Execution Feed
//!
//! Monitors fills and rejections from broker connections with
//! account-level tracking.

use crate::engine::common::{FillEvent, RejectionEvent, RejectionReason, Side};

// ---------------------------------------------------------------------------
// Execution Feed
// ---------------------------------------------------------------------------

pub struct ExecutionFeed {
    pub fills: Vec<FillEvent>,
    pub rejections: Vec<RejectionEvent>,
    pub consecutive_rejections: u32,
    pub total_fills: u64,
    pub total_rejections: u64,
}

impl Default for ExecutionFeed {
    fn default() -> Self {
        Self::new()
    }
}

impl ExecutionFeed {
    pub fn new() -> Self {
        Self {
            fills: Vec::new(),
            rejections: Vec::new(),
            consecutive_rejections: 0,
            total_fills: 0,
            total_rejections: 0,
        }
    }

    /// Record a fill event.
    pub fn record_fill(&mut self, fill: FillEvent) {
        self.consecutive_rejections = 0;
        self.total_fills += 1;
        self.fills.push(fill);
    }

    /// Record a rejection event.
    pub fn record_rejection(&mut self, rejection: RejectionEvent) {
        self.consecutive_rejections += 1;
        self.total_rejections += 1;
        self.rejections.push(rejection);
    }

    /// Parse a JSON fill message.
    pub fn parse_fill_json(json: &str) -> Option<FillEvent> {
        let v: serde_json::Value = serde_json::from_str(json).ok()?;
        let obj = v.as_object()?;

        Some(FillEvent {
            timestamp_ns: obj.get("timestamp_ns")?.as_u64()?,
            account_id: obj.get("account_id")?.as_u64()? as u8,
            side: match obj.get("side")?.as_str()? {
                "buy" | "Buy" => Side::Buy,
                "sell" | "Sell" => Side::Sell,
                _ => return None,
            },
            qty: obj.get("qty")?.as_i64()? as i32,
            price: obj.get("price")?.as_f64()?,
            is_master: obj
                .get("is_master")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
        })
    }

    /// Parse a JSON rejection message.
    pub fn parse_rejection_json(json: &str) -> Option<RejectionEvent> {
        let v: serde_json::Value = serde_json::from_str(json).ok()?;
        let obj = v.as_object()?;

        let reason = match obj.get("reason")?.as_str()? {
            "rate_limit" => RejectionReason::RateLimit,
            "insufficient_margin" => RejectionReason::InsufficientMargin,
            "order_too_large" => RejectionReason::OrderTooLarge,
            "disconnect" => RejectionReason::Disconnect,
            _ => RejectionReason::Other,
        };

        Some(RejectionEvent {
            timestamp_ns: obj.get("timestamp_ns")?.as_u64()?,
            account_id: obj.get("account_id")?.as_u64()? as u8,
            reason,
            original_qty: obj.get("original_qty")?.as_i64()? as i32,
        })
    }

    /// Check if too many consecutive rejections have occurred.
    pub fn is_rejection_threshold_breached(&self, max: u32) -> bool {
        self.consecutive_rejections >= max
    }

    /// Clear recorded events (e.g., daily reset).
    pub fn reset(&mut self) {
        self.fills.clear();
        self.rejections.clear();
        self.consecutive_rejections = 0;
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_record_fill() {
        let mut feed = ExecutionFeed::new();
        let fill = FillEvent {
            timestamp_ns: 1000,
            account_id: 0,
            side: Side::Buy,
            qty: 100,
            price: 50.0,
            is_master: true,
        };
        feed.record_fill(fill);
        assert_eq!(feed.total_fills, 1);
        assert_eq!(feed.consecutive_rejections, 0);
        assert_eq!(feed.fills.len(), 1);
    }

    #[test]
    fn test_record_rejection() {
        let mut feed = ExecutionFeed::new();
        let rejection = RejectionEvent {
            timestamp_ns: 1000,
            account_id: 0,
            reason: RejectionReason::RateLimit,
            original_qty: 100,
        };
        feed.record_rejection(rejection);
        assert_eq!(feed.total_rejections, 1);
        assert_eq!(feed.consecutive_rejections, 1);
    }

    #[test]
    fn test_fill_resets_consecutive_rejections() {
        let mut feed = ExecutionFeed::new();

        // Record some rejections
        for _ in 0..3 {
            feed.record_rejection(RejectionEvent {
                timestamp_ns: 1000,
                account_id: 0,
                reason: RejectionReason::RateLimit,
                original_qty: 100,
            });
        }
        assert_eq!(feed.consecutive_rejections, 3);

        // Fill resets counter
        feed.record_fill(FillEvent {
            timestamp_ns: 2000,
            account_id: 0,
            side: Side::Buy,
            qty: 100,
            price: 50.0,
            is_master: false,
        });
        assert_eq!(feed.consecutive_rejections, 0);
    }

    #[test]
    fn test_parse_fill_json() {
        let json = r#"{"timestamp_ns":1000,"account_id":0,"side":"buy","qty":100,"price":50.0,"is_master":true}"#;
        let fill = ExecutionFeed::parse_fill_json(json).unwrap();
        assert_eq!(fill.timestamp_ns, 1000);
        assert_eq!(fill.account_id, 0);
        assert_eq!(fill.qty, 100);
        assert_eq!(fill.price, 50.0);
        assert!(fill.is_master);
    }

    #[test]
    fn test_parse_fill_json_sell() {
        let json = r#"{"timestamp_ns":1000,"account_id":1,"side":"sell","qty":50,"price":55.0}"#;
        let fill = ExecutionFeed::parse_fill_json(json).unwrap();
        assert!(matches!(fill.side, Side::Sell));
        assert!(!fill.is_master);
    }

    #[test]
    fn test_parse_fill_json_invalid() {
        assert!(ExecutionFeed::parse_fill_json("not json").is_none());
        assert!(ExecutionFeed::parse_fill_json("{}").is_none());
    }

    #[test]
    fn test_parse_rejection_json() {
        let json =
            r#"{"timestamp_ns":1000,"account_id":0,"reason":"rate_limit","original_qty":100}"#;
        let rejection = ExecutionFeed::parse_rejection_json(json).unwrap();
        assert_eq!(rejection.reason, RejectionReason::RateLimit);
        assert_eq!(rejection.original_qty, 100);
    }

    #[test]
    fn test_parse_rejection_json_reasons() {
        let cases = vec![
            ("insufficient_margin", RejectionReason::InsufficientMargin),
            ("order_too_large", RejectionReason::OrderTooLarge),
            ("disconnect", RejectionReason::Disconnect),
            ("unknown_reason", RejectionReason::Other),
        ];
        for (reason_str, expected) in cases {
            let json = format!(
                r#"{{"timestamp_ns":1000,"account_id":0,"reason":"{}","original_qty":100}}"#,
                reason_str
            );
            let rejection = ExecutionFeed::parse_rejection_json(&json).unwrap();
            assert_eq!(rejection.reason, expected);
        }
    }

    #[test]
    fn test_rejection_threshold() {
        let mut feed = ExecutionFeed::new();
        assert!(!feed.is_rejection_threshold_breached(3));

        for _ in 0..3 {
            feed.record_rejection(RejectionEvent {
                timestamp_ns: 1000,
                account_id: 0,
                reason: RejectionReason::RateLimit,
                original_qty: 100,
            });
        }
        assert!(feed.is_rejection_threshold_breached(3));
    }

    #[test]
    fn test_reset() {
        let mut feed = ExecutionFeed::new();
        feed.record_fill(FillEvent {
            timestamp_ns: 1000,
            account_id: 0,
            side: Side::Buy,
            qty: 100,
            price: 50.0,
            is_master: false,
        });
        feed.record_rejection(RejectionEvent {
            timestamp_ns: 1000,
            account_id: 0,
            reason: RejectionReason::RateLimit,
            original_qty: 100,
        });

        feed.reset();
        assert!(feed.fills.is_empty());
        assert!(feed.rejections.is_empty());
        assert_eq!(feed.consecutive_rejections, 0);
    }
}
