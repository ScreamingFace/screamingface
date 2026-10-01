# Plan — E4a deterministic combine (OME-1289)

**Spec:** [docs/spec/2026-09-30-e4a-deterministic-combine/](../spec/2026-09-30-e4a-deterministic-combine/00-overview.md)
(approved by the user, 2026-09-30). **Status:** ready. Implementation has not started. It starts
only when the user says so in plain words.

## 1. Rules for every unit

- **One unit = one worktree = one PR = one Linear leaf under OME-1289.** For each unit:
  `git fetch origin && git worktree add .claude/worktrees/<slug> -b <slug> origin/main`.
  This spec branch (`e4a-deterministic-combine`) holds documents only.
- **Ledger at the start.** Copy `docs/work/TEMPLATE.md` to `docs/work/<date>-<slug>.md`, with
  `ticket: unfiled`.
- **Dev loop.** Use the `sdlc-python` skill: frame → TDD (RED first) → append-only tests → gates →
  review → commit.
- **Gates.** `uv run .claude/scripts/run_gates.py <stack>` from the repo root. The stacks are
  `screamingface-engine` and `screamingface`.
- **Filing at PR-open.** Ask the user first. Then file one leaf under OME-1289 through Linear MCP,
  with: the landing label (`screamingface-engine` → `app/…`, or `client-sf` → `pkg/…`), one
  `who-acts`, one `actor`, and `assignee: me`. Add the `docs/tasks/` mirror. Rename the branch to
  `OME-N-<desc>`. Put `Refs: OME-N` in the PR body. Wait for green CI, then squash-merge.
- **Delegation.** Units 1–3 set the architecture: build them in the main loop, or give them to
  the `implementer` agent only with the PRD tables as a complete spec. After each delegated
  unit, the `design-reviewer` agent checks it against its PRD. Units 4–9 are small and follow
  the PRDs, so they fit `implementer` + `design-reviewer`, or `sdlc-unit-executor`.
- **Order across stacks.** The engine change merges before the SDK change that depends on it.
  The engine accepts the wider binding pattern before the SDK emits it, so each merge is safe
  by itself.

## 2. Units

| # | Slug | Landing | Depends on | PRD tests | Scope (files) |
|---|---|---|---|---|---|
| 1 | `e4a-combine-core` | engine | — | FW-1…FW-11, FW-13, FW-16, FW-17 | `combine/{__init__,ports,registry,spec,evidence,endpoint,builtins}.py`; new codes in `benchmarks/contract.py`; a `COMBINE_CORE` rule in `.claude/scripts/check_layering.py` + fixtures |
| 2 | `e4a-answer-operators` | engine | 1 | OP-1…OP-18 | `combine/operators/{extract,normalize,reduce,select}.py`; golden fixtures under `tests/unit/fixtures/combine/` |
| 3 | `e4a-engine-wiring-evidence` | engine | 1, 2 | FW-12, FW-14, FW-15; EV-1…EV-5, EV-9 (engine half) | `world/factory.py` install; `rest/operators.py` + mount; `operation_calls.py` (`combine` field); `benchmarks/operation_outputs.py` (pattern + copy); `benchmarks/contract.py` (`OperationOutput.combine`) |
| 4 | `e4a-sdk-reducer-slot` | sdk | 3 deployed or local engine | SL-1…SL-14; EV-6…EV-8, EV-11, EV-13, EV-14 | `fusion.py`; `reducer.py` (new); `_evaluation/candidate.py`; `_evaluation/topology.py`; `_engine/catalog.py` (operators client); `case_result.py` (`CaseOperation.combine`); `_evaluation/results.py` decode; `__init__.py` |
| 5 | `e4a-vote-median` | sdk (+ engine tests) | 4 | VT-1…VT-14 | `Vote`, `Median` in `reducer.py`; engine integration tests |
| 6 | `e4a-samples` | sdk | 4 | SM-1…SM-10 | `samples.py`; duplicate warning in the compiler |
| 7 | `e4a-weighted-vote` | sdk (+ engine tests) | 5 | WV-1…WV-9 | `Vote(weights=…)`; spec weights |
| 8 | `e4a-judge-pick` | engine + sdk (two PRs, engine first) | 4 | JG-1…JG-10 | engine: strict judge parser + `by_label@1`/`max_score@1`/`scores@1`; sdk: `Judge`, template `judge-template@1`, `judge_N` source |
| 9 | `e4a-pick-merge` | engine + sdk (two PRs, engine first) | 8 | PM-1…PM-15 | engine: `by_field@1`, `field_rules@1`, `project_field@1`; sdk: `Pick`, `Merge`, `FieldRule`, `writer_N` sources |
| 10 | `e4a-rank-concat` | engine + sdk (two PRs, engine first) | 8 | RK-1…RK-9, CC-1…CC-7 | engine: `top_k@1`, `join@1`, `all@1`; sdk: `Rank`, `Concat`, the selection compile checks |
| 11 | `e4a-e2e-replay` | sdk | 5, 6, 3 | EV-10, EV-12 | `packages/screamingface/tests/e2e/` GSM8K replay lane with `samples(<seed-capable model>, 5)` + `Vote` |

**Waves** (units in one wave can run in parallel; the WIP limit is 2 for each dev):
- Wave A: 1 → 2 (the same stack, in order).
- Wave B: 3.
- Wave C: 4.
- Wave D: 5, 6, 8 (engine half) in parallel.
- Wave E: 7, 8 (sdk half), 9 (engine half).
- Wave F: 9 (sdk half), 10.
- Wave G: 11.

## 3. Per-unit acceptance

A unit is done when:
1. Every PRD test listed for it is RED first, then GREEN.
2. The CHAR tests (SL-1, SL-2, EV-1, EV-2, SM-1) stay green in every later unit.
3. `run_gates.py` passes for each stack that the unit touches.
4. The ledger's Outcome section is filled in.
5. The Linear leaf and the mirror are closed after the merge.

## 4. Baseline (recorded before any code)

See [§6](#6-baseline-results). A unit that finds a red gate on `origin/main` stops and reports it.
It does not fix unrelated failures in the same PR.

## 5. Prerequisites to check before unit 1

- [x] The spec is approved.
- [x] A worktree is made from `origin/main`.
- [x] The engine and SDK baseline gates are run (results in §6).
- [ ] The user says to start.
- [ ] Linear MCP is active (`/mcp`), needed only at the first PR-open.
- [ ] The ERD diagram is exported to `docs/diagrams/` (SVG + PNG). A renderer is needed (for
      example the diagramming plugin). This is not a blocker for unit 1.

## 6. Baseline results

Run on 2026-09-30 in this worktree, at `origin/main` 4eca379d1, with `--skip-append-only`
(no tests have changed yet).

| Stack | Command | Result |
|---|---|---|
| `screamingface-engine` | `uv run .claude/scripts/run_gates.py screamingface-engine` | ALL GATES GREEN: ruff, format, pyright, layering, pytest (cov ≥ 80) |
| `screamingface` | `uv run .claude/scripts/run_gates.py screamingface` | ALL GATES GREEN: ruff, format, pyright, pytest (cov ≥ 95), notebooks, build, distribution check |

**Setup notes for each new unit worktree** (both were found in this run):
- Run the gate runner with `uv run`, not `python3`. It needs PyYAML, which comes through PEP 723.
- The SDK needs `uv sync --extra notebook` (as in `screamingface-tests.yml:54`). Without it,
  pyright fails on `ipywidgets` imports.
- The engine needs `uv sync --dev` (as in `screamingface-engine-tests.yml:55`).
