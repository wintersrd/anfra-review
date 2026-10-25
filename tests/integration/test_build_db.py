"""The fixture DuckDB build: schema, derived columns, storage format."""

from __future__ import annotations

import duckdb
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def con(fixture_db):
    return duckdb.connect(str(fixture_db), read_only=True)


class TestBuildDB:
    def test_four_tables_exist(self, con):
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert {"activities", "weekly_summary", "weekly_by_category", "decoupling_calc"} <= tables

    def test_data_fingerprints(self, con):
        # Exact fingerprints of the committed data/raw CSVs. If a re-sync
        # deliberately changes them, update these numbers in the same commit.
        counts = dict(
            con.execute(
                "SELECT 'activities', COUNT(*) FROM activities UNION ALL "
                "SELECT 'runs', COUNT(*) FROM activities WHERE sport_group='run' UNION ALL "
                "SELECT 'weeks', COUNT(*) FROM weekly_summary UNION ALL "
                "SELECT 'bycat', COUNT(*) FROM weekly_by_category UNION ALL "
                "SELECT 'decoupling', COUNT(*) FROM decoupling_calc"
            ).fetchall()
        )
        assert counts["activities"] == 499
        assert counts["runs"] == 187
        assert counts["weeks"] == 772
        assert counts["bycat"] == 1033
        assert counts["decoupling"] == 71

    def test_run_surface_derivation(self, con):
        rows = con.execute(
            "SELECT type, run_surface, COUNT(*) FROM activities "
            "WHERE sport_group='run' GROUP BY 1, 2 ORDER BY 3 DESC"
        ).fetchall()
        by_type = {}
        for atype, surface, n in rows:
            by_type.setdefault(atype, {})[surface] = n
        assert by_type["Run"] == {"road": 131}
        assert by_type["TrailRun"] == {"trail": 21}
        assert by_type["VirtualRun"] == {"indoor": 35}
        # non-run sports have no surface
        assert (
            con.execute(
                "SELECT COUNT(*) FROM activities "
                "WHERE sport_group<>'run' AND run_surface IS NOT NULL"
            ).fetchone()[0]
            == 0
        )

    def test_stride_guard(self, con):
        # stride only where cadence > 40 AND speed > 0; stride_time mirrors moving_time
        bad = con.execute(
            "SELECT COUNT(*) FROM activities "
            "WHERE stride_m IS NOT NULL AND (avg_cadence <= 40 OR avg_speed_ms <= 0)"
        ).fetchone()[0]
        assert bad == 0
        null_ok = con.execute(
            "SELECT COUNT(*) FROM activities WHERE avg_cadence <= 40 AND stride_m IS NOT NULL"
        ).fetchone()[0]
        assert null_ok == 0
        some_null = con.execute(
            "SELECT COUNT(*) FROM activities WHERE stride_m IS NULL"
        ).fetchone()[0]
        assert some_null > 0  # walk-break-polluted rows are correctly excluded

    def test_ids_are_varchar(self, con):
        # imported activities have string ids like 'i51363809'
        assert con.execute("SELECT COUNT(*) FROM activities WHERE id LIKE 'i%'").fetchone()[0] > 0

    def test_no_reader_snapshot_for_fixture(self, fixture_db):
        assert not fixture_db.with_name("running_reader.duckdb").exists()

    def test_readable_by_installed_duckdb(self, fixture_db):
        # the v0.10 storage format must open with the plain python duckdb too
        c = duckdb.connect(str(fixture_db), read_only=True)
        assert c.execute("SELECT COUNT(*) FROM activities").fetchone()[0] > 0
        c.close()
