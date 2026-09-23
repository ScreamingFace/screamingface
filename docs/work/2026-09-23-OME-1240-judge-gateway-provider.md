---
ticket: OME-1240
stack: screamingface-engine
status: in_progress
started: 2026-09-23
finished:
---

# OME-1240 — Prove an LLM-judged imported benchmark grades through our gateway

## Intent

The model-graded import lane is broken in three places (judge model unavailable outside
inspect's eval loop; judge tokens can't reach `cost_usd` via env vars; judge absent from
the revision hash). Build the gateway-backed judge path — an inspect model provider that
forwards `generate()` through the aigateway connector, bound as the grader role in the
shim — and prove it by importing xstest. Unblocks the judge-scored set (coconot, uccb,
sosbench, frontierscience) and every future judge board. Full design + evidence: the
reshaped ticket body (2026-09-23).

## Planned changes

Stacked PRs (~500 LoC cap each), in `apps/screamingface-engine`:

1. **PR 1 — provider + role binding:** new `src/screamingface_engine_inspect/judge_provider.py`
   (inspect `@modelapi("screamingface")` forwarding to the aigateway connector);
   `shim.py` binds the grader role around `await scorer(state, target)` and fills the
   evidence `accounting` field (currently hardcoded `None` at `shim.py:201,218`).
   PRECHECK first: is the run's usage-sink context live inside the grade route?
2. **PR 2 — revision pins + importer flag:** `single_shot.py` / `boards.py` hash scorer
   reference + kwargs (judge model, template, instructions) for model-graded boards only;
   `importer.py` detects `model_graded_*` / judge kwargs and emits TODO(review).
3. **PR 3 — xstest import:** standard three rows via the importer; judge pinned.
4. **PR 4 — docs:** runbook (`docs/adding-an-imported-benchmark.md` Step 0/2/refusal
   table), spec §3.3 (`docs/spec/2026-09-09-OME-1113-inspect-evals-import.md`), package
   docstring.

## Test plan

- RED: provider unit test (inspect `mockllm` / fake connector) — judge `generate()` goes
  through the aigateway connector and its tokens land in the usage sink (invariant: a
  judged score that omits judge cost is wrong by construction).
- RED: revision test — changing the judge model or template moves the revision; the 10
  published string-match boards' revisions are byte-identical before/after (append-only
  guard).
- RED: importer test — a model-graded scorer yields the TODO(review) flag, not a silent
  board.
- Error path: provider surfaces connector failures as per-Case scorer errors, not crashes.

## Acceptance

- Ticket's items 1, 2, 4 (item 3, the `limit=2` live run, is owner-run — paid).
- All screamingface-engine gates green per `.claude/sdlc.local.md`.

## Outcome (fill at the end — required before COMMIT)

### PR 1 (provider + context plumbing)

- **Actual files:** `src/screamingface_engine_inspect/judge_provider.py` (new),
  `src/screamingface_engine/benchmarks/spine/scored.py` + `single_shot.py`
  (`_run_sync` copies the caller's context into the worker thread),
  `tests/unit/inspect/test_judge_provider.py` (new, 9 tests),
  `tests/unit/test_spine_scored.py` (+1 context-propagation test).
- **Commits:** (filled at commit)
- **Gates:** run_gates.py screamingface-engine ALL GREEN; inspect lane
  `uv run --extra inspect pytest tests/unit/inspect` 219 passed.
- **Deviations:**
  - PRECHECK verdict: the usage sink was NOT live in the grade route (worker
    thread drops contextvars); fixed via `contextvars.copy_context()` in both
    `_run_sync` twins — plumbing, not redesign, as the ticket anticipated.
  - Grader-ROLE binding deferred (YAGNI): the explicit-model path
    (`model="screamingface/<route>"`) covers xstest; role binding lands when a
    role-based eval (simpleqa) imports.
  - Per-case evidence `accounting` stays `None` in PR 1: run-level metering is
    the acceptance; the endpoint seam returns text only. Follow-up noted.
  - Transport BINDING in the aggregate path ships with PR 2 (it needs the
    board-declared judge params from the importer).

### PR 2 (judge declaration: exam identity + binding + assembly guards)

- **Actual files:** `single_shot.py` (JudgeSpec, revision pins for judge
  model/params, check-surface guard, `_aggregate` binds the transport via
  `node.fetch`), `boards.py` (BoardSpec.judge, `_check_judge_declaration`
  cross-checks, `_judge_prompt_pins` — scorer + kwargs hashed for judged boards
  only), `shim.py` (two latent wire bugs fixed: non-JSON Score.metadata filtered;
  invalid failure evidence no longer claims an outcome),
  `tests/unit/inspect/test_judged_board_assembly.py` (new, 13 tests).
- **Gates:** run_gates.py ALL GREEN; inspect lane 232 passed; spine suite green.
- **Deviations:**
  - Importer flag moved from PR 2 to PR 3 (rides with the xstest import) to
    respect the ~500 LoC PR cap.
  - Two pre-existing shim defects surfaced by the first wire-crossing judged
    aggregate: (1) `model_graded_qa` attaches its grading transcript (non-JSON
    objects) to `Score.metadata`, which the shim spread verbatim into wire
    evidence; (2) `_failure` evidence claimed `outcome: FAIL` with
    `valid: False`, which the wire model refuses — meaning a `scorer_error`
    could never publish on ANY imported board. Both fixed, both pinned by the
    end-to-end tests.
