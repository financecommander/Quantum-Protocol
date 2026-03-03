//! Options Chain Feed
//!
//! Options chain data for tail hedging with OTM filtering.

use crate::engine::common::now_ns;

// ---------------------------------------------------------------------------
// Option Data
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct OptionQuote {
    pub symbol: String,
    pub strike: f64,
    pub expiry_days: u16,
    pub is_put: bool,
    pub bid: f64,
    pub ask: f64,
    pub delta: f64,
    pub vega: f64,
    pub implied_vol: f64,
    pub timestamp_ns: u64,
}

impl OptionQuote {
    /// Check if this option is out-of-the-money relative to the underlying.
    pub fn is_otm(&self, underlying_price: f64) -> bool {
        if self.is_put {
            self.strike < underlying_price
        } else {
            self.strike > underlying_price
        }
    }

    /// Moneyness as a ratio of strike to underlying.
    pub fn moneyness(&self, underlying_price: f64) -> f64 {
        if underlying_price > 0.0 {
            self.strike / underlying_price
        } else {
            0.0
        }
    }
}

// ---------------------------------------------------------------------------
// Options Chain Feed
// ---------------------------------------------------------------------------

pub struct OptionsChainFeed {
    pub quotes: Vec<OptionQuote>,
    pub last_update_ns: u64,
}

impl Default for OptionsChainFeed {
    fn default() -> Self {
        Self::new()
    }
}

impl OptionsChainFeed {
    pub fn new() -> Self {
        Self {
            quotes: Vec::new(),
            last_update_ns: 0,
        }
    }

    /// Update with new option quotes.
    pub fn update(&mut self, quotes: Vec<OptionQuote>) {
        self.quotes = quotes;
        self.last_update_ns = now_ns();
    }

    /// Filter for OTM puts useful for tail hedging.
    pub fn otm_puts(&self, underlying_price: f64, max_moneyness: f64) -> Vec<&OptionQuote> {
        self.quotes
            .iter()
            .filter(|q| {
                q.is_put
                    && q.is_otm(underlying_price)
                    && q.moneyness(underlying_price) >= max_moneyness
            })
            .collect()
    }

    /// Filter for OTM calls (e.g. VIX calls for hedging).
    pub fn otm_calls(&self, underlying_price: f64) -> Vec<&OptionQuote> {
        self.quotes
            .iter()
            .filter(|q| !q.is_put && q.is_otm(underlying_price))
            .collect()
    }

