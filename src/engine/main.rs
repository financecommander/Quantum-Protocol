//! Quantum Protocol Engine - Binary Entry Point
//!
//! High-frequency trading engine with UDP ingestion, SPSC ring buffer,
//! crisis protocols, and multiple trading sleeves.
//!
//! Golden Rules:
//! - No memory allocation in the hot path (on_tick)
//! - p99 latency < 120µs
//! - FINRA 3110 compliance via binary audit logging

use quantum_protocol::*;
use std::net::UdpSocket;
use std::sync::atomic::Ordering;

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

    // Blocking mode: recv_from will wait until data arrives
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
