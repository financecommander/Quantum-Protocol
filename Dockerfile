# Quantum Protocol Production Dockerfile
# Multi-stage build for optimized binary size

FROM rust:1.75-bookworm AS builder

WORKDIR /app

# Copy manifests
COPY Cargo.toml Cargo.lock* ./

# Copy source code
COPY src/ src/
COPY config/ config/
COPY benches/ benches/

# Build release binary
RUN cargo build --release --bin quantum-engine

# Runtime stage
FROM debian:bookworm-slim

# Install CA certificates for HTTPS connections
RUN apt-get update && \
    apt-get install -y ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /var/log/quantum-protocol /etc/quantum-protocol

# Copy binary from builder
COPY --from=builder /app/target/release/quantum-engine /usr/local/bin/

# Copy configuration
COPY config/ /etc/quantum-protocol/

# Expose ports
# 9090 - Prometheus metrics HTTP endpoint
# 9999/udp - UDP market data ingestion
EXPOSE 9090 9999/udp

# Set environment variables
ENV QP_CONFIG=/etc/quantum-protocol/quantum_protocol.toml
ENV RUST_LOG=info

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9090/metrics || exit 1

# Run as non-root user
RUN useradd -m -u 1000 quantum && \
    chown -R quantum:quantum /var/log/quantum-protocol
USER quantum

CMD ["quantum-engine"]
