"""Data-quality invariants the dashboards implicitly rely on."""

from __future__ import annotations

import duckdb
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def con(fixture_db):
    return duckdb.connect(str(fixture_db), read_only=True)


class TestIntegrity:
    def test_activity_ids_unique(self, con):
        n, total = con.execute("SELECT COUNT(DISTINCT id), COUNT(*) FROM activities").fetchone()
        assert n == total

    def test_sport_groups_in_known_set(self, con):
        groups = {
            r[0] for r in con.execute("SELECT DISTINCT sport_group FROM activities").fetchall()
        }
        assert groups <= {"run", "ride", "strength", "walk", "yoga", "row", "other"}
        assert "run" in groups

    def test_weeks_per_year_plausible(self, con):
        # the week-dedup bug produced years with >53 weeks; guard forever
        violators = con.execute(
            "SELECT year(week_start) AS yr, COUNT(*) AS n FROM weekly_summary "
            "GROUP BY 1 HAVING n > 53 ORDER BY n DESC"
        ).fetchall()
        assert violators == []

    def test_week_starts_unique_and_mondays(self, con):
        total, distinct = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT week_start) FROM weekly_summary"
        ).fetchone()
        assert total == distinct
        bad_dow = con.execute(
            "SELECT COUNT(*) FROM weekly_summary WHERE dayofweek(week_start) <> 1"
        ).fetchone()[0]  # duckdb dayofweek: Sunday=0 ... Monday=1
        assert bad_dow == 0

    def test_decoupling_values_plausible(self, con):
        mn, mx, n = con.execute(
            "SELECT MIN(decoupling_pct), MAX(decoupling_pct), COUNT(*) FROM decoupling_calc"
        ).fetchone()
        assert n > 0
        assert -100 <= mn <= 100
        assert -100 <= mx <= 100

    def test_decoupling_referential_integrity(self, con):
        # the anfra relationship decoupling_calc.activity_id > activities.id
        orphans = con.execute(
            "SELECT COUNT(*) FROM decoupling_calc d "
            "WHERE NOT EXISTS (SELECT 1 FROM activities a WHERE a.id = d.activity_id)"
        ).fetchone()[0]
        assert orphans == 0

    def test_bycategory_weeks_exist_in_summary(self, con):
        stray = con.execute(
            "SELECT COUNT(*) FROM weekly_by_category b WHERE NOT EXISTS ("
            "SELECT 1 FROM weekly_summary w WHERE w.week_start = b.week_start)"
        ).fetchone()[0]
        assert stray == 0

    def test_activity_dates_span_expected_era(self, con):
        lo, hi = con.execute(
            "SELECT MIN(CAST(start_local AS DATE)), MAX(CAST(start_local AS DATE)) FROM activities"
        ).fetchone()
        assert lo.year >= 2012  # Strava stub era
        assert hi >= con.execute("SELECT MAX(week_start) FROM weekly_summary").fetchone()[0]

    def test_fitness_trend_has_no_gaps_in_loaded_era(self, con):
        # weekly continuity: from first non-null fitness onward, fitness must
        # never be null (CTL carryover is the point of keeping zero weeks)
        gaps = con.execute(
            "WITH flagged AS (SELECT week_start, fitness, "
            "  MIN(CASE WHEN fitness IS NOT NULL THEN week_start END) OVER () AS first_loaded "
            "FROM weekly_summary) "
            "SELECT COUNT(*) FROM flagged WHERE week_start >= first_loaded AND fitness IS NULL"
        ).fetchone()[0]
        assert gaps == 0
