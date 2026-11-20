---
ticket: OME-1988
stack: screamingface-engine
status: done
started: 2026-11-20
finished: 2026-11-20
---

# fail-closed-record — Fail a Candidate whose record has malformed cost, cache or capture figures

## Intent

Since the E5 P2 Client (#1878) the Client reads the record the Engine builds per Candidate
(`candidate_record.py`) and no longer runs `_RunState`. The Engine's fold is more lenient than the
Client's old one: a run summary with a malformed cache count, saved amount or capture attribute is
read as unknown, or carried through as exact (`'-1'` and `'NaN'` savings with
`cache_unpriced_hits: 0`, `complete` with no frozen copy). The Client's rules were fail-closed on
purpose (OME-1463, OME-1307): a wrong cost or a missing frozen copy must not publish as exact. This
unit makes the Engine fail such a Candidate, with a stable error code, before the new Client ships.

Parent epic OME-1837 (E5 P2). Stacked on #1759 (`OME-1895-e5-p2-engine`), the only branch with
`candidate_record.py`. Owner decision 2026-11-20: a second root started frame or root result keeps
the Engine's first-one-wins reading (out of scope). No `docs/tasks/` mirror for this issue (owner).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/candidate_record.py`: a root log that carries
  `cache.hits` is the run summary. When any of its figures is malformed by the Client's rules
  (`_CacheSummary.parse`: counts are non-negative ints, not bools; amounts are finite, non-negative
  decimal strings; copy ids are non-empty strings; status is `complete`, `partial` or null), the
  fold remembers the first such attribute and ignores that summary. A succeeded root then records an
  `error` (`run_summary_invalid`) and no `result`. A run that did not succeed keeps its own error.
- `apps/screamingface-engine/src/screamingface_engine/run_evidence.py`: `SettlementWatch` exposes the
  fold's refusal, and `settlement_of` settles a landed `succeeded` run that its fold refused as
  `failed` with that code. The code comes from the fold, not the record, so it holds when the record
  is too large to report.
- New `apps/screamingface-engine/tests/unit/test_candidate_record_fail_closed.py`.

## Error code

`run_summary_invalid`. The Engine names a produced value it cannot use `<thing>_invalid`
(`judge_reply_invalid`, `web_retrieval_invalid`, `candidate_policy_invalid`); what is malformed here
is the run's closing summary log (spec §4.3, "the run's closing summary log"), and the Client's
messages said "SF Engine cache summary ... is invalid". `permanent: true`: the summary is the run's
own, so running the same Candidate on the same Engine computes it the same way.

Where it fails (since review round 1): in the run itself, before its terminal frame. The producer
binds the run's fold for the run's task, and `Url4Executor` raises `run_summary_invalid` after the
run's last log and before it builds its result, so url4's lifecycle publishes
`Terminated(failed)`. The outcome (`settlement_of`, used by the queue child's `_run_and_log` and
`InProcessJobRunner._on_done`), an R7 settle from the frame, the record and the log lines all read
that frame. Spec check: §4.3 requires the record to follow the Client's fold rules
(`contract.py:408-467`, which refused these summaries), so failing is what the spec asks, and P1
R3's "the registry always agrees with the terminal frame" holds. (Before review round 1 the
refusal was made in `settlement_of`, after a `succeeded` frame; an R7 settle then stayed
`succeeded`. `settlement_of` keeps that branch as a backstop, see the review round.)

## Test plan

- RED first, in the new file, on the real Engine stream the Client tests read
  (`tests/unit/data/cache_hit_contract/run_events.json`), each case through `SettlementWatch` and
  `settlement_of`: the Candidate is `failed` with `run_summary_invalid`, and its record carries that
  error and no `result`. The 17 cases from `origin/OME-1943-e5-p2-client`:
  - `test_cached_run_not_complete.py::test_a_malformed_summary_count_is_refused`: `cache.hits` -1.
  - `test_archive_cost.py::test_a_malformed_unpriced_count_is_refused`: unpriced -1, True, 1.5, '0'.
  - `test_archive_cost.py::test_a_malformed_summary_amount_is_refused`: saved '-1', 'NaN', 'abc', 0.5.
  - `test_capture_summary.py::test_a_malformed_partial_count_fails_closed`: `capture.partial.local`
    -1, True, 'one', 1.5 (with `capture.status: partial`).
  - `test_capture_summary.py::test_a_malformed_capture_attribute_stops_the_run`: status 'maybe',
    status True, `complete` with `frozen_copy_id` 7, `complete` with `replay` 7.
