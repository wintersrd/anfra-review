# Adversarial review — data platform owner's perspective
## Where the Streamlit build (this repo) is superior to the anfra + build-skill + HTML build

Persona: the data team. Owns the warehouse, the semantic layer (AML), the
definitions, data quality, and the operational management of everything
downstream. Reviews dated 2026-10-26; evidence from both builds' artifacts.

### A1. Definition assurance is committed and repeatable — not a one-time dev ritual

The Streamlit build ships a **SQL validation oracle**
(`streamlit_app/cycling_queries.py`) and a **25-case automated AQL↔SQL
equivalence suite** (`tests/integration/test_cycling_aql_equiv.py`) covering
every component (17 table cases + KPIs, on two windows, with deterministic
key/numeric sorting). Any future change to AML, dataset metrics, or the
query layer re-runs this contract in CI/pre-commit.

The anfra build's numeric cross-checks were **manual and uncommitted**: its
WORKLOG records careful one-time SQL verifications (FTP 250 W, K2 weekly rows
mean, C21/C22 count ties), but the committed tests only assert that queries
*execute* (`test_anfra_queries_cycling.py`, 34 lines) and that charts
*render* (`test_chart_render_cycling.py`). Nothing pins the *numbers* a
reader sees to an independent definition. For a data owner, definitions under
perpetual test beat definitions verified once during development.

### A2. Full-app acceptance is automated, not delegated to human eyeballs

The Streamlit gate (`tests/integration/test_cycling_app_apptest.py`) executes
the real application script end-to-end in five scenarios: default load,
empty-window rerun, FTP-unconfigured state, cross-filter clear-on-deselect
(H1 regression), and virtual-only filter narrowing (AC3) — asserting zero
exceptions, the KPI contract, sidebar defaults, and a healthy per-component
load log.

The anfra build's own WORKLOG concedes the gap: *"Browser-level acceptance
(§9) needs human eyes — asked the user to verify per the checklist."* Its SSR
harness proves charts don't throw on real data — a strong check — but no
committed test drives the controls, the cross-filter state machine, or the
four render states. Every future change to the HTML app carries a manual
QA liability; the Streamlit change re-runs its gate in seconds.

### A3. Metric logic lives in tested data code, not presentation JavaScript

K2 (this ISO week vs the mean of the 4 preceding complete ISO weeks) is a
spec-exact KPI definition. In the Streamlit build it lives in versioned,
unit-boundary-tested SQL (Monday `unnest` LEFT JOIN so zero-ride weeks count
as 0) and is equivalence-checked against the oracle. In the anfra build, the
query returns week-grain rows and **the exact KPI semantics are computed in
the app's JavaScript** (`currentMonday()` at `apps/cycling.html:505`, Monday
slicing at `:925`). A KPI definition embedded in presentation code is the
classic governance smell: invisible to the semantic layer, untestable by
`anfra validate`, and silently divergent if another app reimplements it.

### A4. Typed, linted, coverage-gauged application code

The Streamlit data layers are type-annotated Python under ruff + mypy +
pytest coverage (88.86 % overall; both cycling layers at 96 %). The anfra
app's logic is untyped JavaScript inside an HTML file; `anfra validate`
checks *hygiene* (SRI pins, no local refs) but nothing about logic. When a
data owner is asked "is this app's code sound?", one build answers with a
static-analysis + coverage report; the other answers with "the charts
rendered."

### A5. Test-environment independence and smaller blast radius on the shared repo

Streamlit tests build their own fixture warehouse into a temp dir from
committed raw data (`tests/conftest.py`) and point the app at it via
`CYCLING_DB`; the live tests take the server URL via `ANFRA_MCP_URL`. The
anfra build's `.anfra/data_sources.yml` points directly at its worktree's
hand-rebuilt DuckDB (its WORKLOG: "local path is load-bearing"), its CLI
query tests contend on the server-held DuckDB lock, and — more significantly
— it **regenerated committed raw data** (`data/raw/activities.csv`,
+1000/−500 lines, to add `icu_ftp`), shifting every downstream fingerprint in
the shared repo. Surfacing `icu_ftp` was correct (see complimentary review),
but the mechanism (rewrite the committed fixture source inside an app build)
is exactly the kind of change a data owner wants gated by the platform team,
not embedded in an app PR.

### A6. Reader-visible observability is a tested contract

Spec §9.9's data-load log is implemented in-app (per-component ms/rows, footer
expander) and **asserted by the gate** (≥20 entries, no failures). The anfra
app's observability is the skill-mandated `console.log` of `executedAql` on
first success (`cycling.html:898`) — developer-console only, invisible to
readers, and unchecked by tests.

### Caveats (keeping this honest)

- A1/A2/A4 are **process discipline, not Streamlit's intrinsic gift**: nothing
  about Streamlit forces an oracle or an AppTest; the anfra build *could* have
  committed its SQL cross-checks as tests. The fair claim is: the Streamlit
  ecosystem (pytest, AppTest, fixture patterns) made this rigor cheap and
  natural, while the skill path's checks ended at execution + render.
- The Streamlit build's own biggest failure (see complimentary review C1 —
  stale FTP constant) proves automation ≠ fidelity: its excellent test suite
  faithfully verified slightly wrong definitions.