    /// Find the cheapest OTM put by bid/ask midpoint.
    pub fn cheapest_otm_put(&self, underlying_price: f64) -> Option<&OptionQuote> {
        self.otm_puts(underlying_price, 0.0)
            .into_iter()
            .min_by(|a, b| {
                let mid_a = (a.bid + a.ask) / 2.0;
                let mid_b = (b.bid + b.ask) / 2.0;
                mid_a
                    .partial_cmp(&mid_b)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    }

    /// Parse a JSON options chain message.
    pub fn parse_json(json: &str) -> Option<Vec<OptionQuote>> {
        let v: serde_json::Value = serde_json::from_str(json).ok()?;
        let arr = v.as_array()?;

        let mut quotes = Vec::new();
        for item in arr {
            let obj = item.as_object()?;
            quotes.push(OptionQuote {
                symbol: obj.get("symbol")?.as_str()?.to_string(),
                strike: obj.get("strike")?.as_f64()?,
                expiry_days: obj.get("expiry_days")?.as_u64()? as u16,
                is_put: obj.get("is_put")?.as_bool()?,
                bid: obj.get("bid")?.as_f64()?,
                ask: obj.get("ask")?.as_f64()?,
                delta: obj.get("delta").and_then(|v| v.as_f64()).unwrap_or(0.0),
                vega: obj.get("vega").and_then(|v| v.as_f64()).unwrap_or(0.0),
                implied_vol: obj
                    .get("implied_vol")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0),
                timestamp_ns: obj
                    .get("timestamp_ns")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0),
            });
        }
        Some(quotes)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_put(strike: f64, bid: f64, ask: f64) -> OptionQuote {
        OptionQuote {
            symbol: "SPX".to_string(),
            strike,
            expiry_days: 30,
            is_put: true,
            bid,
            ask,
            delta: -0.3,
            vega: 0.5,
            implied_vol: 0.2,
            timestamp_ns: 1000,
        }
    }

    fn make_call(strike: f64) -> OptionQuote {
        OptionQuote {
            symbol: "VIX".to_string(),
            strike,
            expiry_days: 30,
            is_put: false,
            bid: 1.0,
            ask: 1.5,
            delta: 0.4,
            vega: 0.3,
            implied_vol: 0.25,
            timestamp_ns: 1000,
        }
    }

    #[test]
    fn test_option_is_otm_put() {
        let put = make_put(3900.0, 5.0, 6.0);
        assert!(put.is_otm(4000.0));
        assert!(!put.is_otm(3800.0));
    }

    #[test]
    fn test_option_is_otm_call() {
        let call = make_call(25.0);
        assert!(call.is_otm(20.0));
        assert!(!call.is_otm(30.0));
    }

    #[test]
    fn test_moneyness() {
        let put = make_put(3800.0, 5.0, 6.0);
        let m = put.moneyness(4000.0);
        assert!((m - 0.95).abs() < 0.001);
    }

    #[test]
    fn test_moneyness_zero_underlying() {
        let put = make_put(3800.0, 5.0, 6.0);
        assert_eq!(put.moneyness(0.0), 0.0);
    }

    #[test]
    fn test_otm_puts_filter() {
        let mut feed = OptionsChainFeed::new();
        feed.update(vec![
            make_put(3900.0, 5.0, 6.0),
            make_put(4100.0, 10.0, 12.0), // ITM for underlying=4000
            make_put(3800.0, 3.0, 4.0),
        ]);

        let otm = feed.otm_puts(4000.0, 0.0);
        assert_eq!(otm.len(), 2);
    }

    #[test]
    fn test_otm_puts_moneyness_filter() {
        let mut feed = OptionsChainFeed::new();
        feed.update(vec![
            make_put(3900.0, 5.0, 6.0), // 97.5% moneyness
            make_put(3500.0, 1.0, 2.0), // 87.5% moneyness
        ]);

        let otm = feed.otm_puts(4000.0, 0.9);
        assert_eq!(otm.len(), 1);
        assert_eq!(otm[0].strike, 3900.0);
    }

    #[test]
    fn test_otm_calls_filter() {
        let mut feed = OptionsChainFeed::new();
        feed.update(vec![
            make_call(25.0), // OTM if underlying=20
            make_call(15.0), // ITM if underlying=20
        ]);

        let otm = feed.otm_calls(20.0);
        assert_eq!(otm.len(), 1);
        assert_eq!(otm[0].strike, 25.0);
    }

    #[test]
    fn test_cheapest_otm_put() {
        let mut feed = OptionsChainFeed::new();
        feed.update(vec![
            make_put(3900.0, 5.0, 6.0),
            make_put(3800.0, 2.0, 3.0), // Cheaper
        ]);

        let cheapest = feed.cheapest_otm_put(4000.0).unwrap();
        assert_eq!(cheapest.strike, 3800.0);
    }

    #[test]
    fn test_parse_json() {
        let json = r#"[{"symbol":"SPX","strike":3900.0,"expiry_days":30,"is_put":true,"bid":5.0,"ask":6.0,"delta":-0.3,"vega":0.5,"implied_vol":0.2,"timestamp_ns":1000}]"#;
        let quotes = OptionsChainFeed::parse_json(json).unwrap();
        assert_eq!(quotes.len(), 1);
        assert_eq!(quotes[0].strike, 3900.0);
        assert!(quotes[0].is_put);
    }

    #[test]
    fn test_parse_json_invalid() {
        assert!(OptionsChainFeed::parse_json("not json").is_none());
        assert!(OptionsChainFeed::parse_json("42").is_none());
    }

    #[test]
    fn test_update_sets_timestamp() {
        let mut feed = OptionsChainFeed::new();
        assert_eq!(feed.last_update_ns, 0);
        feed.update(vec![make_put(3900.0, 5.0, 6.0)]);
        assert!(feed.last_update_ns > 0);
        assert_eq!(feed.quotes.len(), 1);
    }
}
