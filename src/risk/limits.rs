//! Pre-trade Position Limit Checks
//!
//! Per-symbol and portfolio-aggregate position limits.

use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Position Limits
// ---------------------------------------------------------------------------

pub struct PositionLimits {
    pub max_per_symbol: f64,
    pub max_portfolio: f64,
    positions: HashMap<u32, f64>,
}

impl PositionLimits {
    pub fn new(max_per_symbol: f64, max_portfolio: f64) -> Self {
        Self {
            max_per_symbol,
            max_portfolio,
            positions: HashMap::new(),
        }
    }

    /// Check if a proposed position change would breach limits.
    pub fn check_pre_trade(&self, symbol_id: u32, delta: f64) -> PreTradeResult {
        let current = self.positions.get(&symbol_id).copied().unwrap_or(0.0);
        let new_position = current + delta;

        if new_position.abs() > self.max_per_symbol {
            return PreTradeResult::Rejected(LimitBreach::PerSymbol {
                symbol_id,
                current,
                proposed: new_position,
                limit: self.max_per_symbol,
            });
        }

        let total: f64 =
            self.positions.values().map(|v| v.abs()).sum::<f64>() + delta.abs() - current.abs();

        if total > self.max_portfolio {
            return PreTradeResult::Rejected(LimitBreach::Portfolio {
                current_total: total - delta.abs() + current.abs(),
                proposed_total: total,
                limit: self.max_portfolio,
            });
        }

        PreTradeResult::Approved
    }

    /// Update position after a fill.
    pub fn update_position(&mut self, symbol_id: u32, delta: f64) {
        let entry = self.positions.entry(symbol_id).or_insert(0.0);
        *entry += delta;
    }

    /// Get the current position for a symbol.
    pub fn get_position(&self, symbol_id: u32) -> f64 {
        self.positions.get(&symbol_id).copied().unwrap_or(0.0)
    }

    /// Get total aggregate position.
    pub fn total_position(&self) -> f64 {
        self.positions.values().map(|v| v.abs()).sum()
    }

    /// Reset all positions (daily reset).
    pub fn reset(&mut self) {
        self.positions.clear();
    }
}

#[derive(Debug, PartialEq)]
pub enum PreTradeResult {
    Approved,
    Rejected(LimitBreach),
}

#[derive(Debug, PartialEq)]
pub enum LimitBreach {
    PerSymbol {
        symbol_id: u32,
        current: f64,
        proposed: f64,
        limit: f64,
    },
    Portfolio {
        current_total: f64,
        proposed_total: f64,
        limit: f64,
    },
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_approved_trade() {
        let limits = PositionLimits::new(100_000.0, 500_000.0);
        assert_eq!(
            limits.check_pre_trade(1, 50_000.0),
            PreTradeResult::Approved
        );
    }

    #[test]
    fn test_per_symbol_limit_breach() {
        let mut limits = PositionLimits::new(100_000.0, 500_000.0);
        limits.update_position(1, 80_000.0);

        match limits.check_pre_trade(1, 30_000.0) {
            PreTradeResult::Rejected(LimitBreach::PerSymbol { symbol_id, .. }) => {
                assert_eq!(symbol_id, 1);
            }
            _ => panic!("Expected per-symbol breach"),
        }
    }

    #[test]
    fn test_portfolio_limit_breach() {
        let mut limits = PositionLimits::new(200_000.0, 500_000.0);
        limits.update_position(1, 200_000.0);
        limits.update_position(2, 200_000.0);

        match limits.check_pre_trade(3, 200_000.0) {
            PreTradeResult::Rejected(LimitBreach::Portfolio { .. }) => {}
            _ => panic!("Expected portfolio breach"),
        }
    }

    #[test]
    fn test_update_position() {
        let mut limits = PositionLimits::new(100_000.0, 500_000.0);
        limits.update_position(1, 50_000.0);
        assert_eq!(limits.get_position(1), 50_000.0);

        limits.update_position(1, -20_000.0);
        assert_eq!(limits.get_position(1), 30_000.0);
    }

    #[test]
    fn test_total_position() {
        let mut limits = PositionLimits::new(100_000.0, 500_000.0);
        limits.update_position(1, 50_000.0);
        limits.update_position(2, -30_000.0);
        assert_eq!(limits.total_position(), 80_000.0);
    }

    #[test]
    fn test_get_position_unknown_symbol() {
        let limits = PositionLimits::new(100_000.0, 500_000.0);
        assert_eq!(limits.get_position(999), 0.0);
    }

    #[test]
    fn test_reset() {
        let mut limits = PositionLimits::new(100_000.0, 500_000.0);
        limits.update_position(1, 50_000.0);
        limits.update_position(2, 30_000.0);

        limits.reset();
        assert_eq!(limits.total_position(), 0.0);
        assert_eq!(limits.get_position(1), 0.0);
    }

    #[test]
    fn test_negative_position_allowed() {
        let limits = PositionLimits::new(100_000.0, 500_000.0);
        assert_eq!(
            limits.check_pre_trade(1, -50_000.0),
            PreTradeResult::Approved
        );
    }

    #[test]
    fn test_exact_limit_allowed() {
        let limits = PositionLimits::new(100_000.0, 500_000.0);
        assert_eq!(
            limits.check_pre_trade(1, 100_000.0),
            PreTradeResult::Approved
        );
    }

    #[test]
    fn test_just_over_limit_rejected() {
        let limits = PositionLimits::new(100_000.0, 500_000.0);
        match limits.check_pre_trade(1, 100_001.0) {
            PreTradeResult::Rejected(LimitBreach::PerSymbol { .. }) => {}
            _ => panic!("Expected rejection"),
        }
    }
}
