# Addendum — simulation and analysis apps (the race-planners test case)

Prompt for this addendum: the head-to-head comparison (`01`–`03`) evaluated a
data-**visualization** dashboard. But data apps — as positioned against
Streamlit and Hex — exist for **simulation and analysis**. Does the analysis
hold for that class? Evidence examined: `~/repositories/race-planners`, a
production Streamlit planning app (race pacing/fueling simulation).

---

## 1. What race-planners actually is

| Aspect | Fact |
| --- | --- |
| Shape | ~5,690 lines Python: **~4,200 lines pure domain core** (pacing models per race type, fatigue curves, fueling blocks, grade-adjusted pace from GPX — haversine, elevation smoothing, weighted grades — weather heat multipliers, guardrails) + **~1,485 lines Streamlit rendering** |
| Dependencies | `streamlit`, `numpy`, `pandas`, `matplotlib` — **no warehouse, no SQL, no semantic layer** |
| Tests | **84 tests over the domain core** (pacing models, fatigue, grade, fueling, guardrails, edge cases) — the models are the product; the test suite is its quality asset |
| Interaction | Two input modes including an **inverse problem** (target finish time → solve pacing, vs effort anchor → forward simulate); 30+ sliders/selects/number inputs; tabs; session-state choreography (event switch invalidates dependent keys) |
| I/O & persistence | `file_uploader` ×2 (reload plan JSON, athlete profile), `download_button` ×2 (plan export) |
| i18n | 822 lines, FR/EN |

## 2. Scoring it against the anfra HTML Data App tier

Not "worse ergonomics" — **architecturally out of scope**. The sandbox rules
that serve governed dashboards disqualify simulation apps by construction:

- **No computation libraries**: numpy/matplotlib (and scipy, scikit-learn,
  any solver) are unreachable; CDN JS only. The 4,200-line core would need a
  from-scratch JS rewrite — orphaning the 84-test suite, which is the app's
  entire quality story. (A Pyodide-in-sandbox stunt embeds the core as an
  untested string inside an HTML file: worse than the disease.)
- **No user file ingest**: the skill's law is *data comes only from the
  SDK*; GPX course upload and JSON profile/plan round-trips have no path.
- **No persistence**: `localStorage`/cookies throw in the sandbox; plan
  download/reload semantics don't exist.
- **No forms**, hand-rolled i18n, session resets on frame reload.

Meanwhile the anfra tier's advantages from the dashboard comparison **evaporate
here**: A1/A2/A3 (data fidelity, denominator drift, definitions leaking into
app code) *cannot arise* — there is no shared metric layer to drift. What
survives is real but peripheral: if the event catalog, course library,
athlete profiles, and saved plans became anfra **datasets**, the simulation
gains governed catalogs, lineage, and provenance for its inputs/outputs.
That is a data plane around the compute — useful, not substitute. (For the
private/individual variant, that data plane stops being peripheral — §5.)

## 3. Revised taxonomy (three classes, not two)

| Class | Example | Winning tier | Why |
| --- | --- | --- | --- |
| (a) Governed dashboards / self-serve views | the cycling app | **anfra HTML** | fidelity + governance surfaces + productized loop; recommendation unchanged |
| (b) Warehouse-backed computational apps | the cycling **Streamlit** build | **anfra + Streamlit** (the `anfra-streamlit-apps` skill) | computation over governed metrics; oracle ≡ live equivalence is meaningful because a warehouse exists to be equivalent to |
| (c-pub) Simulation apps, **public inputs** | race-planners as built | **Streamlit/Hex — anfra app tier not a candidate** | domain core in Python + tests is the product; sandbox rules exclude the HTML tier structurally; the MCP data layer is optional, not foundational |
| (c-priv) Simulation apps, **individual/private** (§5) | a private race-planners | **anfra + Streamlit — the strongest form of (b)** | parameters flow IN from the semantic layer, results flow OUT via write-back; only the compute stays Python; the data plane is load-bearing, not optional |

Note the seam between (b) and (c): in (b) the oracle/equivalence gate is the
heart of quality; in (c) there is **nothing to be equivalent to** — the
domain core's own test suite *is* the contract. race-planners already
embodies the right (c) pattern: pure core + thin UI + full pytest on the
core + Streamlit smoke tests. An `anfra-streamlit-apps` build in class (c)
keeps the skill's *discipline* (worklog, four states, load log, AppTest,
theme tokens) but drops oracle/equivalence as inapplicable.

## 4. Effect on the analysis and recommendation

**The recommendation's core survives — it was explicitly scoped to (a)/(b)
("the population of apps this exercise represents") — but three amendments:**

1. **"Escape hatch" was too coarse.** `03` stretched one Streamlit tier to
   cover "computational apps" generally. Class (c) is not an escape hatch
   from the anfra default; it is a category where the anfra app tier is
   absent. A data team should not apologize for Streamlit here or wrap it in
   anfra obligations that reference metrics it doesn't have. The obligations
   that DO carry into (c): definitions-in-a-reviewed-place, worklog,
   four states, full-app gate.
2. **Positioning honesty requirement.** If the platform is marketed as a
   Streamlit/Hex alternative *for apps*, the HTML Data App tier alone does
   not reach classes (b)/(c). Getting there means a **server-side compute
   tier** (executing builder Python under platform governance — the thing
   Hex actually is), not more sandbox capability: the sandbox can never
   host arbitrary libraries, file ingest, or persistence. Until such a tier
   exists, the honest claim is: *governed data apps (a), the governed bridge
   for warehouse-backed Python apps (b), and the data plane — catalogs,
   profiles, plan provenance, write-back — around other people's simulations
   (c).* That data-plane play (hosting event catalogs/athlete profiles/plans
   as governed datasets with lineage) is the differentiated thing anfra
   could add to a race-planners-class app today.
