"""FastMCP server for ATB bus data analysis via BigQuery."""

import os
from contextlib import asynccontextmanager
from datetime import date

from fastmcp import FastMCP, Context
from google.cloud import bigquery

from .bigquery_client import ATBBigQueryClient, KNOWN_TABLES
from .validation import ValidationError


@asynccontextmanager
async def app_lifespan(server):
    project_id = os.environ.get("GCP_PROJECT", "atb-analyse")
    max_bytes_gb = float(os.environ.get("BQ_MAX_BYTES_GB", "10"))
    client = ATBBigQueryClient(project_id, max_bytes_gb)
    try:
        yield {"bq": client}
    finally:
        client.close()


mcp = FastMCP(
    "ATB Bus Data",
    instructions=(
        "MCP server for analyzing ATB bus data from Trondheim, Norway. "
        "Data comes from Entur's public BigQuery dataset with real-time SIRI ET records. "
        "All queries MUST filter on operatingDate (partition key) and dataSource='ATB'. "
        "Use dry_run to estimate cost before running expensive queries."
    ),
    lifespan=app_lifespan,
)


# --- Tools ---


@mcp.tool()
async def get_schema(table_name: str, ctx: Context) -> str:
    """Get column names, types, and descriptions for a BigQuery table.

    Available tables:
    - realtime_siri_et_last_recorded: Main table with one row per stop visit and actual times
    - realtime_siri_et_estimated_times: Estimated times at various points before arrival
    - quays_last_version: Platforms/quays with coordinates (lat/lon)
    - stop_places_last_version: Stop places with names, zones, transport modes
    """
    bq: ATBBigQueryClient = ctx.request_context.lifespan_context["bq"]
    try:
        schema = bq.get_table_schema(table_name)
    except ValidationError as e:
        return f"Error: {e}"

    lines = [f"## Schema: {table_name}\n"]
    for col in schema:
        desc = f" — {col['description']}" if col["description"] else ""
        lines.append(f"- **{col['name']}** ({col['type']}){desc}")
    return "\n".join(lines)


@mcp.tool()
async def query(sql: str, ctx: Context) -> str:
    """Execute a BigQuery SQL query against ATB bus data.

    RULES:
    - Include operatingDate filter (partition column) in every query
    - Include dataSource = 'ATB'
    - Only SELECT statements allowed
    - Results limited to 10,000 rows
    - Max ~10 GB data scanned per query

    Main table: `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`

    Useful patterns:
    - Delay: TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND)
    - ATB lines: lineRef LIKE 'ATB:Line:%'
    - One day of ATB data ~ 1-2 GB
    """
    bq: ATBBigQueryClient = ctx.request_context.lifespan_context["bq"]
    try:
        rows = await bq.execute_query(sql)
    except ValidationError as e:
        return f"Validation error: {e}"
    except Exception as e:
        return f"Query error: {e}"

    if not rows:
        return "Query returned 0 rows."

    return _format_rows(rows)


@mcp.tool()
async def dry_run(sql: str, ctx: Context) -> str:
    """Estimate how much data a query will scan WITHOUT executing it.

    Use this before running expensive queries to check cost.
    Free tier is 1 TB/month. One day of ATB data ~ 1-2 GB.
    """
    bq: ATBBigQueryClient = ctx.request_context.lifespan_context["bq"]
    try:
        estimate = await bq.dry_run(sql)
    except ValidationError as e:
        return f"Validation error: {e}"
    except Exception as e:
        return f"Dry run error: {e}"

    return (
        f"Estimated data scanned: {estimate['total_bytes_processed']:,} bytes "
        f"({estimate['gb']:.2f} GB)"
    )


