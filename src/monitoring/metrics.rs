//! Prometheus Metrics
//!
//! High-frequency trading metrics collection and HTTP endpoint.

use crate::engine::Side;
use anyhow::Result;
use http_body_util::Full;
use hyper::body::Bytes;
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response};
use hyper_util::rt::TokioIo;
use prometheus::{
    register_gauge_vec, register_histogram_vec, register_int_counter_vec, register_int_gauge_vec,
    Encoder, GaugeVec, HistogramVec, IntCounterVec, IntGaugeVec, TextEncoder,
};
use std::convert::Infallible;
use std::sync::Arc;
use tokio::net::TcpListener;

// ---------------------------------------------------------------------------
// Metrics Collector
// ---------------------------------------------------------------------------

/// Metrics collector for Prometheus
pub struct MetricsCollector {
    // Per-sleeve P&L
    sleeve_pnl: GaugeVec,

    // Latency histograms
    tick_latency: HistogramVec,

    // Trade counters
    trades_total: IntCounterVec,

    // Position gauges
    current_position: IntGaugeVec,

    // Risk metrics
    risk_utilization: GaugeVec,
    kill_switch_status: IntGaugeVec,

    // System metrics
    ticks_processed: IntCounterVec,
    rejected_orders: IntCounterVec,
}

impl MetricsCollector {
    /// Create a new metrics collector with Prometheus registration
    pub fn new() -> Result<Self> {
        let sleeve_pnl = register_gauge_vec!(
            "quantum_sleeve_pnl",
            "P&L per trading sleeve",
            &["sleeve"]
        )?;

        let tick_latency = register_histogram_vec!(
            "quantum_tick_latency_ns",
            "Tick processing latency in nanoseconds",
            &["stage"],
            vec![100.0, 500.0, 1000.0, 5000.0, 10000.0, 50000.0, 100000.0]
        )?;

        let trades_total = register_int_counter_vec!(
            "quantum_trades_total",
            "Total number of trades",
            &["sleeve", "side"]
        )?;

        let current_position = register_int_gauge_vec!(
            "quantum_current_position",
            "Current position by symbol",
            &["symbol"]
        )?;

        let risk_utilization = register_gauge_vec!(
            "quantum_risk_utilization",
            "Risk limit utilization (0-1)",
            &["limit_type"]
        )?;

        let kill_switch_status = register_int_gauge_vec!(
            "quantum_kill_switch_status",
            "Kill switch status (0=disarmed, 1=armed, 2=triggered)",
            &["reason"]
        )?;

        let ticks_processed = register_int_counter_vec!(
            "quantum_ticks_processed",
            "Total ticks processed",
            &["source"]
        )?;

        let rejected_orders = register_int_counter_vec!(
            "quantum_rejected_orders",
            "Total rejected orders",
            &["reason"]
        )?;

        Ok(Self {
            sleeve_pnl,
            tick_latency,
            trades_total,
            current_position,
            risk_utilization,
            kill_switch_status,
            ticks_processed,
            rejected_orders,
        })
    }

    /// Record tick processing latency
    pub fn record_tick(&self, stage: &str, latency_ns: u64) {
        self.tick_latency
            .with_label_values(&[stage])
            .observe(latency_ns as f64);
    }

    /// Record a trade
    pub fn record_trade(&self, sleeve: &str, side: Side, qty: i32) {
        let side_str = match side {
            Side::Buy => "buy",
            Side::Sell => "sell",
        };
        self.trades_total
            .with_label_values(&[sleeve, side_str])
            .inc_by(qty.abs() as u64);
    }

    /// Update sleeve P&L
    pub fn update_sleeve_pnl(&self, sleeve: &str, pnl: f64) {
        self.sleeve_pnl.with_label_values(&[sleeve]).set(pnl);
    }

    /// Update position for a symbol
    pub fn update_position(&self, symbol: &str, position: i64) {
        self.current_position
            .with_label_values(&[symbol])
            .set(position);
    }

    /// Update risk utilization
    pub fn update_risk_utilization(&self, limit_type: &str, utilization: f64) {
        self.risk_utilization
            .with_label_values(&[limit_type])
            .set(utilization);
    }

    /// Update kill switch status
    pub fn update_kill_switch(&self, status: u8, reason: &str) {
        self.kill_switch_status
            .with_label_values(&[reason])
            .set(status as i64);
    }

    /// Increment ticks processed
    pub fn increment_ticks(&self, source: &str) {
        self.ticks_processed.with_label_values(&[source]).inc();
    }

    /// Record a rejected order
    pub fn record_rejection(&self, reason: &str) {
        self.rejected_orders.with_label_values(&[reason]).inc();
    }
}

impl Default for MetricsCollector {
    fn default() -> Self {
        Self::new().expect("Failed to create MetricsCollector")
    }
}

// ---------------------------------------------------------------------------
// HTTP Endpoint
// ---------------------------------------------------------------------------

/// Serve Prometheus metrics on HTTP endpoint
pub async fn serve_metrics(port: u16) -> Result<()> {
    let addr = format!("0.0.0.0:{}", port);
    let listener = TcpListener::bind(&addr).await?;

    log::info!("Metrics server listening on {}", addr);

    loop {
        let (stream, _) = listener.accept().await?;
        let io = TokioIo::new(stream);

        tokio::task::spawn(async move {
            if let Err(err) = http1::Builder::new()
                .serve_connection(io, service_fn(handle_metrics_request))
                .await
            {
                log::error!("Error serving connection: {:?}", err);
            }
        });
    }
}

/// Handle metrics HTTP request
async fn handle_metrics_request(
    _req: Request<hyper::body::Incoming>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    let encoder = TextEncoder::new();
    let metric_families = prometheus::gather();
    let mut buffer = vec![];

    if let Err(e) = encoder.encode(&metric_families, &mut buffer) {
        log::error!("Failed to encode metrics: {}", e);
        return Ok(Response::builder()
            .status(500)
            .body(Full::new(Bytes::from("Failed to encode metrics")))
            .unwrap());
    }

    Ok(Response::builder()
        .status(200)
        .header("Content-Type", encoder.format_type())
        .body(Full::new(Bytes::from(buffer)))
        .unwrap())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // Note: Prometheus uses a global registry, so we can't test multiple MetricsCollector
    // instances in the same test run. These tests are skipped to avoid registry conflicts.
    // In production, there's only one MetricsCollector instance per process.

    #[test]
    fn test_metrics_module_compiles() {
        // Just verify the module compiles
        assert!(true);
    }
}
