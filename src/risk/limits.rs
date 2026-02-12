//! Position Limits and Pre-Trade Checks
//!
//! Fixed-size limit enforcement for high-frequency trading.

use crate::engine::Side;
use std::collections::HashMap;
use thiserror::Error;

// ---------------------------------------------------------------------------
// Risk Violation Types
// ---------------------------------------------------------------------------

#[derive(Debug, Error, PartialEq)]
pub enum RiskViolation {
    #[error("Symbol limit breached: {0}")]
    SymbolLimitBreached(String),

    #[error("Portfolio limit breached: {0}")]
    PortfolioLimitBreached(String),

    #[error("Notional exceeded: {0}")]
    NotionalExceeded(String),

    #[error("Concentration risk: {0}")]
    ConcentrationRisk(String),
}

// ---------------------------------------------------------------------------
// Position Limit Configuration
// ---------------------------------------------------------------------------

/// Position limit for a single symbol
#[derive(Debug, Clone)]
pub struct PositionLimit {
    pub symbol_id: u32,
    pub max_long: i64,
    pub max_short: i64,
    pub max_notional: f64,
}

// ---------------------------------------------------------------------------
// Risk Limits
// ---------------------------------------------------------------------------

/// Risk limits with pre-trade checks
pub struct RiskLimits {
    /// Per-symbol position limits
    symbol_limits: HashMap<u32, PositionLimit>,
    /// Current positions per symbol (positive = long, negative = short)
    current_positions: HashMap<u32, i64>,
    /// Portfolio-level limits
    max_portfolio_notional: f64,
    max_total_positions: i64,
    max_concentration_pct: f64,
}

impl RiskLimits {
    /// Create new risk limits
    pub fn new(
        max_portfolio_notional: f64,
        max_total_positions: i64,
        max_concentration_pct: f64,
    ) -> Self {
        Self {
            symbol_limits: HashMap::new(),
            current_positions: HashMap::new(),
            max_portfolio_notional,
            max_total_positions,
            max_concentration_pct,
        }
    }

    /// Add a position limit for a symbol
    pub fn add_symbol_limit(&mut self, limit: PositionLimit) {
        self.symbol_limits.insert(limit.symbol_id, limit);
    }

    /// Update current position for a symbol
    pub fn update_position(&mut self, symbol_id: u32, position: i64) {
        self.current_positions.insert(symbol_id, position);
    }

    /// Get current position for a symbol
    pub fn get_position(&self, symbol_id: u32) -> i64 {
        *self.current_positions.get(&symbol_id).unwrap_or(&0)
    }

    /// Pre-trade check: validate order against limits
    pub fn check_order(
        &self,
        symbol_id: u32,
        side: Side,
        qty: i32,
        price: f64,
    ) -> Result<(), RiskViolation> {
        // Calculate new position after this order
        let current_pos = self.get_position(symbol_id);
        let delta = match side {
            Side::Buy => qty as i64,
            Side::Sell => -(qty as i64),
        };
        let new_pos = current_pos + delta;

        // Check symbol-level limits
        if let Some(limit) = self.symbol_limits.get(&symbol_id) {
            if new_pos > limit.max_long {
                return Err(RiskViolation::SymbolLimitBreached(format!(
                    "New long position {} exceeds max {}",
                    new_pos, limit.max_long
                )));
            }
            if new_pos < -limit.max_short {
                return Err(RiskViolation::SymbolLimitBreached(format!(
                    "New short position {} exceeds max {}",
                    new_pos.abs(),
                    limit.max_short
                )));
            }

            // Check notional limit
            let notional = (new_pos.abs() as f64) * price;
            if notional > limit.max_notional {
                return Err(RiskViolation::NotionalExceeded(format!(
                    "Notional {} exceeds max {}",
                    notional, limit.max_notional
                )));
            }
        }

        // Check portfolio-level limits
        self.check_portfolio_limits(symbol_id, new_pos, price)?;

        Ok(())
    }

    /// Check portfolio-level risk limits
    fn check_portfolio_limits(
        &self,
        symbol_id: u32,
        new_pos: i64,
        price: f64,
    ) -> Result<(), RiskViolation> {
        // Calculate total positions and notional
        let mut total_positions: i64 = 0;
        let mut total_notional: f64 = 0.0;

        for (&sid, &pos) in &self.current_positions {
            if sid == symbol_id {
                // Use new position for this symbol
                total_positions += new_pos.abs();
                total_notional += (new_pos.abs() as f64) * price;
            } else {
                total_positions += pos.abs();
                // Approximate notional (we don't have current prices for other symbols)
                if let Some(limit) = self.symbol_limits.get(&sid) {
                    let approx_price = limit.max_notional / limit.max_long.max(1) as f64;
                    total_notional += (pos.abs() as f64) * approx_price;
                }
            }
        }

        // Check total positions
        if total_positions > self.max_total_positions {
            return Err(RiskViolation::PortfolioLimitBreached(format!(
                "Total positions {} exceeds max {}",
                total_positions, self.max_total_positions
            )));
        }

        // Check total notional
        if total_notional > self.max_portfolio_notional {
            return Err(RiskViolation::NotionalExceeded(format!(
                "Total notional {} exceeds max {}",
                total_notional, self.max_portfolio_notional
            )));
        }

        // Check concentration risk
        let position_notional = (new_pos.abs() as f64) * price;
        if total_notional > 0.0 {
            let concentration = position_notional / total_notional;
            if concentration > self.max_concentration_pct {
                return Err(RiskViolation::ConcentrationRisk(format!(
                    "Concentration {:.2}% exceeds max {:.2}%",
                    concentration * 100.0,
                    self.max_concentration_pct * 100.0
                )));
            }
        }

        Ok(())
    }

