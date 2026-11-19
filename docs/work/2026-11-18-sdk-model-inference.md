---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface   # also screamingface-engine (one small change) and public-docs
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-18
finished:
---

# sdk-model-inference — `sf.ModelInference`: call an ensemble as a chat model from the SDK

## Intent

The SDK gets one public class, `sf.ModelInference(ensemble)`, with `.chat.complete(...)` in the
style of the OpenAI SDK and LiteLLM. It sends the compiled ensemble to the Engine route
`POST /v1/chat/completions` of PR #1937 and gives a reply with the OpenAI field names. Owner
request of 2026-11-18. Parent epic: `OME-1297`.

- Spec: `docs/spec/2026-11-18-sdk-model-inference/` (DRAFT, waits for the owner).
- Plan: `docs/plan/2026-11-18-sdk-model-inference.md` (DRAFT). Code: not started. The repo rule is spec, then plan, then code, and code
  starts only when the owner approves in plain words.
- Branch: `engine-openai-chat-endpoint-variant`, made from the head of PR #1937 (`e5f2d173e`) by
  owner order. Worktree: `.claude/worktrees/engine-openai-chat-endpoint-variant`.

## Planned changes

- `packages/screamingface`: the class, its `chat` namespace, the reply types, the stream frame
  reader, a small public seam for the auth headers, tests, README, changelog, the public surface
  snapshot.
- `apps/screamingface-engine`: the stream error event gets `should_retry` and `retry_after`; a
  plain reply with tool calls and no text gets `content: null`.
- `public-docs`: a new API page, an update of the OpenAI guide page, snippets.
- Repo: the path filter of the SDK test workflow.

## Test plan

`docs/spec/2026-11-18-sdk-model-inference/test-plan.md`: 45 TDD cases (31 SDK call, 7 endpoint,
7 Engine), risk first.

## Acceptance

The scenarios of the three PRDs pass; the gates of the SDK, Engine and repo stacks are green; the
docs examples run in tests.

## Log

- **2026-11-18 — exploration (read-only scouts).** The SDK has no single-prompt call for a
  recipe; only `sf.evaluate` (needs a benchmark) and `sf.classify`. The private compiler
  `compile_candidate` works on a bare recipe with no benchmark and no network; a reducer needs
  the operator catalogue. The Engine route ignores sampling parameters, tells URL4 text from a
  model id by a leading `(`, and its stream error event has no retry hint.
- **2026-11-18 — owner decisions (spec ledger Q1–Q7).** The name `sf.ModelInference`; the reply
  with OpenAI field names; sync, async and streaming; a sampling parameter is accepted with a
  warning and ignored; no retry by default; each call is streamed on the wire; one method name
  `complete` for sync and async.
- **2026-11-18 — spec written** (overview, contracts, three PRDs, test plan).
- **2026-11-18 — one independent review of the spec (Opus, read-only):** approve with fixes;
  1 blocker, 7 major, 13 minor, all applied (overview §8). Main changes: no analytics event (the
  analytics service accepts only four event names); the compiler error types; one shape for a
  tool-call reply with no text (an Engine change); the resend rule after a sign-in challenge;
  the default client is taken at each call; `endpoint()` signs in first; an evaluation URL4 is
  accepted; a typo keyword gives `TypeError`. The review confirmed by execution that the text
  that the SDK compiles passes the recipe check of the Engine.
- **2026-11-18 — owner: "spec approved".** I read this as approval of the whole spec, with the
  reading of Q7 (the mode follows the client) and the proposals P1–P17, P16 (the `openai` dev
  dependency of the SDK) included.
- **2026-11-18 — plan written:** `docs/plan/2026-11-18-sdk-model-inference.md` (units U1–U8,
  decisions D1–D10, stop points S0–S3).
- **2026-11-18 — owner: "plan approved".** S0 done. S1 is approved with the plan: the Engine
  stack runs with `--skip-append-only` on this branch; the SDK stack runs with no skip.
