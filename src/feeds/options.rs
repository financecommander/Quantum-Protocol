//! Options Feed
//!
//! Real-time option chain data for tail hedging.

use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tokio::sync::mpsc;

// ---------------------------------------------------------------------------
// Option Types
// ---------------------------------------------------------------------------

/// Option quote with Greeks
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OptionQuote {
    pub symbol: String,
    pub underlying: String,
    pub strike: f64,
    pub expiry: DateTime<Utc>,
    pub option_type: OptionType,
    pub bid: f64,
    pub ask: f64,
    pub last: f64,
    pub volume: u64,
    pub open_interest: u64,
    pub implied_volatility: f64,
    pub greeks: OptionGreeks,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum OptionType {
    Call,
    Put,
}

/// Option Greeks
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct OptionGreeks {
    pub delta: f64,
    pub gamma: f64,
    pub theta: f64,
    pub vega: f64,
    pub rho: f64,
}

impl Default for OptionGreeks {
    fn default() -> Self {
        Self {
            delta: 0.0,
            gamma: 0.0,
            theta: 0.0,
            vega: 0.0,
            rho: 0.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Option Chain Feed
// ---------------------------------------------------------------------------

/// Option chain data feed for tail hedging
pub struct OptionChainFeed {
    quote_tx: mpsc::Sender<OptionQuote>,
    /// Cache of current option quotes by symbol
    option_cache: HashMap<String, OptionQuote>,
}

impl OptionChainFeed {
    /// Create a new option chain feed
    pub fn new(quote_tx: mpsc::Sender<OptionQuote>) -> Self {
        Self {
            quote_tx,
            option_cache: HashMap::new(),
        }
    }

    /// Process an option quote update
    pub async fn handle_quote(&mut self, quote: OptionQuote) -> Result<()> {
        // Update cache
        self.option_cache.insert(quote.symbol.clone(), quote.clone());

        // Send to consumers
        self.quote_tx.send(quote).await?;

        Ok(())
    }

    /// Get OTM puts for tail hedging
    /// Returns puts where strike < current_price * (1 - otm_threshold)
    pub fn get_otm_puts(
        &self,
        underlying: &str,
        current_price: f64,
        otm_threshold: f64,
    ) -> Vec<OptionQuote> {
        let strike_threshold = current_price * (1.0 - otm_threshold);

        self.option_cache
            .values()
            .filter(|q| {
                q.underlying == underlying
                    && q.option_type == OptionType::Put
                    && q.strike < strike_threshold
            })
            .cloned()
            .collect()
    }

    /// Get VIX calls for tail hedging
    /// Returns calls where strike > current_vix + strike_offset
    pub fn get_vix_calls(&self, current_vix: f64, strike_offset: f64) -> Vec<OptionQuote> {
        let strike_threshold = current_vix + strike_offset;

        self.option_cache
            .values()
            .filter(|q| {
                q.underlying == "VIX"
                    && q.option_type == OptionType::Call
                    && q.strike > strike_threshold
            })
            .cloned()
            .collect()
    }

    /// Get option quote by symbol
    pub fn get_quote(&self, symbol: &str) -> Option<&OptionQuote> {
        self.option_cache.get(symbol)
    }

    /// Get all quotes for an underlying
    pub fn get_chain(&self, underlying: &str) -> Vec<&OptionQuote> {
        self.option_cache
            .values()
            .filter(|q| q.underlying == underlying)
            .collect()
    }

    /// Get total number of cached quotes
    pub fn cache_size(&self) -> usize {
        self.option_cache.len()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_option(
        symbol: &str,
        underlying: &str,
        strike: f64,
        option_type: OptionType,
    ) -> OptionQuote {
        OptionQuote {
            symbol: symbol.to_string(),
            underlying: underlying.to_string(),
            strike,
            expiry: Utc::now(),
            option_type,
            bid: 1.0,
            ask: 1.1,
            last: 1.05,
            volume: 100,
            open_interest: 1000,
            implied_volatility: 0.25,
            greeks: OptionGreeks::default(),
        }
    }

    #[tokio::test]
    async fn test_option_quote_handling() {
        let (tx, mut rx) = mpsc::channel(10);
        let mut feed = OptionChainFeed::new(tx);

        let quote = create_test_option("SPY_250101C00450000", "SPY", 450.0, OptionType::Call);

        feed.handle_quote(quote.clone()).await.unwrap();

        // Should receive the quote
        let received = rx.recv().await.unwrap();
        assert_eq!(received.symbol, "SPY_250101C00450000");

        // Should be in cache
        assert_eq!(feed.cache_size(), 1);
        assert!(feed.get_quote("SPY_250101C00450000").is_some());
    }

    #[tokio::test]
    async fn test_get_otm_puts() {
        let (tx, _rx) = mpsc::channel(10);
        let mut feed = OptionChainFeed::new(tx);

        // SPY trading at 450
        let current_price = 450.0;
        let otm_threshold = 0.05; // 5% OTM

        // Add some puts at different strikes
        feed.handle_quote(create_test_option("SPY_P420", "SPY", 420.0, OptionType::Put))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("SPY_P430", "SPY", 430.0, OptionType::Put))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("SPY_P440", "SPY", 440.0, OptionType::Put))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("SPY_C460", "SPY", 460.0, OptionType::Call))
            .await
            .unwrap();

        let otm_puts = feed.get_otm_puts("SPY", current_price, otm_threshold);

        // Strike threshold = 450 * 0.95 = 427.5
        // Should get 420 put only
        assert_eq!(otm_puts.len(), 1);
        assert_eq!(otm_puts[0].strike, 420.0);
    }

    #[tokio::test]
    async fn test_get_vix_calls() {
        let (tx, _rx) = mpsc::channel(10);
        let mut feed = OptionChainFeed::new(tx);

        let current_vix = 20.0;
        let strike_offset = 10.0;

        // Add VIX calls at different strikes
        feed.handle_quote(create_test_option("VIX_C25", "VIX", 25.0, OptionType::Call))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("VIX_C30", "VIX", 30.0, OptionType::Call))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("VIX_C35", "VIX", 35.0, OptionType::Call))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("VIX_P15", "VIX", 15.0, OptionType::Put))
            .await
            .unwrap();

        let vix_calls = feed.get_vix_calls(current_vix, strike_offset);

        // Strike threshold = 20 + 10 = 30
        // Should get 30 and 35 calls (strike > 30 means strictly greater, so 30.0 is NOT included)
        // Actually, the function uses > not >=, so we need strikes > 30
        // That means only 35 should match
        assert_eq!(vix_calls.len(), 1);
        assert_eq!(vix_calls[0].strike, 35.0);
    }

    #[tokio::test]
    async fn test_get_chain() {
        let (tx, _rx) = mpsc::channel(10);
        let mut feed = OptionChainFeed::new(tx);

        // Add options for different underlyings
        feed.handle_quote(create_test_option("SPY_C450", "SPY", 450.0, OptionType::Call))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("SPY_P440", "SPY", 440.0, OptionType::Put))
            .await
            .unwrap();
        feed.handle_quote(create_test_option("QQQ_C380", "QQQ", 380.0, OptionType::Call))
            .await
            .unwrap();

        let spy_chain = feed.get_chain("SPY");
        assert_eq!(spy_chain.len(), 2);

        let qqq_chain = feed.get_chain("QQQ");
        assert_eq!(qqq_chain.len(), 1);
    }
}