    /// Get total portfolio notional (approximate)
    pub fn get_total_notional(&self) -> f64 {
        let mut total = 0.0;
        for (&sid, &pos) in &self.current_positions {
            if let Some(limit) = self.symbol_limits.get(&sid) {
                let approx_price = limit.max_notional / limit.max_long.max(1) as f64;
                total += (pos.abs() as f64) * approx_price;
            }
        }
        total
    }

    /// Get number of symbols with open positions
    pub fn get_position_count(&self) -> usize {
        self.current_positions.values().filter(|&&p| p != 0).count()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_check_order_within_limits() {
        let mut limits = RiskLimits::new(1_000_000.0, 10_000, 0.5);

        limits.add_symbol_limit(PositionLimit {
            symbol_id: 1,
            max_long: 1000,
            max_short: 1000,
            max_notional: 100_000.0,
        });

        // Should pass: buying 100 shares
        let result = limits.check_order(1, Side::Buy, 100, 100.0);
        assert!(result.is_ok());
    }

    #[test]
    fn test_check_order_exceeds_long_limit() {
        let mut limits = RiskLimits::new(1_000_000.0, 10_000, 0.5);

        limits.add_symbol_limit(PositionLimit {
            symbol_id: 1,
            max_long: 100,
            max_short: 100,
            max_notional: 100_000.0,
        });

        // Try to buy 150 shares (exceeds max_long of 100)
        let result = limits.check_order(1, Side::Buy, 150, 100.0);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            RiskViolation::SymbolLimitBreached(_)
        ));
    }

    #[test]
    fn test_check_order_exceeds_short_limit() {
        let mut limits = RiskLimits::new(1_000_000.0, 10_000, 0.5);

        limits.add_symbol_limit(PositionLimit {
            symbol_id: 1,
            max_long: 100,
            max_short: 50,
            max_notional: 100_000.0,
        });

        // Try to sell 75 shares (exceeds max_short of 50)
        let result = limits.check_order(1, Side::Sell, 75, 100.0);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            RiskViolation::SymbolLimitBreached(_)
        ));
    }

    #[test]
    fn test_check_order_exceeds_notional() {
        let mut limits = RiskLimits::new(1_000_000.0, 10_000, 0.5);

        limits.add_symbol_limit(PositionLimit {
            symbol_id: 1,
            max_long: 1000,
            max_short: 1000,
            max_notional: 10_000.0, // $10k max
        });

        // Try to buy 200 shares @ $100 = $20k notional (exceeds $10k)
        let result = limits.check_order(1, Side::Buy, 200, 100.0);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            RiskViolation::NotionalExceeded(_)
        ));
    }

    #[test]
    fn test_position_updates() {
        let mut limits = RiskLimits::new(1_000_000.0, 10_000, 0.5);

        limits.update_position(1, 100);
        assert_eq!(limits.get_position(1), 100);

        limits.update_position(1, -50);
        assert_eq!(limits.get_position(1), -50);

        assert_eq!(limits.get_position(999), 0); // Unknown symbol
    }

    #[test]
    fn test_incremental_position_building() {
        // Use higher concentration limit to avoid failing on concentration risk
        let mut limits = RiskLimits::new(1_000_000.0, 10_000, 1.0); // 100% concentration allowed

        limits.add_symbol_limit(PositionLimit {
            symbol_id: 1,
            max_long: 500,
            max_short: 500,
            max_notional: 100_000.0,
        });

        // Build position incrementally
        limits.check_order(1, Side::Buy, 100, 100.0).unwrap();
        limits.update_position(1, 100);

        limits.check_order(1, Side::Buy, 200, 100.0).unwrap();
        limits.update_position(1, 300);

        limits.check_order(1, Side::Buy, 100, 100.0).unwrap();
        limits.update_position(1, 400);

        // This should fail (400 + 150 = 550 > 500 max)
        let result = limits.check_order(1, Side::Buy, 150, 100.0);
        assert!(result.is_err());
    }
}
