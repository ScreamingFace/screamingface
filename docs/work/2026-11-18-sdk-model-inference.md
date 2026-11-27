---
ticket: OME-2005   # filed 2026-11-23 under OME-1297; lands in PR #1937 with OME-1963
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
- **2026-11-19 — S2 paid check (owner: "Yes, local stack").** Local stack `~/sf-local/inference/`
  (Engine + aigateway from this worktree, OpenRouter). Playground notebook
  `model-inference-playground.ipynb` (generator `make_nb.py`), executed once:
  `model-inference-playground.executed.ipynb`. Every example worked: model id, fusion, regex gate,
  messages, URL4 text, sync and async stream, `include_usage`, `asyncio.gather` of 3, tool
  call round trip, ignored-parameter warnings, `TypeError` on a typo, `model_not_found` as
  `PlanningError`, `endpoint()` with the real openai client (plain and stream). Cost 0.126 USD
  (plan said about 0.05). Findings, not fixed:
  (1) a missing provider key fails the run with `profile_not_found`, and the chat route answers
  `internal_error` "the request failed" with no hint about the key (Engine, PR #1937 area);
  (2) fusion calls with nearly the same tokens cost 0.0003 or 0.0143 USD: not explained yet;
  (3) the local gateway had `AIGW_REQUEST_CACHE_ENABLED` off (its default), so no request came
  from the cache; the start script now sets it;
  (4) about 300 prompt tokens for a five-word prompt: the default Candidate prompt of the recipe;
  (5) this branch predates E4c, so the notebook uses `sf.RegexClassifier`, not `sf.Keywords`.
- **2026-11-23 — Team review: rename and OpenAI call path (spec §5.4, D11, D12).** Two items of
  feedback, through the owner: F1 "ModelInference" is not clear (proposed `Endpoint`, else
  `InferenceSession` or `InferenceClient`); F2 (Andrew) mirror the OpenAI or HF API as closely
  as possible, a "Client object" with `chat.completions`. The owner told me to examine them and
  apply what is correct. Done: the class is `sf.InferenceClient` (not `Client`: `sf.Client`
  exists; not `Endpoint`: it clashes with `endpoint()`/`InferenceEndpoint` and suggests a
  deployed server; not `InferenceSession`: suggests a conversation state); the path is
  `chat.completions.create` (class `Completions`, no alias, not released yet); `model` is
  optional on the constructor and `create(model=...)` / `endpoint(model=...)` give a model for
  one call (no model anywhere: `TypeError` before a request). Kept: the reply types (already
  OpenAI-shaped), `prompt`/`use_cache`/`max_retries` as additions, the async mode that
  follows the client (D7). Not done (possible later): an `AsyncInferenceClient` class,
  `timeout`/`max_retries` on the constructor, `extra_headers`/`extra_query`/`extra_body`
  (they need a change to the parameter list that `test_model_inference_params.py` fixes).
  Prior tests of this branch (not on `main`) changed by a rename only (`ModelInference` →
  `InferenceClient`, `chat.complete` → `chat.completions.create`, the `TypeError` text
  `create() got ...`); no assertion changed. New tests MI-32…MI-35
  (`tests/test_model_inference_openai_shape.py`). Test file names keep `model_inference` (the
  feature slug). Spec, contracts, PRDs, test plan and plan updated; the Q1/Q2 quotes stay
  verbatim. Local playground notebook renamed in place (owner edits kept) plus a new cell 1.6
  (the OpenAI form). Gates: SDK green (`--base` merge base).
- **2026-11-23 — U7 and U8 done (owner: "orchestrate parallel agents").** Tiered-build run
  `wf_ccf05047-4dc`: Opus planned 2 waves, 7 tasks; 5 Haiku implementers in parallel in wave 1
  (U7 exports + snapshot + changelog + MI-27, U7 MI-25, U7 README, U8 MI-28, U8 snippets +
  snippet tests), 2 in wave 2 (docs pages + page tests, public-docs/CLAUDE.md + CI paths). The
  run stopped at the gates: the only red check is append-only on
  `tests/public_surface_snapshot.json` (195 lines added, 0 removed). That file is made to change
  with the surface (test plan §5); its approval record `.claude/test-change-approvals/OME-N.json`
  needs the issue id and the final branch name, so it is made at PR-open. I ran the Opus design
  review by hand: accept with fixes, no STRUCTURAL finding. Findings 1-14 fixed by 3 Haiku
  implementers in parallel (MI-28 now sends a compiled recipe and checks the cost; docs: the
  browser sign-in of `endpoint()`, the stream `timeout`, the refused values, the error table,
  a signature block, `IgnoredParameterWarning` on the errors page, STE wording; tests: one
  `plain_reply` helper, a hosted case of the `endpoint_openai.py` snippet, the privacy test
  now goes through the real 403 sign-in challenge). I fixed the errors page intro and the
  Prettier format of two pages myself (an implementer said that they failed at HEAD; they did
  not). Not fixed: finding 16 (the surface snapshot does not pin `__iter__`/`__aenter__`;
  on `main`, out of scope); finding 14 part (`Store`/`Sink` copies in analytics tests on
  `main`). MI-28 ran against a real local Engine: 3 passed (Colima started for the run, then
  stopped; once more with a plugin that skips the docker check). Gates: SDK green with
  `--skip-append-only` (the snapshot item above); Engine docs tests 8 passed; public-docs
  oxlint, eslint, type-check, build green.
- **2026-11-23 — Rebased onto PR #1937 head `bc9eb75a9` for a stacked PR (owner: "open a PR").**
  #1937 was rebased onto a newer `main` today, so the 9 commits moved from `e5f2d173e`
  (backup tag `backup/variant-before-rebase-20261123`). Conflicts only in `CHANGELOG.md` and
  `ErrorsPage.vue` (both sides kept). `main` deleted `_engine/trace.py` (9c49b846f), which the
  chat call uses for its `traceparent` (P8): the helper now lives in `_inference/trace.py`, with
  a new test file `test_model_inference_trace.py`. Gates vs `bc9eb75a9` with
  `--skip-append-only`: SDK green, Engine green (after `uv sync --dev --locked`). Append-only
  vs `bc9eb75a9` lists 5 files, all planned: the SDK surface snapshot (test plan §5) and 4 Engine
  tests of #1937 that U1 changes (`should_retry`/`retry_after` on the stream error event, P10;
  `content: null`, P13). One approval record at PR-open covers them.
