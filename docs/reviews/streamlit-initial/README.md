# Comparative reviews — anfra-native vs Streamlit cycling app builds

Two agent builds executed the same specification (`docs/cycling-app-spec.md`,
C1–C17 + K1–K4) from the same base commit `989eb9a`, in parallel:

| | **anfra-native build** | **Streamlit build** |
|---|---|---|
| Repo | `~/repositories/cycling-anfra` (branch `cycling-anfra`) | `~/.local/share/opencode/worktree/518d31/cycling-app` (branch `feat/cycling-app`) |
| Path | Spec Appendix A: `build-data-app` skill → single-file HTML app on `anfra serve` | Spec Appendix B: Streamlit app over `anfra_client` MCP SDK |
| Product | `apps/cycling.html` (1,596 lines; 21 embedded AQL queries + appMeta; 17 ECharts + 4 KPI tiles) | `cycling_app.py` + `cycling_queries_aql.py` + `cycling_queries.py` (SQL oracle) + theme/test suite (~3,100 lines) |
| Semantic layer | `cycling_*` metric family + `ride_type`/`ftp_ref`/`decoupling` dims; `icu_ftp` surfaced from raw NDJSON into the warehouse | `cycle_*` metric family + `ride_type`/`work_kj`/`hr_decoupling` dims |
| Gates | `anfra validate` clean (incl. data_app hygiene), 22/22 embedded queries execute, 17/17 charts headless SSR render, full pytest 152✓/65 skip, MCP-live 65/65 after serving | Full-script AppTest (zero exceptions, 5 scenarios), 25-case AQL↔SQL equivalence vs committed SQL oracle, full pytest 278✓, coverage 88.86 %, pre-commit green |
| Commits | `ebf7b6b`, `f8bdfd8`, `8b19e66`, `f9c0ef9` | `1c39df6`, `e390f64`, `0c0aefd`, `9ef1dbb`, `19badeb`, `731de6d` (+ review fixes) |

## Review streams

Two personas, each reviewed in both directions:

1. **Adversarial** — where the Streamlit solution is superior:
   - `1-adversarial-data-platform.md` (data team / owner of definitions & platform)
   - `2-adversarial-stakeholder-builder.md` (non-technical builder of custom apps)
2. **Complimentary** — where the anfra-native solution is superior:
   - `3-complimentary-data-platform.md`
   - `4-complimentary-stakeholder-builder.md`
3. `5-recommendation.md` — deployment recommendation.
4. `6-streamlit-skill-hypothesis.md` — follow-up counterfactual: what a
   Streamlit skill modeled on `build-data-app` would and would not change
   (skill-borne vs technology-borne split, speed/quality effects, revised
   recommendation).

## Method & ground rules

- Evidence sources: both WORKLOGs, both apps' source, both AML diffs, both
  test suites, the `build-data-app` skill content, and recounted test/gate
  results. Findings cite files/commits wherever possible.
- Per the owner's instruction, **port-collision errors between the
  simultaneous builds are ignored** (7878 seizure, `--addr` pinning,
  `ANFRA_MCP_URL` juggling as *error sources*). Where port/env plumbing is a
  *structural* property of a deployment model, it is assessed as such.
- Hosting is assumed solved in both cases; infra is out of scope. The lens is
  the experience of **building and managing** data apps.
- Both builds were agent-executed; "builder experience" therefore means the
  experience of a non-technical stakeholder directing an agent and living
  with the result, not hand-coding.
- Direction convention: "adversarial" reviews argue the Streamlit product's
  advantages for that persona; "complimentary" reviews argue the anfra
  product's advantages. Each finding is meant to stand on evidence, and each
  file ends with caveats that keep it honest.