- **2026-11-18 — U1 (Engine) done.** The stream error event has `should_retry` (and
  `retry_after` when set), from one builder `_error_line` in `rest/chat_stream.py`; a reply
  with tool calls and no text has `content: null`. New tests in
  `tests/unit/test_chat_stream_retry_flag.py` (SE-1, SE-3, SE-4, SE-5, SE-7, plus the
  no-usable-result rows); SE-2 and SE-6 sit in the existing route and docs-page tests. Three
  branch tests changed as the spec approved (the event bytes now have the flag). One design
  review (Opus): accept with fixes, no structural finding; fixes M1–M3, L1, L2, L4–L9 applied
  (L3 and L10 not done: style only). The docs page also corrects the abstain line: `content`
  is empty, not null. Gates: Engine `--skip-append-only` green; public-docs prettier, lint and
  build green.
- **2026-11-18 — U2 (SDK foundation) done.** `sf.ModelInference` shape in
  `screamingface/inference.py` (constructor overloads C1.1, the six `complete` rows C1.2,
  `endpoint()` C1.5; bodies raise NotImplementedError until U4–U6), placeholder reply types in
  `screamingface/chat_completion.py`, and the replay-safe streamed POST seam
  `Client._engine_post_stream` / `AsyncClient._engine_post_stream` (D4, P15). Pyright basic
  accepts the one-method overload, so the stop rule did not trigger. Tests: MI-1
  (`test_model_inference_typing.py`), MI-2 and MI-3 (`test_engine_post_stream.py`, the 302,
  401 and 403 challenge forms, sync and async). Built by tiered-build run `wf_f8a1db43-cf2`
  (2 Haiku tasks); the run stopped at its gate step (see deviation below), so I ran the design
  review by hand: accept with fixes, no structural finding; fixes 1–3 and 5–9 applied.
  Deviations: (a) the SDK append-only check must use `--base $(git merge-base origin/main HEAD)`:
  against `origin/main` it reports files that `main` changed after the branch point
  (`tests/e2e/workbench/*`), not files of this branch. (b) Review finding 4 is not done: the
  pyright helper of the new typing test copies `_pyright` of
  `tests/test_evaluate_overload_types.py`; a shared helper needs an edit of that main test
  file, which the append-only rule blocks. Follow-up. Gates: SDK green (vs merge base).