- **2026-11-23 — Pushed onto PR #1937 (owner: "add these changes as new commits on top of the
  original chat-endpoint PR").** Fast-forward `bc9eb75a9..111298808` on
  `OME-1963-engine-openai-chat-endpoint`; the SDK surface snapshot joined the approval record
  `OME-1963.json`; PR title and body updated; a comment told the reviewer. The variant worktree
  and branch were removed; work continues in the worktree `engine-openai-chat-endpoint`.
- **2026-11-23 — U9 started: `chat` on the recipe and on the client (spec §5.5, D13 to D17).**
  Owner request: no new object; each model or ensemble has `.chat.completions`. My evaluation
  of the code (one `Recipe` base class, the client namespace pattern, `Run` as a value that
  makes calls) gave the design; the owner said "let`s do exactly as you recommend". Spec
  overview §1 and §5.5, contracts C1 (rewritten), test plan MI-36 to MI-39 and plan U9 written
  before the build.
- **2026-11-23 — U9 done: `chat` on the recipe, on the client and as `sf.chat`;
  `sf.InferenceClient` removed.** Tiered-build run `wf_c5a75e00-f35`: Opus planned 3 waves and
  14 tasks, all with Haiku implementers (wave 1: the core and the new tests MI-36 to MI-38;
  wave 2: 6 parallel test conversions, the docs site, README and changelog, the spec examples;
  wave 3: the docs tests and a final check). Gates green; Opus review: accept with fixes. Code:
  `inference.py` has `Completions`, `Chat`, `AsyncCompletions`, `AsyncChat`,
  `RecipeCompletions`, `RecipeChat` and `InferenceEndpoint`; `_inference/calls.py` has the
  shared checks and send; `chat.py` is the module twin; `Recipe.chat` is a property;
  `Client.chat` and `AsyncClient.chat` are attributes; `check_other` has a `stacklevel`
  argument. Review fixes: F1 and F2 by me (typed entry points `create_sync`, `create_async`,
  `endpoint_sync`, `endpoint_async`, so no `cast`; `InferenceEndpoint` is defined in
  `screamingface.inference` again); F3 (contracts say that `recipe.chat` and `sf.chat` call
  the shared implementation directly); F5 (the warning tests assert the line number, each
  surface called directly); F6 (PRD rows and names); F7 (the import comment). Not changed: F4
  (the `create` signature is written for each surface, because the spec asks for typed
  overloads on each); F8 (no `__repr__` on the namespaces; optional). F9: an implementer ran
  Prettier on `public-docs/CLAUDE.md` and re-aligned 51 table rows; `main` fails Prettier on
  that table, so I put the rows back and kept the 4 changed lines. Tests replaced because their
  subject is gone (each has the equal test of the new surface; no assertion on the wire, the
  reply, a stream, a retry or an error is weaker): the constructor and `client=` type checks
  (`test_constructor_argument_errors`, the two constructor tests of the typing file, the
  refused snippet `a-client-of-another-type`), `test_the_object_keeps_no_state_of_a_call`,
  the three constructor tests of `test_model_inference_recipes.py` (now the access, `create`
  and `endpoint` forms), and the five client-model tests of
  `test_model_inference_openai_shape.py` (now the MI-37 tests). Two lines
  `# noqa: PLR0915` on `Client.__init__` and `AsyncClient.__init__` (one statement over the
  limit after the new attribute; the repo uses this form). The approval record has the new
  snapshot blob; against `main` the snapshot has new lines and one changed entry (`Recipe`
  members: empty, now `chat`). Gates with no skip: SDK green (append-only with the approval
  record); Engine docs tests 8 passed; public-docs oxlint, eslint, type-check, build green;
  MI-28 against a real local Engine: 3 passed. Pushed to PR #1937 on 2026-11-23 on the
  owner's word ("yes, push it and update the PR"); the PR title and body were updated after the push.

