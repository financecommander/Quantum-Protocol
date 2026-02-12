//! Engine Module
//!
//! This module contains the core trading engine and all trading sleeves.

pub mod common;
pub use common::*;

pub mod prop_scaling;
pub mod prop_scaling_integration;
pub mod rwa_crypto_hft;
pub mod rwa_crypto_integration;
pub mod tail_hedging;
pub mod tail_hedging_integration;

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

// ---------------------------------------------------------------------------
// SPSC Ring Buffer (fixed-size, lock-free, single producer / single consumer)
// ---------------------------------------------------------------------------

pub const RING_BUFFER_SIZE: usize = 16_384;

pub struct RingBuffer {
    buffer: Box<[MarketPacket; RING_BUFFER_SIZE]>,
    write_pos: AtomicU64,
    read_pos: AtomicU64,
}

impl Default for RingBuffer {
    fn default() -> Self {
        Self::new()
    }
}

impl RingBuffer {
    pub fn new() -> Self {
        // Heap-allocate the large buffer to avoid stack overflow.
        // This allocation happens once at startup, NOT in the hot path.
        let buffer = vec![MarketPacket::default(); RING_BUFFER_SIZE]
            .into_boxed_slice()
            .try_into()
            .unwrap();
        Self {
            buffer,
            write_pos: AtomicU64::new(0),
            read_pos: AtomicU64::new(0),
        }
    }

    /// Push a packet. If the buffer is full the oldest entry is overwritten
    /// (consumer is too slow — drop stale data per design doc).
    pub fn push(&mut self, packet: MarketPacket) {
        let pos = self.write_pos.load(Ordering::Relaxed) as usize % RING_BUFFER_SIZE;
        self.buffer[pos] = packet;
        self.write_pos.fetch_add(1, Ordering::Release);
    }

    /// Pop the next packet. Returns `None` when the ring is empty.
    pub fn pop(&self) -> Option<MarketPacket> {
        let rp = self.read_pos.load(Ordering::Relaxed);
        let wp = self.write_pos.load(Ordering::Acquire);
        if rp >= wp {
            return None;
        }
        let pos = rp as usize % RING_BUFFER_SIZE;
        let pkt = self.buffer[pos];
        self.read_pos.fetch_add(1, Ordering::Release);
        Some(pkt)
    }

    pub fn len(&self) -> usize {
        let wp = self.write_pos.load(Ordering::Relaxed);
        let rp = self.read_pos.load(Ordering::Relaxed);
        (wp - rp) as usize
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

// ---------------------------------------------------------------------------
// Crisis Protocols (v9.3)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum CrisisState {
    Normal,
    SmartBunker,
    SurgicalSniper,
}

/// Evaluate crisis state from current market data. No allocations.
pub fn evaluate_crisis(packet: &MarketPacket) -> CrisisState {
    if packet.vix > 45.0 {
        CrisisState::SmartBunker
    } else if packet.depeg_pct > 5.0 {
        CrisisState::SurgicalSniper
    } else {
        CrisisState::Normal
    }
}

// ---------------------------------------------------------------------------
// Sleeve 1: Treasury Basis Arbitrage
// ---------------------------------------------------------------------------

/// Treasury basis signal: spot vs. futures spread.
/// Returns a signal in [-1.0, 1.0]. No allocations.
pub fn sleeve_treasury_basis(packet: &MarketPacket, config: &SharedConfig) -> f64 {
    let spread = packet.ask - packet.bid;
    let fair_value = packet.last * config.hedge_ratio;

    (spread - fair_value * 0.001).clamp(-1.0, 1.0)
}

// ---------------------------------------------------------------------------
// Sleeve 2: Vol Regime
// ---------------------------------------------------------------------------

/// Volatility regime classification.
/// Returns:
///   -1.0  => low-vol (risk-on, go long)
///    0.0  => neutral
///    1.0  => high-vol (risk-off, reduce exposure)
///
/// Uses VIX thresholds from SharedConfig. No allocations.
pub fn sleeve_vol_regime(packet: &MarketPacket, config: &SharedConfig) -> f64 {
    if packet.vix < config.vol_regime_threshold_low {
        -1.0 // low vol — risk on
    } else if packet.vix > config.vol_regime_threshold_high {
        1.0 // high vol — risk off
    } else {
        0.0 // neutral
    }
}

// ---------------------------------------------------------------------------
// Engine Core (tick processing)
// ---------------------------------------------------------------------------

pub struct Engine {
    pub ring: RingBuffer,
    pub audit: AuditRing,
    pub config: SharedConfig,
    pub crisis_state: CrisisState,
    pub running: AtomicBool,
    pub ticks_processed: u64,
    pub last_tick_ns: u64,
}

impl Default for Engine {
    fn default() -> Self {
        Self::new()
    }
}

impl Engine {
    pub fn new() -> Self {
        Self {
            ring: RingBuffer::new(),
            audit: AuditRing::new(),
            config: SharedConfig::default(),
            crisis_state: CrisisState::Normal,
            running: AtomicBool::new(true),
            ticks_processed: 0,
            last_tick_ns: 0,
        }
    }

    /// Hot path — process a single tick. NO ALLOCATIONS allowed here.
    pub fn on_tick(&mut self, packet: &MarketPacket) {
        // 1. Crisis evaluation
        let new_crisis = evaluate_crisis(packet);
        if new_crisis != self.crisis_state {
            self.audit.push(AuditRecord {
                timestamp_ns: packet.timestamp_ns,
                event_type: AuditEventType::CrisisProtocol,
                sleeve_id: 0,
                signal_value: packet.vix,
                position_delta: 0.0,
                risk_flag: match new_crisis {
                    CrisisState::SmartBunker => 2,
                    CrisisState::SurgicalSniper => 3,
                    CrisisState::Normal => 0,
                },
            });
            self.crisis_state = new_crisis;
        }

        // 2. In SmartBunker, skip normal sleeve processing (hard pivot to T-Bills)
        if self.crisis_state == CrisisState::SmartBunker {
            self.ticks_processed += 1;
            self.last_tick_ns = packet.timestamp_ns;
            return;
        }

        // 3. Sleeve signals
        let tb_signal = sleeve_treasury_basis(packet, &self.config);
        self.audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::SleeveSignal,
            sleeve_id: 1, // Treasury Basis
            signal_value: tb_signal,
            position_delta: tb_signal * self.config.max_position,
            risk_flag: 0,
        });

        let vol_signal = sleeve_vol_regime(packet, &self.config);
        self.audit.push(AuditRecord {
            timestamp_ns: packet.timestamp_ns,
            event_type: AuditEventType::SleeveSignal,
            sleeve_id: 2, // Vol Regime
            signal_value: vol_signal,
            position_delta: vol_signal * self.config.max_position * 0.5,
            risk_flag: if vol_signal > 0.5 { 1 } else { 0 },
        });

        self.ticks_processed += 1;
        self.last_tick_ns = packet.timestamp_ns;
    }

    /// Ingest raw UDP bytes into a MarketPacket. Minimal copying.
    pub fn parse_udp_packet(buf: &[u8]) -> Option<MarketPacket> {
        if buf.len() < std::mem::size_of::<MarketPacket>() {
            return None;
        }
        // Safety: MarketPacket is repr(C), Copy, and buf length is verified.
        let packet: MarketPacket =
            unsafe { std::ptr::read_unaligned(buf.as_ptr() as *const MarketPacket) };
        Some(packet)
    }
}

// ---------------------------------------------------------------------------
// Tests (included via module)
// ---------------------------------------------------------------------------

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
