"""Pure-function tests for the intervals.icu sync script."""

from __future__ import annotations

import pytest
import sync_intervals_icu as sync


@pytest.mark.unit
class TestCleanText:
    def test_strips_control_chars(self):
        # Zwift activity names contain \u0002 segment markers
        assert sync.clean_text("Zwift\u0002 - Group Ride") == "Zwift - Group Ride"

    def test_none_and_whitespace(self):
        assert sync.clean_text(None) == ""
        assert sync.clean_text("  paced  ") == "paced"

    def test_keeps_tab(self):
        assert sync.clean_text("a\tb") == "a\tb"


@pytest.mark.unit
class TestParseTs:
    def test_iso_z(self):
        assert sync.parse_ts("2026-03-01T07:00:00Z") == "2026-03-01 07:00:00"

    def test_offset(self):
        assert sync.parse_ts("2026-03-01T07:00:00+00:00") == "2026-03-01 07:00:00"

    def test_garbage_and_empty(self):
        assert sync.parse_ts("") == ""
        assert sync.parse_ts(None) == ""
        assert sync.parse_ts("not-a-date") == ""


@pytest.mark.unit
class TestFnum:
    def test_first_present_key(self):
        assert sync.fnum({"a": "1.5", "b": 2}, "a", "b") == 1.5

    def test_skips_bad_values(self):
        assert sync.fnum({"a": "", "b": None, "c": "x"}, "a", "b", "c", default=7) == 7

    def test_default(self):
        assert sync.fnum({}, "missing", default=0) == 0


@pytest.mark.unit
class TestIsStub:
    def test_strava_note_is_stub(self):
        assert sync.is_stub({"_note": "STRAVA activities are not available"}) is True

    def test_minimal_record_without_payload_is_stub(self):
        assert sync.is_stub({"id": 1, "start_date_local": "2015-01-01"}) is True

    def test_real_activity_is_not_stub(self):
        assert sync.is_stub({"id": 2, "type": "Run", "distance": 5000}) is False
        assert sync.is_stub({"id": 3, "moving_time": 3600}) is False


@pytest.mark.unit
class TestActivityRow:
    def test_full_mapping(self):
        row = sync.activity_row(
            {
                "id": 99,
                "name": "Morning\u0002 run",
                "start_date": "2026-03-01T06:00:00Z",
                "start_date_local": "2026-03-01T07:00:00+01:00",
                "type": "TrailRun",
                "moving_time": 3600,
                "elapsed_time": 3700,
                "distance": 10000.0,
                "total_elevation_gain": 250,
                "average_speed": 2.78,
                "average_heartrate": 150.0,
                "average_cadence": 170.0,
                "icu_training_load": 88.0,
            }
        )
        assert row["sport_group"] == "run"
        assert row["type"] == "TrailRun"
        assert row["moving_time_s"] == 3600
        assert row["distance_m"] == 10000.0
        assert row["training_load"] == 88.0
        assert row["is_race"] is False

    def test_sport_group_map_covers_history(self):
        # v2 requirement: sport-agnostic schema — every historical type maps
        expected = {
            "Run": "run",
            "TrailRun": "run",
            "VirtualRun": "run",
            "Ride": "ride",
            "VirtualRide": "ride",
            "MountainBikeRide": "ride",
            "GravelRide": "ride",
            "WeightTraining": "strength",
            "Workout": "strength",
            "Walk": "walk",
            "Hike": "walk",
            "Yoga": "yoga",
            "Rowing": "row",
        }
        for atype, group in expected.items():
            assert sync.SPORT_GROUP.get(atype) == group, atype
        # unknown types fall back to 'other', never crash
        assert sync.activity_row({"id": 1, "type": "SomethingNew"})["sport_group"] == "other"

    def test_subtype_fallback_for_type(self):
        row = sync.activity_row({"id": 5, "subtype": "Run"})
        assert row["type"] == "Run"

    def test_numeric_defaults(self):
        row = sync.activity_row({"id": 7, "type": "Run"})
        assert row["moving_time_s"] == 0
        assert row["calories"] == 0
        assert row["gap_s"] == 0
        assert row["distance_m"] is None


@pytest.mark.unit
class TestLoadEnv:
    def test_parses_quotes_and_comments(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nA=\"quoted\"\nB='single'\nC=bare\n\nbroken-line\n")
        monkeypatch.setattr(sync, "ROOT", tmp_path)
        monkeypatch.delenv("INTERVALS_ICU_API_KEY", raising=False)
        env = sync.load_env()
        assert env["A"] == "quoted"
        assert env["B"] == "single"
        assert env["C"] == "bare"
        assert "broken-line" not in env

    def test_os_env_overrides_file(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("INTERVALS_ICU_API_KEY=from-file\n")
        monkeypatch.setattr(sync, "ROOT", tmp_path)
        monkeypatch.setenv("INTERVALS_ICU_API_KEY", "from-os")
        assert sync.load_env()["INTERVALS_ICU_API_KEY"] == "from-os"
