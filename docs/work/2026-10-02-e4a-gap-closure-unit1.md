---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
---

# e4a-gap-closure unit 1 -- Answer, abstain and signals in the combine core

## Intent

Fold the engine-core part of the E4a gap-closure into the combine core: members become `Answer`
values with a status and a reason, the evidence gets a computed `result` and a `dropped` count, a
vote with no usable member abstains instead of failing (`combine_no_votes` leaves the failure
vocabulary), and the core resolves the one signal a spec reads (a `field:` key from the member
text, or an accounting key through an injected reader). The world side keeps each model call's
ORIGINAL accounting (`SignalAccounting`) and the route adapter looks it up by exact call
fingerprint. No real operators ship here.

## Planned changes

- `combine/ports.py`: `Answer`, `answer_status`, `READING_TO_ANSWER`, `NoVotes` (not a
  `CombineError`), `FIELD_PATH` + `decode_json_reply` + `walk_field_path`, `is_signal_key`,
  `field_signal_value`, `SignalRead`, `AccountingReader`, `OperatorDescriptor.signal_read`.
- `combine/evidence.py`: `AnswerRecord`, `ResultRecord`, `SignalRecord`, `dropped`, new checks.
- `combine/spec.py`: `SignalWeights`, `sources` in the context, `canonical_params`.
- `combine/endpoint.py`: answers, computed result, abstain path, signal resolution.
- `operation_accounting.py`: `SignalAccounting`, `combine_signal_accounting`.
- `world/accounting.py`: `signal_accounting_from_aigw`. `world/connector.py`: collect per round trip.
- `operation_calls.py`: `OperationCall.signal_accounting`, `current_operation_calls`.
- `world/combine.py`: `_read_member_accounting` (exact fingerprint lookup).
- `benchmarks/contract.py`, SDK `_report_primitives.py`, `test_failure_classes.py`: drop
  `combine_no_votes` (owner-approved edit, 2026-09-30).

## Test plan

CHAR: AR#1, AB#1 (green on today's code) · B: AR#2-8, AR#15, AB#19 · C: AB#2, AB#2b, AB#8, AB#20,
AB#5, AB#7, AB#6, AB#16 · D: ports grammar, SG#7, weights grammar, SG#12, SG#14, SG#11, SG#17,
SG#16 · E: SG#1-3, SG#19, accounting fold, refusal record · F: SG#8, SG#10, SG#11 (adapter),
SG#18, current_operation_calls.

## Notes

Decisions F1-F12 (from the unit spec):

- F1 one direction: `status != "answered"` implies `value is None`; the core raises `RuntimeError`
  when the spec has an extract step and an answered member has `value=None`.
- F2 `result.value` is the output for kinds `answer` and `projection`, `None` for `selection`.
- F3 `score:judge` is not a signal key yet (unit 8E).
- F4 the `weights: {"signal": key}` grammar lives here; `Answer.weight` comes from the signal.
- F5 `run_combine(..., accounting=)` injects the reader; no `CombineInput.accounting`.
- F6 `OperatorDescriptor.signal_read` (reduce only); at most one signal read per spec.
- F7 `sources` is present exactly when an accounting key is read.
- F8 a miss uses the last succeeded attempt of a complete capture; signals ignore `cache.retried`.
- F9 no shared evidence fixture (unit 12 regenerates it).
- F10 AR#1 and AB#1 CHAR rows are the existing stack tests; changed in place in the delta commits.
- F11 log outcome `abstain_no_votes` / `abstain_cut_not_met`.
- F12 `NoVotes(message="", *, reason="no_votes")`.

CHAR results: recorded below as they run.
