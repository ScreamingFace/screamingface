# E2E notebook workbench: reviewable notebooks, any target, evidence by trace id

Status: draft for owner review, 2026-10-16.
Refs: unfiled (ledger `docs/work/2026-10-16-e2e-notebook-workbench.md`).
Plans: `docs/plan/2026-10-16-e2e-workbench-u1-client-pairing-and-token.md`,
`docs/plan/2026-10-16-e2e-workbench-u2-core.md`.
Explainer: https://claude.ai/artifact/XzJH59USTJ8GwFSHhNv1eP (private).

## 1. Problem

The public Colab quickstart is the most complete end-to-end check we have. Part A runs against
the hosted dev engine: compose, `evaluate`, url4, cached DRACO reproduction, submit. Part B runs
the same recipes on a local BYOK stack. It has four problems:

- **Hard-wired targets.** Part A only runs on `fusion.dev`, Part B only on `127.0.0.1:9108`.
  Running it against a PR preview means editing cells.
- **Almost no assertions.** One printed score. "$0 because cached" is a markdown claim, not a
  check.
- **No evidence of where it ran.** A green notebook does not show that the request crossed
  engine → runner → aigateway, under which trace, or what each hop logged.
- **A publication hole.** `sf.configure(engine_url=…)` defaults `scoreboard_url` to the hosted
  leaderboard, now `https://leaderboard.screamingface.ai` (`client.py:40-41`,
  `_default_client.py:67-71`). Part B with `SUBMIT=True` therefore publishes a local-engine score
  to the public leaderboard.

The pieces to fix this already exist but are split across three places:

- **Local replay e2e:** `packages/screamingface/tests/e2e/`
- **Local correlation ladder:** `tests/e2e/test_correlation_chain.py`, OME-1105
- **Hand-run k8s tracing notebook:** `e2e/failor/notebooks/traceability_e2e_k8s.ipynb`, OME-1074

## 2. Decisions (locked with the owner)

