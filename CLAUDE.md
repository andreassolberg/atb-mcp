# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync --dev

# Run server locally
./run.sh

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_validation.py

# Run a single test by name
uv run pytest tests/test_validation.py::TestValidateQuery::test_valid_query

# Docker
docker compose up --build
```

## Architecture

This is a **FastMCP server** (`fastmcp>=2.0`) that exposes ATB bus delay data from Trondheim via 6 MCP tools. The data lives in Entur's public BigQuery dataset (`ent-data-sharing-ext-prd`).

```
src/atb_mcp/
  __main__.py       — entry point, reads MCP_TRANSPORT/HOST/PORT env vars
  server.py         — FastMCP app with all tools, resources, and prompts
  bigquery_client.py — ATBBigQueryClient: wraps google-cloud-bigquery, runs queries in asyncio.to_thread
  validation.py     — SQL guard: blocks writes, enforces operatingDate + dataSource='ATB' filters, appends LIMIT
```

**Request flow**: MCP client → `server.py` tool → `ATBBigQueryClient` → Google BigQuery → markdown table response.

**Lifespan**: `ATBBigQueryClient` is created once at startup and injected into every tool via `ctx.request_context.lifespan_context["bq"]`.

**Two query paths**:
- `execute_query(sql)` — goes through `validate_query()` in `validation.py` (used by the free-form `query` tool)
- `execute_parameterized(sql, params)` — bypasses validation (used by pre-built tools like `list_lines`, `delay_summary`)

## BigQuery data

- Main table: `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
- 2.8B rows, 639 GB, partitioned on `operatingDate`
- **Always** filter on `operatingDate` (partition key) and `dataSource = 'ATB'` — a full table scan costs the entire free monthly quota (1 TB)
- One day of ATB data ≈ 1–2 GB scanned

## Credentials

Put the GCP service account JSON key at `credentials/sa-key.json` (gitignored). Set `GOOGLE_APPLICATION_CREDENTIALS` to point to it. The `credentials/` directory is mounted read-only in Docker.
