//! Sleeve 5: Tail Hedging Engine
//!
//! Tail risk protection through:
//! - VIX spike detection
//! - Put option hedging
//! - Volatility regime monitoring
//! - Crisis protocol integration

use super::{AuditEventType, AuditRecord};

// ---------------------------------------------------------------------------
// Hedging Instrument
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
pub enum HedgeInstrument {
    VixCall = 1,
    SpxPut = 2,
    TailFund = 3,
    Treasury = 4,
}

#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct HedgePosition {
    pub instrument: HedgeInstrument,
    pub notional: f64,
    pub strike: f64,
    pub expiry_days: u16,
    pub cost_bps: f64, // Cost in basis points
    pub delta: f64,    // Position delta
    pub vega: f64,     // Position vega
}

impl Default for HedgePosition {
    fn default() -> Self {
        Self {
            instrument: HedgeInstrument::SpxPut,
            notional: 0.0,
            strike: 0.0,
            expiry_days: 0,
            cost_bps: 0.0,
            delta: 0.0,
            vega: 0.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Tail Event Detection
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
pub enum TailRiskLevel {
    Normal = 0,
    Elevated = 1,
    High = 2,
    Critical = 3,
}

#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct TailEvent {
    pub timestamp_ns: u64,
    pub risk_level: TailRiskLevel,
    pub vix_level: f64,
    pub vix_change_pct: f64,
    pub market_drop_pct: f64,
    pub triggered_hedges: u8,
}

impl Default for TailEvent {
    fn default() -> Self {
        Self {
            timestamp_ns: 0,
            risk_level: TailRiskLevel::Normal,
            vix_level: 0.0,
            vix_change_pct: 0.0,
            market_drop_pct: 0.0,
            triggered_hedges: 0,
        }
    }
}

// ---------------------------------------------------------------------------
// Tail Hedging Engine
// ---------------------------------------------------------------------------

pub struct TailHedgingEngine {
    pub positions: [HedgePosition; 8], // Up to 8 hedge positions
    pub events: [TailEvent; 32],       // Recent tail events
    pub num_positions: usize,
    pub num_events: usize,
    pub current_risk_level: TailRiskLevel,
    pub total_hedge_cost: f64,
    pub total_hedge_pnl: f64,
    pub vix_ema: f64, // Exponential moving average of VIX
    pub last_vix: f64,
}

impl Default for TailHedgingEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl TailHedgingEngine {
    pub const MAX_POSITIONS: usize = 8;
    pub const MAX_EVENTS: usize = 32;
    pub const VIX_THRESHOLD_ELEVATED: f64 = 20.0;
    pub const VIX_THRESHOLD_HIGH: f64 = 30.0;
    pub const VIX_THRESHOLD_CRITICAL: f64 = 45.0;
    pub const VIX_SPIKE_PCT: f64 = 20.0; // 20% VIX increase
    pub const EMA_ALPHA: f64 = 0.1; // EMA smoothing factor

    pub fn new() -> Self {
        Self {
            positions: [HedgePosition::default(); 8],
            events: [TailEvent::default(); 32],
            num_positions: 0,
            num_events: 0,
            current_risk_level: TailRiskLevel::Normal,
            total_hedge_cost: 0.0,
            total_hedge_pnl: 0.0,
            vix_ema: 15.0, // Initialize to typical low-vol level
            last_vix: 15.0,
        }
    }

    /// Update VIX and detect tail risk
    pub fn update_vix(&mut self, vix: f64, timestamp_ns: u64) -> Option<TailEvent> {
        // Update EMA
        self.vix_ema = Self::EMA_ALPHA * vix + (1.0 - Self::EMA_ALPHA) * self.vix_ema;

        // Calculate VIX change
        let vix_change_pct = if self.last_vix > 0.0 {
            ((vix - self.last_vix) / self.last_vix) * 100.0
        } else {
            0.0
        };

        // Determine risk level
        let risk_level = self.classify_risk(vix);
        let prev_risk_level = self.current_risk_level;
        self.current_risk_level = risk_level;

        self.last_vix = vix;

        // Detect tail event (VIX spike or critical level)
        if vix_change_pct > Self::VIX_SPIKE_PCT || risk_level == TailRiskLevel::Critical {
            let event = TailEvent {
                timestamp_ns,
                risk_level,
                vix_level: vix,
                vix_change_pct,
                market_drop_pct: 0.0, // Would be calculated from market data
                triggered_hedges: 0,
            };

            if self.num_events < Self::MAX_EVENTS {
                self.events[self.num_events] = event;
                self.num_events += 1;
            }

            // Escalation from lower to higher risk
            if risk_level as u8 > prev_risk_level as u8 {
                return Some(event);
            }
        }

        None
    }

    /// Classify risk level based on VIX
    fn classify_risk(&self, vix: f64) -> TailRiskLevel {
        if vix >= Self::VIX_THRESHOLD_CRITICAL {
            TailRiskLevel::Critical
        } else if vix >= Self::VIX_THRESHOLD_HIGH {
            TailRiskLevel::High
        } else if vix >= Self::VIX_THRESHOLD_ELEVATED {
            TailRiskLevel::Elevated
        } else {
            TailRiskLevel::Normal
        }
    }

    /// Add a hedge position
    pub fn add_hedge(&mut self, position: HedgePosition) -> bool {
        if self.num_positions >= Self::MAX_POSITIONS {
            return false;
        }

        self.positions[self.num_positions] = position;
        self.num_positions += 1;
        self.total_hedge_cost += position.cost_bps;

        true
    }

    /// Remove expired hedges
    pub fn remove_expired_hedges(&mut self) -> usize {
        let mut write_idx = 0;
        let mut removed = 0;

        for read_idx in 0..self.num_positions {
            let pos = &self.positions[read_idx];

            if pos.expiry_days > 0 {
                if write_idx != read_idx {
                    self.positions[write_idx] = *pos;
                }
                write_idx += 1;
            } else {
                removed += 1;
            }
        }

        self.num_positions = write_idx;
        removed
    }

    /// Calculate recommended hedge size based on risk level
    pub fn recommended_hedge_notional(&self, portfolio_value: f64) -> f64 {
        let hedge_pct = match self.current_risk_level {
            TailRiskLevel::Normal => 0.01,   // 1% of portfolio
            TailRiskLevel::Elevated => 0.03, // 3% of portfolio
            TailRiskLevel::High => 0.05,     // 5% of portfolio
            TailRiskLevel::Critical => 0.10, // 10% of portfolio
        };

        portfolio_value * hedge_pct
    }

    /// Calculate total portfolio delta from hedges
    pub fn total_delta(&self) -> f64 {
        let mut delta = 0.0;
        for i in 0..self.num_positions {
            delta += self.positions[i].delta;
        }
        delta
    }

    /// Calculate total portfolio vega from hedges
    pub fn total_vega(&self) -> f64 {
        let mut vega = 0.0;
        for i in 0..self.num_positions {
            vega += self.positions[i].vega;
        }
        vega
    }

    /// Rebalance hedges based on current risk level
    pub fn rebalance_hedges(&mut self, portfolio_value: f64) -> Vec<HedgePosition> {
        let recommended = self.recommended_hedge_notional(portfolio_value);
        let current_notional: f64 = self.positions[..self.num_positions]
            .iter()
            .map(|p| p.notional)
            .sum();

        let mut actions = Vec::new();

        if (current_notional - recommended).abs() > recommended * 0.1 {
            // Need to rebalance (>10% deviation)
            if current_notional < recommended {
                // Add hedges
                let new_position = HedgePosition {
                    instrument: HedgeInstrument::SpxPut,
                    notional: recommended - current_notional,
                    strike: 0.0, // Would be calculated from market
                    expiry_days: 30,
                    cost_bps: 50.0,
                    delta: -0.3,
                    vega: 0.5,
                };
                actions.push(new_position);
            }
            // Note: In production, would also handle reducing hedges
        }

        actions
    }

    /// Reset daily statistics
    pub fn reset_daily(&mut self) {
        // Keep positions and risk state, only reset counters
        self.num_events = 0;
    }

    /// Get current statistics
    pub fn get_stats(&self) -> TailHedgeStats {
        TailHedgeStats {
            num_positions: self.num_positions,
            total_hedge_cost: self.total_hedge_cost,
            total_hedge_pnl: self.total_hedge_pnl,
            current_risk_level: self.current_risk_level,
            vix_ema: self.vix_ema,
            total_delta: self.total_delta(),
            total_vega: self.total_vega(),
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct TailHedgeStats {
    pub num_positions: usize,
    pub total_hedge_cost: f64,
    pub total_hedge_pnl: f64,
    pub current_risk_level: TailRiskLevel,
    pub vix_ema: f64,
    pub total_delta: f64,
    pub total_vega: f64,
}

// ---------------------------------------------------------------------------
// Unit Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_update_vix_normal() {
        let mut engine = TailHedgingEngine::new();

        let event = engine.update_vix(18.0, 1000);

        assert!(event.is_none());
        assert_eq!(engine.current_risk_level, TailRiskLevel::Normal);
        assert_eq!(engine.last_vix, 18.0);
    }

    #[test]
    fn test_update_vix_spike() {
        let mut engine = TailHedgingEngine::new();
        engine.last_vix = 15.0;

        // 50% spike triggers event
        let event = engine.update_vix(22.5, 1000);

        assert!(event.is_some());
        if let Some(e) = event {
            assert!(e.vix_change_pct > 20.0);
            assert_eq!(e.risk_level, TailRiskLevel::Elevated);
        }
    }

    #[test]
    fn test_update_vix_critical() {
        let mut engine = TailHedgingEngine::new();

        let event = engine.update_vix(50.0, 1000);

        assert!(event.is_some());
        assert_eq!(engine.current_risk_level, TailRiskLevel::Critical);
    }

    #[test]
    fn test_classify_risk() {
        let engine = TailHedgingEngine::new();

        assert_eq!(engine.classify_risk(15.0), TailRiskLevel::Normal);
        assert_eq!(engine.classify_risk(25.0), TailRiskLevel::Elevated);
        assert_eq!(engine.classify_risk(35.0), TailRiskLevel::High);
        assert_eq!(engine.classify_risk(50.0), TailRiskLevel::Critical);
    }

    #[test]
    fn test_add_hedge() {
        let mut engine = TailHedgingEngine::new();

        let position = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 100_000.0,
            strike: 4000.0,
            expiry_days: 30,
            cost_bps: 50.0,
            delta: -0.3,
            vega: 0.5,
        };

        assert!(engine.add_hedge(position));
        assert_eq!(engine.num_positions, 1);
        assert_eq!(engine.total_hedge_cost, 50.0);
    }

    #[test]
    fn test_add_hedge_max_limit() {
        let mut engine = TailHedgingEngine::new();

        let position = HedgePosition::default();

        // Fill to capacity
        for _ in 0..TailHedgingEngine::MAX_POSITIONS {
            assert!(engine.add_hedge(position));
        }

        // Should fail when full
        assert!(!engine.add_hedge(position));
    }

    #[test]
    fn test_remove_expired_hedges() {
        let mut engine = TailHedgingEngine::new();

        // Add active hedge
        let active = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 100_000.0,
            strike: 4000.0,
            expiry_days: 30,
            cost_bps: 50.0,
            delta: -0.3,
            vega: 0.5,
        };
        engine.add_hedge(active);

        // Add expired hedge
        let expired = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 50_000.0,
            strike: 3900.0,
            expiry_days: 0, // Expired
            cost_bps: 30.0,
            delta: -0.2,
            vega: 0.3,
        };
        engine.add_hedge(expired);

        let removed = engine.remove_expired_hedges();

        assert_eq!(removed, 1);
        assert_eq!(engine.num_positions, 1);
        assert_eq!(engine.positions[0].expiry_days, 30);
    }

