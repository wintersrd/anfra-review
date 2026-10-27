# Complimentary review — data platform owner's perspective
## Where the anfra + build-skill + HTML build is superior to the Streamlit build

### C1. Data fidelity: it found the truth in the raw data; mine settled for a constant

The single most consequential difference. The anfra build interrogated the
raw NDJSON, discovered per-activity `icu_ftp` (present on 154/155 rides, 4
distinct values, 240→250 W over time), extended the sync script + model
(`ftp_ref`), and implemented spec §8.1 **case 1**: real per-activity FTP,
K1 showing the actual current 250 W, and %FTP zones / IF / K4 computed
against the FTP that was in effect on each ride.

My Streamlit build asked the spec owner to choose an FTP *constant*; the
owner picked 240 W — without being told the real per-ride values existed in
the raw layer, because my reconnaissance never looked past the warehouse
columns (`icu_ftp` wasn't in `ACTIVITY_COLUMNS`). Result: my K4/C7/C8/C9 are
systematically ~4 % mis-zoned against the truth. The owner's decision was
informed by an incomplete picture — the failure is mine, and the AML-first
workflow is what structurally prevented it on the other side: the skill's
step 1 says, in effect, *if a number the app needs has no field, add it to
the AML* — forcing raw-data interrogation *before* app code exists. My
app-first path treated the warehouse as given.

### C2. Deeper, committed data understanding

Their WORKLOG root-caused what my build only patched around: the 88
distance-less rides are **HR-only indoor TrainerDay sessions** (watch-recorded,
no GPS/power) — which is *why* weekly distance has NaN weeks, why cadence
density is 122-not-86 rides, and why denominator guards matter. They also
pinned the weight-carry-forward endpoint (last weight 2026-01-05 → W/kg
carry-forward is genuinely load-bearing for 2026 rides). My tests *handle*
these cases (NaN weeks allowed, >40 rpm guard); their recon *explains* them.
For a data owner, the second is what future apps are built on.

### C3. Definitions centralized in the semantic layer, guarded once

Their `cycling_*` family (10 metrics, `running_analytics.dataset.aml`)
encodes the ride population guard (`ride_type is not null`) and null-field
denominator guards **once**; the app's queries just reference metrics. My
build expresses guards in the dataset metrics *and* re-expresses them in the
AQL query layer *and* again in the SQL oracle — three places to keep aligned
(the equivalence suite catches drift, but the alignment labor never ends).
Their single-definition property is precisely the "semantic layer as single
source of truth" the platform exists to provide.

### C4. Platform-enforced app hygiene — the app cannot misbehave

`anfra validate`'s data_app checks + the serving sandbox give the platform
owner, for free and without review: SRI-hash-pinned CDN scripts (a library
changed at its CDN fails to load rather than runs beside reader data), a
network-blocked frame (no `fetch`/XHR/WebSocket beyond the CDN allowlist), no
`localStorage`/cookies/forms/iframes, no local file references. The app is a
*static artifact with a security posture*. A Streamlit app is arbitrary
Python with ambient network access — every app is a trusted-code commitment;
the platform can enforce nothing about it.

### C5. Operational simplicity: one process, one artifact, no plumbing

The anfra build adds an app by adding a file to `apps/`. No per-app process
to supervise, no port, no env var, no dependency install on a host, no
second health thing to monitor — the semantic server it needs is already
running. My Streamlit app requires the anfra server *and* a Streamlit
runtime *and* correct `ANFRA_MCP_URL` wiring (a real, recurring friction
source in this very session, independent of the port collisions). At ten
apps, that's ten extra moving parts on the Streamlit path and zero on the
anfra path. The app is also one reviewable 1,596-line artifact — vs a
~3,100-line multi-module Python footprint — and `anfra serve` hot-reloads it
on every file/AML change.

### C6. Raw truth surfaced once benefits every future app

By landing `icu_ftp` in the warehouse (with a density fingerprint test:
154/155 rides, 220–250 W, 4 distinct), the next app — whatever path it takes
— inherits correct FTP for free. My build's derived-at-build-time `ride_type`
(left the committed raw data untouched — lower churn, true) also means every
future consumer must re-derive or re-import it. Surfacing ground truth into
the governed layer is the platform-correct direction of travel.

### Caveats (keeping this honest)

- **The AML extension governance gap is the platform's own finding**: two
  parallel builds extended the *same* shared AML independently — `cycling_*`
  vs `cycle_*`, `ftp_ref` vs nothing, `decoupling` vs `hr_decoupling` dims —
  producing two divergent metric families for identical concepts. Whichever
  path deploys, semantic-layer changes need a single owning gatekeeper; app
  builds must not fork the definition layer.
- C6's mechanism (regenerating committed `data/raw/activities.csv` inside an
  app PR) worked here but is the wrong gate: raw-source regeneration should
  be a platform-team change, not an app-build side effect.
- The correctness win (C1) came from the *skill's AML-first discipline*, not
  from HTML vs Python — evidence that the discipline, not the renderer, is
  the asset (see recommendation).
