//! Prometheus-style Metrics
//!
//! Latency histograms, trade counters, position gauges.
//! Exposes metrics in Prometheus text format for scraping.

use std::sync::atomic::{AtomicU64, Ordering};

// ---------------------------------------------------------------------------
// Metrics Collector
// ---------------------------------------------------------------------------

pub struct MetricsCollector {
    pub ticks_processed: AtomicU64,
    pub trades_executed: AtomicU64,
    pub rejections_total: AtomicU64,
    pub hedge_operations: AtomicU64,
    pub kill_switch_triggers: AtomicU64,
    latency_sum_ns: AtomicU64,
    latency_count: AtomicU64,
    latency_max_ns: AtomicU64,
    position_gauge: AtomicU64,
}

impl Default for MetricsCollector {
    fn default() -> Self {
        Self::new()
    }
}

impl MetricsCollector {
    pub fn new() -> Self {
        Self {
            ticks_processed: AtomicU64::new(0),
            trades_executed: AtomicU64::new(0),
            rejections_total: AtomicU64::new(0),
            hedge_operations: AtomicU64::new(0),
            kill_switch_triggers: AtomicU64::new(0),
            latency_sum_ns: AtomicU64::new(0),
            latency_count: AtomicU64::new(0),
            latency_max_ns: AtomicU64::new(0),
            position_gauge: AtomicU64::new(0),
        }
    }

    pub fn inc_ticks(&self) {
        self.ticks_processed.fetch_add(1, Ordering::Relaxed);
    }

    pub fn inc_trades(&self) {
        self.trades_executed.fetch_add(1, Ordering::Relaxed);
    }

    pub fn inc_rejections(&self) {
        self.rejections_total.fetch_add(1, Ordering::Relaxed);
    }

    pub fn inc_hedges(&self) {
        self.hedge_operations.fetch_add(1, Ordering::Relaxed);
    }

    pub fn inc_kill_switch(&self) {
        self.kill_switch_triggers.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_latency(&self, latency_ns: u64) {
        self.latency_sum_ns.fetch_add(latency_ns, Ordering::Relaxed);
        self.latency_count.fetch_add(1, Ordering::Relaxed);

        // Update max (relaxed CAS loop)
        let mut current = self.latency_max_ns.load(Ordering::Relaxed);
        while latency_ns > current {
            match self.latency_max_ns.compare_exchange_weak(
                current,
                latency_ns,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(c) => current = c,
            }
        }
    }

    pub fn set_position(&self, position: f64) {
        self.position_gauge
            .store(position.to_bits(), Ordering::Relaxed);
    }

    pub fn avg_latency_ns(&self) -> u64 {
        let count = self.latency_count.load(Ordering::Relaxed);
        if count == 0 {
            return 0;
        }
        self.latency_sum_ns.load(Ordering::Relaxed) / count
    }

    pub fn max_latency_ns(&self) -> u64 {
        self.latency_max_ns.load(Ordering::Relaxed)
    }

    /// Render metrics in Prometheus text exposition format.
    pub fn render_prometheus(&self) -> String {
        let position = f64::from_bits(self.position_gauge.load(Ordering::Relaxed));
        format!(
            "# HELP qp_ticks_processed_total Total market ticks processed.\n\
             # TYPE qp_ticks_processed_total counter\n\
             qp_ticks_processed_total {}\n\
             # HELP qp_trades_executed_total Total trades executed.\n\
             # TYPE qp_trades_executed_total counter\n\
             qp_trades_executed_total {}\n\
             # HELP qp_rejections_total Total order rejections.\n\
             # TYPE qp_rejections_total counter\n\
             qp_rejections_total {}\n\
             # HELP qp_hedge_operations_total Total hedge operations.\n\
             # TYPE qp_hedge_operations_total counter\n\
             qp_hedge_operations_total {}\n\
             # HELP qp_kill_switch_triggers_total Total kill switch triggers.\n\
             # TYPE qp_kill_switch_triggers_total counter\n\
             qp_kill_switch_triggers_total {}\n\
             # HELP qp_latency_avg_ns Average tick processing latency in nanoseconds.\n\
             # TYPE qp_latency_avg_ns gauge\n\
             qp_latency_avg_ns {}\n\
             # HELP qp_latency_max_ns Maximum tick processing latency in nanoseconds.\n\
             # TYPE qp_latency_max_ns gauge\n\
             qp_latency_max_ns {}\n\
             # HELP qp_position_total Current aggregate position.\n\
             # TYPE qp_position_total gauge\n\
             qp_position_total {}\n",
            self.ticks_processed.load(Ordering::Relaxed),
            self.trades_executed.load(Ordering::Relaxed),
            self.rejections_total.load(Ordering::Relaxed),
            self.hedge_operations.load(Ordering::Relaxed),
            self.kill_switch_triggers.load(Ordering::Relaxed),
            self.avg_latency_ns(),
            self.max_latency_ns(),
            position,
        )
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_inc_ticks() {
        let m = MetricsCollector::new();
        m.inc_ticks();
        m.inc_ticks();
        assert_eq!(m.ticks_processed.load(Ordering::Relaxed), 2);
    }

    #[test]
    fn test_inc_trades() {
        let m = MetricsCollector::new();
        m.inc_trades();
        assert_eq!(m.trades_executed.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn test_inc_rejections() {
        let m = MetricsCollector::new();
        m.inc_rejections();
        assert_eq!(m.rejections_total.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn test_inc_hedges() {
        let m = MetricsCollector::new();
        m.inc_hedges();
        assert_eq!(m.hedge_operations.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn test_inc_kill_switch() {
        let m = MetricsCollector::new();
        m.inc_kill_switch();
        assert_eq!(m.kill_switch_triggers.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn test_record_latency() {
        let m = MetricsCollector::new();
        m.record_latency(1000);
        m.record_latency(3000);
        assert_eq!(m.avg_latency_ns(), 2000);
        assert_eq!(m.max_latency_ns(), 3000);
    }

    #[test]
    fn test_avg_latency_empty() {
        let m = MetricsCollector::new();
        assert_eq!(m.avg_latency_ns(), 0);
    }

    #[test]
    fn test_set_position() {
        let m = MetricsCollector::new();
        m.set_position(12345.67);
        let stored = f64::from_bits(m.position_gauge.load(Ordering::Relaxed));
        assert!((stored - 12345.67).abs() < 0.01);
    }

    #[test]
    fn test_render_prometheus() {
        let m = MetricsCollector::new();
        m.inc_ticks();
        m.inc_trades();
        m.record_latency(5000);
        m.set_position(100.0);

        let output = m.render_prometheus();
        assert!(output.contains("qp_ticks_processed_total 1"));
        assert!(output.contains("qp_trades_executed_total 1"));
        assert!(output.contains("qp_latency_avg_ns 5000"));
        assert!(output.contains("qp_position_total 100"));
    }

    #[test]
    fn test_render_prometheus_format() {
        let m = MetricsCollector::new();
        let output = m.render_prometheus();
        assert!(output.contains("# HELP"));
        assert!(output.contains("# TYPE"));
        assert!(output.contains("counter"));
        assert!(output.contains("gauge"));
    }

    #[test]
    fn test_max_latency_update() {
        let m = MetricsCollector::new();
        m.record_latency(5000);
        m.record_latency(3000);
        m.record_latency(7000);
        assert_eq!(m.max_latency_ns(), 7000);
    }
}
