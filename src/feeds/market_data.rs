//! WebSocket Market Data Feed
//!
//! Connects to a WebSocket endpoint for real-time market data,
//! with exponential backoff reconnection and heartbeat monitoring.

use crate::engine::common::{hash_symbol, now_ns, MarketPacket};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message;

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct MarketDataFeedConfig {
    pub ws_url: String,
    pub api_key: String,
    pub symbols: Vec<String>,
    pub heartbeat_interval_ms: u64,
    pub reconnect_max_delay_ms: u64,
}

impl Default for MarketDataFeedConfig {
    fn default() -> Self {
        Self {
            ws_url: "wss://feed.example.com/v1/market".to_string(),
            api_key: String::new(),
            symbols: Vec::new(),
            heartbeat_interval_ms: 1000,
            reconnect_max_delay_ms: 60_000,
        }
    }
}

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

pub struct MarketDataFeed {
    pub config: MarketDataFeedConfig,
    pub last_heartbeat_ns: u64,
    pub reconnect_attempts: u32,
    pub connected: bool,
}

impl MarketDataFeed {
    pub fn new(config: MarketDataFeedConfig) -> Self {
        Self {
            config,
            last_heartbeat_ns: 0,
            reconnect_attempts: 0,
            connected: false,
        }
    }

    /// Calculate reconnection delay with exponential backoff.
    /// Sequence: 1s, 2s, 4s, 8s, ... up to max.
    pub fn reconnect_delay_ms(&self) -> u64 {
        let base = 1000u64;
        let delay = base.saturating_mul(1u64 << self.reconnect_attempts.min(6));
        delay.min(self.config.reconnect_max_delay_ms)
    }

    /// Parse a JSON market data message into a `MarketPacket`.
    pub fn parse_json_message(json: &str) -> Option<MarketPacket> {
        let v: serde_json::Value = serde_json::from_str(json).ok()?;
        let obj = v.as_object()?;

        let symbol = obj.get("symbol")?.as_str()?;
        let symbol_id = hash_symbol(symbol);

        Some(MarketPacket {
            symbol_id,
            bid: obj.get("bid")?.as_f64()?,
            ask: obj.get("ask")?.as_f64()?,
            last: obj.get("last")?.as_f64()?,
            volume: obj.get("volume")?.as_u64()?,
            timestamp_ns: obj
                .get("timestamp_ns")
                .and_then(|v| v.as_u64())
                .unwrap_or_else(now_ns),
            vix: obj.get("vix").and_then(|v| v.as_f64()).unwrap_or(0.0),
            depeg_pct: obj.get("depeg_pct").and_then(|v| v.as_f64()).unwrap_or(0.0),
        })
    }

    /// Check if heartbeat is stale (no data for longer than interval).
    pub fn is_heartbeat_stale(&self) -> bool {
        if self.last_heartbeat_ns == 0 {
            return false;
        }
        let elapsed_ms = (now_ns() - self.last_heartbeat_ns) / 1_000_000;
        elapsed_ms > self.config.heartbeat_interval_ms * 3
    }

    /// Reset reconnection state after successful connection.
    pub fn on_connected(&mut self) {
        self.connected = true;
        self.reconnect_attempts = 0;
        self.last_heartbeat_ns = now_ns();
    }

    /// Mark disconnected and increment reconnect counter.
    pub fn on_disconnected(&mut self) {
        self.connected = false;
        self.reconnect_attempts = self.reconnect_attempts.saturating_add(1);
    }

    /// Record a heartbeat from incoming data.
    pub fn record_heartbeat(&mut self) {
        self.last_heartbeat_ns = now_ns();
    }

