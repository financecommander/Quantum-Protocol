#!/usr/bin/env bash
# Quantum Protocol - Deploy Python Engine
# Deploys the Python engine + dashboard to a target host.
#
# Usage: ./scripts/deploy.sh [TARGET_HOST]

set -euo pipefail

TARGET_HOST="${1:-localhost}"
DEPLOY_DIR="/opt/quantum-protocol"

echo "=== Quantum Protocol Engine Deployment ==="
echo "Target: $TARGET_HOST"

# Verify Python tests pass
echo "Running tests..."
python -m pytest tests/ src/dashboard/tests/ brain/tests/ -q --tb=short
echo "Tests passed."

if [ "$TARGET_HOST" = "localhost" ]; then
  echo "Local deployment — run with:"
  echo "  PYTHONPATH=. python -m brain.engine"
  echo ""
  echo "Or use docker-compose:"
  echo "  docker-compose up --build"
else
  echo "Deploying to $TARGET_HOST..."

  # Sync code
  rsync -avz --exclude '__pycache__' --exclude '.git' --exclude 'target' \
    --exclude '.pytest_cache' --exclude '*.pyc' \
    . "$TARGET_HOST":"$DEPLOY_DIR"/

  # Install deps on remote
  ssh "$TARGET_HOST" "cd $DEPLOY_DIR && pip install -r requirements.txt"

  # Install systemd service
  ssh "$TARGET_HOST" "sudo cp $DEPLOY_DIR/deploy/quantum-engine.service /etc/systemd/system/ && sudo systemctl daemon-reload"

  echo "Deployed. Start with:"
  echo "  sudo systemctl start quantum-engine"
  echo "  sudo systemctl enable quantum-engine"
fi

echo "=== Deployment complete ==="
