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

    def test_ride_type_derivation(self, con):
        rows = con.execute(
            "SELECT type, ride_type, COUNT(*) FROM activities "
            "WHERE sport_group='ride' GROUP BY 1, 2 ORDER BY 3 DESC"
        ).fetchall()
        by_type = {
            atype: {surface: n for t, surface, n in rows if t == atype} for atype, _, _ in rows
        }
        assert by_type["VirtualRide"] == {"virtual": 106}
        assert by_type["Ride"] == {"road": 34}
        assert by_type["MountainBikeRide"] == {"mtb": 13}
        assert by_type["GravelRide"] == {"gravel": 1}
        # e-bike rides carry no ride_type and are excluded from the cycling app
        assert by_type["EBikeRide"] == {None: 1}
        # non-ride sports have no ride_type
        assert (
            con.execute(
                "SELECT COUNT(*) FROM activities "
                "WHERE sport_group<>'ride' AND ride_type IS NOT NULL"
            ).fetchone()[0]
            == 0
        )

    def test_icu_ftp_density(self, con):
        # per-activity FTP: 154 of 155 rides (the e-bike ride is the null one), 220-250 W
        n, lo, hi, distinct = con.execute(
            "SELECT COUNT(*), MIN(icu_ftp), MAX(icu_ftp), COUNT(DISTINCT icu_ftp) "
            "FROM activities WHERE sport_group='ride' AND icu_ftp IS NOT NULL"
        ).fetchone()
        assert (n, lo, hi, distinct) == (154, 220.0, 250.0, 4)
        assert con.execute(
            "SELECT type FROM activities WHERE sport_group='ride' AND icu_ftp IS NULL"
        ).fetchall() == [("EBikeRide",)]

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