@mcp.tool()
async def list_lines(operating_date: str, ctx: Context) -> str:
    """List all ATB bus lines operating on a given date.

    Args:
        operating_date: Date in YYYY-MM-DD format
    """
    bq: ATBBigQueryClient = ctx.request_context.lifespan_context["bq"]
    sql = """
        SELECT lineRef, MIN(originName) as origin, MIN(destinationName) as destination,
               COUNT(DISTINCT serviceJourneyId) as trips
        FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
        WHERE operatingDate = @operating_date AND dataSource = 'ATB'
        GROUP BY lineRef
        ORDER BY lineRef
    """
    params = [
        bigquery.ScalarQueryParameter("operating_date", "DATE", operating_date),
    ]
    try:
        rows = await bq.execute_parameterized(sql, params)
    except Exception as e:
        return f"Error: {e}"

    if not rows:
        return f"No lines found for {operating_date}."

    return _format_rows(rows)


@mcp.tool()
async def delay_summary(
    operating_date: str,
    line_ref: str | None = None,
    ctx: Context = None,
) -> str:
    """Get average delay statistics for ATB buses on a given date.

    Without line_ref: returns per-line summary.
    With line_ref: returns per-stop delays for that line.

    Args:
        operating_date: Date in YYYY-MM-DD format
        line_ref: Optional line reference (e.g. 'ATB:Line:2_3')
    """
    bq: ATBBigQueryClient = ctx.request_context.lifespan_context["bq"]
    params = [
        bigquery.ScalarQueryParameter("operating_date", "DATE", operating_date),
    ]

    if line_ref:
        sql = """
            SELECT stopPointName, sequenceNr,
                   AVG(TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND)) as avg_delay_s,
                   COUNT(*) as observations
            FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
            WHERE operatingDate = @operating_date AND dataSource = 'ATB'
                  AND lineRef = @line_ref AND departureTime IS NOT NULL
            GROUP BY stopPointName, sequenceNr
            ORDER BY sequenceNr
        """
        params.append(bigquery.ScalarQueryParameter("line_ref", "STRING", line_ref))
    else:
        sql = """
            SELECT lineRef,
                   AVG(TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND)) as avg_delay_s,
                   COUNT(*) as observations,
                   COUNTIF(TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND) > 180) as late_3min,
                   COUNTIF(journeyCancellation) as cancellations
            FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
            WHERE operatingDate = @operating_date AND dataSource = 'ATB'
                  AND departureTime IS NOT NULL
            GROUP BY lineRef
            ORDER BY avg_delay_s DESC
        """

    try:
        rows = await bq.execute_parameterized(sql, params)
    except Exception as e:
        return f"Error: {e}"

    if not rows:
        return f"No data found for {operating_date}."

    return _format_rows(rows)


@mcp.tool()
async def nearby_stops(
    points: list[dict],
    max_distance_m: int = 500,
    max_stops: int = 3,
    ctx: Context = None,
) -> str:
    """Find bus stops near one or more geographic positions.

    Returns stops sorted by distance for each point, with stop name, quay ID,
    and distance in meters. Useful for finding which stops serve a location.

    Args:
        points: List of positions, each a dict with 'lat' and 'lon' keys.
                Example: [{"lat": 63.4345, "lon": 10.4115}]
                Supports up to 500 points in one call.
        max_distance_m: Maximum distance in meters (1-5000, default 500)
        max_stops: Maximum stops to return per point (1-50, default 3)
    """
    bq: ATBBigQueryClient = ctx.request_context.lifespan_context["bq"]

    if not points or not isinstance(points, list):
        return "Error: 'points' must be a non-empty list of {lat, lon} objects."
    if len(points) > 500:
        return "Error: Maximum 500 points per request."
    for i, p in enumerate(points):
        if not isinstance(p, dict) or "lat" not in p or "lon" not in p:
            return f"Error: Point {i} must have 'lat' and 'lon' keys."
        try:
            float(p["lat"])
            float(p["lon"])
        except (TypeError, ValueError):
            return f"Error: Point {i} lat/lon must be numbers."

    max_distance_m = max(1, min(5000, int(max_distance_m)))
    max_stops = max(1, min(50, int(max_stops)))

    try:
        rows = await bq.find_nearby_stops(points, max_distance_m, max_stops)
    except Exception as e:
        return f"Error: {e}"

    if not rows:
        return "No stops found within the specified distance."

    return _format_rows(rows)


