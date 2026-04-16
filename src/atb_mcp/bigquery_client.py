"""BigQuery client wrapper with cost control guardrails."""

import asyncio
from google.cloud import bigquery

from .validation import validate_query, ValidationError


DATASET = "ent-data-sharing-ext-prd.realtime_siri_et"
STOP_REGISTRY_DATASET = "ent-data-sharing-ext-prd.national_stop_registry"

KNOWN_TABLES = {
    "realtime_siri_et_last_recorded": DATASET,
    "realtime_siri_et_estimated_times": DATASET,
    "quays_last_version": STOP_REGISTRY_DATASET,
    "stop_places_last_version": STOP_REGISTRY_DATASET,
}


class ATBBigQueryClient:
    def __init__(self, project_id: str, max_bytes_gb: float = 10.0):
        self.client = bigquery.Client(project=project_id)
        self.max_bytes = int(max_bytes_gb * 1e9)

    def _job_config(self, dry_run: bool = False) -> bigquery.QueryJobConfig:
        return bigquery.QueryJobConfig(
            maximum_bytes_billed=self.max_bytes,
            dry_run=dry_run,
        )

    async def execute_query(self, sql: str) -> list[dict]:
        """Validate and execute a query. Returns list of row dicts."""
        cleaned_sql = validate_query(sql)

        def _run():
            job = self.client.query(cleaned_sql, job_config=self._job_config())
            return [dict(row) for row in job.result()]

        return await asyncio.to_thread(_run)

    async def dry_run(self, sql: str) -> dict:
        """Estimate bytes scanned without executing."""
        cleaned_sql = validate_query(sql)

        def _run():
            job = self.client.query(cleaned_sql, job_config=self._job_config(dry_run=True))
            return {
                "total_bytes_processed": job.total_bytes_processed,
                "gb": job.total_bytes_processed / 1e9,
            }

        return await asyncio.to_thread(_run)

    async def execute_parameterized(
        self, sql: str, parameters: list[bigquery.ScalarQueryParameter]
    ) -> list[dict]:
        """Execute a pre-built parameterized query (bypasses validation)."""
        config = self._job_config()
        config.query_parameters = parameters

        def _run():
            job = self.client.query(sql, job_config=config)
            return [dict(row) for row in job.result()]

        return await asyncio.to_thread(_run)

    def get_table_schema(self, table_name: str) -> list[dict]:
        """Return column definitions for a table."""
        if table_name not in KNOWN_TABLES:
            raise ValidationError(
                f"Unknown table '{table_name}'. "
                f"Available: {', '.join(KNOWN_TABLES.keys())}"
            )
        dataset = KNOWN_TABLES[table_name]
        table_ref = f"{dataset}.{table_name}"
        table = self.client.get_table(table_ref)
        return [
            {
                "name": field.name,
                "type": field.field_type,
                "description": field.description or "",
            }
            for field in table.schema
        ]

    async def find_nearby_stops(
        self,
        points: list[dict],
        max_distance_m: int = 500,
        max_stops: int = 3,
    ) -> list[dict]:
        """Find stops near geographic points using BigQuery geo functions."""
        # Build UNNEST array from points (floats/ints only — no injection risk)
        structs = ", ".join(
            f"STRUCT({i} AS point_id, {float(p['lat'])} AS lat, {float(p['lon'])} AS lon)"
            for i, p in enumerate(points)
        )

        sql = f"""
            WITH points AS (
              SELECT * FROM UNNEST([{structs}])
            ),
            nearby AS (
              SELECT p.point_id, p.lat AS point_lat, p.lon AS point_lon,
                     q.id AS quay_id, q.publicCode, q.stopPlaceRef,
                     q.location_latitude, q.location_longitude,
                     ST_DISTANCE(
                       ST_GEOGPOINT(p.lon, p.lat),
                       ST_GEOGPOINT(q.location_longitude, q.location_latitude)
                     ) AS distance_m
              FROM points p
              CROSS JOIN `{STOP_REGISTRY_DATASET}.quays_last_version` q
              WHERE q.location_latitude IS NOT NULL
                AND ST_DISTANCE(
                      ST_GEOGPOINT(p.lon, p.lat),
                      ST_GEOGPOINT(q.location_longitude, q.location_latitude)
                    ) <= {int(max_distance_m)}
            ),
            ranked AS (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY point_id ORDER BY distance_m) AS rn
              FROM nearby
            )
            SELECT r.point_id, r.point_lat, r.point_lon,
                   r.quay_id, r.publicCode, r.stopPlaceRef,
                   sp.name AS stop_name,
                   r.location_latitude, r.location_longitude,
                   ROUND(r.distance_m, 1) AS distance_m
            FROM ranked r
            LEFT JOIN `{STOP_REGISTRY_DATASET}.stop_places_last_version` sp
              ON r.stopPlaceRef = sp.id
            WHERE r.rn <= {int(max_stops)}
            ORDER BY r.point_id, r.distance_m
        """

        def _run():
            job = self.client.query(sql, job_config=self._job_config())
            return [dict(row) for row in job.result()]

        return await asyncio.to_thread(_run)

    def close(self):
        self.client.close()
