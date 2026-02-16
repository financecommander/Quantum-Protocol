//! Quantum Protocol Engine - Binary Entry Point
//!
//! High-frequency trading engine with UDP ingestion, SPSC ring buffer,
//! crisis protocols, and multiple trading sleeves.
//!
//! Golden Rules:
//! - No memory allocation in the hot path (on_tick)
//! - p99 latency < 120µs
//! - FINRA 3110 compliance via binary audit logging

use quantum_protocol::config::{load_config, watch_config};
use quantum_protocol::engine::quantum_engine::QuantumEngine;
use quantum_protocol::engine::MarketPacket;
use quantum_protocol::feeds::MarketDataFeed;
use quantum_protocol::monitoring::serve_metrics;
use std::env;
use tokio::sync::{broadcast, mpsc, watch as tokio_watch};

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    env_logger::init();
    log::info!("Quantum Protocol Engine v0.1.0 starting...");

    // Load configuration
    let config_path =
        env::var("QP_CONFIG").unwrap_or_else(|_| "config/quantum_protocol.toml".to_string());
    let config = match load_config(&config_path) {
        Ok(c) => c,
        Err(e) => {
            log::error!("Failed to load config from {}: {}", config_path, e);
            std::process::exit(1);
        }
    };

    log::info!("Configuration loaded from: {}", config_path);

    // Create channels
    let (market_data_tx, market_data_rx) = mpsc::channel::<MarketPacket>(10000);
    let (config_tx, config_rx) = tokio_watch::channel(config.clone());
    let (shutdown_tx, _shutdown_rx) = broadcast::channel(16);

    // Initialize QuantumEngine
    let mut engine = match QuantumEngine::new(
        config.clone(),
        market_data_rx,
        config_rx,
        shutdown_tx.clone(),
    ) {
        Ok(e) => e,
        Err(e) => {
            log::error!("Failed to initialize QuantumEngine: {}", e);
            std::process::exit(1);
        }
    };

    // Start metrics HTTP server
    let metrics_port = config.engine.metrics_port;
    tokio::spawn(async move {
        log::info!("Starting metrics server on port {}", metrics_port);
        if let Err(e) = serve_metrics(metrics_port).await {
            log::error!("Metrics server error: {}", e);
        }
    });

    // Start config file watcher (hot reload)
    let config_path_clone = config_path.clone();
    tokio::spawn(async move {
        log::info!("Starting config file watcher for: {}", config_path_clone);
        if let Err(e) = watch_config(config_path_clone, config_tx).await {
            log::error!("Config watcher error: {}", e);
        }
    });

    // Start market data feed
    let mut market_feed = MarketDataFeed::new(
        config.feeds.market_data_ws_url.clone(),
        config.feeds.market_data_api_key.clone(),
        config.feeds.symbols.clone(),
        config.feeds.heartbeat_interval_ms,
        config.feeds.reconnect_max_delay_secs,
        market_data_tx.clone(),
    );

    tokio::spawn(async move {
        log::info!("Starting market data feed...");
        if let Err(e) = market_feed.connect().await {
            log::error!("Market data feed error: {}", e);
        }
    });

    // Set up CTRL+C handler
    let shutdown_signal = shutdown_tx.clone();
    tokio::spawn(async move {
        if let Err(e) = tokio::signal::ctrl_c().await {
            log::error!("Failed to listen for CTRL+C: {}", e);
            return;
        }
        log::info!("CTRL+C received, initiating shutdown...");
        let _ = shutdown_signal.send(());
    });

    // Run the main engine
    log::info!("Quantum Engine running. Press CTRL+C to stop.");
    if let Err(e) = engine.run().await {
        log::error!("Engine error: {}", e);
    }

    // Graceful shutdown
    log::info!("Shutting down gracefully...");
    if let Err(e) = engine.shutdown().await {
        log::error!("Shutdown error: {}", e);
    }

    let stats = engine.get_stats();
    log::info!(
        "Engine shutdown complete. Ticks processed: {}",
        stats.ticks_processed
    );
}
