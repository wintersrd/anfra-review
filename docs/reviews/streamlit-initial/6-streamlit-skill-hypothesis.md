# 6 — Hypothesis: a Streamlit skill modeled on the anfra one

> Question under test (spec owner): "It seems that the biggest issues encountered
> come from the quality of the skill more than the technology. If we were to
> create a Streamlit skill, based on the anfra one, to guide development using
> Python instead of the HTML, how would that change the recommendation and
> speed/quality of build?"

This is a counterfactual analysis, not a build. Evidence base: the two A/B
builds (Streamlit, unguided but repo-conventioned; anfra-native, skill-guided)
plus the six review files. All port-collision and ops noise excluded, per the
ground rules in the README.

---

## 1. Premise check: skill-borne vs technology-borne

Splitting every material finding from the A/B by *cause* rather than by
*direction*:

| Issue | Borne by | Would a Streamlit skill close it? |
| --- | --- | --- |
| FTP gap on the Streamlit side (240 W constant vs real per-ride `icu_ftp` 240→250 W) | **Skill** — no mandated raw-payload interrogation before modelling | **Yes** — the anfra skill's step 1 (learn the datasets, AML first) is what found it; port verbatim |
| No design agreement on the Streamlit side (2 mid-flight questions vs their 4 crisp decisions) | **Skill** — step 2 is exactly this | **Yes** — ports cleanly; smaller widget surface makes the declaration list easier |
| UX floor: shape+color encoding, alarm tints, aria-live, empty states | **Skill** (DESIGN.md + rules); Streamlit gives native-widget aria largely free | **Yes** — rules port; some anfra specifics (Basecoat, sandbox CSS) become theme-token rules |
| Definition assurance: manual one-time cross-checks (anfra) vs committed oracle + 25-case equivalence suite (Streamlit) | **Split** — the anfra skill only *asks* for a manual headline check; the committed suite is this repo's convention, enabled by Python's test ecosystem | **Yes, and it upgrades both paths** — the ported skill should *mandate* the committed equivalence suite (the anfra skill's weakest instruction, made structural on the Python side) |
| Acceptance = human browser checklist (anfra) vs headless full-app gate (Streamlit) | **Technology** — AppTest exists for Streamlit; nothing equivalent drives an anfra frame today | N/A — this is the Streamlit structural advantage; the skill mandates it rather than invents it |
| Business logic in the view (their K2 Monday-slicing in JS) | **Technology-shaped, skill-preventable** — client-side rendering *invites* client-side math | **Yes, more easily** — "no week/zone/bucket math in the UI layer" is trivially followable in typed, tested Python |
| Business logic in the view, my version (zone thresholds in 3 places: SQL oracle, AQL layer, captions) | **Skill** (no single-source mandate) | **Yes** — port the rule: definitions live in AML, both layers *reference*, equivalence proves it |
| Sandbox, SRI, no-network, no-local-files enforcement | **Technology** — anfra physics | **No** — Python is arbitrary; best case is CI policy (banned-import checks), i.e. advice + lint, not physics |
| Definitions physically centralized (anfra app *cannot* bypass the semantic layer) | **Technology** — SDK-only data path | **Partially** — a repo test can fail on `import duckdb` inside `streamlit_app/`, which is surprisingly close to enforcement… but it is still policy |
| One process / one artifact / host Inspect panel / instant publish | **Technology** (platform) | **No** — approximated by an in-app diagnostics expander (my load log) and a canonical file layout; not host-native |
| Two-process runtime, port pinning, `ANFRA_MCP_URL` plumbing | **Technology** (mostly neutralized by the hosting-solved assumption, but the management surface remains) | **No** |
| General UI ceiling, mainstream stack, regression safety on change | **Technology** — Streamlit structural advantages | The skill inherits them for free |

**Verdict on the premise: substantially right on quality, wrong on trust.**
Roughly: every *correctness and UX* delta in both directions was skill-borne,
and a good Streamlit skill closes or flips most of them. The irreducible
technology core is about *enforcement and posture* (sandbox, single artifact,
definitions-by-physics, host integration) on anfra's side, and *capability and
assurance tooling* (AppTest, pytest, typing, ceiling) on Streamlit's side.

One subtlety worth naming: the anfra skill is good partly *because* the
technology is constrained — the sandbox forces rules to exist, the SDK state
model gives the skill something precise to describe. Porting the skill to an
unconstrained space ports the checklist but not the physics that made the
checklist cheap to follow. "Skill vs technology" is not fully separable; skill
quality was partly downstream of technological constraint.

## 2. The hypothetical skill (port map)

What a `build-streamlit-app` skill, modeled on `build-data-app`, would mandate:

1. **Learn the datasets** — `anfra show`, AML-first extension, **and raw-payload
   interrogation** (grep the NDJSON/CSV for undrilled fields — the `icu_ftp`
   lesson, now explicit).
2. **Agree on the design** — the declaration list restated for Python: every
   component as a named data-layer function returning a DataFrame, its filter
   line (date-only vs type-honoring), widget inventory, cross-filter source and
   targets, the four states rule (loading/success/error/empty-as-`st.info`).
3. **Definitions in AML only** — the live layer goes through `anfra_client`
   metrics; a SQL oracle twin is *required*, not optional; a committed
   equivalence suite proves them equal on fixture windows; every query runs
   headless before any UI exists.
4. **App skeleton from reference** — theme tokens, section/grid helpers,
   diagnostics expander with stable block keys (the Streamlit analogue of
   `data-anfra-block` handles + a mini Inspect panel), a11y rules (never
   color-alone; keyboard path for every pointer interaction — the multiselect
   already mirrors the donut).
5. **Gates** — AppTest scenario checklist (default / empty window / type
   filter / focus / theme toggle / FTP-unconfigured), equivalence suite,
   ruff+mypy+coverage floor, pre-commit; **CI policy tests**: no direct DuckDB
   imports in app modules, no date math outside the data layer, coverage floor
   enforced per app module.
6. **Handover** — user-terms description, block handles, WORKLOG.

What ports badly: the sandbox/CDN/SRI rules (no equivalent — become CI lint),
host Inspect/publish (become in-app diagnostics), single-file reviewability
(becomes a canonical multi-file layout), and enforcement itself (becomes policy).

## 3. Effects on speed and quality

**Speed, first build:** modestly faster than my unguided build (skeleton +
checklists remove the wandering: the placeholder-app detour, the architecture
pivot a design agreement would have caught, ad-hoc recon). Still slower to
first green gate than anfra-native, because the mandated oracle + equivalence +
AppTest investment is real work — but that gap is the anfra build *underpaying*
for assurance it should also owe (its checks were one-time and manual). Fair
comparison narrows it.

**Speed, change loop (what actually dominates TCO):** strictly faster than
anfra-native — rerunning committed suites vs manual browser acceptance. The
recommendation file's "fund a headless app driver" condition is already met by
the ecosystem on this path.

**Quality floor:** rises to ≈ the anfra-skill floor on correctness and UX
(AML-first, design agreement, four states, a11y rules) and **exceeds it on
assurance** (mandated equivalence + full-app headless gate + typing + coverage).
The FTP-class failure becomes structurally unlikely on both paths.

**Quality variance:** both skills cut agent-dependent variance — the A/B
showed unguided agents invest rigor inconsistently (they went deep on recon
and skipped committed tests; I went deep on tests and under-reconned).

**What does not move:** Streamlit keeps its ceiling and its enforcement debt
(policy, not physics); anfra-native keeps its posture, single-artifact
coherence, and host integration.

## 4. How the recommendation changes

Previous recommendation (file 5): anfra standalone as default, Streamlit as a
sanctioned exception tier; in a binary forced choice, anfra standalone.

With a funded, maintained Streamlit skill **plus the CI policy layer**:

- **The exception-tier demotion is no longer justified on quality grounds.**
  Anfra-backend + Streamlit-skill becomes defensible as the *default app tier*
  for a portfolio that will outgrow dashboards: it keeps the semantic layer as
  the single source of truth (enforced by AML gatekeeping + CI), gains the
  mainstream stack and the general UI ceiling, and its assurance is stronger
  than the native path's *in practice* (committed suites vs manual checks).
- **It does not flip to an unqualified Streamlit default**, for three reasons
  that survive the skill: (1) policy can be circumvented by a rushed agent or
  a new hire — physics cannot; the platform's worst-case posture still favors
  anfra-native; (2) the second skill is a real maintenance liability — the A/B
  already forked the metric namespace (`cycle_*` vs `cycling_*`) precisely
  because two build processes ran in parallel without a single gatekeeper;
  a second skill doubles the drift surface unless someone owns both; (3) ops
  friction (two processes, env plumbing) is neutralized by assumption here but
  not in general.
- **The decision becomes trust-model-shaped, not quality-shaped:** if the
  platform team has review capacity to *enforce policy* (CI gates that fail
  builds, a single AML gatekeeper, skill maintenance ownership), choose the
  Streamlit tier as default and keep anfra-native for sandboxed/hosted
  distribution. If not, anfra-native remains the default because its floor is
  held up by physics rather than by anyone's diligence.

**Either way, the cheapest immediate move is skill cross-pollination, not a
new skill:** fold the raw-payload interrogation step into the anfra skill
(closes the FTP class for both paths), and fold the committed-equivalence +
headless-gate mandate into whichever path ships next. The A/B's real lesson is
that each skill should steal the other's best instruction — after that, the
technology choice is genuinely about capability, security posture and ops, not
about build quality.

## 5. Answer, compressed

- Premise: ~70% right. Quality deltas were mostly skill-borne; trust/enforcement
  deltas were technology-borne.
- A Streamlit skill modeled on the anfra one would raise its quality floor to
  parity-or-better (correctness + UX from discipline; assurance from the
  ecosystem), cut first-build variance, and win the change loop outright.
- It cannot port the physics: sandbox, definitions-by-construction, one
  artifact, host integration. Those become CI policy — good policy, but policy.
- Recommendation shifts from "anfra standalone default / Streamlit exception"
  to "Streamlit tier defensible as default **iff** the skill exists and CI
  re-creates enforcement; otherwise physics beats policy for a platform
  default." With funding for only one artifact, fund the skill cross-
  pollination first — it improves both paths for a fraction of the cost.
