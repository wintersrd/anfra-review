"""SQL fragment builders and shared constants of the query layer."""

from __future__ import annotations

import pytest
import queries


@pytest.mark.unit
class TestClauses:
    def test_empty_means_no_filter(self):
        assert queries._sport_clause(()) == "1=1"
        assert queries._surface_clause(()) == "1=1"

    def test_single_and_multi(self):
        assert queries._sport_clause(("run",)) == "sport_group IN ('run')"
        clause = queries._surface_clause(("road", "trail"), col="a.run_surface")
        assert clause == "a.run_surface IN ('road', 'trail')"

    def test_custom_column(self):
        assert queries._sport_clause(("ride",), col="b.sport") == "b.sport IN ('ride')"


@pytest.mark.unit
class TestPaceBuckets:
    def test_ordering_constants(self):
        labels = queries.PACE_BUCKETS
        # fast -> slow, unknown last (bucket_num -1); en dashes in range labels
        assert labels[0] == "<4:00"
        assert labels[-1] == "unknown"
        assert (
            labels.index("4\u20135")
            < labels.index("5\u20136")
            < labels.index("6\u20137")
            < labels.index("7+")
        )