- **2026-11-18 — U3 (reply types and frame reader) done.** The C1.3 types in
  `screamingface/chat_completion.py` (frozen, `to_dict()`, short forms) and the pure reader
  `screamingface/_inference/frames.py` (SSE lines to events, events to chunks, chunks to one
  `ChatCompletion` by C2.3). Tests MI-4, MI-5, MI-26 (`test_chat_completion_types.py`,
  `test_model_inference_frames.py`, `test_model_inference_frames_invalid.py`, helper
  `tests/_chat_frames.py`). Tiered-build run `wf_4ed732d0-c5e`; review accept with fixes, no
  structural finding; F1–F3, F5–F8 fixed in the run, F9 skipped (C1.3 has no place for "key
  missing" vs null). Readings of C2.3 (strict, as the Engine sends a buffered stream): a content,
  refusal or tool call split over two deltas, or a repeated tool-call index, is `wrong_shape`
  (U4 maps it to invalid_response); a body that is not UTF-8 is `not_text`; a negative cost is
  `wrong_shape`. Known drift point: `tests/_chat_frames.py` copies the Engine wire by hand
  (no cross-package import); MI-28 (U8) catches drift. Open for U4 (F4): read lines with
  httpx `iter_lines()` and keep `lines_from_bytes` only if production uses it. Gates: SDK green.
- **2026-11-18 — U4 (sync call) done.** `screamingface/_inference/request.py` (model rule P1/P14,
  compile P2/P17 with the operator catalogue at each call for a reducer, parameter policy P4 with
  `IgnoredParameterWarning`, body and headers C2.1), `screamingface/_inference/transport.py`
  (send through the seam via a Protocol, `iter_lines()`, read limit and total timeout P11, each
  limit bounded by the time left, `max_retries` C2.5, close on each exit),
  `screamingface/_inference/error_map.py` (C2.4, one Retry-After parser reused from
  `_core/retry.py`), and the sync half of `Chat.complete` (default client at each call).
  Tests MI-6…MI-19, MI-23, MI-29, MI-30, sync MI-31 (`test_model_inference_*.py`, helper
  `tests/_chat_engine.py`). Tiered-build run `wf_d81ddcce-ef2`: it stopped once at a wave
  check whose grep for `not_text` also hit four test files of `main`; I checked the real
  intent by hand (no hits) and resumed with that one check filtered. Review accept with fixes,
  no structural finding; F1–F9, F11, F12 fixed. U3 note F4 done: `lines_from_bytes` and the
  `not_text` reason removed (production reads with httpx). Deviations: (a) plan D3 puts the
  error map in `transport.py`; it is a fourth private module `error_map.py` (450-line limit,
  U5 async twin). (b) F13 open for U5: tests inject the clock and sleep as module globals; U5
  decides once for sync and async. (c) For U5: with `stream=True` the caller's
  `stream_options` decides if the usage chunk reaches the caller (C2.1); the wire always asks
  for usage. Gates: SDK green.
  **Correction (U5):** note (c) above was wrong. Contracts C2.1 (P6) say that with
  `stream=True` the wire carries the caller's `stream_options`; only `stream=False` always
  asks for usage.
- **2026-11-18 — U5 (streams, async, concurrency) done.** `ChatStream` / `AsyncChatStream`
  (C1.4), the async twin of the transport, `complete` returns a coroutine with an
  `AsyncClient` (argument errors before the coroutine), pure chunk steps in
  `screamingface/_inference/chunks.py`, a push-form `EventReader` in `frames.py`. Tests MI-20,
  MI-21, MI-22, MI-24, the stream and async half of MI-31. Tiered-build run `wf_d38f572c-6c1`
  (6 Haiku tasks); the review gave one STRUCTURAL finding (F3): from my wrong run note, the SDK
  always asked for usage and copied the Engine frame rule to drop the usage chunk for the
  caller. Per the routing rule, I fixed it in the main loop: the stream body carries the
  caller's `stream_options` (C2.1), the stream gives each wire chunk as it is, and
  `CallerChunks` / `caller_view` / `caller_wants_usage` are deleted. Same pass: F1 (a stream
  stops the caller deadline at the first chunk, because the Engine stream is buffered; a reply
  call keeps it to the end; tests sync and async), F4, F6 (one shared per-line step), F7 (WHY on
  the retry rule of `send_chat`), F10 (`include_usage` must be a bool). Not done: F2 (the pull
  helpers of `frames.py` are thin compositions of the same steps; low drift risk), F5 (a stream
  passes the wire through, as an OpenAI client gets it), F9 (stream constructor parameters:
  check in U7 with the surface snapshot), F11, F12 (style). F13 of U4 decided: module globals
  for the clock and both sleeps. `frames.py` and `transport.py` are at 450 lines (no headroom).
  Gates: SDK green.
- **2026-11-19 — U6 (`endpoint()`) done.** `InferenceEndpoint` repr hides header values,
  hashable (headers excluded from the hash); `endpoint()` sync and async, login first on an
  https Engine, the Access header from the client auth, no headers on an http Engine; the
  model text from the same compile step as `complete()`. D9: `openai==2.54.0` in the SDK dev
  group, `uv.lock` updated. Tests EB-1…EB-7 (EB-7 runs the C5 example with the real openai
  client on the mock wire). Tiered-build run `wf_ee4e9f4e-29a`; review accept with fixes, no
  structural finding; F1, F3, F6, F8 fixed. Open: F2/F4 (an https Engine with no Access in
  front: `login()` raises; this follows C1.5 as written, owner may decide later), F5 (EB-7 does
  not run the public-docs snippet: U8), F7 (`tests/_endpoint_access.py` is the fifth copy of the
  Access fake; later units import it). The run used the network beyond `uv lock`: it
  downloaded the openai wheel and the locked `notebook` extra wheels into the package venv.
  Gate pitfall: the SDK venv needs `uv sync --locked --extra notebook` (as CI) or pyright fails
  on the ipywidgets imports. Gates: SDK green.

## Outcome (fill at the end — required before COMMIT)

Not started.