    #[test]
    fn test_recommended_hedge_notional() {
        let mut engine = TailHedgingEngine::new();
        let portfolio = 1_000_000.0;

        engine.current_risk_level = TailRiskLevel::Normal;
        assert_eq!(engine.recommended_hedge_notional(portfolio), 10_000.0);

        engine.current_risk_level = TailRiskLevel::Elevated;
        assert_eq!(engine.recommended_hedge_notional(portfolio), 30_000.0);

        engine.current_risk_level = TailRiskLevel::High;
        assert_eq!(engine.recommended_hedge_notional(portfolio), 50_000.0);

        engine.current_risk_level = TailRiskLevel::Critical;
        assert_eq!(engine.recommended_hedge_notional(portfolio), 100_000.0);
    }

    #[test]
    fn test_total_delta() {
        let mut engine = TailHedgingEngine::new();

        let pos1 = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 100_000.0,
            strike: 4000.0,
            expiry_days: 30,
            cost_bps: 50.0,
            delta: -0.3,
            vega: 0.5,
        };

        let pos2 = HedgePosition {
            instrument: HedgeInstrument::VixCall,
            notional: 50_000.0,
            strike: 25.0,
            expiry_days: 15,
            cost_bps: 100.0,
            delta: 0.5,
            vega: 0.8,
        };

