---
ticket: OME-1988
stack: screamingface-engine
status: done
started: 2026-11-20
finished: 2026-11-20
---

# OME-1988-fail-closed-record — Fail a Candidate whose record has malformed cost, cache or capture figures

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

Where it fails: in the outcome, `run_evidence.settlement_of`, which both producers (the queue
child's `SETTLED` report via `runner/main.py::_run_and_log`, and `InProcessJobRunner._on_done`) use;
the registry's `settle` stores it first-wins. Spec check: §4.3 requires the record to follow the
Client's fold rules (`contract.py:408-467`, which refused these summaries), so failing is what the
spec asks. P1 R3's "the registry always agrees with the terminal frame the Client reads" describes
the producer gate (only the writer whose terminal frame landed publishes), which still holds; in P2
the Client reads the registry and the record, and terminal frames only for display (D9). If the
outcome is lost and R7 settles the Candidate from the frame, it settles `succeeded` with no record,
the late `failed` outcome changes nothing (§4.4, first-wins), and the Client reads it as
`run_result_lost`: still fail-closed.

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
  - The evidence lines (`log_terminated`, the runner's `run finished`) still state the run's
    terminal frame (`succeeded`); only the Candidate's outcome and record say `failed`. They
    describe how the run ended, and the record's message names the malformed attribute.
