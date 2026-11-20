# PRD: shared gateway round trip (move with no behaviour change)

**Source:** ans:Q11 · **Priority:** P1 (first unit; the final-step endpoint needs it)
**Lifecycle:** existing (characterize + delta) · **Owner:** unassigned

## 1. Summary and the flows it serves

The existing model endpoint and the new final-step endpoint must talk to the AI gateway in the
same way. The owner decided to move the shared parts into one module `[stated ans:Q11]` ("move").
This PRD serves [tool-calls](tool-calls.md). No user flow drives it.

Design review 1 found that the three parts named in the interview (identity headers, HTTP send,
cost report) are not enough. The moved set is larger: the full **round trip**, which is all the
code below the tool loop `[proposed — review 1]`.

## 2. Background and constraints

### 2.1 Current behavior

`E/world/connector.py` has 2,096 lines. The parts that one logical gateway call needs are spread
over it:

| Behaviour | Where today |
|---|---|
| identity and trace headers | `_headers` `[existing E/world/connector.py:1938]` |
| time-out headers for the gateway | built in the loop `[existing E/world/connector.py:1609]` |
| one observed call: heartbeat, model-call log, reply facts, accounting, refusal | `_logged_round_trip`, `_observed_round_trip` `[existing E/world/connector.py:209]` `[existing E/world/connector.py:239]` |
| capture, replay or normal call | `_recorded_completion` `[existing E/world/connector.py:1428]` |
| cache policy field, cache read-back | `_fetch_completion` `[existing E/world/connector.py:1237]` |
| Candidate retry on 429 and 5xx | `_post_answered` `[existing E/world/connector.py:1293]` |
| transport retry and deadline | `_post_completion` `[existing E/world/connector.py:993]` `[existing E/world/connector.py:165]` |
| status and body mapping to Engine errors | `_raise_for_status`, `_json_or_raise` `[existing E/world/connector.py:2040]` `[existing E/world/connector.py:1964]` |
| cost, usage and cache-status reports | `_report_usage`, `_report_response` `[existing E/world/connector.py:907]` `[existing E/world/connector.py:782]` |

- The capture digest is the sha256 of the full request body
  `[existing E/capture_outcomes.py:106]`. A change of one byte changes the digest.
- The loop comment states that the body of attempt 1 is "byte-identical to before"
  `[existing E/world/connector.py:1631]`.
- Review 3 counted 26 existing test files that refer to names of `connector` which this move
  relocates (for example the transport back-off, the heartbeat interval, the usage sink and the
  reply-facts helpers). After the move, those patches do not reach the moved code
  `[proposed — review 3]`. The plan lists each file and each target.
- One source file imports six of the moved names from `connector`:
  `E/world/classification.py` `[existing E/world/classification.py:33]`. Its imports change.

### 2.2 Delta

- Move the round trip to `E/world/gateway_transport.py`: every function in the table above and
  their private helpers, with the capture and replay branch `[proposed — review 1]`. The public
  entry is one function for one logical call, `round_trip` (the `_logged_round_trip` of
  before), and `timeout_headers`. The other names keep their leading underscore, so the move is
  a pure move: they are private to the `world` package, and `connector.py` and
  `classification.py` read them as attributes of the module, as `classification.py` read them
  from `connector` before `[proposed — build review of U1]`.
- Extract the time-out headers from the loop into one function. The header bytes do not change.
- `connector.py` keeps the endpoint, the message builder, the tool loop and the world builder. It
  imports the round trip `[stated ans:Q11]`.
- `connector.py` imports the **module**, not the names (`gateway_transport.x`, never
  `from … import x`). Then a test that still patches a moved name on `connector` fails with an
  attribute error. With a name import, the patch would succeed and test nothing
  `[proposed — review 2]`.
- The time-out helper takes plain values, not the config object, so the new module does not
  import `connector` `[proposed — review 2]`.
- No function body changes in this unit, apart from names and imports `[proposed]`.
- The existing tests that patch the moved globals change their patch target, and nothing else.
  The repo requires an approved test-change record for this
  `[existing .claude/scripts/run_gates.py:382]`. The plan lists the files, and the owner approves
  the record before the unit starts `[proposed — review 1]`.

## 3. Scenarios and acceptance criteria

**GT-S1 Same bytes after the move.** `[stated ans:Q11]`
- Given a fixed request scope and a fixed model call
- When the existing endpoint runs before and after the move
- Then the outbound headers and the request body are byte-identical.

**GT-S2 Same errors and retries after the move.** `[implied]`
- Given each gateway status class (2xx, 400, 401, 429, 5xx, malformed body)
- Then the Engine error code, the transport retry count and the Candidate retry count are the
  same before and after the move.

**GT-S3 Same cost records after the move.** `[implied]`
- Given a priced call, an unpriced call and a cache hit
- Then the cost, usage and cache-status records are the same before and after the move.

**GT-S4 One call works without the endpoint.** `[proposed — gap §per-connection/dependency]` M×M
- Given a caller that binds a request scope
- When it calls the public round-trip function with headers and a body
- Then it gets the parsed choice, with the cache policy, the retries, the deadline and the
  reports applied, without `_ModelEndpoint` and without the tool loop.

**GT-S5 Layering.** `[proposed — gap §per-connection/dependency]` M×L
- `gateway_transport` is part of `world`. It imports neither half
  `[existing .claude/scripts/check_layering.py:26]`.

**GT-S6 Capture and replay still work.** `[implied]` H×M
- Given a capture run and a replay run of an existing Benchmark
- Then the frozen-copy digests and the replay results are the same before and after the move.

## 4. Non-functional requirements

- **Risk control.** This unit is the first commit of the pull request, with no feature code in it
  `[stated ans:Q22]`. A revert of the unit is one commit. The move is about half of `connector.py`, so the review of this unit is a line-by-line
  move check.
- **Module size.** Both modules stay under the repo size ratchet `[proposed]`.

## 5. Out of scope

- A change to the tool loop or the message builder `[stated ans:Q6]`.
- A change to the capture logic. It moves with the round trip and stays the same.
- A public rename of any error code.

## 6. Open questions

None.

## 7. TDD plan

Characterization tests come first. They pass on the code of today by design.

| # | Test | Level | Source | Risk | Note |
|---|---|---|---|---|---|
| GT-1 | CHAR `headers_for_fixed_scope_match_golden` | unit | [existing E/world/connector.py:1938] | H×M | identity, trace and time-out headers |
| GT-2 | CHAR `model_call_body_digest_matches_golden` | unit | [existing E/capture_outcomes.py:106] | H×H | `request_digest` of a fixed call |
| GT-3 | CHAR `status_classes_map_to_same_error_codes_and_retries` | unit | [existing E/world/connector.py:2040] | H×M | table of status → code, both retry counts |
| GT-4 | CHAR `usage_report_for_priced_unpriced_cached_matches_golden` | unit | [existing E/world/connector.py:907] | H×M | three fixed gateway replies |
| GT-5 | `round_trip_works_without_model_endpoint` | unit | [proposed] | M×M | RED until the public module exists |
| GT-6 | `connector_has_no_private_copy_of_moved_functions` | unit | [stated ans:Q11] | M×L | import check; one definition only |
| GT-7 | CHAR `capture_and_replay_digests_match_golden` | integration | [implied] | H×M | existing capture fixtures |
| GT-8 | `moved_names_are_not_attributes_of_connector` | unit | [proposed] | H×M | a stale patch target must raise, not pass; the list has the functions, the constants, the sinks and the helpers |
