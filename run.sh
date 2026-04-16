#!/usr/bin/env bash
set -euo pipefail

export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-./credentials/sa-key.json}"

if [ -z "${GCP_PROJECT:-}" ]; then
  echo "Error: GCP_PROJECT is not set. Set it in .env or as an environment variable." >&2
  exit 1
fi

exec uv run python -m atb_mcp
