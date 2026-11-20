---
ticket: OME-1990
stack: screamingface
status: done
started: 2026-11-20
finished: 2026-11-20
---

# e5-p2-client-port — E5 P2 Client port: one transport port, the follow-a-Run port

## Intent

The Client port PR of E5 P2 (`OME-1837`), plan step CP1. After the Client PR (#1878) the Engine
drives every Run and the Client follows it; only test fakes still reach the per-Candidate `run()`
port and the runner's pool. This unit leaves one transport port: `SyncRunTransport` and
`AsyncRunTransport` become the follow-a-Run port, and the runner loses its pool, its fan-out cap
and the `GET /v1/limits` read. The rules `_RunState` used to fold a Candidate's outcome by (cache
evidence, the capture summary, client provenance, span time clamping, root detection) are pinned
by tests of the Engine's fold, which builds the record the Client now reads, and `_RunState`'s
outcome building goes. It changes nothing a user of `evaluate` can observe; `run_transport`
changes shape once, before the next Client release.

Spec `docs/spec/2026-11-04-e5-p2-detached-run.md` (§4.6 "The transport port is 'follow a Run'",
§5 landing 4) and plan `docs/plan/2026-11-04-e5-p2-detached-run.md`, "Client port PR", CP1, and
"Prior tests" → "Client port". Stacked on #1878 (branch `OME-1943-e5-p2-client`), which is stacked
on the Engine PR #1759; the owner asked to start this on top of #1878. Closes the item #1878's
review deferred here: the legacy `run()`-only branch in `ports.py` and `runner.py`, with its casts
and the `load_caller_cap` loaders.

## Planned changes

Paths under `packages/screamingface/` unless named.

- `src/screamingface/_core/ports.py`: `SyncRunTransport` / `AsyncRunTransport` are the
  follow-a-Run port (the shape `_RunFollowing` / `_AsyncRunFollowing` have today: `register_run`,
  `follow_run`, `cancel_run`, `close`); `run()`, `cancel_active`, `_RunRegistration`,
  `_ConnectionListener` (if nothing reads it) and the `_SyncTransport` / `_AsyncTransport` unions
  go.
- `src/screamingface/_evaluation/runner.py`: remove `_run_candidates_sync`,
  `_run_candidates_async`, `_MAX_CANDIDATES_IN_FLIGHT`, `load_caller_cap` and its loaders,
  `_isolated_*`, `_settled_results`, `_settled_tasks`, `_sweep_*` (the `cancel_active` sweep),
  `open_run_*`, `_opened_*` and the capability check between the two paths, with their casts.
- `src/screamingface/_evaluation/url4.py`: the same for the one-Candidate path.
- `src/screamingface/_evaluation/following.py`: typed on the port.
- `src/screamingface/_engine/limits.py`: removed (#1745).
- `src/screamingface/client.py`: `run_transport` takes the follow-a-Run port; no cap loader.
- `src/screamingface/_engine/contract.py`, `_engine/run_lifecycle.py`: `_RunState` no longer builds
  an outcome.
- `CHANGELOG.md`: one entry for `run_transport`'s new shape. `tests/public_surface_snapshot.json`
  if the signature text changes.
- New `tests/_run_transport.py`: turns a scripted per-Candidate function (return an outcome, raise,
  emit events, wait for a signal) into a follow-a-Run fake that settles Candidates in the scripted
  order.
- New Engine tests (`apps/screamingface-engine/tests/unit/`) porting `_RunState`'s rules to
  `screamingface_engine/candidate_record.py`.
- Prior tests rewritten, exactly the plan's CP1 groups (the 40 files with a `run()` fake, and the
  seven `_RunState` outcome files), each named in the approvals manifest.

## Test plan

- RED first: the helper's own test (settles in scripted order, routes events by index, a raised
  error settles that Candidate failed, a Candidate waiting for a signal lets its sibling settle
  first, `cancel_run` stops the rest); the ported fold-rule tests, run against the Engine's fold.
- The 29 fail-if-called and canned-outcome fakes rebuilt on the helper; their assertions
  unchanged.
- The 11 concurrency, ordering, sibling-failure and abort files keep every assertion about what the
  Client shows and returns, driven by the order of settled frames; assertions about threads in
  flight inside the Client become "the Client starts no Candidate".
- Targeted: the Client suite (`packages/screamingface`) and the Engine tests added or touched.

## Acceptance

- One transport port; no `run()` / `cancel_active` / `load_caller_cap` / `_engine/limits.py` /
  pool / casts left in the Client source.
- Every `_RunState` outcome rule is pinned by a passing test of the Engine's fold, or reported as
  a finding.
