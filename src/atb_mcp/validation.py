"""SQL validation for BigQuery queries against ATB bus data."""

import re


class ValidationError(Exception):
    """Raised when a query fails validation."""


_DANGEROUS_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_OPERATING_DATE_FILTER = re.compile(
    r"\boperatingDate\b", re.IGNORECASE
)

_DATASOURCE_FILTER = re.compile(
    r"\bdataSource\s*=\s*['\"]ATB['\"]", re.IGNORECASE
)

_LIMIT_CLAUSE = re.compile(
    r"\bLIMIT\s+\d+", re.IGNORECASE
)


def is_read_only(sql: str) -> bool:
    """Check that the query contains only SELECT statements."""
    return _DANGEROUS_KEYWORDS.search(sql) is None


def has_partition_filter(sql: str) -> bool:
    """Check that the query references operatingDate in a filter."""
    return _OPERATING_DATE_FILTER.search(sql) is not None


def has_datasource_filter(sql: str) -> bool:
    """Check that the query filters on dataSource = 'ATB'."""
    return _DATASOURCE_FILTER.search(sql) is not None


def ensure_limit(sql: str, max_rows: int = 10000) -> str:
    """Append LIMIT if not already present."""
    if _LIMIT_CLAUSE.search(sql):
        return sql
    return f"{sql.rstrip().rstrip(';')}\nLIMIT {max_rows}"


def validate_query(sql: str) -> str:
    """Validate and clean a SQL query. Returns cleaned SQL or raises ValidationError."""
    sql = sql.strip()

    if not sql:
        raise ValidationError("Empty query")

    # Reject multi-statement queries
    # Remove trailing semicolon first, then check for remaining ones
    cleaned = sql.rstrip(";")
    if ";" in cleaned:
        raise ValidationError(
            "Multi-statement queries are not allowed. Send one SELECT at a time."
        )

    if not is_read_only(cleaned):
        raise ValidationError(
            "Only SELECT queries are allowed. "
            "INSERT, UPDATE, DELETE, DROP and other write operations are rejected."
        )

    if not has_partition_filter(cleaned):
        raise ValidationError(
            "Query must filter on operatingDate (the partition column). "
            "Example: WHERE operatingDate = '2025-01-15'"
        )

    if not has_datasource_filter(cleaned):
        raise ValidationError(
            "Query must include dataSource = 'ATB' filter. "
            "Example: WHERE operatingDate = '2025-01-15' AND dataSource = 'ATB'"
        )

    cleaned = ensure_limit(cleaned)

    return cleaned
