//! Quantum Protocol Engine Library
//!
//! High-frequency trading engine with UDP ingestion, SPSC ring buffer,
//! crisis protocols, and multiple trading sleeves.
//!
//! This library exposes the engine module for use by the binary crate
//! and benchmarks.

pub mod config;
pub mod engine;
pub mod feeds;
pub mod monitoring;
pub mod risk;

// Re-export commonly used types
pub use engine::*;
