---
ticket: OME-964
stack: py-screamingface
status: done
started: 2026-08-25
finished: 2026-08-25
---

# OME-964 — Turn one real benchmark run into a free CI replay that fails when the published score drifts

## Intent

Make the OME-961 e2e replay harness actually bite: bless real fixtures so
`tests/e2e/test_boards.py` goes green for at least one real board (draco-3pass)
and CI replays the board free forever, failing on any score drift. The bless tool
(`slice_snapshot.py`) turns the owner-held production cache dump + the owner-held
legacy run archive into a committed sliced snapshot + manifest + golden. Recorded
judge rows replay as-is; candidate rows are re-keyed through the gateway's own
`build_global_cache_plan` (single-authority hashing) with the archived answers as
payloads.

## Planned changes

- `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — the bless tool:
  boot gateway (Postgres testcontainer) → load dump → capture pass (proxy records
  the engine-rendered candidate bodies, which miss) → re-key archived answers via
  an aigateway-venv helper subprocess → splice upload → verified replay → slice by
  hit-count delta → write `<board>.snapshot.gz` + `<board>.manifest.json` +
  `<board>.golden.json`.
- `packages/screamingface/tests/e2e/fixtures/snapshots/draco-3pass.snapshot.gz`
  (+ `draco-3pass.manifest.json`) and
  `packages/screamingface/tests/e2e/fixtures/goldens/draco-3pass.golden.json`.
- healthbench-worst30: verify presence of its rows in the dump; bless the same way
  if present, otherwise report exactly what is missing.
- `packages/screamingface/justfile` — `e2e-bless` recipe (package-local dev
  tooling, same file as `stack-*`).
- `.gitignore` — scoped negation so the blessed board's manifest sidecar is
  committable (added during implementation; see Deviations).
- `packages/screamingface/tests/e2e/test_bless_contracts.py` — non-docker unit
  tests for the tool's pure seams (COPY escaping round-trip, dump-row parsing,
  answer matching, golden authorship).

## Test plan

- RED first: contract tests for COPY escape/unescape round-trip (tab/newline/
  backslash payloads), dump COPY-line parsing, archive answer→case matching
  (exact question containment; ambiguous/missing → loud error), golden authorship
  (conforms to `GoldenReport`, counters derived, score canonicalized).
- Integration: run the bless tool for draco-3pass on this machine; then
  `SCREAMINGFACE_TEST_E2E=1 uv run pytest tests/e2e -m e2e` must turn the
  draco-3pass board test green from the committed fixtures alone.
- Full default lane stays green.

## Acceptance

- `test_boards.py::test_board_replays_end_to_end_and_matches_its_golden[draco-3pass]`
  passes from committed fixtures (no dump, no archive, no keys, no spend).
- Sliced fixture ≤ ~10 MB or STOP and report options.
- healthbench-worst30: blessed with golden cross-checked against the owner's saved
  report (score `-0.091`, coverage `0.7898`, 157 cases, revision
  `39cfd96b068f7230`) — or an exact missing-rows report, never a fake.
- No local machine paths in any committed fixture/provenance text.

## healthbench-worst30 verdict — NOT blessable from the available recordings

Checked definitively against the production cache dump (204,765 rows). The board's
saved report (`screamingface.report.v1`, fusion candidate `best_open_source`,
157 cases, revision `39cfd96b068f7230`, score `-0.091`, coverage `0.7898`) names
five models:

- members: `openrouter/openai/gpt-oss-120b`,
  `openrouter/nvidia/nemotron-3-ultra-550b-a55b`, `openrouter/tencent/hy3`
- synthesis: `openrouter/deepseek/deepseek-v4-pro-0813`
- judge: `openrouter/openai/gpt-5.4`

The dump contains **zero rows for all five** (grep over the full dump: 0 hits each;
the dump's only judge model is `openrouter/google/gemini-3.1-pro-preview` — the
draco judge). There is nothing to slice and nothing recorded to re-key against, so
blessing healthbench-worst30 would require a new cache dump taken from the
deployment that served the 2026-08-19 healthbench run (member + synthesis + judge
rows for those five models). Not faked; reported as missing.

Second blocker even once rows exist: the board is a FUSION candidate (4 models in
`models` + a judge), and both `GoldenReport` consumers assume one model —
`test_boards.py` fails a golden naming ≠1 model, and `client.evaluate(sf.Model(…))`
replays single-model candidates only. Recommendation: a deliberate follow-up that
extends the golden schema + board test to fusion candidates (models tuple + fusion
name + member seam) rather than hacking the one-model rule here.

## CI job — PROPOSAL — owner approval required (nothing under .github/ was touched)

A new job (or separate workflow) for the e2e replay lane. Deliberately triggered by
engine/gateway changes too — those are exactly the changes that can shift a
published score. Docker is present on `ubuntu-latest`; the harness syncs the
aigateway + engine venvs itself; assets are prepared once per run from the pinned
datasets.

```yaml
# PROPOSAL — owner approval required. Suggested home:
# .github/workflows/screamingface-e2e-replay.yml (or a job in screamingface-tests.yml)
name: ScreamingFace E2E Replay

