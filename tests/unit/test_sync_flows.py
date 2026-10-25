"""Pagination / weekly / decoupling logic tests with a scripted fake API."""

from __future__ import annotations

import datetime as dt

import pytest
import sync_intervals_icu as sync


class FakeApi:
    """Mimics sync.Api without network; records calls."""

    def __init__(self, activity_pages=None, weekly=None):
        self.calls: list[tuple[str, dict]] = []
        self.activity_pages = list(activity_pages or [])
        self.weekly = weekly or {}

    def get(self, path, params=None):
        self.calls.append((path, params or {}))
        if "/streams" in path:
            return {}
        if "athlete-summary" in path:
            return self.weekly.get(params.get("start"), {"weeks": []})
        page = self.activity_pages.pop(0) if self.activity_pages else []
        return page


def act(aid, days_ago, atype="Run", dist=10000.0, moving=3600):
    start = dt.date.today() - dt.timedelta(days=days_ago)
    return {
        "id": aid,
        "type": atype,
        "start_date": start.isoformat() + "T06:00:00Z",
        "start_date_local": start.isoformat() + "T07:00:00",
        "distance": dist,
        "moving_time": moving,
    }


@pytest.mark.unit
class TestSyncActivities:
    def test_walks_pages_backward_and_dedupes(self):
        api = FakeApi(
            activity_pages=[
                [act(1, 1), act(2, 2), act(3, 3)],
                [act(2, 2), act(4, 4)],  # overlap: id 2 repeated
                [act(5, 5)],
                [],  # empty page stops
            ]
        )
        acts = sync.sync_activities(api, "A1", dt.date.today() - dt.timedelta(days=10), 10)
        assert {a["id"] for a in acts} == {1, 2, 3, 4, 5}
        # newest-cursor walks back to the oldest page's start date
        cursors = [p["newest"] for _, p in api.calls if p.get("oldest")]
        assert cursors[0] == dt.date.today().isoformat()
        assert len(cursors) >= 3

    def test_stops_at_since_floor(self):
        since = dt.date.today() - dt.timedelta(days=5)
        api = FakeApi(activity_pages=[[act(1, 1), act(2, 7)]])  # second act below floor
        acts = sync.sync_activities(api, "A1", since, 10)
        assert {a["id"] for a in acts} == {1, 2}
        # second call must have newest <= since (page 1 reached the floor)
        assert len(api.calls) == 1

    def test_stall_guard_forces_step_back(self):
        # server ignores the cursor: every page returns the same recent day
        api = FakeApi(activity_pages=[[act(1, 1)]] * 10)
        acts = sync.sync_activities(api, "A1", dt.date.today() - dt.timedelta(days=200), 10)
        assert {a["id"] for a in acts} == {1}
        cursors = [p["newest"] for _, p in api.calls if p.get("oldest")]
        # first step lands on page-1's oldest day, then forced 30-day hops
        assert len(cursors) >= 4
        steps = [
            (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
            for a, b in zip(cursors, cursors[1:], strict=False)
        ]
        assert steps[0] == -1  # today -> page 1 oldest (walking backward)
        assert all(s == -30 for s in steps[1:4])  # stall guard: 30-day hops

    def test_max_pages_respected(self):
        api = FakeApi(activity_pages=[[act(i, i)] for i in range(1, 50)])
        sync.sync_activities(api, "A1", dt.date.today() - dt.timedelta(days=500), 3)
        assert len(api.calls) == 3


@pytest.mark.unit
class TestSyncWeekly:
    def _summary(self, weeks):
        return FakeApi(
            weekly={(dt.date(int(y), 1, 1)).isoformat(): {"weeks": ws} for y, ws in weeks.items()}
        )

    def test_dedupes_by_week_start_across_years(self):
        week = {
            "week_start": "2026-03-02",
            "time": 3600,
            "distance": 10000,
            "count": 3,
            "fitness": 50.0,
            "fatigue": 40.0,
        }
        api = self._summary({"2025": [week], "2026": [dict(week, time=999)]})
        rows, cats = sync.sync_weekly(api, "A1", dt.date(2025, 1, 1))
        assert len(rows) == 1
        assert rows[0]["time_s"] == 3600  # first sighting wins
        assert cats == []

    def test_keeps_ctl_carryover_but_drops_empty_placeholders(self):
        carryover = {"week_start": "2024-01-01", "fitness": 55.0, "fatigue": 44.0}
        empty = {"week_start": "2010-01-04"}
        api = self._summary({"2024": [carryover, empty]})
        rows, _ = sync.sync_weekly(api, "A1", dt.date(2024, 1, 1))
        starts = [r["week_start"] for r in rows]
        assert "2024-01-01" in starts  # zero-volume but fitness present: trend continuity
        assert "2010-01-04" not in starts  # all-null placeholder

    def test_by_category_dict_and_list_forms(self):
        week = {
            "week_start": "2026-03-02",
            "time": 10,
            "byCategory": {"Run": {"time": 6, "count": 1}, "Ride": 4},
        }
        api = self._summary({"2026": [week]})
        rows, cats = sync.sync_weekly(api, "A1", dt.date(2026, 1, 1))
        assert {(c["category"], c["time_s"]) for c in cats} == {("Run", 6), ("Ride", 4)}
        assert rows[0]["time_s"] == 10

    def test_zones_survive_as_json(self):
        week = {"week_start": "2026-03-02", "time": 5, "time_in_zones": [1, 2, 3]}
        api = self._summary({"2026": [week]})
        rows, _ = sync.sync_weekly(api, "A1", dt.date(2026, 1, 1))
        assert rows[0]["time_in_zones"] == "[1, 2, 3]"


def stream(seconds=7200, hr=150, speed=3.0):
    n = seconds // 10
    return (
        list(range(0, seconds, 10)),  # time
        [hr] * n,  # heartrate
        [speed] * n,  # velocity_smooth
    )


@pytest.mark.unit
class TestDecouplingPct:
    def test_flat_streams_zero(self):
        t, h, v = stream()
        pct, minutes = sync.decoupling_pct(t, h, v)
        assert pct == 0.0
        assert minutes == pytest.approx(7200 / 60, abs=0.5)

    def test_hr_drift_positive_sign_convention(self):
        t, v = list(range(0, 7200, 10)), [3.0] * 720
        h1 = stream(3600, hr=140)[1]
        h2 = stream(3600, hr=170)[1]
        pct, _ = sync.decoupling_pct(t, h1 + h2, v)
        assert pct > 5  # positive = fatigue drift

    def test_hr_drop_negative(self):
        t, v = list(range(0, 7200, 10)), [3.0] * 720
        h1 = stream(3600, hr=170)[1]
        h2 = stream(3600, hr=140)[1]
        pct, _ = sync.decoupling_pct(t, h1 + h2, v)
        assert pct < -5

    def test_guards(self):
        assert sync.decoupling_pct([1], [1], [1]) is None  # too few samples
        assert sync.decoupling_pct(list(range(40)), [150] * 40, [3.0] * 39) is None  # mismatch
        # stopped periods (v < 0.5) are filtered; all-stopped -> None
        assert sync.decoupling_pct(list(range(40)), [150] * 40, [0.0] * 40) is None


@pytest.mark.unit
class TestComputeDecoupling:
    def test_candidate_filter_and_stream_shapes(self):
        long_run = {
            "id": "i1",
            "name": "Long",
            "sport_group": "run",
            "moving_time_s": 5400,
            "start_utc": "2026-03-01 06:00:00",
        }
        short = dict(long_run, id="i2", moving_time_s=600)
        ride = dict(long_run, id="i3", sport_group="ride")
        early = dict(long_run, id="i4", start_utc="2020-01-01 06:00:00")

        api = FakeApi()
        results = sync.compute_decoupling(
            api,
            [long_run, short, ride, early],
            since=dt.date(2024, 1, 1),
            min_seconds=4500,
        )
        # only the long run since 2024 is a candidate; its streams fetch
        # returns {} (FakeApi) -> unusable -> no results, but call happened
        assert [p for pth, p in api.calls if "/streams" in pth] == [
            {"types": "time,heartrate,velocity_smooth"}
        ]
        assert results == []

    def test_accepts_list_shaped_streams(self):
        run = {
            "id": "i9",
            "name": "Long",
            "sport_group": "run",
            "moving_time_s": 5400,
            "start_utc": "2026-03-01 06:00:00",
        }

        class StreamApi(FakeApi):
            def get(self, path, params=None):
                if "/streams" in path:
                    t, h, v = stream()
                    return [
                        {"type": "time", "data": t},
                        {"type": "heartrate", "data": h},
                        {"type": "velocity_smooth", "data": v},
                    ]
                return {}

        results = sync.compute_decoupling(StreamApi(), [run], dt.date(2024, 1, 1), 4500)
        assert len(results) == 1
        assert results[0]["decoupling_pct"] == 0.0
        assert results[0]["activity_id"] == "i9"
