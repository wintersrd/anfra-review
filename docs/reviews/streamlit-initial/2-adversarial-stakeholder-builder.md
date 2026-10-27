# Adversarial review — non-technical stakeholder builder's perspective
## Where the Streamlit build (this repo) is superior to the anfra + build-skill + HTML build

Persona: a non-technical stakeholder who commissions custom data apps from an
agent and lives with the result — requesting changes, trusting the numbers,
showing it to colleagues.

### B1. Handover = machine-verified, not "please go click around"

The Streamlit build ended with five automated end-to-end scenarios proving the
app renders, filters, degrades, and recovers — the stakeholder receives "this
is verified" rather than homework. The anfra build's handover explicitly
asked the user to perform browser acceptance per the §9 checklist. For a
non-technical builder, "the machine checked it" is confidence; "please verify
it and report what you see against what you expected, with the console open"
is a burden and a hidden cost on every future change.

### B2. A transferable, mainstream stack

Everything the Streamlit stakeholder touches — Python, Streamlit widgets,
pytest — is one of the most transferable skill sets in data work. If the
platform team is unavailable, almost any data-literate person or agent can
pick the app up. The anfra path concentrates knowledge in platform-specific
arcana (AQL syntax, `explore{}` rules, ECharts option trees, Basecoat
classes, sandbox/CSP/SRI rules, the SDK state model). The stakeholder is
locked to the platform and to agents that know its skill set.

### B3. A higher ceiling when needs outgrow a dashboard

Streamlit is a general app framework: input widgets, forms, file upload,
multi-page flows, text/table composition, arbitrary pandas computation. The
cycling spec happened to be dashboard-shaped; stakeholder requests rarely
stay that way ("add a training-log entry form", "let me upload a fit file",
"email me a weekly summary"). On Streamlit those are incremental; on the
anfra app model they are off-pattern — the skill itself says apps may not
fetch, post, store, or navigate, and are a single sandboxed HTML frame.

### B4. Regression safety for the change loop

The stakeholder's real lifecycle is *changes*: "actually, exclude gravel";
"make it 8 weeks". In the Streamlit repo, every change lands through
pre-commit running lint + unit layers, with the AppTest gate and equivalence
suite one command away — earlier changes stay broken loudly rather than
silently. In the anfra repo, a change re-checks that queries execute and
charts render; interaction-level regressions (the cross-filter banner, the
K2 Monday slicing, focus wiring) are re-verified by… the user's eyes.

### B5. Interaction polish with fewer bespoke pitfalls

Plotly gives tooltips, zoom, legend-toggle, unified hover out of the box, and
the app's interactivity (sidebar presets, multiselect, cross-filter with
banner + clear) is standard widget machinery. The anfra path hand-rolls
interaction in JS, where the skill has to warn about real pitfalls the
stakeholder would never diagnose: selection changes must restyle marks rather
than rebuild (or the chart replays its animation), `localStorage` throws in
the sandbox, `<form>` is blocked, `.card` clips dropdowns. Each warning
exists because a builder hit it — and the non-technical stakeholder can't see
any of them.

### Caveats (keeping this honest)

- Runtime simplicity favors the anfra build: the Streamlit stakeholder's app
  needs *two* live processes (anfra serve + streamlit) and correct env
  plumbing; the friction this caused in a parallel-build session is real even
  with port collisions excluded as error sources.
- B1's "machine-verified" applies to *this* build because the gate was built;
  a lazy Streamlit build ships neither gate nor oracle. The mainstream stack
  lowers the floor; it doesn't raise it automatically.
- For pure dashboard needs, B3's ceiling is theoretical. The evidence in both
  WORKLOGs shows 100 % dashboard-shaped requests.