- **2026-11-24 — U10 planned: the one-line change from the OpenAI SDK.** Team feedback F3
  through the owner: `openai.OpenAI(…)` to `screamingface.Client(…)` must be the only change. I ran
  typical OpenAI code against `sf.Client` on a mock Engine: the constructor arguments, the tool
  loop that appends the reply message, `model_dump()`, 8 reply attributes and 14 call keywords
  failed. Owner answers Q8 to Q11 (spec §5.6): no model name map; `api_key` accepted and never
  sent, `base_url` = the Engine URL; no error classes; chat completions only. Spec §5.6 (D18 to
  D25), contracts C1.7, test plan MI-40 to MI-46, plan U10. Planned files: the two client
  constructors, `_inference/client_options.py` (new), `_inference/request.py`,
  `_inference/calls.py`, `chat_completion.py`, `_chat_dump.py` (new), `inference.py`,
  `chat.py`, two new test files, the docs page and one snippet, README, changelog, the
  snapshot.

- **2026-11-24 — U10 done (local, not pushed).** RED first: MI-40 to MI-44 in three new test
  files (`test_model_inference_openai_dropin.py`, `..._limits.py`, `..._reply.py`); they failed
  on the missing module. GREEN by one Haiku implementer with a full spec (source files only), then
  an Opus design review: no STRUCTURAL finding; 2 BUG, 3 LOCAL, 9 NIT. Fixed by me: a bad
  `engine_url` or `scoreboard_url` now raises before a warning; `base_url` uses the shared
  origin check and removes `/v1` from the path only (a host with the name `v1` is valid); the 13
  OpenAI-only keywords have their own warning text, with no `sf.Model(params=...)` advice; the
  call builder is typed again; one WHY text for the `None` attributes; the tests for these;
  README wording. New modules: `_inference/client_options.py`, `_inference/parameters.py` (the
  parameter policy moved out of `request.py`, which was at 447 lines), `_chat_dump.py`. Not
  changed (review notes): a create keyword with the value `None` still warns (the rule of D4; the
  spec now states the difference to D22); a traceback of a failed constructor holds its
  arguments, as in each Python call. Deviations from the plan: the test of the defaults is a
  third file (the 450-line rule); two test bugs of mine were fixed after the first run (the
  timeout assertions need the fake clock; one explicit `openai` import for pyright). The approval
  record has the new snapshot blob (the surface change is the owner request of 2026-11-24).
  Check with the probe of the planning step: the constructor arguments, the tool loop,
  `model_dump()`, the reply attributes and the call keywords pass; the lines that still fail are
  the limits of Q10 and Q11 and the refused `functions` keywords. Gates with no skip: SDK green
  (8,482 tests, coverage gate, append-only with the approval record); public-docs oxlint,
  eslint, type-check and build green. Not run: MI-28 against a real Engine (no wire change in
  this unit) and a paid call.

