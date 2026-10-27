---
ticket: OME-1744
stack: screamingface-engine
status: blocked   # planned | in_progress | done | blocked
started: 2026-10-27
finished:
---

# engine-image-token-forwarding — forward image/file input tokens into the run cost

## Intent

Merged PR #1481 (OME-1546, gateway half) added
`usage.prompt_tokens_details.image_and_file_tokens` to non-streaming chat answers. It is an integer
when the provider gave a breakdown and `null` or absent (unknown) otherwise, never `0` for unknown.
This unit carries that value from the engine's connector into `ai.url4.cost.usage`
(`url4.streaming.protocol.TokenUsage`) so a run's cost frames say how much of the input was media.
Epic OME-1529.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`: `_report_usage` reads
  `usage.prompt_tokens_details.image_and_file_tokens` (bounded non-negative int, else `None`) and
  passes it to the sink. It reads `usage` even when `_aigw` is present, because the spec puts the
  field there and not under `_aigw`.
- `packages/url4/src/url4/observe.py`: `Usage` gains a trailing `image_and_file_tokens: int | None = None`.
- `packages/url4/src/url4/dag/_context.py`: `ExecutionContext.report_usage` gains the matching
  keyword argument.
- `packages/url4/src/url4/streaming/protocol/taxonomy.py`: `TokenUsage` gains
  `image_and_file_tokens: int | None`, alias `gen_ai.usage.image_and_file_tokens`, written with
  `exclude_if=None` (the precedent is `ResultData.artifact`), so text-only frames stay
  byte-identical.
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py`: `_SpanUsage` carries it;
  span level uses `accumulate` (an unknown part makes the whole unknown); the run level ALSO
  poisons, unlike the other classes, because the wire can now say "unknown"; `_token_usage` and
  `build_subtree` pass it through without flattening to 0.

## Test plan

- Field present → forwarded onto the self and subtree frames.
- Absent / `null` / malformed → unknown (key omitted from the frame), never `0`.
- A run where one call is known and another unknown → unknown at both span and run level.
- Text-only run: encoded `cost.usage` frames are byte-identical to today's.

## Acceptance

- The three acceptance tests from OME-1744 pass, and the `screamingface-engine` and `url4` gates are green.

## Live check (best effort)

- Gateway `http://127.0.0.1:9115` is up: `/health` returns 404 and `/v1/models` returns 401 without
  a key.
- The env file the task named
  (`<scratchpad>/live/gw/env.sh`) does not exist; `live/gw/` is empty. No credentials, so no call
  was made, and no usage block was captured. Spend: none.

## Outcome

- **Status: BLOCKED** on the append-only test rule before RED. No production or test code was written.
- **Blocking prior test:** `packages/url4/tests/unit/test_usage_parity.py::test_report_usage_puts_each_argument_in_its_own_field`.
  It hard-codes the full `url4.observe.Usage` field list
  (`assert list(values) == _event_fields(Usage)`), so ANY new field on `Usage` fails it, whatever
  else is changed alongside. Measured: with only the `Usage` field added, three parity tests fail.
  Two of them (`..._takes_the_usage_fields_in_order`,
  `..._token_classes_are_the_wire_token_classes`) go green again once `report_usage` and
  `TokenUsage` change too; this one cannot.
- **Why the field must go on `Usage`:** it is the only seam from a world adapter (the connector,
  through `current_usage_sink`) to the executor that builds `cost.usage`. Leaving it off `Usage`
  and adding it to `TokenUsage` alone fails
  `test_usage_token_classes_are_the_wire_token_classes`. Avoiding that by giving the wire key a
  name that does not end in `_tokens`, or by adding an engine-private side channel, would sidestep
  the contract the parity test protects. Neither was done.
- **Unblock:** an approval manifest in `.claude/test-change-approvals/` that names this test and
  allows one change: add `"image_and_file_tokens": <value>` to its `values` dict and the call. The
  change is additive and the test's intent is unchanged.
- **Actual files:** this ledger only.
- **Gates:** not run on code (no code changed).
- **Deviations:** none. Stopped per the hard rule.

## Open questions (for when it unblocks)

- Wire key name: `gen_ai.usage.image_and_file_tokens` (matches the existing `gen_ai.usage.*`
  aliases and the gateway's own key). OTel GenAI semconv has no such attribute.
- Cache hit: report unknown (`None`), not `0`, for the image class. A hit consumed nothing, but
  the stored body's breakdown is the original call's, so `None` is the conservative choice.
- Run-level aggregation poisons (one unknown call makes the run unknown). This departs from the
  OME-869 no-poison rule for the other classes, as that rule's own AIDEV-NOTE anticipates for an
  optional wire count.
- `world/accounting.py` and `operation_accounting.py` (the benchmark operation accounting) are out
  of scope here.
