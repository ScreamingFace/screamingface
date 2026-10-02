---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
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


## Outcome

- **CHAR (green on today's code before any change):** AR#1 `test_combine_endpoint.py::
  test_vote_evidence_has_every_pinned_field` and AB#1 `test_endpoint_raises_combine_no_votes_when_no_
  member_votes` plus `test_world_combine.py::...[no-votes]` (57 passed). The delta commits changed
  them in place (F10). Also green at once, as guards: AB#5 (spec errors still fail the case), AB#6
  (a member transport error still fails the case), SG#1 (the cache hit keeps its zero retained cost).
- **Commits:** B Answer + result, C abstain, D signals in the core, E signal accounting, F route
  lookup. Each RED was seen on a stub first; mutation checks were run for the spec/signal/accounting
  rules (every live mutation was killed).
- **Not done:** row 34 (tool-loop rounds through a web-tool fake) is skipped: no cheap web-tool fake
  exists. The fold itself is covered by `test_combine_signal_accounting_is_contagious_and_order_free`.
- **Small choices the spec left open:** `fake_best@1` raises `NoVotes` when no member has a score;
  `_observed_round_trip` gets `# noqa: PLR0915` (the two signal-accounting lines pass the 26
  statement cap); `_reduce_select` and `_member_numbers` are small helpers added to stay under the
  ruff branch/return caps; a `_checked` stage result also rejects a non-str value.
- **Append-only:** the only base test file edited is `test_failure_classes.py` (the approved pin;
  the net diff from base is the three combine codes).
- **Gates (last run, base 4eca379d1):** focused pytest (spec section 5): 280 passed. Engine gate
  (`--skip-append-only`; ruff, format, pyright, check_layering, pytest with coverage): ALL GATES
  GREEN. SDK gate (`screamingface --skip-append-only`; includes the failure-code twin
  conformance and the notebook and distribution checks): ALL GATES GREEN. Repo gate: ALL GATES
  GREEN. The engine and SDK conformance tests both pass with the three-code set. No `url4` import
  under `combine/` and no plugin import in the core (check_layering).