- **2026-11-24 — U11: tool calls are turned off (local, not pushed).** Team feedback F4 through
  the owner: disable tool use for now and give a proper error. Owner answers Q12 to Q14 (spec
  §5.7): the Engine and the SDK refuse; declared tools and tool turns count; a fixed refusal
  with no switch, and the tool code stays. Spec §5.7 (D26 to D30), contracts C1.8, test plan
  MI-47 to MI-50, plan U11; Engine PRD `tool-calls.md` §0 (TC-S23, TC-23).
  SDK: `refuse_tool_use` in `_inference/parameters.py`, called by the shared checks before the
  warnings: `PlanningError`, code `tools_not_available`, `details["param"]`. `functions` with an
  item gets the same error; `function_call` now only warns, as `tool_choice` (D29 replaces that
  part of D25). New test file `test_model_inference_tools_off.py`. Tests changed because their
  call is now refused (all are files of this PR; no assertion on the wire is weaker):
  `test_messages_and_tools_are_sent_unchanged` checks the tools at the body builder;
  the two-client program of MI-40 is a conversation with no tool; the reply-message tests use a
  text reply at the call and the tool form at the helper; `test_tools` of the docs snippets is
  removed with its snippet. Engine: `_tool_use` at the boundary (`rest/chat_body.py`) answers
  400 `tools_not_available` before a run, a blob write and a catalogue read; the request model
  keeps `functions` so the route can refuse it. 21 route tests of the tool code (4 files) run
  with the check removed by the test-only fixture `tests/unit/_chat_tools_reachable.py`; no test
  was removed. Docs: the Chat API page, the OpenAI guide page (the six limits of a request with
  tools left the page; one new limit), the two READMEs, the SDK changelog; the snippet
  `tools.py` is removed. Deviation from the answer of Q14 to report: the owner option said that
  the tests "call the inner functions or are removed"; I kept the route tests with a test-only
  fixture, because the route checks of the tool code have no other caller.

- **2026-11-24 — before the push.** MI-28 (`tests/e2e/test_model_inference_local_engine.py`)
  had a case that sent tools to a real local Engine. It is now the refusal case: the SDK raises
  `tools_not_available` before a request, and a raw POST to the real Engine gets HTTP 400 with
  the same code. Run with Docker and `SCREAMINGFACE_TEST_E2E=1`: 3 of 3 pass. The mirrors of
  `OME-2005`, `OME-1963` and `OME-1964` have the notes of U10 and U11.

## Outcome (fill at the end — required before COMMIT)

Not started.

## Review round 2 (2026-11-25)

The re-review of PR #1937 has two SDK items (stream cancel, and `timeout` as the limit of the
full call) and one docs item (the OpenAI client retries in the bridge examples). They are units
U-G and U-H of `docs/plan/2026-11-25-chat-endpoint-review-round-2.md`; the scenarios are RR-S17
to RR-S19 and the tests MI-51 to MI-56 of
`docs/spec/2026-11-17-engine-openai-chat-endpoint/prd/review-round-2.md`. The record of the round
is in `docs/work/2026-11-17-engine-openai-chat-endpoint.md`.
