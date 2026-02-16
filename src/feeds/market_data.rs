//! Market Data Feed
//!
//! WebSocket feed for real-time market data with automatic reconnection.

use crate::engine::{hash_symbol, now_ns, MarketPacket};
use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::time::sleep;
use tokio_tungstenite::{connect_async, tungstenite::Message};

// ---------------------------------------------------------------------------
// Market Data Message Types
// ---------------------------------------------------------------------------

#[allow(dead_code)]
#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "T")]
enum MarketDataMessage {
    #[serde(rename = "t")]
    Trade(TradeMessage),
    #[serde(rename = "q")]
    Quote(QuoteMessage),
    #[serde(rename = "b")]
    Bar(BarMessage),
}

#[derive(Debug, Deserialize, Serialize)]
struct TradeMessage {
    #[serde(rename = "S")]
    symbol: String,
    #[serde(rename = "p")]
    price: f64,
    #[serde(rename = "s")]
    size: u64,
    #[serde(rename = "t")]
    timestamp: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct QuoteMessage {
    #[serde(rename = "S")]
    symbol: String,
    #[serde(rename = "bp")]
    bid_price: f64,
    #[serde(rename = "ap")]
    ask_price: f64,
    #[serde(rename = "t")]
    timestamp: String,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize, Serialize)]
struct BarMessage {
    #[serde(rename = "S")]
    symbol: String,
    #[serde(rename = "c")]
    close: f64,
    #[serde(rename = "v")]
    volume: u64,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct SubscribeRequest {
    action: String,
    trades: Option<Vec<String>>,
    quotes: Option<Vec<String>>,
    bars: Option<Vec<String>>,
}

// ---------------------------------------------------------------------------
// Market Data Feed
// ---------------------------------------------------------------------------

/// WebSocket market data feed with automatic reconnection
pub struct MarketDataFeed {
    ws_url: String,
    api_key: String,
    symbols: Vec<String>,
    heartbeat_interval_ms: u64,
    max_reconnect_delay_secs: u64,
    packet_tx: mpsc::Sender<MarketPacket>,
}

impl MarketDataFeed {
    /// Create a new market data feed
    pub fn new(
        ws_url: String,
        api_key: String,
        symbols: Vec<String>,
        heartbeat_interval_ms: u64,
        max_reconnect_delay_secs: u64,
        packet_tx: mpsc::Sender<MarketPacket>,
    ) -> Self {
        Self {
            ws_url,
            api_key,
            symbols,
            heartbeat_interval_ms,
            max_reconnect_delay_secs,
            packet_tx,
        }
    }

    /// Connect to the WebSocket feed
    pub async fn connect(&mut self) -> Result<()> {
        let mut reconnect_delay = 1u64;

        loop {
            log::info!("Connecting to market data feed: {}", self.ws_url);

            match self.connect_once().await {
                Ok(_) => {
                    log::info!("Market data feed disconnected normally");
                    reconnect_delay = 1; // Reset delay on successful connection
                }
                Err(e) => {
                    log::error!("Market data feed error: {}", e);
                }
            }

            // Exponential backoff: 1s, 2s, 4s, 8s, ..., max 60s
            let delay = reconnect_delay.min(self.max_reconnect_delay_secs);
            log::info!("Reconnecting in {} seconds...", delay);
            sleep(Duration::from_secs(delay)).await;

            reconnect_delay = (reconnect_delay * 2).min(self.max_reconnect_delay_secs);
        }
    }

    /// Single connection attempt
    async fn connect_once(&mut self) -> Result<()> {
        let (ws_stream, _) = connect_async(&self.ws_url)
            .await
            .context("Failed to connect to WebSocket")?;

        log::info!("WebSocket connected");

        let (mut write, mut read) = ws_stream.split();

        // Authenticate (if needed, depends on the WebSocket API)
        let auth_msg = serde_json::json!({
            "action": "auth",
            "key": self.api_key,
        });
        write
            .send(Message::Text(auth_msg.to_string()))
            .await
            .context("Failed to send auth message")?;

        // Subscribe to symbols
        let subscribe_msg = serde_json::json!({
            "action": "subscribe",
            "trades": self.symbols,
            "quotes": self.symbols,
        });
        write
            .send(Message::Text(subscribe_msg.to_string()))
            .await
            .context("Failed to send subscribe message")?;

        log::info!("Subscribed to symbols: {:?}", self.symbols);

        // Heartbeat monitoring
        let heartbeat_interval = Duration::from_millis(self.heartbeat_interval_ms);
        let mut last_message = tokio::time::Instant::now();

        loop {
            tokio::select! {
                msg = read.next() => {
                    match msg {
                        Some(Ok(Message::Text(text))) => {
                            last_message = tokio::time::Instant::now();
                            if let Err(e) = self.handle_message(&text).await {
                                log::warn!("Failed to handle message: {}", e);
                            }
                        }
                        Some(Ok(Message::Ping(_))) => {
                            last_message = tokio::time::Instant::now();
                        }
                        Some(Ok(Message::Close(_))) => {
                            log::info!("WebSocket closed by server");
                            break;
                        }
                        Some(Err(e)) => {
                            log::error!("WebSocket error: {}", e);
                            break;
                        }
                        None => {
                            log::warn!("WebSocket stream ended");
                            break;
                        }
                        _ => {}
                    }
                }
                _ = sleep(heartbeat_interval) => {
                    if last_message.elapsed() > heartbeat_interval * 2 {
                        log::warn!("Heartbeat timeout, reconnecting...");
                        break;
                    }
                }
            }
        }

        Ok(())
    }