on:
  pull_request:
    paths:
      - "packages/screamingface/**"
      - "apps/screamingface-engine/**"
      - "apps/aigateway/**"
      - ".github/workflows/screamingface-e2e-replay.yml"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  replay:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    defaults:
      run:
        working-directory: packages/screamingface
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.12"
          enable-cache: true

      - name: Install SDK dev dependencies
        run: uv sync --extra notebook

      - name: Prepare benchmark assets
        run: uv run --project ../../apps/screamingface-engine --with datasets \
             python -m screamingface_engine.benchmarks.prepare \
             --root /tmp/screamingface-benchmark-assets

      - name: Replay the blessed boards against their goldens
        env:
          SCREAMINGFACE_TEST_E2E: "1"
          # Deliberately NO provider keys anywhere in this job: the harness scrubs
          # the child env; a cache miss is a loud 404, never a spend.
        run: uv run pytest tests/e2e -m e2e -v --tb=short
```

## Bless run evidence (draco-3pass, 2026-08-25, this machine)

- Inputs: production cache dump 2026-08-24 (204,765 rows; content sha256
  `41dafce81adf9a42ef0a4835ec8daa796dc542c196e82f0906b23612377fc45d`) + owner-held
  draco archive run 2026-08-06 eval JSONL (sha256
  `0bf59b209d69cc117def6d16b13c6047c4db1175eebb71d1162a5d65e02610bd`).
- Capture pass: 100/100 distinct candidate bodies rendered, all loud 404 misses
  (keyless by construction).
- Re-key: 100 candidate rows spliced under gateway-computed keys (inserted=100).
- Verified replay: **score 0.3593, coverage 1.0, 100/100 cases scored**, 1,325 s,
  ~11.9k cache hits, **zero misses, zero provider traffic, zero keys**.
- Slice: 11,902 rows touched → `draco-3pass.snapshot.gz` **1.12 MB** (size gate:
  10 MB) + manifest (revisions `openrouter-global-cache-2026-08d` /
  `aigw-parameter-contract-2026-08b`) + golden (revision `b8c8afd8f9dddca0`,
  expression_sha `21a30cd0…`).
- NOTE: the recordings cover judge seeds 1–3 only, so the blessed board is
  **draco-3pass** (not 5-pass draco), full 100 cases, one model
  (`openrouter/google/gemini-3-flash-preview`) per the golden one-model rule.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` (the bless tool)
  - `packages/screamingface/tests/e2e/test_bless_contracts.py` (14 default-lane
    contract tests for its pure seams)
  - `packages/screamingface/tests/e2e/fixtures/snapshots/draco-3pass.snapshot.gz`
    (+ `draco-3pass.manifest.json`)
  - `packages/screamingface/tests/e2e/fixtures/goldens/draco-3pass.golden.json`
  - `packages/screamingface/justfile` (`e2e-bless` recipe)
  - `docs/tasks/2026-08-24-OME-964-golden-scores.md` (title updated to the
    ticket's new one), this ledger
  - healthbench-worst30 NOT blessed — see the verdict section (all five of its
    models absent from the dump); no fixture faked
- **Commits:** uncommitted — pending local owner review
- **Gates:**
  - default lane: **1123 passed, 10 skipped** (includes the 14 new bless-contract
    tests); ruff check + `ruff format --check` + pyright clean on the new files
  - e2e lane (`SCREAMINGFACE_TEST_E2E=1`, docker): **5 passed, 4 skipped** in 78 s —
    `test_boards[draco-3pass]` **PASSED from the committed fixtures alone** (~60 s
    replay, CI-friendly); draco / ifeval / healthbench-worst30 /
    healthbench-professional skip loudly naming their missing fixtures; all 4
    plumbing tests pass (synthetic fixtures regenerated per-machine via
    `generate_synthetic.py` — they are gitignored by design)
  - drift guard proven to bite: a deliberately perturbed golden score
    (`0.9999`) made the board test **FAIL** at the score rung in 69 s; restored
    (`0.3593`) and green again
- **Deviations:**
  - dump found at its new owner-held location (moved from the original path
    mid-task) and re-gzipped locally before blessing — the recorded provenance sha
    is of the DECOMPRESSED dump, stable across re-compressions
  - `.gitignore` gained a one-line negation so the blessed board's
    `draco-3pass.manifest.json` sidecar can be committed past the OME-951 blanket
    `*.manifest.json` ignore (deliberately file-specific: synthetic stays
    generated + ignored) — flagged for owner review
  - healthbench-worst30 not blessed (recordings absent — see verdict section)

### Owner review round (approve with nits) — all three fixed, tool-only

All three review findings verified against the code and confirmed real; fixes are in
`slice_snapshot.py` only (the run-once bless tooling), and the committed draco-3pass
fixtures are **byte-unchanged** (sha256 before/after identical:
snapshot `5210a227…`, manifest `56e8004a…`, golden `eee8b582…`).

1. **Truncated COPY block** — `iter_copy_rows` now raises when the input ends while
   a COPY block is still open (a partial dump must never bless a partial fixture);
   new contract test `test_iter_copy_rows_refuses_a_truncated_copy_block` (RED
   confirmed against the old behavior by design, GREEN now) → **15** contract tests.
2. **Orphaned Postgres on boot failure** — `_boot_gateway` wraps its piecewise boot
   in `try/except BaseException: stop_sync(); raise`, mirroring `start_sync`'s own
   cleanup guarantee (`stop_sync` is stage-safe).
3. **stderr interleaving into the slice** — `_psql` now demuxes via
   `get_wrapped_container().exec_run(demux=True)`: only stdout can reach the
   committed snapshot, a psql NOTICE lands on stderr, and failures surface stderr in
   the raised error. Verified live against a Postgres testcontainer (COPY stdout
   clean with NOTICE-emitting statements; error path carries the psql message);
   reproducible-gzip contract test still green.

### Scope addition (owner-approved 2026-08-26) — the CI workflow job

The "CI workflow job running the e2e lane" bullet moved from *Out of scope* into this
unit: the owner directed it into PR #722 directly. Added
`.github/workflows/screamingface-e2e-replay.yml` — a standalone path-filtered
workflow (NOT a job inside `screamingface-tests.yml`, because `paths:` is
workflow-level and this lane must also fire on `apps/screamingface-engine/**` and
`apps/aigateway/**`, the main score-drift sources, without dragging the SDK matrix
along). One `golden-replay` job on ubuntu-latest: uv sync → cached
`benchmarks.prepare` asset bundles (same command as `just stack-prepare`) →
`SCREAMINGFACE_TEST_E2E=1 pytest tests/e2e -rs`. No provider keys anywhere in the
job, so spend stays impossible; `-rs` keeps fixture-less boards' skip reasons
visible in the log. Verified locally before wiring: the draco-3pass board test
PASSES in 72s under the same env/flag from the committed fixtures.

### Re-bless after rebase onto main (2026-08-26)

The first CI run of the new e2e-replay workflow caught exactly what the gate exists
for: main had moved (fail-fast grading fan-outs + url4 error-payload fixes) and the
merge run failed rung 1 — "expression changed, goldens stale" (21a30cd0… →
df2cfd7b…). Branch rebased onto main and draco-3pass re-blessed from the same two
owner-held recordings (shas verified against the committed provenance header before
use). First re-bless attempt was REFUSED (score 0.3451, coverage 0.91, 9 failed
cases) — diagnosed as ~30 local request timeouts under machine load, not protocol
drift (CI's own replay under new main served 100/100 at coverage 1.0). Quiet-machine
retry: 0 timeouts, 100/100 scored, score 0.3593 exactly — the published number never
moved, only the expression string. New fixtures verified green through the real gate
(70s). Observation for a follow-up nit: a timeout-degraded replay and a genuine
score drift currently produce the same BLESS REFUSED message; coverage < 1.0 could
name the environmental case.
