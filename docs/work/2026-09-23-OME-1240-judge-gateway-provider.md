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
3. **PR 3 — sample-metadata plumbing + importer judge flag** (plan updated: the
   proof board moved to frontierscience; see the PR-3 outcome below).
4. **PR 4 — FrontierScience import;** **PR 5 — docs** (runbook Step 0/2/refusal
   table, spec §3.3, package docstring).

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

### PR 3 (sample-metadata plumbing + importer judge flag)

- **Proof board re-picked: frontierscience replaces xstest.** The sweep (PR #1018
  Appendix A) + a live probe settled it: xstest's dataset (walledai/XSTest) is
  GATED on the HF Hub → `OME-1270`'s lane; uccb bakes clean but carries the
  cc-by-nc-sa-4.0 licence the owner refused for sec_qa; coconot/sosbench fail
  the bake (empty targets). frontierscience: clean bake, apache-2.0, explicit
  `model` kwarg (our path), 160 cases, needs shuffle-seed + sample metadata.
- **Actual files:** `prepare.py` (`SnapshotSpec.keep_sample_metadata` opt-in —
  bakes Sample metadata into the private target; JSON-refusal by case; default
  False keeps published snapshots byte-identical), `boards.py` (the opt-in is a
  revision pin), `shim.py` (material metadata → TaskState.metadata),
  `importer.py` (model_graded_* scorers emit `judge=JudgeSpec(model="TODO")` +
  TODO(review) — refused at assembly until resolved), tests appended to shim /
  snapshots / importer suites (9 new).
- **Gates:** run_gates.py ALL GREEN; inspect lane 241 passed.

### PR 4 (the frontierscience board — first judged import)

- **Actual files:** importer-generated rows in `pins.py` / `prepare.py` /
  `boards.py` (160 cases, apache-2.0, dataset revision `25ed67db…`, shuffle seed
  20260923), TODOs resolved by hand: prose, difficulty=hard, judge pinned to
  `openrouter/openai/gpt-5.4` (HealthBench's judge; params mirror its
  web_search=false + max_tokens=4096, temperature deliberately unpinned),
  `keep_sample_metadata=True`, check surface off (judged);
  `tests/unit/inspect/test_inspect_frontierscience_board.py` (new — both judge
  formats grade end-to-end through the node route); catalogue-table extensions
  in `test_inspect_imported_boards.py` (family label "judged") and
  `test_benchmark_declaration.py` (one row) — **owner approved
  --skip-append-only for these on 2026-09-23**.
- **Gates:** run_gates.py --skip-append-only ALL GREEN; inspect lane 250 passed.
- **Deviations:** proof board is frontierscience, not the ticket's xstest
  (gated dataset) — recorded in the PR-3 section above.

### Review round (2026-09-24) — 5 blockers verified and fixed

All five external findings CONFIRMED (NaN abort reproduced; httpx
"bound to a different event loop" reproduced on the deployed shape; the
importer gap matched this ledger's own frontierscience run). Fixes, each in
the PR where its cause lives, merged forward through the stack:

- #1032: non-finite Score → `invalid_score_value` (one Case, never the run);
  provider refuses empty replies and eval-supplied sampling settings; the spine
  gains an async aggregate face (`aggregate_async` + `async_aggregate_endpoint`)
  so judged grading stays on the run's own loop.
- #1034: judged detection keys on judge-model KWARGS (not scorer names), foreign
  provider models refused; the judged aggregate registers the async face; the 17
  published revisions frozen as literals; `_run_sync` twins parity-pinned.
- #1037: the importer detects judged rows by kwarg and never emits a check
  surface for them.
- #1040: honest comparability note (paper judge = GPT-5 high reasoning effort;
  ours not comparable); board revision literal (`34155c32aec9841b`); gradeless
  reply loses one case; olympiad prompt asserted chunk-for-chunk vs upstream.
- #1041: runbook — judge-model-is-declared checklist item, judged-row default
  wording; this ledger refresh.

Accepted, not implemented: truncated judge replies can read as real zeros
(watch finish reasons in the live run before touching the max_tokens cap);
per-case judge accounting stays run-level.
