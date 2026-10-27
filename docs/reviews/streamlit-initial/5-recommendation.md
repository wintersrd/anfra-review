# Deployment recommendation

**Question**: should a data team deploy (a) anfra standalone for data
applications, or (b) anfra as application backend + Streamlit for building
data applications? Hosting assumed solved in both cases; the lens is the
experience of building and managing apps.

## Recommendation

**Deploy anfra standalone (a) as the platform default.** Make the
`build-data-app`/HTML path the standard way stakeholders get data apps.
Keep **(b) — anfra backend + Streamlit — as a sanctioned exception tier**
for apps whose needs are genuinely not dashboard-shaped (input forms, file
ingestion, modeling loops, multi-step flows), owned by users who accept a
heavier process. If forced to choose exactly one: **(a)**.

## Why

**1. The A/B's biggest failure happened on the Streamlit side of the fence,
and the anfra path is structurally armored against it.** The decisive
correctness error in this comparison — a stale 240 W FTP constant silently
mis-zoning every power metric by ~4 % — arose because an app-first build
treats the warehouse as given. The skill's AML-first discipline (*if a
number has no field, add it to the AML — don't compute it in presentation
code*) forces raw-data interrogation before app code exists, and it found
the real per-activity FTP. Definitions-first is the correct default for a
platform that exists to be a semantic layer.

**2. The anfra path's costs are mostly one-time or tooling-closable; the
Streamlit path's costs are per-app and structural.**

| Gap in the anfra-native path | Closeable by |
|---|---|
| Numeric definitions verified once, manually, not under committed test | Port the SQL-oracle/equivalence pattern into the per-app test harness (the running repo already proves the pattern; the SSR harness shows per-app node tests are feasible) |
| Browser acceptance is manual | Add a headless app driver to the harness (drive controls/cross-filter against the sandbox; the SSR harness is halfway there) |
| KPI logic can leak into app JS (K2 Monday slicing) | Platform lint: flag non-trivial expression logic outside `explore{}`; or provide the K2-style week math as an AQL idiom |

The Streamlit path's costs — a second runtime per app, no app sandbox or
hygiene enforcement, env/port plumbing, per-app acceptance automation to
build, a definition surface spread across dataset + two Python layers —
recur for every app and every app count. Ten apps on path (a) is one
process and ten reviewable files; ten apps on path (b) is ten processes,
ten dependency stacks, and ten trust commitments of arbitrary Python.

**3. The compounding properties favor the platform path.** Central
definitions guarded once (C3), ground truth surfaced into the governed
layer for every future app (C6), enforced app security posture (C4), a
guided design-agreement and change-request protocol for non-technical
builders (D1/D2), instant publish and discovery (D3). These advantages
*grow* with the number of apps; the Streamlit path's advantages (general
ceiling, mainstream stack, cheap automation) are static per app.

**4. What the Streamlit tier is still for.** The evidence also shows what
(b) buys when needed: a general UI framework, the strongest test tooling in
this comparison (AppTest full-app execution; the only automated acceptance
between the two builds), and a transferable stack. Keep it available —
gated by platform-owner review precisely because it bypasses the sandbox
and the single-definition discipline.

## Conditions for choosing (a), from this A/B's lessons

1. **Semantic-layer changes get a single gatekeeper.** Two parallel builds
   forked the AML (`cycling_*` vs `cycle_*`, `ftp_ref` vs constant-FTP
   approach). App builds may *propose* AML extensions; only the platform
   team lands them. Merge the two cycling metric families into one before
   either app is canonized.
2. **Raw-source regeneration is a platform action**, not an app-PR side
   effect (the `data/raw/activities.csv` rewrite was correct content at the
   wrong gate).
3. **Fund the definition-assurance harness** (equivalence tests) and a
   headless app driver, or the manual-acceptance and untested-numbers gaps
   will quietly erode trust in the platform path — the Streamlit build
   demonstrated exactly the assurance bar stakeholders should get by
   default.