    /// Connect to the WebSocket feed and send parsed packets through the channel.
    pub async fn run(
        &mut self,
        tx: mpsc::Sender<MarketPacket>,
        mut shutdown: tokio::sync::broadcast::Receiver<()>,
    ) {
        loop {
            match tokio_tungstenite::connect_async(&self.config.ws_url).await {
                Ok((ws_stream, _)) => {
                    self.on_connected();
                    log::info!("Market data feed connected to {}", self.config.ws_url);

                    let (mut _write, mut read) = ws_stream.split();

                    loop {
                        tokio::select! {
                            msg = read.next() => {
                                match msg {
                                    Some(Ok(Message::Text(text))) => {
                                        self.record_heartbeat();
                                        if let Some(packet) = Self::parse_json_message(&text) {
                                            if tx.send(packet).await.is_err() {
                                                log::error!("Market data channel closed");
                                                return;
                                            }
                                        }
                                    }
                                    Some(Ok(Message::Ping(data))) => {
                                        self.record_heartbeat();
                                        let _ = _write.send(Message::Pong(data)).await;
                                    }
                                    Some(Err(e)) => {
                                        log::warn!("WebSocket error: {e}");
                                        break;
                                    }
                                    None => {
                                        log::warn!("WebSocket stream ended");
                                        break;
                                    }
                                    _ => {}
                                }
                            }
                            _ = shutdown.recv() => {
                                log::info!("Market data feed shutting down");
                                return;
                            }
                        }
                    }
                }
                Err(e) => {
                    log::warn!("WebSocket connect failed: {e}");
                }
            }

            self.on_disconnected();
            let delay = self.reconnect_delay_ms();
            log::info!(
                "Reconnecting in {delay}ms (attempt {})",
                self.reconnect_attempts
            );

            tokio::select! {
                _ = tokio::time::sleep(std::time::Duration::from_millis(delay)) => {}
                _ = shutdown.recv() => {
                    log::info!("Market data feed shutting down during reconnect");
                    return;
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_json_message_valid() {
        let json = r#"{"symbol":"BTC-USD","bid":50000.0,"ask":50100.0,"last":50050.0,"volume":1000,"timestamp_ns":123456789,"vix":18.0,"depeg_pct":0.0}"#;
        let packet = MarketDataFeed::parse_json_message(json).unwrap();
        assert_eq!(packet.symbol_id, hash_symbol("BTC-USD"));
        assert_eq!(packet.bid, 50000.0);
        assert_eq!(packet.ask, 50100.0);
        assert_eq!(packet.last, 50050.0);
        assert_eq!(packet.volume, 1000);
        assert_eq!(packet.vix, 18.0);
    }

    #[test]
    fn test_parse_json_message_missing_optional() {
        let json = r#"{"symbol":"ETH-USD","bid":3000.0,"ask":3010.0,"last":3005.0,"volume":500}"#;
        let packet = MarketDataFeed::parse_json_message(json).unwrap();
        assert_eq!(packet.symbol_id, hash_symbol("ETH-USD"));
        assert_eq!(packet.vix, 0.0);
        assert_eq!(packet.depeg_pct, 0.0);
    }

    #[test]
    fn test_parse_json_message_invalid() {
        assert!(MarketDataFeed::parse_json_message("not json").is_none());
        assert!(MarketDataFeed::parse_json_message("{}").is_none());
    }

    #[test]
    fn test_parse_json_message_missing_required() {
        let json = r#"{"symbol":"BTC-USD","bid":50000.0}"#;
        assert!(MarketDataFeed::parse_json_message(json).is_none());
    }

    #[test]
    fn test_reconnect_delay_exponential_backoff() {
        let mut feed = MarketDataFeed::new(MarketDataFeedConfig::default());
        feed.reconnect_attempts = 0;
        assert_eq!(feed.reconnect_delay_ms(), 1000);

        feed.reconnect_attempts = 1;
        assert_eq!(feed.reconnect_delay_ms(), 2000);

        feed.reconnect_attempts = 2;
        assert_eq!(feed.reconnect_delay_ms(), 4000);

        feed.reconnect_attempts = 3;
        assert_eq!(feed.reconnect_delay_ms(), 8000);
    }

    #[test]
    fn test_reconnect_delay_max_cap() {
        let mut feed = MarketDataFeed::new(MarketDataFeedConfig::default());
        feed.reconnect_attempts = 10;
        assert!(feed.reconnect_delay_ms() <= feed.config.reconnect_max_delay_ms);
    }

    #[test]
    fn test_on_connected_resets_state() {
        let mut feed = MarketDataFeed::new(MarketDataFeedConfig::default());
        feed.reconnect_attempts = 5;
        feed.connected = false;
        feed.on_connected();
        assert!(feed.connected);
        assert_eq!(feed.reconnect_attempts, 0);
        assert!(feed.last_heartbeat_ns > 0);
    }

    #[test]
    fn test_on_disconnected() {
        let mut feed = MarketDataFeed::new(MarketDataFeedConfig::default());
        feed.connected = true;
        feed.reconnect_attempts = 2;
        feed.on_disconnected();
        assert!(!feed.connected);
        assert_eq!(feed.reconnect_attempts, 3);
    }

    #[test]
    fn test_heartbeat_stale_fresh() {
        let mut feed = MarketDataFeed::new(MarketDataFeedConfig::default());
        feed.last_heartbeat_ns = 0;
        assert!(!feed.is_heartbeat_stale());
    }

    #[test]
    fn test_heartbeat_stale_recent() {
        let mut feed = MarketDataFeed::new(MarketDataFeedConfig::default());
        feed.record_heartbeat();
        assert!(!feed.is_heartbeat_stale());
    }

    #[test]
    fn test_record_heartbeat() {
        let mut feed = MarketDataFeed::new(MarketDataFeedConfig::default());
        assert_eq!(feed.last_heartbeat_ns, 0);
        feed.record_heartbeat();
        assert!(feed.last_heartbeat_ns > 0);
    }
}
