# Cycling build experiment — synthesis

Three agent builds executed the same technology-agnostic spec
(`docs/cycling-app-spec.md`, K1–K4 + C1–C17) from the same base commit (`989eb9a`),
plus a follow-on skill experiment. This document combines their findings into one
place; the per-flow evidence lives in the files referenced throughout.

| # | Flow | Where it happened | Product | Outcome merged here |
| --- | --- | --- | --- | --- |
| 1 | anfra-native (skill-guided) | `~/repositories/cycling-anfra` (`cycling-anfra`) | `apps/cycling.html` — 1,596 lines, 21 AQL queries, 17 charts + 4 KPI tiles | **merged, canonical model** |
| 2 | Streamlit, unguided (pre-skill) + **skill creation** | `~/.local/share/opencode/worktree/518d31/cycling-app` (`feat/cycling-app`) | `streamlit_app/cycling_*.py` v1 (~3,100 lines w/ tests) — **superseded, not merged**; authored the `anfra-streamlit-apps` skill | **skill merged**; app + reviews kept as record |
| 3 | Streamlit, rebuilt with the skill (the A/B variable) | `~/repositories/cycling-streamlit` (`cycling-streamlit`) | `cycling_app.py` + `cycling_queries_aql.py` (live) + `cycling_queries.py` (SQL oracle) + gates | **merged as reference**; requires its own model extension (`docs/cycling-model-delta.md`), suites skipped until reconciled |

Original review docs are preserved verbatim:

- `docs/reviews/streamlit-initial/` — flow 1 vs 2 comparison (6 reviews + README
  with method/ground-rules), including `6-streamlit-skill-hypothesis.md`, the
  counterfactual that motivated flow 3.
- `docs/reviews/cycling-final/` — the v2 re-review against the skill-built build
  (adversarial, complimentary, deployment recommendation, simulation-apps addendum).
- Work logs: `docs/worklogs/{streamlit-initial,cycling-anfra,cycling-streamlit-v2}.md`.

## The A/B result: what the skill changed

Same builder ecosystem, same spec, same warehouse — one variable (the
`anfra-streamlit-apps` skill). From `docs/reviews/cycling-final/01`/`02`/`03`:

1. **The skill closed the fidelity gap.** The unguided build's headline defect —
   a 240 W typed-constant FTP on data where per-activity `icu_ftp`
   (154/155 rides, 220–250 W) existed all along — is gone; the skill's mandatory
   raw-payload interrogation found the column. Headline KPIs then **reconciled
   exactly across the two independent codebases** (K1 250 W; K2 29.7026 vs 29.70;
   K3, K4, road-speed identical) — the strongest validation either build got.
2. **Verification widened the Streamlit lead.** 43 equivalence tests + 27 pinned
   fingerprints + a constants-pinned-between-layers test + a 5-scenario AppTest,
   300 passed / 0 skipped, 88.72% coverage — vs the anfra build's one-time
   interactive reconciliation plus structural gates (validate-clean, 22/22 query
   execution, 17/17 headless SSR render).
3. **But prose rules don't govern models.** The skill's same-column denominator
   rule existed — and the v2 AML still mixed moving-weighted numerators with
   elapsed-time divisors, because the rule lived in the layer-parity section and
   never governed AML authoring. The oracle mirrored the convention, so 43 green
   equivalence tests pinned the slip: **parity, not truth**. The anfra build
   carried the mirror bug (metric descriptions saying "moving" over elapsed
   formulas). The missing piece in both paths: a model-review step where
   conventions are decided once, written into definitions, and diffed.

## Process comparison (headline facts)

| | anfra-native | Streamlit initial (unguided) | Streamlit v2 (skill) |
| --- | --- | --- | --- |
| Gates | `anfra validate` clean; 22/22 queries execute; 17/17 SSR render; pytest 152✓/65 skip | AppTest 5 scenarios; 25-case equivalence; pytest 278✓; coverage 88.86% | AppTest 5 scenarios incl. cross-filter seed + clear; 43 equivalence + 27 fingerprints; pytest 300✓/0 skip; 88.72% |
| Structure | one HTML file (by design) | 3 app modules + oracle + theme | same shape, skill-mandated declaration table + decision register D1–D14 |
| Data recon | found `icu_ftp` (skill step 1) | missed it → 240 W constant (fixed in v2) | found it (skill-mandated interrogation) |
| Design agreement | 4 crisp decisions pre-build | 2 mid-flight questions | numbered decision register before implementation |
| Iteration loop | edit → SSR → "please check in browser" | edit → AppTest green | edit → AppTest green (gates caught NaN truthiness, Timestamp window skew, NULL-vs-0 semantics) |

## Where each tier won (quality synthesis)

- **anfra-native won fidelity + governance**: per-activity FTP used as measured;
  denominator-consistent math; definitions in AML + page AQL only; sandbox, SRI,
  structure markup, Inspect panel, `/apps/` listing, live reload — "physics, not policy".
- **Streamlit won verification + ergonomics**: committed suites that re-pin every
  number on every run; full-app headless gate; typed data layers; the whole Python
  ecosystem (analyst ceiling); native widgets; session persistence; injectable
  `today` / fixture-DB reproducibility.
- **Neither win was caused by the tier alone** — and the skill experiment showed the
  quality floor is portable (~70% of deltas were skill-borne), while enforcement
  posture (sandbox/definitions-by-physics/one artifact) vs capability/assurance
  (AppTest/pytest/typing) is technology-borne (`streamlit-initial/6-…hypothesis.md`).

## Deployment recommendation (final form)

Condensed from `docs/reviews/cycling-final/03-recommendation.md` (+ addenda `04`,
BI-tool-first, Holistics context) and `streamlit-initial/5-…recommendation.md`:

1. **The semantic layer is the substrate, full stop** — both builds converged on it
   independently; one Streamlit build was redirected onto it mid-flight and its
   failures were all definitional.
2. **anfra-native (HTML tier) is the default for governed custom apps** — the
   BI-overflow class a fixed chart vocabulary can't express; in a Holistics org
   that wedge largely collapses into the platform itself (AML/AQL is Holistics'
   own modeling language, with agentic authoring + MCP/API semantic-layer access).
3. **anfra backend + Streamlit (the skill tier) is a credible first-class tier** —
   no longer merely an escape hatch — for Python-fluent builders and
   analysis/computational apps, under obligations: definitions in AML never app
   code, metric changes through model review, oracle-equivalence + full-app gates
   as standard CI. Simulation-class apps: public-input simulators are
   Streamlit/Hex by architecture; private/parameterized simulators are the skill
   tier at full strength (parameters in, results written back, only compute in
   Python) — `04` §5.
4. **Adopt the Streamlit build's two disciplines platform-wide**: oracle
   equivalence suites for every new metric family, and a full-app headless gate
   (an "AppTest for anfra apps" — the node chart harness is 70% of one).

## Merge housekeeping (blocking clean reconciliation)

See **`docs/cycling-model-delta.md`** — the canonical-vs-v2 model difference and the
seven-point checklist: one metric family, EBikeRide mapping, bucket edges,
warehouse weight carry-forward, pure-alias `ftp_ref`, one denominator convention
(including descriptions), then un-skip the three reference suites and let
equivalence prove the lift.