        engine.add_hedge(pos1);
        engine.add_hedge(pos2);

        assert_eq!(engine.total_delta(), 0.2); // -0.3 + 0.5
    }

    #[test]
    fn test_total_vega() {
        let mut engine = TailHedgingEngine::new();

        let pos1 = HedgePosition {
            instrument: HedgeInstrument::SpxPut,
            notional: 100_000.0,
            strike: 4000.0,
            expiry_days: 30,
            cost_bps: 50.0,
            delta: -0.3,
            vega: 0.5,
        };

        let pos2 = HedgePosition {
            instrument: HedgeInstrument::VixCall,
            notional: 50_000.0,
            strike: 25.0,
            expiry_days: 15,
            cost_bps: 100.0,
            delta: 0.5,
            vega: 0.8,
        };

        engine.add_hedge(pos1);
        engine.add_hedge(pos2);

        assert_eq!(engine.total_vega(), 1.3); // 0.5 + 0.8
    }

    #[test]
    fn test_rebalance_hedges() {
        let mut engine = TailHedgingEngine::new();
        engine.current_risk_level = TailRiskLevel::High;

        let actions = engine.rebalance_hedges(1_000_000.0);

        // Should recommend adding hedges (current is 0, recommended is 50k)
        assert!(!actions.is_empty());
    }

    #[test]
    fn test_get_stats() {
        let mut engine = TailHedgingEngine::new();
        engine.num_positions = 2;
        engine.total_hedge_cost = 100.0;
        engine.total_hedge_pnl = 50.0;
        engine.current_risk_level = TailRiskLevel::Elevated;

        let stats = engine.get_stats();

        assert_eq!(stats.num_positions, 2);
        assert_eq!(stats.total_hedge_cost, 100.0);
        assert_eq!(stats.total_hedge_pnl, 50.0);
        assert_eq!(stats.current_risk_level, TailRiskLevel::Elevated);
    }
}
