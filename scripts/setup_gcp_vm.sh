#!/usr/bin/env bash
# Quantum Protocol - GCP VM Setup Script
# Sets up a GPU-enabled VM for quantum training and engine deployment.
#
# Usage: ./scripts/setup_gcp_vm.sh [PROJECT_ID] [ZONE]

set -euo pipefail

PROJECT_ID="${1:-quantum-protocol}"
ZONE="${2:-us-central1-a}"
INSTANCE_NAME="qp-engine-vm"
MACHINE_TYPE="n1-standard-8"
GPU_TYPE="nvidia-tesla-t4"
GPU_COUNT=1
IMAGE_FAMILY="ubuntu-2204-lts"
IMAGE_PROJECT="ubuntu-os-cloud"
BOOT_DISK_SIZE="100GB"

echo "=== Quantum Protocol GCP VM Setup ==="
echo "Project:  $PROJECT_ID"
echo "Zone:     $ZONE"
echo "Instance: $INSTANCE_NAME"
echo "Machine:  $MACHINE_TYPE + ${GPU_COUNT}x $GPU_TYPE"

# Create GPU-enabled instance
gcloud compute instances create "$INSTANCE_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --accelerator="type=$GPU_TYPE,count=$GPU_COUNT" \
  --maintenance-policy=TERMINATE \
  --image-family="$IMAGE_FAMILY" \
  --image-project="$IMAGE_PROJECT" \
  --boot-disk-size="$BOOT_DISK_SIZE" \
  --boot-disk-type=pd-ssd \
  --metadata=startup-script='#!/bin/bash
    apt-get update && apt-get install -y docker.io nvidia-driver-535 nvidia-container-toolkit
    systemctl enable docker
    systemctl start docker
    nvidia-smi
  ' \
  --scopes=default,storage-rw

echo "VM created. Waiting for startup..."
sleep 30

# Verify GPU is available
gcloud compute ssh "$INSTANCE_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --command="nvidia-smi" || echo "GPU verification pending (driver may still be installing)"

echo "=== GCP VM setup complete ==="
echo "SSH: gcloud compute ssh $INSTANCE_NAME --project=$PROJECT_ID --zone=$ZONE"