- The Client suite and the touched Engine tests pass; no prior assertion is loosened.
- One signed commit for CP1; the manifest names every rewritten prior test.

## Progress

- 2026-11-20: worktree `.claude/worktrees/e5-p2-client-port` on `e5-p2-client-port`, from
  `origin/OME-1943-e5-p2-client` at `ccad0b15b`.
- 2026-11-20: the ported fold rules, RED first against the Engine's fold:
  `apps/screamingface-engine/tests/unit/test_candidate_record_rules.py`, 71 cases, 52 pass and
  19 fail (STOP B below).
- 2026-11-20: the source port, uncommitted: `_core/ports.py` (one port: `register_run`,
  `follow_run`, `cancel_run`, `close`), `_evaluation/runner.py` (1358 to 1003 lines: no pool, no
  cap, no sweep, no casts), `_evaluation/url4.py`, `_evaluation/following.py`, `client.py`,
  `_engine/limits.py` removed, `_engine/contract.py` and `_engine/run_lifecycle.py` (no outcome).
  ruff and pyright clean on `src/`. Full Client suite after it, with the notebook extra: 7145
  passed, 320 failed, 12 errors. 37 failing files are in the plan's CP1 groups; 22 are not, of
  which 18 only import a fake from a CP1 file (they pass once it is rebuilt under its name).
- **STOP (2026-11-20), blocked on the owner:**
  - A. Four prior test files outside the plan's CP1 groups must change: the three from #1745
    (`test_evaluate_fanout_cap.py`, `test_engine_limits.py`,
    `test_engine_limits_fallback_logging.py`; merged 2026-11-12, after the plan listed the groups),
    which test only what CP1 removes; and `test_archive_cost.py`, whose decode tests read
    `_RunState`'s outcome through `test_cached_run_not_complete._decode`.
  - B. 19 ported assertions fail on the Engine's fold: it reads as unknown, or ignores, what the
    Client's fold refused (a second root started frame or result; malformed summary counts and
    amounts; malformed capture attributes). Engine source is not changed here.
- **Owner decisions (2026-11-20):**
  - A1. Delete `tests/test_evaluate_fanout_cap.py`, `tests/test_engine_limits.py` and
    `tests/test_engine_limits_fallback_logging.py`: every test in them covers code CP1 removes (the
    runner's pool and fan-out cap, its loaders, `_engine/limits.py`). Their replacements are
    tested elsewhere: the Engine driver filling the per-caller cap (E3, the Engine PR's driver
    tests) and the Client's follow with no pool (`tests/test_run_follow_runner.py`, C1).
  - A2. `tests/test_archive_cost.py` is an eighth `_RunState` file: its decode tests move to the
    Engine's fold tests and its other tests stay as they are. (Recount: 11 decode tests, 20
    cases, and 10 others; the STOP said 12 and 9.)
  - B. Engine source is not changed here; a separate Engine leaf makes `candidate_record.py` fail
    closed on malformed summary and capture figures before the Client release. The two
    duplicate-root rules are ported in the Engine's reading (the first started frame and the
    first result win). The other 17 stay out of this commit and are listed below for that fix.

## Land with the Engine fold fix (not in CP1)

The 17 `_RunState` rules the Engine's fold does not hold yet (owner decision B, 2026-11-20). Each
input is put on the run summary log of the real cache-hit stream
(`apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json`, the `ai.url4.log`
whose attributes carry `cache.hits`); the capture cases first drop that log's `capture.*` keys. The
Client's fold stopped the Candidate with `ExecutionError` on every one. The Engine's fold today
records a successful record; its reading is noted after each so the fix can port them as written.

Removed from `packages/screamingface/tests/test_cached_run_not_complete.py`,
`test_a_malformed_summary_count_is_refused`:
1. `cache.hits = -1` → Client: `ExecutionError` ("cache summary cache.hits is invalid"). Engine:
   the summary is ignored, `cache_hits` 1 from the spans, `cache_unpriced_hits` None.

Removed from `packages/screamingface/tests/test_archive_cost.py`,
`test_a_malformed_unpriced_count_is_refused[value]`:
2. `cache.saved_cost.unpriced_hits = -1` → Client: `ExecutionError`. Engine: unpriced None.
3. `cache.saved_cost.unpriced_hits = True` → Client: `ExecutionError`. Engine: unpriced None.
4. `cache.saved_cost.unpriced_hits = 1.5` → Client: `ExecutionError`. Engine: unpriced None.
5. `cache.saved_cost.unpriced_hits = "0"` → Client: `ExecutionError`. Engine: unpriced None.

