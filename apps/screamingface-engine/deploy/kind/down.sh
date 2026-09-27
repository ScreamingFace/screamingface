#!/usr/bin/env bash
set -euo pipefail

# Tear down the uniform executor kind environment. Does not touch the standalone `nats-js`
# container the integration test suite uses (localhost:4222) — this cluster runs its own NATS.
CLUSTER_NAME="sf-uniform"
kind delete cluster --name "${CLUSTER_NAME}"
