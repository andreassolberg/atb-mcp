"""Tests for SQL validation logic."""

import pytest
from atb_mcp.validation import (
    ValidationError,
    validate_query,
    is_read_only,
    has_partition_filter,
    has_datasource_filter,
    ensure_limit,
)


class TestIsReadOnly:
    def test_select_is_allowed(self):
        assert is_read_only("SELECT * FROM table") is True

    @pytest.mark.parametrize("keyword", [
        "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE",
    ])
    def test_dangerous_keywords_rejected(self, keyword):
        assert is_read_only(f"{keyword} something") is False

    def test_case_insensitive(self):
        assert is_read_only("delete FROM table") is False


class TestHasPartitionFilter:
    def test_with_filter(self):
        assert has_partition_filter("WHERE operatingDate = '2025-01-15'") is True

    def test_without_filter(self):
        assert has_partition_filter("WHERE lineRef = 'ATB:Line:2_3'") is False


class TestHasDatasourceFilter:
    def test_with_filter(self):
        assert has_datasource_filter("AND dataSource = 'ATB'") is True

    def test_double_quotes(self):
        assert has_datasource_filter('AND dataSource = "ATB"') is True

    def test_without_filter(self):
        assert has_datasource_filter("WHERE operatingDate = '2025-01-15'") is False


class TestEnsureLimit:
    def test_adds_limit_when_missing(self):
        result = ensure_limit("SELECT * FROM t")
        assert "LIMIT 10000" in result

    def test_preserves_existing_limit(self):
        sql = "SELECT * FROM t LIMIT 50"
        result = ensure_limit(sql)
        assert result == sql
        assert "LIMIT 10000" not in result

    def test_custom_max_rows(self):
        result = ensure_limit("SELECT * FROM t", max_rows=500)
        assert "LIMIT 500" in result


class TestValidateQuery:
    def test_valid_query(self):
        sql = """
            SELECT lineRef, AVG(TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND))
            FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
            WHERE operatingDate = '2025-01-15' AND dataSource = 'ATB'
            GROUP BY lineRef
        """
        result = validate_query(sql)
        assert "LIMIT 10000" in result

    def test_empty_query(self):
        with pytest.raises(ValidationError, match="Empty query"):
            validate_query("")

    def test_multi_statement(self):
        with pytest.raises(ValidationError, match="Multi-statement"):
            validate_query("SELECT 1; SELECT 2")

    def test_rejects_delete(self):
        with pytest.raises(ValidationError, match="Only SELECT"):
            validate_query("DELETE FROM table WHERE operatingDate = '2025-01-15' AND dataSource = 'ATB'")

    def test_rejects_missing_partition_filter(self):
        with pytest.raises(ValidationError, match="operatingDate"):
            validate_query("SELECT * FROM t WHERE dataSource = 'ATB'")

    def test_rejects_missing_datasource(self):
        with pytest.raises(ValidationError, match="dataSource"):
            validate_query("SELECT * FROM t WHERE operatingDate = '2025-01-15'")

    def test_trailing_semicolon_ok(self):
        sql = "SELECT * FROM t WHERE operatingDate = '2025-01-15' AND dataSource = 'ATB';"
        result = validate_query(sql)
        assert "LIMIT" in result
