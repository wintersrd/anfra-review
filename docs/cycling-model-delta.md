# Cycling model delta — anfra (canonical) vs Streamlit v2 (reference)

Two parallel builds extended the same semantic layer from the same spec. Per the
merge decision, the **anfra flow's extension is canonical and is what this repo
now carries**; the skill-built Streamlit app is merged as reference work and its
required model extension is **not** merged. This note is the reconciliation map.

## What is merged (canonical — anfra flow)

| Item | Content |
| --- | --- |
| `activities` dims | `ride_type` (road/virtual/mtb/gravel; EBikeRide & unmapped → NULL), `ftp_ref` (pure alias on per-activity FTP — null when unmeasured, so "FTP not configured" stays reachable), `decoupling` |
| Warehouse columns | `icu_ftp` surfaced from the raw payload into `activities` |
| Dataset metrics | `cycling_*` family (8 metrics) |
| Aggregation convention | weighted means weight and divide by the same column (moving/moving) |

## What the Streamlit v2 app additionally requires (not merged)

| Item | Streamlit v2 | Difference that matters |
| --- | --- | --- |
| Dataset metrics | `ride_*` family (12 metrics) | name family + 4 extra metrics |
| `weight_ref_kg` | **build-time warehouse column** (§8.5 carry-forward, 155/155 resolvable) | anfra computes carry-forward at render time — a SQL consumer cannot reproduce v2's W/kg without this column |
| `ftp_ref` semantics | `COALESCE(icu_ftp, build-time FTP constant)` via `CYCLING_FTP_WATTS` (default 250) | blends one assumed value into the column and makes "FTP not configured" unreachable; canonical keeps provenance pure |
| `EBikeRide` mapping | `road` (their decision D3 → road count 35) | canonical: NULL/excluded (road count 34) |
| `icu_ftp`, `work_kj` as dims | exposed | canonical exposes `icu_ftp` in the warehouse but not as an AML dim; work/KJ unused |
| Aggregation convention | several `ride_*` metrics weight by `moving_time_s` but divide by `total_time_s` (mixed denominator — flagged in review `01` A1; invisible on the fixture) | canonical is same-column consistent; the v2 oracle mirrors the same convention, so its equivalence suite pins it — parity, not truth |
| App constants | cadence buckets `<70, 70–80, 80–90, 90–100, 100+` (5) | canonical uses 6 buckets starting `<60` |

## Blast radius in this repo

- `streamlit_app/cycling_app.py`, `cycling_queries_aql.py` (live AQL over MCP),
  `cycling_queries.py` (SQL oracle) and their suites
  (`tests/integration/test_cycling_app_apptest.py`, `test_cycling_equiv.py`,
  `test_cycling_oracle.py`) are merged **verbatim** but skipped via
  `tests/integration/conftest.py` — they compile queries against `ride_*`
  metrics and query `weight_ref_kg`, neither of which exists in the canonical
  layer.
- The v2 build's own `models/`+`datasets/`+`scripts/` diffs were **not** merged;
  they live on branch `cycling-streamlit` if reconciliation wants them side by
  side.

## Reconciliation checklist (one owner, one afternoon)

From the comparison's recommendation (`docs/reviews/cycling-final/03-recommendation.md`,
"Housekeeping, updated"):

1. Pick one metric family name (`cycling_*` vs `ride_*`).
2. Decide EBikeRide: `road` (35) vs NULL (34).
3. Decide cadence bucket edges (5 vs 6 buckets).
4. Prefer the warehouse `weight_ref_kg` carry-forward (reproducible; review `02` A3)
   and add it to the canonical sync script.
5. Prefer the pure-alias `ftp_ref` (provenance + reachable case-3) over the
   `COALESCE` constant.
6. One denominator convention (moving vs elapsed) across metrics *and* their
   descriptions — both builds carry a formula/description drift.
7. Re-point the Streamlit data layers at the reconciled model, un-skip the three
   suites, and let the oracle-equivalence gates prove the lift.