    /// Handle incoming message
    async fn handle_message(&mut self, text: &str) -> Result<()> {
        // Try to parse as array of messages (common for market data feeds)
        if let Ok(messages) = serde_json::from_str::<Vec<serde_json::Value>>(text) {
            for msg in messages {
                self.process_message(&msg).await?;
            }
        } else if let Ok(msg) = serde_json::from_str::<serde_json::Value>(text) {
            self.process_message(&msg).await?;
        }

        Ok(())
    }

    /// Process a single message
    async fn process_message(&mut self, msg: &serde_json::Value) -> Result<()> {
        // Extract message type
        let msg_type = msg.get("T").and_then(|t| t.as_str());

        match msg_type {
            Some("t") => {
                // Trade message
                if let Ok(trade) = serde_json::from_value::<TradeMessage>(msg.clone()) {
                    self.send_packet_from_trade(&trade).await?;
                }
            }
            Some("q") => {
                // Quote message
                if let Ok(quote) = serde_json::from_value::<QuoteMessage>(msg.clone()) {
                    self.send_packet_from_quote(&quote).await?;
                }
            }
            _ => {
                // Ignore other message types (control messages, etc.)
            }
        }

        Ok(())
    }

    /// Convert trade to MarketPacket and send
    async fn send_packet_from_trade(&mut self, trade: &TradeMessage) -> Result<()> {
        let packet = MarketPacket {
            symbol_id: hash_symbol(&trade.symbol),
            bid: 0.0, // Not available in trade message
            ask: 0.0, // Not available in trade message
            last: trade.price,
            volume: trade.size,
            timestamp_ns: now_ns(),
            vix: 0.0,       // Will be updated from VIX feed separately
            depeg_pct: 0.0, // Will be calculated separately
        };

        self.packet_tx
            .send(packet)
            .await
            .context("Failed to send packet")?;

        Ok(())
    }

    /// Convert quote to MarketPacket and send
    async fn send_packet_from_quote(&mut self, quote: &QuoteMessage) -> Result<()> {
        let packet = MarketPacket {
            symbol_id: hash_symbol(&quote.symbol),
            bid: quote.bid_price,
            ask: quote.ask_price,
            last: (quote.bid_price + quote.ask_price) / 2.0,
            volume: 0,
            timestamp_ns: now_ns(),
            vix: 0.0,
            depeg_pct: 0.0,
        };

        self.packet_tx
            .send(packet)
            .await
            .context("Failed to send packet")?;

        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hash_symbol() {
        let spy_id = hash_symbol("SPY");
        let qqq_id = hash_symbol("QQQ");
        assert_ne!(spy_id, qqq_id);
        assert_eq!(spy_id, hash_symbol("SPY")); // Consistent
    }

    #[test]
    fn test_parse_trade_message() {
        let json = r#"{"T":"t","S":"SPY","p":450.25,"s":100,"t":"2024-01-01T00:00:00Z"}"#;
        let trade: Result<TradeMessage, _> = serde_json::from_str(json);
        assert!(trade.is_ok());
        let trade = trade.unwrap();
        assert_eq!(trade.symbol, "SPY");
        assert_eq!(trade.price, 450.25);
    }

    #[test]
    fn test_parse_quote_message() {
        let json = r#"{"T":"q","S":"SPY","bp":450.00,"ap":450.50,"t":"2024-01-01T00:00:00Z"}"#;
        let quote: Result<QuoteMessage, _> = serde_json::from_str(json);
        assert!(quote.is_ok());
        let quote = quote.unwrap();
        assert_eq!(quote.symbol, "SPY");
        assert_eq!(quote.bid_price, 450.00);
        assert_eq!(quote.ask_price, 450.50);
    }
}
