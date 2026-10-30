---
ticket: OME-1744
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-27
finished: 2026-10-27
---

# engine-image-token-forwarding — forward image/file input tokens into the run cost

## Intent

Merged PR #1481 (OME-1546, gateway half) added
`usage.prompt_tokens_details.image_and_file_tokens` to non-streaming chat answers. It is an integer
when the provider gave a breakdown and `null` or absent (unknown) otherwise, never `0` for unknown.
This unit carries that value from the engine's connector into `ai.url4.cost.usage`
(`url4.streaming.protocol.TokenUsage`) so a run's cost frames say how much of the input was media.
Epic OME-1529.

## Owner decisions (Sergey, 2026-10-27, AskUserQuestion in the main session)

1. Approved test change, additive only:
   `packages/url4/tests/unit/test_usage_parity.py::test_report_usage_puts_each_argument_in_its_own_field`
   gains `image_and_file_tokens` in its `values` dict and its `report_usage` call. Manifest:
   `.claude/test-change-approvals/OME-1744.json`. No other prior test may change.
2. Semantics accepted: wire key `gen_ai.usage.image_and_file_tokens`; a cache hit reports the
   class unknown (`None`), never `0`; a span or run total is unknown if any contributing call is
   unknown (a deliberate departure from the OME-869 run-total rule, documented at the code).
   `world/accounting.py` / `operation_accounting.py` are out of scope (follow-up below).
3. Live check skipped: no credentials in this session (see Live check).

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

- Live check not run: no credentials available in this session. The gateway env file
  (`<scratchpad>/live/gw/env.sh`) is gone, so no call was made and no usage block was captured.
  Spend: none. The ticket's live acceptance stays OPEN.

## Outcome

- **Status: DONE** (code + tests + gates). Live acceptance open (see above).
- **Actual files:**
  - `packages/url4/src/url4/observe.py` — `Usage.image_and_file_tokens: int | None = None`
    (trailing, so positional constructions keep their meaning); `UsageSink` comment.
  - `packages/url4/src/url4/dag/_context.py` — `report_usage(..., image_and_file_tokens=None)`.
  - `packages/url4/src/url4/streaming/protocol/taxonomy.py` — `TokenUsage.image_and_file_tokens`,
    alias `gen_ai.usage.image_and_file_tokens`, `exclude_if=None` (unknown is omitted).
  - `apps/screamingface-engine/src/screamingface_engine/world/connector.py` —
    `_image_and_file_tokens(usage)` (bounded `0..2**53-1` int, else `None`), read from `usage` even
    when `_aigw` is present; a cache hit passes `None`.
  - `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` — `_SpanUsage` field;
    span level `accumulate` (poisons); run level latches unknown on the first unknown call (WHY note
    on the departure from OME-869 beside the code); `_token_usage` / `build_subtree` pass `None`
    through, never 0.
  - Tests (new): `packages/url4/tests/unit/test_image_and_file_tokens.py` (11),
    `apps/screamingface-engine/tests/unit/test_image_token_forwarding.py` (26 incl. parametrized).
  - Approved prior-test edit: `packages/url4/tests/unit/test_usage_parity.py::test_report_usage_puts_each_argument_in_its_own_field`
    (additive only), manifest `.claude/test-change-approvals/OME-1744.json`.
- **Acceptance tests:** present → forwarded (self + subtree frames, known 0 kept); absent / null /
  malformed / cache hit → unknown (key omitted); text-only run frames byte-identical to literals
  captured from the pre-change code.
- **Gates:** `run_gates.py url4` ALL GREEN; `run_gates.py screamingface-engine` ALL GREEN. One
  earlier engine run had `test_model_call_lifecycle_logging.py::test_a_slow_call_heartbeats_until_it_resolves`
  fail under `-n auto` load (timing; passes 3/3 alone; unrelated code path); the next full run was
  green. The `screamingface` stack gate was not run: it does not import `Usage`/`TokenUsage` and
  reads cost frames with `.get`, so an extra key is ignored there.
- **Re-verification (resumed run, 2026-10-27):** b0e2eb020 checked against this design and the
  owner decisions; nothing missing. Gates re-run with `--base <merge-base with origin/main>` so the
  append-only check exercises the manifest: `url4` ALL GREEN (approved OME-1744 transition matched),
  `screamingface-engine` ALL GREEN. `git diff origin/main...HEAD --stat -- '*tests*'`: two new test
  modules + the approved 2-line edit, nothing else.
- **Self-review (no blocking findings):** unknown never reaches the wire as 0 (connector, cache
  hit, span `accumulate`, run latch, `_token_usage` all keep `None`); text-only frames pinned
  byte-identical by literal tests. Nuance: a provider that DOES break the prompt down (Gemini via
  `bounded_image_and_file_tokens_from_gemini`) yields a known `0` on a text-only call, so those
  frames gain `"gen_ai.usage.image_and_file_tokens":0` — correct per decision 2 (a known 0 is a
  claim), byte-identity holds where the provider gives no breakdown.
- **Deviations:** none from the approved design. Manifest carries an extra `approved_by` key beside
  the existing format's fields (the matcher ignores extra keys).

## Follow-ups

- `world/accounting.py` / `operation_accounting.py` (benchmark operation accounting) do not carry
  the image class — out of scope by owner decision.
- `packages/screamingface/_engine/contract.py` does not surface the new key to the SDK consumer yet.
- Live acceptance (one tiny image call through a credentialed gateway) still to run.
- `SpanData` (span frames / OTel span attributes via `tracing/span_tree.py`) does not carry the
  class; only `cost.usage` frames do. Add it there if span-level consumers need it.

## Open questions

- The approval manifest pins `branch: engine-image-token-forwarding`. If the branch is renamed to
  `OME-1744-<desc>` at PR-open, the manifest's `branch` must be updated in the same push or the
  append-only gate fails closed.
