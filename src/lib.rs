//! Quantum Protocol Engine Library
//!
//! High-frequency trading engine with UDP ingestion, SPSC ring buffer,
//! crisis protocols, and multiple trading sleeves.
//!
//! This library exposes the engine module for use by the binary crate
//! and benchmarks.

pub mod engine;

// Re-export commonly used types
pub use engine::*;
