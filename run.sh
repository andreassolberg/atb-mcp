#!/usr/bin/env bash
set -euo pipefail

export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-./credentials/sa-key.json}"
export GCP_PROJECT="${GCP_PROJECT:-solberg-cluster}"

exec uv run python -m atb_mcp
