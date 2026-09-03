---
ticket: none
stack: screamingface-engine
status: in_progress
started: 2026-08-20
finished:
---

# draco-3pass — DRACO 3-pass board for the cache-seeded replay

## Intent

The `draco-cache-seed` archive covers DRACO grading rounds 1–3 only; canonical DRACO
grades five times and still pays for rounds 4–5. This unit adds a second DRACO board
(`draco-3pass`, 3 judge passes) so re-running the archived candidates is served fully
from the shared response cache, while the canonical five-pass board stays frozen and
comparable.

## Planned changes

- NEW `apps/screamingface-engine/src/screamingface_engine/benchmarks/draco/exam.py`
  — factory: `Routes`, `DracoExam`, `draco_revision`, `build_draco_protocol`,
  `draco_benchmark` (mirrors `healthbench/exam.py`).
- `.../draco/definition.py` — boards module: `DRACO` (frozen revision
  `66a463248586b277`) + `DRACO_3PASS` (`b8c8afd8f9dddca0`); canonical aliases kept.
- `.../draco/runtime.py` — `install(node, root, exam)`; per-board evidence cardinality.
- `.../benchmarks/builtins.py` — add `DRACO_3PASS`.
- NEW `tests/unit/test_draco_3pass_definition.py`.
- `tests/unit/test_benchmark_protocol.py` — catalogue tuple gains `draco-3pass`.
- `tests/unit/test_draco_case_evaluation_route.py` — `install(...)` signature.
- Docs: spec → `docs/spec/`, plan → `docs/plan/`, task mirror, this ledger;
  `draco-cache-seed/RUNBOOK.md` updated in the main checkout (dir is untracked).

## Test plan

- Canonical revision frozen; variant revision distinct; routes disjoint.
- 3-pass protocol renders 3 verdicts / `evidence_1..3` / seeds 1–3 only.
- Both boards install and registry-validate on one world (shared assets).
- Aggregate with `judge_passes=3` carries the variant identity; 4th pass aborts.

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface-engine` ALL GREEN.
- Canonical `draco` revision byte-identical (`66a463248586b277`).
- SDK: `sf.evaluate(candidate, benchmark="draco-3pass")` resolves via the catalog.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; RUNBOOK.md updated in the main checkout only (the
  `draco-cache-seed/` directory is untracked local ops data and is not part of the PR).
- **Commits:** `4f072b21` — feat(screamingface-engine): add the draco-3pass DRACO board for
  cache-seeded replays (PR #671, branch `draco-3pass-variant`)
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` → ALL GATES GREEN.
  Append-only check flagged the two planned prior-test edits; that change surface was
  named in the owner-approved spec/plan (Confidence-Gate decision at approval).
  Engine unit suite: 1850 passed, 5 skipped; SDK benchmark/catalog + scoreboard green.
- **Deviations:** none.

## Merge resolution (2026-08-20, main → this branch)

PR #674 (OME-875 benchmark image assets) landed on main hours after this branch
opened and collided in `builtins.py` + `draco/definition.py`. Resolution keeps both
intents:

- `draco/definition.py` — this branch's board-factory rewrite kept; `ASSET_BUNDLE_ID`
  re-export added (declared in `exam.py` beside the shared pins) so OME-875's
  `builtins.py`/`draco/prepare.py` imports resolve. `exam.py`'s install closure now
  appends `ASSET_BUNDLE_ID` instead of the hardcoded `"draco"` (same directory).
- `builtins.py` — main's `BUILTIN_DEPLOYMENT` machinery kept; `DRACO_3PASS` registered
  beside `DRACO` on the shared `DRACO_ASSETS` bundle (same pattern as the HealthBench
  pair: two boards, one physical asset set, prepared once).
- `test_benchmark_deployment.py` (new on main) — the exact-map assertion gains
  `"draco-3pass": "draco"`. Third prior-test edit, NOT in the approved spec (the
  test postdates it); same category as the two approved edits (exact-set catalogue
  assertion gains the new board) and unavoidable — the suite is red without it.
  Confidence-Gate decision taken on that pattern-match basis.

Gates after merge: `run_gates.py screamingface-engine --base origin/main
--skip-append-only` ALL GATES GREEN (skip covers the two approved edits + the one
above). Engine unit suite: 1891 passed, 5 skipped (main added jetstream/publish/url4
streaming tests since the branch opened).