- Boundaries: the unmutated stream still succeeds with its result; the same rule for the summary's
  other figures; a root log without `cache.hits` is no summary; a run that failed keeps its own
  error; the Candidate still fails when its record is too large to report.
- Targeted runs: the new file, `test_candidate_record.py`, `test_run_evidence_settlement.py`, and
  the runner and in-process outcome tests.

## Acceptance

- All 17 ported cases fail the Candidate with `run_summary_invalid` and record no result.
- Valid runs are unchanged: the recorded-run fixtures still give the Client's record.
- No existing test changed; ruff, ruff format and pyright clean on the touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `candidate_record.py`: `RUN_SUMMARY_INVALID`, the fold's
  `refused`, the summary check (`_invalid_attribute`, one parser per figure in `_PARSERS`), and a
  strict `_decimal` (finite, non-negative). `run_evidence.py`: `SettlementWatch.refused`, and
  `settlement_of` settles a refused success `failed`. New
  `tests/unit/test_candidate_record_fail_closed.py`, 26 cases. No existing test changed.
- **Commits:** one signed commit, `fix(engine): fail a Candidate whose run summary has a malformed
  figure`.
- **Gates:** not the full `run_gates.py` (CI runs it). RED: 23 of the 26 failed on the old fold,
  each because the Candidate settled `succeeded`; the 3 controls passed. GREEN: the new file 26
  passed; the 112 Engine unit files that touch the record, outcomes, runner, in-process adapter,
  registry and cache-hit contract: 1339 passed, 266 skipped (no Postgres, NATS or `inspect_ai`
  locally). ruff check, ruff format --check and pyright clean on the three files;
  `check_layering.py` OK. Branch coverage of the new lines: full.
- **Deviations:**
  - Five cases beyond the 17 ported, for the summary's other figures the same parsers read
    (reported and archive counts, the archive amount, an empty copy id, a null replay id), plus
    four edges (control, no-summary log, failed run, record too large).
  - Superseded in review round 1: the evidence lines (`run terminated`, the runner's
    `run finished`) and the terminal frame now say `failed` with `run_summary_invalid`, as the
    outcome and the record do.

## Review round 1 — 2026-11-20

A `/code-review` at xhigh; the owner approved every fix on 2026-11-20. Planned:

1. **Refuse before the terminal frame (owner decision).** The refusal was decided in
   `settlement_of`, after the run's `succeeded` frame was on the stream, so an R7 settle from that
   frame stayed `succeeded` and the late `failed` outcome could not correct it (first-wins). Now
   the producer binds the run's fold for the run's task, and `Url4Executor` raises
   `run_summary_invalid` (permanent) after its last log and before it builds its result, so url4's
   lifecycle publishes `Terminated(failed)` and every reader agrees, R7 included. Both producers
   (the queue child's `_run_and_log`, `InProcessJobRunner.schedule`) bind it.
2. A WARNING naming the topic and the malformed attribute when the fold refuses a run summary.
3. The PR body, this ledger and the docstrings about the log lines.
4. A refused record carries none of the summary's figures: the cache and capture fields are null.
5. Tests of the sticky rule: a malformed summary then a well-formed one, and the reverse.
6. `_decimal` accepts only a canonical fixed-point string (`[0-9]+(\.[0-9]+)?`), as
   `format(total, "f")` writes it; `1E+999999999` no longer expands to ~1 GB in `_amount`.
7. This ledger renamed to its slug.

Test plan: RED first, in a new `tests/unit/test_run_summary_refused_before_terminal.py`, on the
real `Url4Executor` running a node that logs the summaries: R7 settles a Candidate whose outcome
is late from its frame as `failed`/`run_summary_invalid`; both producers publish that frame, no
result frame, and agree in their log lines; the figures are null; the sticky rule; a refused
amount fails the run; a run with no record keeps succeeding. Appended to
`test_candidate_record_fail_closed.py`: each non-canonical amount is refused. No existing test
changes.

### Review round 1 — outcome

- **1, refuse before the terminal frame.** `candidate_record.py`: `binding_record(fold)` binds the
  run's fold in a ContextVar and `bound_refusal()` reads its `refusal` (the message naming the
  attribute). `runner/main.py::_run_and_log` and `InProcessJobRunner.schedule` bind it around the
  creation of the run's task. `runner/executor.py::_refuse_an_unvouched_summary`, called in
  `_run_steps` after `_closing_logs` and before `build_result`, raises
  `ResolutionError(code=run_summary_invalid, permanent=True)`. The run's terminal frame is now
  `failed` with `{code: run_summary_invalid, message: "SF Engine run summary <attribute> is
  invalid", permanent: true}`, with no result or subtree cost frame before it; the executor's
  summary is `failed` (so `run finished ... outcome=failed code=run_summary_invalid`), the outcome
  carries no cost, and an R7 settle from the frame is `failed` too. No url4 or Client change.
