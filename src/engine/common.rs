//! Common types and utilities shared across all engine modules
//!
//! This module contains the core data structures used by all sleeves:
//! - MarketPacket: Raw market data
//! - AuditRecord/AuditRing: Compliance logging
//! - SharedConfig: Runtime configuration
//! - FillEvent, RejectionEvent: Order execution types

use std::sync::atomic::{AtomicU64, Ordering};

// ---------------------------------------------------------------------------
// Market Data Structures (zero-copy compatible)
// ---------------------------------------------------------------------------

/// Raw market data packet received via UDP multicast.
/// Fixed-size for zero-copy ingestion — no heap allocations.
#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct MarketPacket {
    pub symbol_id: u32,
    pub bid: f64,
    pub ask: f64,
    pub last: f64,
    pub volume: u64,
    pub timestamp_ns: u64,
    pub vix: f64,
    pub depeg_pct: f64,
}

impl Default for MarketPacket {
    fn default() -> Self {
        Self {
            symbol_id: 0,
            bid: 0.0,
            ask: 0.0,
            last: 0.0,
            volume: 0,
            timestamp_ns: 0,
            vix: 0.0,
            depeg_pct: 0.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Audit Logging (binary structs — WORM / Splunk compatible)
// ---------------------------------------------------------------------------

/// Binary audit record emitted for every decision branch.
/// Written to the Audit Ring and forwarded to Splunk.
#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct AuditRecord {
    pub timestamp_ns: u64,
    pub event_type: AuditEventType,
    pub sleeve_id: u8,
    pub signal_value: f64,
    pub position_delta: f64,
    pub risk_flag: u8,
}

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
pub enum AuditEventType {
    SleeveSignal = 1,
    CrisisProtocol = 2,
    ConfigUpdate = 3,
    Heartbeat = 4,
    CircuitBreaker = 5,
}

// ---------------------------------------------------------------------------
// Audit Ring (fixed-size ring for compliance records)
// ---------------------------------------------------------------------------

pub const AUDIT_RING_SIZE: usize = 4_096;

pub struct AuditRing {
    buffer: Box<[AuditRecord; AUDIT_RING_SIZE]>,
    write_pos: usize,
    count: usize,
}

impl Default for AuditRing {
    fn default() -> Self {
        Self::new()
    }
}

impl AuditRing {
    pub fn new() -> Self {
        let default_record = AuditRecord {
            timestamp_ns: 0,
            event_type: AuditEventType::Heartbeat,
            sleeve_id: 0,
            signal_value: 0.0,
            position_delta: 0.0,
            risk_flag: 0,
        };
        let buffer: Box<[AuditRecord; AUDIT_RING_SIZE]> = vec![default_record; AUDIT_RING_SIZE]
            .into_boxed_slice()
            .try_into()
            .unwrap();
        Self {
            buffer,
            write_pos: 0,
            count: 0,
        }
    }

    /// Append an audit record (lock-free, no allocation).
    pub fn push(&mut self, record: AuditRecord) {
        self.buffer[self.write_pos] = record;
        self.write_pos = (self.write_pos + 1) % AUDIT_RING_SIZE;
        if self.count < AUDIT_RING_SIZE {
            self.count += 1;
        }
    }

    pub fn last(&self) -> Option<&AuditRecord> {
        if self.count == 0 {
            return None;
        }
        let idx = if self.write_pos == 0 {
            AUDIT_RING_SIZE - 1
        } else {
            self.write_pos - 1
        };
        Some(&self.buffer[idx])
    }

    pub fn count(&self) -> usize {
        self.count
    }
}

// ---------------------------------------------------------------------------
// Shared Memory Config Block (written by Python Layer 2, read by Rust)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct SharedConfig {
    pub hedge_ratio: f64,
    pub max_position: f64,
    pub vol_regime_threshold_low: f64,
    pub vol_regime_threshold_high: f64,
    pub quantum_weights: [f64; 8],
    pub circuit_breaker_enabled: bool,
    pub heartbeat_max_lag_us: u64,
}

impl Default for SharedConfig {
    fn default() -> Self {
        Self {
            hedge_ratio: 0.8,
            max_position: 1_000_000.0,
            vol_regime_threshold_low: 15.0,
            vol_regime_threshold_high: 30.0,
            quantum_weights: [0.125; 8],
            circuit_breaker_enabled: true,
            heartbeat_max_lag_us: 100,
        }
    }
}

// ---------------------------------------------------------------------------
// Order Execution Types (for Prop Scaling and other sleeves)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct FillEvent {
    pub timestamp_ns: u64,
    pub account_id: u8,
    pub side: Side,
    pub qty: i32,
    pub price: f64,
    pub is_master: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
pub enum Side {
    Buy = 1,
    Sell = 2,
}

#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct RejectionEvent {
    pub timestamp_ns: u64,
    pub account_id: u8,
    pub reason: RejectionReason,
    pub original_qty: i32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
pub enum RejectionReason {
    RateLimit = 1,
    InsufficientMargin = 2,
    OrderTooLarge = 3,
    Disconnect = 4,
    Other = 5,
}

// ---------------------------------------------------------------------------
// Performance Metrics (for health monitoring)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, Default)]
pub struct PerformanceMetrics {
    pub ticks_processed: u64,
    pub avg_latency_ns: u64,
    pub p99_latency_ns: u64,
    pub rejected_orders: u64,
    pub hedge_operations: u64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
#[repr(u8)]
pub enum HealthStatus {
    Healthy = 0,
    Degraded = 1,
    Critical = 2,
}

#[derive(Clone, Copy, Debug)]
pub struct HealthCheck {
    pub status: HealthStatus,
    pub sync_lag_ns: u32,
    pub active_accounts: u8,
    pub rate_limited_accounts: u8,
}

// ---------------------------------------------------------------------------
// Utility Functions
// ---------------------------------------------------------------------------

/// Hash a symbol string to a u32 ID
pub fn hash_symbol(symbol: &str) -> u32 {
    let mut hash = 0u32;
    for b in symbol.bytes() {
        hash = hash.wrapping_mul(31).wrapping_add(b as u32);
    }
    hash
}

/// Get current time in nanoseconds (monotonic)
pub fn now_ns() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64
}
