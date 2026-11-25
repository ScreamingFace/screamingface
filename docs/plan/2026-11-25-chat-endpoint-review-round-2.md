# Plan: review round 2 of PR #1937 (chat endpoint and SDK chat calls)

- **Date:** 2026-11-25
- **Spec (rubric):** `docs/spec/2026-11-17-engine-openai-chat-endpoint/prd/review-round-2.md`
  (scenarios RR-S1 to RR-S20, tests RR-1 to RR-23 and MI-51 to MI-56).
- **Tickets:** OME-1963 (Engine), OME-2005 (SDK), OME-1964 (public docs). No new ticket.
- **Branch:** `OME-1963-engine-openai-chat-endpoint`, rebased onto `origin/main` `d69e15a58` on
  2026-11-25 (one conflict, in the `__all__` list of `benchmarks/operation_outputs.py`).
- **Owner approval:** "carefully read through them, validate them, then properly plan and
  orchestrate" (2026-11-25), and the answers R1 to R4 of the spec, section 0.

## 1. Decisions of the plan

| Id | Decision |
|---|---|
| D1 | One round, one PR. Each unit below is one commit. |
| D2 | The build runs as a tiered build: Opus plans the waves, Haiku workers implement, the gates run, an Opus design review uses the spec as its rubric. |
| D3 | Each fix starts with its failing test (RED), then the smallest code (GREEN). |
| D4 | New tests go into new files or new functions. A test that exists changes only when the new rule makes its assertion false (answer R3); the ledger lists each such change. |
| D5 | The gates run with `--skip-append-only` during the build. The approval record gets its new hashes one time, at the end; then the gates run with no skip, before the push. |
| D6 | The tool-code defects are not fixed here (answer R2). The spec, section 9, and the ledger list them. |
| D7 | No change to shared accounting (`world/accounting.py`), to the queue runner, or to a benchmark path. |

## 2. Units

Engine source root: `apps/screamingface-engine/src/screamingface_engine/`. Engine tests:
`apps/screamingface-engine/tests/unit/`. SDK: `packages/screamingface/`.

### U-A Run start and stop (RR-S1 to RR-S5; tests RR-1 to RR-5, RR-21)
- `rest/chat_completions.py`: wrap the schedule call in `deps.job_runner.start_attempt(topic)`;
  give `ChatCleanup` `deps.job_runner.stop_bound`. Exemplar: `rest/routes.py::_claim_topic`.
- `rest/chat_cleanup.py`: `write` starts the store write as its own task and waits for it behind
  `asyncio.shield`; `_clean` waits for that task (result or error) before the delete.
- `rest/chat_wait.py`: `RunWait.__init__` and `wait_for_run` start the scan through a small
  `async def` that makes the `scan_run` coroutine inside the task.
- New tests: `tests/unit/test_chat_review2_lifecycle.py`.
- Do not change `adapters/queue_runner.py`, `ports.py` or `rest/routes.py`.

### U-B Result delivery (RR-S6 to RR-S9; tests RR-6 to RR-10)
- `rest/chat_answer.py`: `CHAT_RESULT_MAX_BYTES`; the size check before a local read; the
  bounded read of a remote stream; `store.content` inside the `try`; catch
  `(OSError, S3StorageError)`; the row of a transient `chat_input_unavailable`.
- `rest/chat_errors.py`: the code `result_too_large` with a fixed message.
- `rest/chat_stream.py`: the result is prepared in a task while keep-alive lines are sent.
- New tests: `tests/unit/test_chat_review2_results.py`.

### U-C Request boundary (RR-S10 to RR-S12; tests RR-11 to RR-16)
- `rest/chat_body.py`: the total read deadline; the list of ignored names on `ChatBody`.
- `chat/wire.py`: `n` with `ge=1`.
- The names travel from the body to the answer and to the stream plan; `ScreamingFaceInfo` gets
  `ignored_parameters`, absent when empty. They never go into `RequestFacts` or a log line.
- New tests: `tests/unit/test_chat_review2_boundary.py`.
- Run after U-B: both units change `rest/chat_answer.py` and `rest/chat_stream.py`.

### U-D Local blob files (RR-S13; tests RR-17, RR-18)
- `artifacts/blob_objects.py`: private directories and files; the owner and mode check of the
  root. New tests: `tests/unit/test_blob_files_private.py`.

### U-E Final step on a cache hit (RR-S14; tests RR-19, MI-56)
- `chat/result.py`: `FinalStep.cached`; `world/chat_turn.py::_step` sets it from
  `accounting.cache.hits`; the answer and the stream give the key only when it is true.
- SDK `chat_completion.py`: `FinalStep.cached`. The SDK surface snapshot changes.
- Spec text: `erd.md` line 187 and the `FinalStep` docstring.
- Run after U-C (the same answer code).

### U-F OpenAPI document and CI paths (RR-S15, RR-S16; tests RR-20, RR-22)
- `rest/chat_openapi.py` (and `schemas/openapi.py` only where the security of this operation is
  set). Run after U-B, U-C and U-E, because it declares their codes and fields.
- `.github/workflows/screamingface-engine-tests.yml`: two paths in both lists.

### U-G SDK calls (RR-S17, RR-S18; tests MI-51 to MI-55)
- `chat_completion.py` (`AsyncChatStream`, `ChatStream`), `_inference/calls.py` (the total
  limit). New tests: `tests/test_model_inference_review2.py`.

### U-H Docs (RR-S19, RR-S20; test RR-23)
- Snippets `public-docs/src/snippets/chat/endpoint_openai.py`,
  `public-docs/src/snippets/openai-chat/*.py`; `packages/screamingface/README.md`;
  `ChatPage.vue`, `OpenAiApiPage.vue`; the Engine `README.md`; `prd/chat-completion.md` (the
  rows of CC-S16, the terminal table, CC-S35); the SDK `CHANGELOG.md`.
- A worker changes only the lines of its task. It runs no formatter on a whole file.

## 3. Gates

From the worktree root:
1. `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main --skip-append-only`
2. `uv run .claude/scripts/run_gates.py screamingface --base origin/main --skip-append-only`
3. `uv run .claude/scripts/run_gates.py repo --base origin/main --skip-append-only`
4. `cd public-docs && npm run build`

Before the push: gates 1 to 3 again with no `--skip-append-only`, after the approval record has
its new hashes; `uv sync --dev --locked` in `apps/screamingface-engine` first.

## 4. Stop points

- S1: the approval record. The permission check of the session refused my write two times, also
  after the owner answer R3. The planner makes the new record as a file and the owner applies it
  with one command, or the owner lets the write pass.
- S2: push, PR body and the reply to the reviewer: approved (answer R4). No merge.

## 5. Risks

- U-A changes when a run is stopped. The tests must show that a normal end calls no stop.
- U-C adds a key to the reply. It is absent when empty, so replies that tests pin do not change.
- U-D changes file modes for each local blob. A root that another user owns stops local mode.
- U-B: the 8 MiB limit is a new refusal. No valid answer comes near it today.

## 6. Not in this plan

The tool-code defects (spec section 9); stored token counts on a cache hit; a new ticket.
