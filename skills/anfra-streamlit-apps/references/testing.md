# The gate suite

Acceptance is automated or it is folklore. Four layers, each with a fixed
shape; copy from [example/](example/) rather than reinventing.

## 1. Fixture conftest (repo `tests/conftest.py`)

```python
@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory):
    """Build the warehouse from committed data/raw via the sync script."""
    db = tmp_path_factory.mktemp("db") / "fixture.duckdb"
    sync.build_db(raw_dir=REPO / "data" / "raw", db_path=db, write_reader=False)
    return db

@pytest.fixture(scope="session")
def fixture_conn(fixture_db):
    return duckdb.connect(str(fixture_db), read_only=True)

@pytest.fixture
def oracle_mod(fixture_conn, monkeypatch):
    """Oracle reads the fixture, not the dev reader snapshot."""
    import <name>_queries as oracle
    monkeypatch.setattr(oracle, "get_conn", lambda: fixture_conn)
    return oracle
```

The oracle's `get_conn()` opens the reader snapshot read-only, path
overridable by `$<NAME>_DB` (that's how AppTest points the app at the
fixture). `FileNotFoundError` → message with the rebuild command.

## 2. Unit layer (server-indifferent, fast)

- Constants pinned: bucket labels/order (en-dashes!), enums, thresholds —
  **and the oracle ↔ live-layer duplicates equal**.
- Pure helpers: filter-clause builders, bucket-case generators, env parsing
  (`"300"→300`, `""→None`, `"0"→None`, garbage→default), theme token contract
  (same keys both dicts; registers match ORDER; fallback to muted).
- Theme tests must not import half the app: keep `theme.py` import-light.

## 3. Equivalence: oracle ≡ live layer (server up)

Marker the repo uses for live MCP tests (e.g. `anfra`); skip with a reason
when `get_client().ping()` is false or `ANFRA_LIVE_TESTS=0`:

```python
pytestmark = [pytest.mark.integration, pytest.mark.anfra]


@pytest.fixture(scope="module", autouse=True)
def _require_server():
    if os.environ.get("ANFRA_LIVE_TESTS") == "0":
        pytest.skip("live tests disabled")
    try:
        aql.get_client().ping() or pytest.skip("anfra serve not reachable")
    except Exception as exc:
        pytest.skip(f"anfra serve not reachable: {exc}")
```

Cases: **default window, empty window, narrowed filter** — every data
function, oracle vs live, column names and row content. Normalization before
compare (`_norm`): day-grain strings sliced `[:10]`, numerics coerced via
`pd.to_numeric` (so `'0' == '0.0'`), NaN↔None↔empty handled, and **sort by
the natural key plus numeric columns** before asserting equality — duplicate
natural keys (two same-day same-name activities) otherwise pair
non-deterministically and the suite flakes.

## 4. The full-app gate (AppTest — the acceptance test)

```python
from streamlit.testing.v1 import AppTest


def _fresh_app() -> AppTest:
    return AppTest.from_file("streamlit_app/<name>_app.py", default_timeout=120)
```

Scenario checklist — run the default first, then **rerun** variants (mutate
via `at.sidebar.date_input[0].set_value((d1, d2))`, `at.multiselect[0].set_value([...])`,
env flips, `at.session_state` pre-seeds):

1. **Default run**: `at.run()` → `assert not at.exception`; the expected
   `at.metric` count and labels; sidebar contract present (preset radio
   default, date input, multiselect); `at.session_state["load_log"]` has the
   expected component keys, no `rows == -1`; **no `st.error`** in the tree.
2. **Empty window**: date range in a data-free era → no exception, friendly
   states (not zeros).
3. **Narrowed filter**: type/category-only → the type-honoring components'
   load-log rows shrink or empty-state; date-only components unchanged.
4. **Feature fallbacks**: e.g. unset constant (`os.environ["X"]="0"` +
   `finally: pop`) → the dependent sections show the not-configured state.
5. **Cross-filter focus**: pre-seed `at.session_state["focus_…"]`, rerun →
   banner present and the filtered components changed; an empty selection
   *clears* a pre-seeded focus (that is the observable deselect behavior —
   AppTest cannot click plotly marks).

Streamlit emits a `SessionStateWarning` for `date_input` keys on fresh runs —
same as the production app pattern; assert on state, not on warnings.

## 5. Server up/down matrix (know which half you ran)

| Layer | `anfra serve` | Why |
| --- | --- | --- |
| unit | indifferent | pure Python |
| oracle integration (fixture) | indifferent | reads fixture DuckDB |
| equivalence + AppTest gates | **up** | live MCP queries |
| CLI-anfra layers (`tests/anfra/`, chart SSR) | **down** | server holds the warehouse lock |

Every live suite skips with a reason when its precondition fails; use
`ANFRA_LIVE_TESTS=0` to force the down-half. A green run of only one half is
not a green run — record in the worklog exactly which halves ran, with the
serve port (`ANFRA_MCP_URL`) if pinned.

## 6. Repo gates + commits

- `uv run ruff check .` and `ruff format --check .` clean; `mypy` clean (new
  code; pre-existing failures verified at base and noted, not silently
  inherited); pre-commit green; coverage floor per `pyproject.toml`
  (`--cov-fail-under`, `--no-cov` for partial marker runs).
- `anfra validate` after AML changes; restart serve after warehouse rebuilds.
- Commit order that keeps every commit green (each adds its tests):
  semantic layer → oracle + fixture tests → live layer + equivalence →
  app + AppTest gate + unit tests → docs/worklog.
- **Pre-commit stash gotcha**: hooks stash unstaged *tracked* files but
  untracked files stay — a partial stage can make the unit layer run against
  a half-tree and fail on missing symbols. Stage everything the unit layer
  imports (theme, constants modules) in the same commit as the tests that
  import them.
- Worklog final entry: the gate table with exact numbers ("278 passed, 25.7s,
  coverage 88.86%; serve on :7879; halves: unit+fixture+live+CLI all run").