- **2.** `SettlementWatch.publish` logs `run summary refused topic=<topic>
  attribute='<attribute>' code=run_summary_invalid` (WARNING) once, when the fold first refuses.
- **3.** The PR body, the "Where it fails" paragraph and the deviation above, and the docstrings of
  `settlement_of`, `SettlementWatch`, `CandidateRecordFold.refusal` and `RUN_SUMMARY_INVALID`.
- **4.** A refused record sets `cache_hits`, `cache_unpriced_hits`, both saved amounts,
  `frozen_copy_id`, `capture_status`, `capture_replay` and `capture_partial_reasons` to null.
- **5.** Malformed then well-formed, and the reverse, are both refused (the fold's rule was already
  sticky; the tests pin it, on the real run).
- **6.** `_decimal` accepts only `[0-9]+(\.[0-9]+)?` (`_AMOUNT`, `fullmatch`) before `Decimal`.
- **7.** Renamed to `docs/work/2026-11-20-fail-closed-record.md`; the PR body points at it.
- **Tests.** New `tests/unit/test_run_summary_refused_before_terminal.py` (9 cases plus the
  Postgres parameter, skipped locally): a control; R7 settles a Candidate whose outcome is late
  `failed`/`run_summary_invalid` from its frame and the late outcome agrees; the local runner and
  the queue child each publish the refusal as the terminal frame with no result frame, and their
  `run terminated` / `run finished` lines and the WARNING agree; one malformed summary refuses the
  run whatever comes before or after it, and the record has no figures; `1E+999999999` fails the
  run; a run with no record is not refused. Appended to `test_candidate_record_fail_closed.py`:
  nine amounts the run never writes are refused (`1E+999999999`, `1E+3`, `1e3`, `1_000`, `' 1 '`,
  `+1`, `1.`, `.5`, a full-width `1`). Each run is the real `Url4Executor` running a node that logs
  the summaries, through the real producer.
- **Gates.** Not the full `run_gates.py` (CI runs it). RED: 14 of the 16 new cases run failed on
  acc77128d (the terminal frame or the R7 settle said `succeeded`, the figures were set, or the
  amount was read); the 2 controls passed; the 2 `1E+999999999` cases were deselected in RED
  because the old code expands that amount to about 1 GB. GREEN: the two files 44 passed, 1
  skipped; the 151 Engine unit files on the record, outcomes, runner, executor, in-process
  adapter, driver and registry 1941 passed, 317 skipped; the whole Engine unit suite 10085 passed,
  514 skipped (no Postgres, NATS or `inspect_ai` locally). ruff check, ruff format --check and
  pyright clean on the seven touched files; `check_layering.py` OK. Branch coverage of the new
  lines: full.
- **Deviation (for the owner).** `settlement_of` keeps its branch that settles a landed success
  its record refused as `failed`, and the record keeps the matching error, as a backstop for an
  executor that does not read `bound_refusal` (the producers' factory is a port). Removing it would
  change the assertions of this PR's own `test_candidate_record_fail_closed.py`, which replays a
  recorded success, `succeeded` terminal frame included: `_assert_refused` expects `details: None`,
  and the too-large case expects no record. The dispatch allowed no change to an existing test's
  assertions, so it stays; the docstrings say what it does. In production the `Url4Executor`
  fails the run first, so the branch is not reached.
- **Commit.** One signed commit, `fix(engine): address the review on the fail-closed record`.
