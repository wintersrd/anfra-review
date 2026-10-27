"""Integration-suite configuration.

The skill-built Streamlit cycling app (``cycling_app.py`` + ``cycling_queries*.py``)
is merged as *reference work* against the canonical (anfra-flow) semantic layer.
Its data layer requires the v2 Streamlit model extension — ``ride_*`` dataset
metrics, the ``weight_ref_kg`` warehouse column, ``work_kj`` — which was
deliberately NOT merged (see ``docs/cycling-model-delta.md`` for the full delta
and the reconciliation checklist).

Until that reconciliation lands, the three suites below are skipped wholesale
via this central hook so their code stays byte-identical to the branch they
came from (``cycling-streamlit``). Remove the entries to run them against a
reconciled model.
"""

from __future__ import annotations

import pytest

REFERENCE_ONLY_FILES = (
    "test_cycling_app_apptest.py",
    "test_cycling_equiv.py",
    "test_cycling_oracle.py",
)

_SKIP_REASON = (
    "reference build: requires the unmerged v2 Streamlit model extension "
    "(see docs/cycling-model-delta.md)"
)


def pytest_collection_modifyitems(config, items):
    del config
    for item in items:
        if str(item.location[0]).replace("\\", "/").rsplit("/", 1)[-1] in REFERENCE_ONLY_FILES:
            item.add_marker(pytest.mark.skip(reason=_SKIP_REASON))
