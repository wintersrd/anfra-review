# Complimentary review — non-technical stakeholder builder's perspective
## Where the anfra + build-skill + HTML build is superior to the Streamlit build

### D1. The skill is a genuinely guided pipeline — the user experience is a handful of crisp decisions

`build-data-app` walks the agent through: learn the datasets (`anfra show`) →
**agree on the design** (restate the request as one checkable result; "ask
only what changes the numbers"; declaration list of every query/filter/
control, one line each, with a yes before code) → look & feel options →
pre-run every query → mandate the four render states (loading / success /
empty / error) → hand over "in the user's terms".

Their WORKLOG shows what that produces: a 16:52 design agreement where the
user made **four crisp, well-framed decisions** (look, cadence bucket edges,
EBike mapping, 22-query declaration list) before any code existed. My
Streamlit build asked two narrower questions *mid-flight* and recorded a
dozen interpretations in a developer-facing WORKLOG the stakeholder will
never read. For a non-technical builder, the anfra path's contract is
legible; mine was attorney's work product.

### D2. A change-request protocol the stakeholder can actually use

The skill mandates `data-anfra-block` markup on every page part plus a host
**Inspect panel** (Structure tab: the tree of named parts; Data tab: every
query's state, executed AQL, error, and a Locate button). A stakeholder can
say "the *time by ride type* block is wrong" — naming a handle — or open the
panel and point at the red query. My Streamlit app has section labels and a
load log, but nothing equivalent to a live per-query debugger in the user's
hands; when something looks wrong, the stakeholder's report is a screenshot
and a vibe.

### D3. Instant publish, instant discovery, nothing to install

The app appears in the platform's `/apps/` listing next to the existing
running dashboard the moment the file lands; viewers need no environment, no
URL-scheme education, no second service. For a stakeholder showing results
to colleagues, "it's in the apps list, same place as the other one" is a
meaningfully better answer than "run this uv command with this env var on
this port".

### D4. Professional design and accessibility largely for free

Basecoat + DESIGN.md tokens + the skill's finished-look rules produced:
consistent Great Wave parity, dark mode, an `aria-live="polite"` focus
banner, an `aria-multiselectable` listbox with keyboard semantics, and a C16
drift alarm encoded as **shape + color** (diamond + red) — which beats my
color-only tint on accessibility. The skill even encodes craft most
stakeholders would never think to ask for: restyle-don't-rebuild on selection
(no replayed entry animations), tabular numerals, styled empty/error states.
My Streamlit app is polished too — but that polish came from me mirroring
an existing app.py, not from a platform guarantee.

### D5. Zero environment management

No uv, no venv, no Python version, no dependency drift, no "restart
streamlit when an imported module changes" rule (a real AGENTS.md rule on my
side). The stakeholder's mental model is "apps are files in the repo that
the platform serves" — which is exactly right for someone non-technical.

### Caveats (keeping this honest)

- Acceptance still ends with "please look at it in a browser" (D-review
  counterpart of B1): the skill's own instructions admit the agent may not
  drive a browser and defer to the user. Guided build ≠ guided verification.
- The sandbox rules that protect the stakeholder (SRI hashing, CDN
  allowlist, no storage) are invisible constraints they cannot debug when
  something "just won't load".
- The stakeholder is *more* dependent on platform-versed agents (B2), and
  the protocol only works while the skill/host maintain these affordances
  (Inspect panel, handles).