| # | Decision | Rejected |
|---|---|---|
| D1 | A run is one cell of **Target × Scenario × Mode**. | Two hard-coded notebook parts |
| D2 | **Notebooks are the scenarios; pytest is the harness.** pytest finds the notebooks, injects the target, executes them, and decides pass/fail. | Pure pytest, which loses the reviewable story; notebooks alone, which have no gate |
| D3 | **Evidence is checked independently of the notebook.** A run passes only when the notebook's asserts pass *and* the trace chain is complete. | Trusting notebook output alone |
| D4 | The UI is a **local web app** (`screamingface workbench`) that launches the same runner and views bundles. | A new Electron app (second desktop toolchain); a Studio dev route (couples tests to the product's release) |
| D5 | **Auth: option A now, option B for the UI** (§6). CI stays on replay and local. | C (service tokens) deferred; D (aigateway API keys) is a product decision |

## 3. Shape

```
packages/screamingface/tests/e2e/workbench/
  notebooks/            # scenarios; generated, committed output-free
  build_notebooks.py    # deterministic builder (the examples/ rule)
  runner.py             # nbclient execution + parameter injection
  targets.py            # Target profiles + lifecycle
  evidence.py           # log sources, trace chain
  bundle.py             # evidence bundle writer (redacting)
  conftest.py           # env-selected target, require-all, fixtures
  test_notebooks.py     # one parametrized test per notebook
```

It sits inside the existing replay suite, so it reuses `tests/e2e/harness` (replay stack,
gating, assets, goldens) instead of copying it, and the existing replay workflow runs it. The
SDK wheel excludes `tests/`, so test tooling still never ships. Selection uses env vars
(`SCREAMINGFACE_WORKBENCH_TARGET`, `…_OUT`, `…_REQUIRE_ALL`) rather than CLI options, which a
nested conftest cannot register. Where the local UI (unit 4) lives is decided in that unit's
plan.

### 3.1 Target

```python
@dataclass(frozen=True)
class Target:
    name: str                      # replay | local | preview:<N> | hosted-dev
    engine_url: str
    scoreboard_url: str            # always explicit — never the SDK default
    auth: Literal["none", "access"]
    lifecycle: Lifecycle           # testcontainer stack | screamingface up/down | no-op
    log_sources: list[LogSource]   # files on disk | kubectl selectors
    submit_allowed: bool = False
    budget_usd: float = 0.50
```

| Target | Engine / scoreboard | Auth | Lifecycle | Log sources |
|---|---|---|---|---|
| replay | harness stack + keyless gateway serving a tape | none | `tests/e2e/harness/stack.py` | harness log files |
| local | `127.0.0.1:9108` / `:9106` | none (BYOK key from env) | `screamingface prepare · up · down` | `SCREAMINGFACE_DATA_DIR` logs |
| preview:N | `fusion-pr-N` / `leaderboard-pr-N` `.preview.dev.screamingface.ai` | Access (B) | none | `kubectl` on engine, `url4-runner`, aigateway |
| hosted-dev | `fusion.dev` / `leaderboard.dev` | Access (B) | none | `kubectl` (aks-dev) |

### 3.2 Scenario notebooks

- Each notebook has a papermill-style `parameters` cell (target URLs, limit, budget, flags). The
  harness overwrites it; a person edits it by hand.
- Cells hold real `assert`s (`report.ok`, url4 present, score inside a band, cache hits where the
  cache is warm).
- The final cell emits one JSON result: `{"trace_ids": [...], "run_ids": [...], "candidates": {name: {score, cache_hits, cache_saved_cost_usd, spend}}}`.
  `Report.trace_id` (`report.py:191`) is minted by the client (OME-967), so evidence follows
  what the real client did, not an id the harness injected.
- Initial set:
  - `quickstart` (compose + ifeval)
  - `cached-repro` (DRACO from cache, asserts $0 on warm targets)
  - `pipeline`
  - `leaderboard-read`
  - `submit` (runs only where `submit_allowed`)

### 3.3 Evidence

1. Start the tailers **before** execution. Runner frames are purged about 60 s after a run, and
   runner Jobs are reaped (see `e2e/failor/notebooks/README.md`).
2. Execute the notebook with nbclient (already a dev dependency).
3. Collect by trace id:
   - client frames (`events.py` traceparent)
   - engine and runner `run scheduled` / `run terminated` lines (`run_evidence.py`)
   - aigateway lines carrying `gateway_call_id` (OME-938)
   - spans from the OTLP backend, where reachable
4. Assert the chain:
   - every hop is present under the trace
   - every aigateway line in the window has `gateway_call_id`
   - a scheduled line pairs with a terminated line
5. Write the bundle `out/<target>/<notebook>/`:
   - `executed.ipynb`
   - `trace.json` (the id, each hop with found/missing and source, cache hits)
   - `logs/*.txt` (excerpts filtered by trace id)
   - a `junit.xml` entry with `trace_id` as a property
   - one `out/summary.md` per run, in the layout of `tests/paid/_board_summary.py`

The chain assertions reuse the rungs of `tests/e2e/test_correlation_chain.py`. They are one
implementation run against two kinds of log source, not a copy.

### 3.4 Guards

- **`--require-all`:** a skipped notebook is a failure (same pattern as `SCREAMINGFACE_PAID_REQUIRED`).
- **Budget:** before each evaluate cell, projected spend (limit × candidates × last observed
  $/case) must fit in what's left; otherwise abort. Default `limit=1`.
- **Submit:** only when `target.submit_allowed` and `SUBMIT=1` are both set; the scoreboard URL
  comes from the target.
- **Secrets:** BYOK keys and Access tokens come from env (or Colab `userdata`), never from
  parameters, so they never appear in an executed notebook. The bundle writer redacts known
  secret patterns as a backstop.
- **Scores:** assert bands, never exact values.

### 3.5 Local web UI (`screamingface workbench`)

- A loopback-only server.
- **Launch:** pick notebooks and a target (local, preview:N, hosted-dev), set limit and budget,
  run. It spawns the same `pytest e2e/workbench …` command CI uses and streams its progress.
- **View:** list bundles, from local runs or unzipped CI artifacts. Per notebook it shows:
  - the rendered executed notebook
  - the trace chain (hop, found/missing, source)
  - log excerpts
  - cost and cache hits
  - a link by trace id to the tracing backend
- **Login:** runs the Access login once per target and passes the token to the runner through
  `SCREAMINGFACE_ACCESS_TOKEN` (§6, B).
- **Never executes notebooks itself.**

## 4. Run lanes

| Trigger | Targets | Gate |
|---|---|---|
| Every PR touching the SDK, engine, aigateway or workbench | replay | keyless |
| Manual dispatch | local | `SCREAMINGFACE_TEST_PAID` + `OPENROUTER_API_KEY` |
| Human, via UI or CLI | preview:N, hosted-dev | Access login (B) |

## 5. The public Colab

The public Colab becomes a thin wrapper over the `quickstart` and `cached-repro` notebooks with
target = hosted-dev, generated by the same builder. That way the demo and the test can't drift.

## 6. Authentication

**Today:**
- Hosted user login is Cloudflare Access only. The client runs the transfer flow
  (`_access/contract.py`), keeps the token in process memory (`_access/auth.py:54`), and sends
  `Cf-Access-Token`.
- Envoy maps only the `email` claim to `X-User-Email`
  (`apps/screamingface-engine/deploy/helm/templates/securitypolicy.yaml:60`). The engine,
  aigateway and scoreboard trust that header.
- No machine identity exists (`screamingface_engine/job_env.py:57`).
- The local stack runs with auth disabled.

**Options:**

| Option | Change | Status |
|---|---|---|
| A | No auth work; cloud runs are manual | **now** |
| B | Client seeds its token store from `SCREAMINGFACE_ACCESS_TOKEN`; the UI logs in once per target and passes the token on | **now (UI)** |
| C | Cloudflare service token → Envoy maps `common_name` to a *separate* header → aigateway and scoreboard allow-list a `ci-e2e` account | deferred until a cloud CI lane is needed; needs security review |
| D | aigateway-issued API keys | product decision |

Rejected: mapping a service token into `X-User-Email`. It mixes machines into the email-keyed
account space and weakens the SET-not-append invariant in `securitypolicy.yaml`.

B runs as the person who logged in: their BYOK keys and their identity on submissions. That is
acceptable for human-launched runs and is why B is not used for CI.

## 7. Units (cross-cutting → one leaf per landing)

1. **`client-sf`:** honour an explicit `scoreboard_url` pairing, so a non-default `engine_url`
   no longer silently pairs with the dev scoreboard. Add `SCREAMINGFACE_ACCESS_TOKEN` seeding
   (B). Both changes are small and need their own tests.
2. **`cross-unit/repo-dev-processes`:** the `e2e/workbench` core (targets, notebook builder, the
   two initial notebooks, pytest harness, evidence for replay and local, bundle writer) and the
   replay CI lane.
3. **Same landing:** kubectl evidence sources for preview and hosted-dev; merge the failor k8s
   notebook in as a scenario.
4. **Same landing:** the local web UI.
5. **`client-sf`:** regenerate the public Colab from the builder.

## 8. Open questions

- **Preview Access app.** Do previews share the dev Access application (audience, team domain)?
  It isn't in this repo, and B depends on it.
- ~~Unit 1 pairing~~: decided 2026-10-16. A non-default engine without a scoreboard
  **raises**, in `configure()` and on the env path. `sf.Client` is unchanged; see the unit 1
  plan.
- ~~Score bands~~: decided 2026-10-16. **Hand-set per scenario** in the parameters cell.
- **OTLP span query:** which backend API the collector calls for cloud spans, and with what
  credential.
