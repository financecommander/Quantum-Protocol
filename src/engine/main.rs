//! Quantum Protocol Engine - Layer 1 "Iron Core"
//!
//! High-frequency trading engine with UDP ingestion, SPSC ring buffer,
//! crisis protocols, and multiple trading sleeves.
//!
//! Golden Rules:
//! - No memory allocation in the hot path (on_tick)
//! - p99 latency < 120µs
//! - FINRA 3110 compliance via binary audit logging

use std::net::UdpSocket;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

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

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

fn main() {
    env_logger::init();
    log::info!("Quantum Protocol Engine v0.1.0 starting...");

    let mut engine = Engine::new();

    // Bind UDP socket for market data ingestion
    let bind_addr = std::env::var("QP_UDP_ADDR").unwrap_or_else(|_| "0.0.0.0:9999".to_string());
    let socket = match UdpSocket::bind(&bind_addr) {
        Ok(s) => {
            log::info!("Listening on {}", bind_addr);
            s
        }
        Err(e) => {
            log::error!("Failed to bind UDP socket on {}: {}", bind_addr, e);
            std::process::exit(1);
        }
    };

    // Set non-blocking for graceful shutdown support
    if let Err(e) = socket.set_nonblocking(false) {
        log::warn!("Could not set socket blocking mode: {}", e);
    }

    let mut buf = [0u8; 2048];

    log::info!("Engine running. Waiting for market data...");

    while engine.running.load(Ordering::Relaxed) {
        match socket.recv_from(&mut buf) {
            Ok((n, _src)) => {
                if let Some(packet) = Engine::parse_udp_packet(&buf[..n]) {
                    engine.ring.push(packet);
                    engine.on_tick(&packet);
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // Non-blocking: no data yet
                continue;
            }
            Err(e) => {
                log::error!("UDP recv error: {}", e);
            }
        }
    }

    log::info!(
        "Engine shutdown. Ticks processed: {}",
        engine.ticks_processed
    );
}
