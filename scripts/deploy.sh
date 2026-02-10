#!/usr/bin/env bash
# Quantum Protocol - Deploy Engine
# Builds and deploys the Rust engine binary.
#
# Usage: ./scripts/deploy.sh [TARGET_HOST]

set -euo pipefail

TARGET_HOST="${1:-localhost}"

echo "=== Quantum Protocol Engine Deployment ==="
echo "Target: $TARGET_HOST"

# Build release binary
echo "Building release binary..."
cargo build --release

BINARY="target/release/quantum-engine"
if [ ! -f "$BINARY" ]; then
  echo "ERROR: Binary not found at $BINARY"
  exit 1
fi

echo "Binary size: $(du -h "$BINARY" | cut -f1)"

if [ "$TARGET_HOST" = "localhost" ]; then
  echo "Local deployment — binary ready at $BINARY"
  echo "Run with: QP_UDP_ADDR=0.0.0.0:9999 RUST_LOG=info $BINARY"
else
  echo "Deploying to $TARGET_HOST..."
  scp "$BINARY" "$TARGET_HOST":~/quantum-engine
  ssh "$TARGET_HOST" "chmod +x ~/quantum-engine"
  echo "Deployed. Start with: QP_UDP_ADDR=0.0.0.0:9999 RUST_LOG=info ~/quantum-engine"
fi

echo "=== Deployment complete ==="