# --- Resources ---


@mcp.resource("atb://tables")
def available_tables() -> str:
    """List of available BigQuery tables and their descriptions."""
    return """Available tables:

1. **realtime_siri_et_last_recorded**
   Main table. One row per stop visit with last recorded actual times.
   2.8 billion rows, 639 GB. Partitioned on operatingDate. Data from Q1 2020.
   ALWAYS filter on operatingDate and dataSource='ATB'.

2. **realtime_siri_et_estimated_times**
   Estimated times captured at various points before actual arrival/departure.
   Useful for analyzing prediction accuracy over time.

3. **quays_last_version** (national_stop_registry)
   Platform/quay data with coordinates (lat/lon).
   Join on stopPointRef = quay NSR ID.

4. **stop_places_last_version** (national_stop_registry)
   Stop place metadata: names, zones, transport modes.
"""


@mcp.resource("atb://query-guide")
def query_guide() -> str:
    """Guide for writing BigQuery queries against ATB bus data."""
    return """# ATB BigQuery Query Guide

## Required filters (MANDATORY in every query)
- `operatingDate`: Partition column. Always filter on this.
- `dataSource = 'ATB'`: Limit to ATB data.

## Main table
`ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`

## Useful SQL patterns
- Delay: `TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND)`
- Date range: `operatingDate BETWEEN '2025-01-01' AND '2025-01-31'`
- Specific line: `lineRef = 'ATB:Line:2_3'` (line 3)
- Extract line number: `REGEXP_EXTRACT(lineRef, r'ATB:Line:2_(\\d+)')`

## Cost awareness
- One day of ATB data ~ 1-2 GB scanned
- One month ~ 30-60 GB
- Full table scan = 639 GB — NEVER do this
- Free tier: 1 TB/month
- Use the dry_run tool to estimate before large queries
"""


# --- Prompts ---


@mcp.prompt()
def analyze_delays(date: str, line: str | None = None) -> str:
    """Comprehensive delay analysis for ATB buses."""
    line_clause = f" for line {line}" if line else ""
    return f"""Analyze bus delays{line_clause} on {date} in Trondheim (ATB).

Steps:
1. Use get_schema to understand the realtime_siri_et_last_recorded table
2. Use dry_run to estimate query cost
3. Use delay_summary to get an overview
4. If interesting patterns appear, use query for deeper analysis
5. Identify: which lines/stops have the worst delays?
6. Summarize findings with actionable insights
"""


@mcp.prompt()
def compare_periods(
    period1_start: str, period1_end: str, period2_start: str, period2_end: str
) -> str:
    """Compare ATB bus performance between two time periods."""
    return f"""Compare ATB bus performance between two periods:
Period 1: {period1_start} to {period1_end}
Period 2: {period2_start} to {period2_end}

Steps:
1. Query average delays per line for each period
2. Query trip counts per day for each period
3. Query cancellation rates
4. Present a comparative summary highlighting improvements or regressions
"""


@mcp.prompt()
def line_deep_dive(line: str, date: str) -> str:
    """Deep dive into a specific ATB bus line."""
    return f"""Deep dive analysis of ATB line {line} on {date}.

Steps:
1. Use list_lines to verify the line exists on this date
2. Use delay_summary with the line_ref to see per-stop delays
3. Query individual trips to see delay propagation along the route
4. Check for cancellations
5. Summarize: where do delays build up? Are some trips worse than others?
"""


# --- Helpers ---


def _format_rows(rows: list[dict]) -> str:
    """Format query result rows as a readable markdown table."""
    if not rows:
        return "No results."

    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows[:200]:  # Cap display at 200 rows
        values = [str(row.get(h, "")) for h in headers]
        lines.append("| " + " | ".join(values) + " |")

    total = len(rows)
    if total > 200:
        lines.append(f"\n*Showing 200 of {total} rows.*")
    else:
        lines.append(f"\n*{total} rows.*")

    return "\n".join(lines)
