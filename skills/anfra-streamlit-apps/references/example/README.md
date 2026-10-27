# Example app — the skill's starting skeleton

A complete miniature app over this repo's `running_analytics` dataset (run
volume + surface mix), exercising every pattern the skill mandates:

| File | Role |
| --- | --- |
| `example_data_aql.py` | live layer — `anfra_client` queries, cached client, filter helpers |
| `example_data_oracle.py` | SQL oracle — reader snapshot, `$EXAMPLE_DB` override, tests only |
| `example_app.py` | the app — bootstrap, sidebar contract, four states, cross-filter, load log |
| `conftest_addition.py` | fixture block to paste into `tests/conftest.py` |
| `test_example_equivalence.py` | oracle ≡ live layer, three windows (server up) |
| `test_example_app_apptest.py` | full-script AppTest gate, four scenarios (server up) |

**To adapt**: copy `example_*` into `streamlit_app/` as `<app>_*`, the tests
into `tests/integration/` (drop the `example_` prefix on the fixtures in
`conftest_addition.py` as you paste), rename modules/keys, and swap the
`run_*` metrics and `activities` dimensions for your model's fields. The
`theme.py` import assumes the repo token contract (see
[../design.md](../design.md)); port `theme.py` if the repo lacks one.

**This skeleton is validated**: its equivalence and AppTest suites were run
green against a live `anfra serve` when the skill was authored.
