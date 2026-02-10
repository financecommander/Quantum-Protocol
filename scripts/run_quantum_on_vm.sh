#!/usr/bin/env bash
# Quantum Protocol - Run Quantum Training on GCP VM
# Ephemeral: spin up, train, save weights, terminate.
#
# Usage: ./scripts/run_quantum_on_vm.sh [INSTANCE_NAME] [PROJECT_ID] [ZONE]

set -euo pipefail

INSTANCE_NAME="${1:-qp-engine-vm}"
PROJECT_ID="${2:-quantum-protocol}"
ZONE="${3:-us-central1-a}"
OUTPUT_BUCKET="gs://${PROJECT_ID}-weights"

echo "=== Quantum Training on VM: $INSTANCE_NAME ==="

# Copy training script to VM
gcloud compute scp scripts/quantum_training.py "$INSTANCE_NAME":~/quantum_training.py \
  --project="$PROJECT_ID" \
  --zone="$ZONE"

# Run training
gcloud compute ssh "$INSTANCE_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --command="
    cd ~ && \
    pip3 install qiskit qiskit-optimization qiskit-algorithms 2>/dev/null || true && \
    python3 quantum_training.py --num-assets 8 --iterations 100 --output quantum_weights.json && \
    echo 'Training complete.'
  "

# Copy results back
gcloud compute scp "$INSTANCE_NAME":~/quantum_weights.json ./quantum_weights.json \
  --project="$PROJECT_ID" \
  --zone="$ZONE"

echo "Weights saved to ./quantum_weights.json"

# Optionally upload to GCS
if gsutil ls "$OUTPUT_BUCKET" &>/dev/null; then
  gsutil cp ./quantum_weights.json "$OUTPUT_BUCKET/quantum_weights_$(date +%Y%m%d_%H%M%S).json"
  echo "Weights uploaded to $OUTPUT_BUCKET"
fi

echo "=== Training complete. Consider terminating the VM to save costs ==="
echo "gcloud compute instances delete $INSTANCE_NAME --project=$PROJECT_ID --zone=$ZONE"