Removed from `packages/screamingface/tests/test_archive_cost.py`,
`test_a_malformed_summary_amount_is_refused[value]`:
6. `cache.saved_cost_usd = "-1"` → Client: `ExecutionError`. Engine: carried as `"-1"` with
   unpriced 0 (the Client later refuses it at `CandidateResult`, a `ValueError`).
7. `cache.saved_cost_usd = "NaN"` → Client: `ExecutionError`. Engine: carried as `"NaN"` with
   unpriced 0 (the Client's record reader refuses it as a malformed record).
8. `cache.saved_cost_usd = "abc"` → Client: `ExecutionError`. Engine: saved None, unpriced None.
9. `cache.saved_cost_usd = 0.5` (a float) → Client: `ExecutionError`. Engine: saved None,
   unpriced None.

Removed from `packages/screamingface/tests/test_capture_summary.py`,
`test_a_malformed_partial_count_fails_closed[count]`, each with `capture.status = "partial"`:
10. `capture.partial.local = -1` → Client: `ExecutionError` ("capture.partial.local is invalid").
    Engine: the reason is dropped, status `partial`.
11. `capture.partial.local = True` → as 10.
12. `capture.partial.local = "one"` → as 10.
13. `capture.partial.local = 1.5` → as 10.

Removed from `packages/screamingface/tests/test_capture_summary.py`,
`test_a_malformed_capture_attribute_stops_the_run[attributes]`:
14. `{"capture.status": "maybe"}` → Client: `ExecutionError` ("capture summary"). Engine: status
    None.
15. `{"capture.status": True}` → as 14.
16. `{"capture.status": "complete", "capture.frozen_copy_id": 7}` → Client: `ExecutionError`.
    Engine: status `complete`, copy None.
17. `{"capture.status": "complete", "capture.replay": 7}` → Client: `ExecutionError`. Engine:
    status `complete`, replay None.

## Outcome

- **Actual files** (vs planned):
  - Client source (+156 / −972 lines in 9 files): `_core/ports.py` (`SyncRunTransport` and
    `AsyncRunTransport` are the follow-a-Run port: `register_run`, `follow_run`, `cancel_run`,
    `close`; `_RunFollowing`, `_RunRegistration`, their async twins and the transport unions
    go), `_evaluation/runner.py` (1358 to 1003 lines), `_evaluation/url4.py`,
    `_evaluation/following.py`, `client.py`, `_engine/contract.py` and `_engine/run_lifecycle.py`
    (`_RunState` validates and decodes, and builds no outcome), `runs.py` (two comments);
    `_engine/limits.py` deleted.
  - `CHANGELOG.md`: one entry, `run_transport`'s new shape. `tests/public_surface_snapshot.json`
    is unchanged: the annotation still reads `SyncRunTransport | None`.
  - New `tests/_run_transport.py` (`ScriptedRun`, `AsyncScriptedRun`, `AsyncPlaying`,
    `settled_sync`, `settled_async`) and its test `tests/test_run_transport.py`.
  - New Engine tests: `apps/screamingface-engine/tests/unit/test_candidate_record_rules.py` (root
    detection, the result, the usage) and `test_candidate_record_evidence_rules.py` (cache
    evidence, capture summary, provenance, span clamping); 55 cases.
  - Prior tests: 34 of the plan's CP1 files rewritten, plus `test_archive_cost.py` (A2); the 3
    #1745 files deleted (A1). 10 listed files needed no edit: their fakes subclass a rebuilt fake
    (`test_answer_seed_report.py`, `test_reproduce_review.py`, `test_accounting_token_unknowns.py`,
    `test_accounting_evaluation.py`, `test_inverted_grade_report.py`, `test_use_cache.py`,
    `test_cache_saved_cost_submission.py`, `test_combine_evidence.py`, `test_case_selection.py`),
    or C1 already moved them onto the Run stub (`test_evaluation_outcome.py`).
  - `.claude/test-change-approvals/OME-E5P2-CP1.json` (placeholder id, see below).
- **Commits:** one signed commit for CP1, `refactor(screamingface): leave one transport port, the
  follow-a-Run port`, on branch `OME-1990-e5-p2-client-port`.
- **Gates:** not run as `run_gates.py` (CI runs them). Locally, with the notebook extra: the
  Client suite 7520 passed, 38 skipped, coverage 96.74% (floor 95); `ruff check`, `ruff format
  --check` and `pyright` (src and tests) clean. Engine: the two new files 55 passed, ruff and
  pyright clean; the two edited subprocess tests above, 25 passed with their files. The pre-push
  Engine gates (`run_gates.py screamingface-engine`) ran at the push. The append-only check alone, against the merge-base with `origin/main`: the
  Engine stack passes; the Client stack lists only the three deletions (A1), which no blob pair
  can approve. No hook runs that check for this stack.
- **Manifest:** `.claude/test-change-approvals/OME-1990.json`, branch
  `OME-1990-e5-p2-client-port`, 96 entries: every prior test file the stack changes against
  `origin/main` (this unit's, and, unchanged, the Client and Engine PRs' carried from `OME-1943`).
  Regenerated at PR-open under the filed id and the renamed branch (it replaced the placeholder
  `OME-E5P2-CP1.json`); regenerate it again after the rebase onto `main` once #1878 merges, or
  after any merge of `main` that touches a listed file.
- **Owner decision at PR-open (2026-11-20):** the pre-push Engine gates found two more prior tests
  outside the CP1 groups that read `_RunState`'s outcome, each through the Client in a subprocess:
  `apps/screamingface-engine/tests/unit/test_model_activity_stream.py::test_existing_independent_client_accepts_real_model_activity_wire`
  and
  `apps/screamingface-engine/tests/unit/test_structured_log_forwarding.py::test_existing_client_decodes_real_serialized_engine_lifecycle`.
  The owner approved replacing `assert accepted.outcome is not None` in each with
  `assert isinstance(accepted.event, Terminated) and accepted.event.status == "succeeded"` (and
  importing `Terminated` beside `Log`), nothing else. Reason: the Client builds no outcome from
  frames any more (it reads the Engine's record, pinned by the fold tests and
  `test_run_record_outcome.py`); the new line keeps what the check proves, that the independent
  Client accepts the real lifecycle through the root's successful end. Both are in the manifest.
- **PR-open (2026-11-20):** filed `OME-1990` under `OME-1837` with the owner's confirmation;
  branch renamed from `e5-p2-client-port`; the PR targets `OME-1943-e5-p2-client` (#1878) and is
  retargeted to `main` and rebased after #1878 merges.
- **Deviations:**
  - **`_evaluation/following.py` behaviour fix.** The follow path (C1) canceled the Run on an
    abort but never showed the siblings still running as stopped, so a callback error, a
    cancelled task or `SystemExit` read them as `run_failed`, and the terminal printed no
    "run stopped" line: OME-1071's invariant, which `test_evaluation_outcome_abort.py` and
    `test_evaluation_outcome_cancelled.py` pin. Those rewritten tests failed first; the follow now
    shows each Candidate that began and has not ended as stopped once it cancels the Run, except
    the one whose own `on_event` raised (the final abort shows that one, as before). A released
    Client shows the same.
  - **Port shape.** The plan names the port `(follow_run, close)`; the runner also registers and
    cancels the Run through it, so the port is the shape `_RunFollowing` had.
  - **The fakes' per-Candidate script keeps the name `run`.** `test_cache_saved_cost_timestamp.py`
    (outside the CP1 groups) monkeypatches `_CachedReplayTransport.run`; keeping the name leaves it
    unchanged. `run` is no longer on the port.
  - **Abort scenes.** Ctrl-C used to be scripted inside a Candidate's own `run()`; on the follow it
    lands on the caller's thread, so `test_swept_sibling_reads_as_stopped[interrupt]` raises it
    while the follow shows `a`'s start. Its assertions are unchanged.
  - **Notes on a failed cancel** now read "Canceling Run … on the SF Engine also failed: …" (the
    follow's text since C1) where they read "Stopping active SF Engine runs also failed".
  - **`test_run_registration.py`:** `test_an_evaluation_without_a_run_is_unchanged` is removed,
    since no transport runs an evaluation without a Run (P2 D2); the raw-URL4 test asserts the Run
    is registered with no benchmark and one Candidate (P1's `open_run` took a label and 0 cases).
  - **Draco:** `max_active == 3` (threads in flight in the Client) is now "the Client registers
    every Candidate in one Run and starts none" (`transport.registered`), as the plan says.
  - **Kept, not removed:** `_RunState` keeps its root checks (a second root started frame; an
    end with no root), and `contract._accumulated` stays, because
    `test_activity_decoder_bounds.py`, `test_engine_cost_breakdown_warning.py` and
    `test_run_cost_status.py` (outside the CP1 groups) use them. After C1 nothing in `src/` uses
    `_RunState` or `_engine/run_lifecycle.py`.
  - **No Engine counterpart** for "an advisory (unsequenced) log cannot stamp the root": the fold
    sees only frames its own runner published, and advisory notices are added by the App.
  - **Left as is:** `test_run_report_fallbacks.py` (outside the groups) passes a `run()`-only
    `_CannotFollow` through `cast(Any, …)`; it still covers `Run.wait()` and `Run.report()` with a
    transport that cannot wait or rebuild.