3. **The skill-quality conclusion partially transfers — with one hard limit.**
   The process disciplines (declaration list, worklog, gates, four states)
   improve any tier, and a class-(c) Streamlit skill is worth having on the
   `race-planners` template. But the earlier conclusion "biggest issues came
   from skill quality, not technology" inverts here: **no skill can port a
   tested Python domain core into a JS sandbox without losing the tests —
   that gap is technology, and it is the whole gap.**

## 5. Owner correction — the private/individual case: the data → application seam

**Premise corrected by the owner**: race-planners is public *by design* —
hence raw manual inputs. A private/individual version **would** lean on the
underlying database: pace data, LTHR, FTP, and even the technical-terrain
slowdown factors are derivable from training history. The data layer is not
the open question — it should be the semantic layer. The question is the
**data → application aspect**: how governed data flows into and is consumed
by a simulation app. That seam is where the platform wins or loses this
class, and the dashboard head-to-head already contains its miniature.

### 5.1 The miniature: the FTP story *is* this seam

The public app asks the athlete to type their FTP. The recorded Streamlit
build shipped **240 W — a typed constant** — on data where per-activity
measured FTP (`icu_ftp`, 154/155 rides, 220–250 W) existed all along; the
anfra build declared `ftp_ref` and showed **250 W measured**. A manual
input surviving unchanged into a DB-backed world is precisely that mistake.
The private race-planners rule follows: **every DB-derivable model input is
a declared metric, never a literal in the core** — `athlete_ftp`,
`run_lthr`, threshold pace, `technical_descent_penalty`, fade parameters.
The core receives them as constructor arguments; it never queries.

### 5.2 Parameter estimation is a definition, and definitions drift

"Current LTHR" is an estimation *policy* (max of test activities? rolling
percentile of hard intervals?), and so is "technical-terrain slowdown
factor" (segment-pace regression over historical technical vs rolling
terrain — derivable from the warehouse's activity history, as is fade from
the 84 rides carrying `decoupling`). These policies are exactly the kind of
definition that drifted between apps in the dashboard comparison (A1/A3):
if they live in app Python, two apps compute two athletes. They belong in
the AML — versioned, lineage'd, reviewed — and note the new pattern they
force: today's metrics are **activity- or week-grain**; simulation inputs
are **athlete-grain** parameters ("the athlete's X as of date D"), a grain
the current layer barely exercises (`weekly_summary` is the closest).

### 5.3 Provenance and as-of semantics — the requirement dashboards don't have

A plan is a reproducible claim ("given my parameters on date X, 3 h 58 m").
Dashboards re-query live data and are always "current"; a simulation must
be re-runnable *later* against the parameters it was built on. The plan
artifact must therefore embed or reference a **parameter snapshot**: values
+ the metric names + the data generation behind them. anfra already exposes
the ingredients (compiled/executed AQL, generated SQL, dataset
fingerprints); what's missing is a first-class way to say "parameters as of
D" and to detect drift when a plan is re-opened months later. This — not
charting — is where **lineage becomes the killer feature for simulation**:
"why does my plan say hike this climb?" traces fade preset ← decoupling
history ← specific activities. The public app can only answer "because you
typed 12%".

### 5.4 Write-back closes the loop

Plans and results written back as datasets turn the simulator into a
longitudinal instrument: predicted-vs-actual splits become a *query*
(model calibration), iteration history accumulates, and the next plan
starts from what execution taught. The public app structurally cannot have
this; a warehouse-backed one gets it for free. Without write-back the
simulation is a dead end; with it, the platform gains the flywheel.

### 5.5 Manual inputs don't vanish — they become provenance-tracked overrides

Sliders remain, but their *defaults* come from the semantic layer and every
departure is recorded in the plan ("overrode LTHR 162 → 168, reason: heat").
Public mode is the all-overrides degenerate case of the same seam — one
architecture, graceful degradation.

### 5.6 Mechanics with today's stack

`anfra_client.query()` → a typed `AthleteParameters` dataclass → the pure
core. The 84-test suite is untouched (fixtures feed the same dataclass);
the oracle-equivalence gate now pins **parameter values** (LTHR, FTP,
slowdown factors) exactly as it pinned KPIs; the AppTest gate runs the app
on fixture parameters. The `anfra-streamlit-apps` skill needs one added
rule: *model inputs are declared metrics, never literals in the core* —
the simulation-grade restatement of "definitions live in AML".

### 5.7 Effect on the recommendation

Class (c) splits: **(c-pub)** stands as analyzed (Streamlit/Hex; anfra app
tier absent). **(c-priv)** is not an escape hatch — it is class (b) at
full strength: the semantic layer load-bearing in *both* directions
(parameters in, results out), only the compute tier staying Python. The
positioning vs Hex improves accordingly: for private/individual simulation
apps, anfra owns exactly what Hex is weak at — governed parameter
definitions, provenance/as-of semantics, lineage, write-back — and concedes
only hosted compute (still conceded, until a governed compute tier ships).

**Bottom line:** the dashboard head-to-head answered which tier should host
*governed metric consumption*; race-planners shows the boundary of that
answer. Recommendation unchanged for (a)/(b); for (c-pub) — simulation with
public inputs — Streamlit/Hex-class tooling wins by architecture. For
(c-priv) — the individually-parameterized simulator the owner actually
wants next — the seam is data → application: declare the athlete's
parameters as governed metrics, snapshot them into every plan, write the
results back, and keep only the simulation itself in Python. The platform's
play is to own the parameters and the provenance around the simulation,
not the simulation itself, until it ships a governed compute tier.
