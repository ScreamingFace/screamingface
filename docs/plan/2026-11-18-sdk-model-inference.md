# Plan — SDK model inference (`sf.InferenceClient`)

Status: DRAFT, waits for the owner's approval in plain words. No code before that.
Spec (approved 2026-11-18, with the reading of Q7 and the proposals P1–P17):
`docs/spec/2026-11-18-sdk-model-inference/`. Ledger: `docs/work/2026-11-18-sdk-model-inference.md`.
Branch: `engine-openai-chat-endpoint-variant` (from the head of PR #1937). Parent epic: `OME-1297`.

Paths: `S/` = `packages/screamingface/src/screamingface/`, `T/` = `packages/screamingface/tests/`,
`E/` = `apps/screamingface-engine/src/screamingface_engine/`.

## 1. Decisions of the plan

| Id | Decision | Why |
|---|---|---|
| D1 | One branch, one PR; the units below are ordered commits | the same shape as PR #1937; the units depend on each other |
| D2 | The Engine change comes first (U1) | the SDK reader is written against the final frames, and test SE-5 pins the reply rule that the SDK copies |
| D3 | New SDK files, each 450 lines or less: `S/inference.py` (public: `InferenceClient`, the `chat` namespace, the overloads, `InferenceEndpoint`); `S/chat_completion.py` (public: the reply and chunk types, `ChatStream`, `AsyncChatStream`); `S/_inference/` (private: `frames.py` the SSE reader and the reply builder, pure; `request.py` the model rule, the compile step and the parameter policy; `transport.py` the send, the error map and the retry, sync and async) | the SDK puts public types in top-level modules (`answer.py`, `classification.py`) and the mechanics in private packages |
| D4 | One streamed POST seam on each client, next to `_engine_get`: `_engine_post_stream(path, *, json, headers, timeout)`, with the replay-safe mark (P15) | the existing seams are GET-only or not streamed [existing S/client.py:571] |
| D5 | Exemplar for the transport and the error map: `S/_engine/classification.py`; for the tests: `T/test_classify.py` (`httpx.MockTransport` through `http_transport=`) | the closest single paid call |
| D6 | The `IgnoredParameterWarning` class goes where the SDK defines its other public `*Warning` classes | one place for warnings |
| D7 | The trace header comes from `S/_engine/trace.py` (`new_trace_context().headers()`) | reuse (P8) |
| D8 | The candidate part of an evaluation URL4 is found with the `url4` parser, as the docs snippet does today (`public-docs/src/snippets/openai-chat/candidate_url4.py`); the snippet then calls the SDK and is deleted from the guide | one rule, now in the SDK (P14) |
| D9 | `openai==2.54.0` joins the SDK dev group (P16), the same pin as the Engine tests | the docs example runs with the real client |
| D10 | Build with the tiered-build workflow, one run for each SDK unit (Opus plans the waves, Haiku implements, gates, Opus design review, one fix round). U1 and U8 are small enough to build in the main loop with one design review | the owner's routing rule; the memory note: a wave with only RED tests stops the workflow, so each wave pairs its RED tests with their GREEN code |

## 2. Units (ordered commits)

### U1 — Engine: retry flag in the stream error event, null content (spec `prd/stream-error-retry-flag.md`)

- Tests: SE-1 … SE-7.
- `E/chat/sse.py`: `error_event(message, type_, code, *, should_retry, retry_after=None)`; the
  `error` object gets `should_retry`, and `retry_after` only when it is not `None`.
- `E/rest/chat_stream.py` (`_step`): passes `exc.should_retry` and `exc.retry_after` of the
  `ChatError`; the unexpected error passes `should_retry=False`.
- `E/rest/chat_answer.py` (`_completion`): `content` is `None` when the status is `refused`, or
  when the result has tool calls and no text (P13).
- SE-5 has its own small reference builder in the test (frames to a reply); the SDK builder of
  U3 follows the same rule.
- Docs: the stream section of `public-docs/.../OpenAiApiPage.vue` names `should_retry` and
  `retry_after`; `tests/unit/test_chat_docs_page.py` gets that text. The Engine README states
  that a `chat_keepalive_s` above 60 s is not supported by the SDK (risk R7).
- Gates: Engine stack (see S1), repo stack.

### U2 — SDK foundation: the public shape, the typing, the POST seam

- Tests: MI-1 (a typing file with `assert_type` for the six rows of C1.2, the two constructor
  forms and the two results of `endpoint()`), MI-2, MI-3.
- `S/inference.py`: `InferenceClient` with the constructor overloads, `Chat` with the
  `create` overloads, `endpoint()` overloads; the bodies raise `NotImplementedError` until U4.
- `Client._engine_post_stream` and `AsyncClient._engine_post_stream` (D4).
- STOP rule: if pyright (basic) refuses the overload shape, the unit stops and the owner sees
  the options before a change of the public shape.

### U3 — SDK reply types and the frame reader (pure)

- Tests: MI-4, MI-5, MI-26.
- `S/chat_completion.py`: the types of C1.3 with `to_dict()` and the short forms.
- `S/_inference/frames.py`: lines to events (keep-alive dropped, `[DONE]`, error event, JSON
  check), events to chunks, chunks to one `ChatCompletion` (C2.3). Table tests with no transport.

### U4 — SDK sync call

- Tests: MI-6 … MI-19, MI-23, MI-29, MI-30, and the sync half of MI-31.
- `S/_inference/request.py`: the model rule (P1, P14), the compile step (P2, P17; a recipe with a
  reducer compiles at each call with `Client._operator_catalog.load`), the parameter policy
  (P4), the request body and headers (C2.1).
- `S/_inference/transport.py`: send through `_engine_post_stream`, the error map (C2.4), the read
  limit of 60 s and the total `timeout` (P11), `max_retries` (C2.5), the close of the connection
  on each exit.
- `InferenceClient` takes `default_client()` at each call when it has no client (MI-S20b).

### U5 — SDK streams, async, concurrency

- Tests: MI-20, MI-21, MI-22, MI-24, the stream and async half of MI-31.
- `ChatStream` and `AsyncChatStream` (C1.4); the async path of `transport.py`; `create`
  returns a coroutine with an `AsyncClient`; argument errors are raised before the coroutine is
  made.

### U6 — SDK `endpoint()`

- Tests: EB-1 … EB-7.
- `InferenceEndpoint` with a `repr` that hides the header values; on an `https` Engine,
  `login()` (or its async form) first, then the headers of the auth object of the client
  [existing S/_access/base.py:23]. D9 (the dev dependency) lands here, with `uv.lock`.

### U7 — SDK privacy, public surface, changelog, README

- Tests: MI-25, MI-27.
- `__all__` and `T/public_surface_snapshot.json` (the 17 names of C1.6); a `CHANGELOG.md` entry
  under "Unreleased / Added"; a README section "Call an ensemble as a chat model".

### U8 — Integration and docs

- Test: MI-28 with the e2e harness of the SDK (a real local Engine, the fake gateway); it carries
  the `e2e` marker, as the other tests of `T/e2e/`.
- `public-docs`: a new API page `/sf-client/api/inference-client` (route, navigation entry, snippets
  in `src/snippets/inference-client/`, each one run by an SDK test against the mock Engine; names
  after the 2026-11-23 rename, spec §5.4 D11/D12); the OpenAI guide page uses `endpoint().model` to
  get the Candidate URL4, and the "run an evaluation first" way stays as an alternative;
  `public-docs/CLAUDE.md` names the new files.
- `.github/workflows/screamingface-tests.yml`: both path blocks get
  `public-docs/src/snippets/inference-client/**`.

### U9 — `chat` on the recipe and on the client; remove `sf.InferenceClient` (spec §5.5)

Owner order of 2026-11-23: "let`s do exactly as you recommend, properly write the spec, then launch
parallel workers using haiku to implement it". Contracts: C1 (rewritten), D13 to D17.

- Code: `S/inference.py` becomes the namespaces `Chat`, `Completions`, `AsyncChat`,
  `AsyncCompletions` (three `stream` overloads each; no generic class), with one shared
  implementation of the checks and the send. `RecipeChat` and `RecipeCompletions` (bound to a
  recipe, through `default_client()`); the property `Recipe.chat`; the attribute `chat` of
  `Client` and `AsyncClient`; the module `S/chat.py`; the exports (16 names and `chat`).
  `check_other` gets a stack-level argument so the warning names the line of the caller on each
  surface. No change in `S/_inference/` transport, frames, chunks, error map, trace; no change in
  the Engine.
- Tests: the tests of this PR that make an `InferenceClient` change to the new surface by a
  fixed rule (`InferenceClient(X, client=c).chat.completions.create(A)` becomes
  `c.chat.completions.create(A, model=X)`; `.endpoint()` becomes `c.chat.endpoint(X)`). No
  assertion on the wire, the reply or an error is made weaker. A test whose subject is gone (the
  constructor, the model of the client against the model of the call, the generic types) is
  replaced by the test of the new surface; the ledger lists each one. New tests MI-36 to MI-39.
- Docs: the API page becomes `/sf-client/api/chat` (`ChatPage.vue`), the snippets move to
  `public-docs/src/snippets/chat/`, the OpenAI guide page, the errors page, `public-docs/CLAUDE.md`,
  the SDK README section, the changelog entry and the CI path filters follow. The PRD and
  test-plan examples of the spec follow.
- After the build: the approval record gets the new blob of the surface snapshot; MI-28 runs
  again; the local playground notebook follows. No push before the owner's word.

### U10 — The one-line change from the OpenAI SDK (spec §5.6)

Owner request of 2026-11-24 (team feedback F3): "Could you add that approach as well so we can
also meet that criteria". Answers Q8 to Q11. Contracts: C1.7, D18 to D25.

- Code: a new module `S/_inference/client_options.py` (the checks of `base_url`, `api_key`,
  `timeout`, `max_retries` and the ignored options; one function for the two clients). The two
  client constructors call it first and keep two private values (the chat defaults).
  `S/_inference/request.py`: `messages` and `tools` as iterables, a `ChatMessage` item, the
  timeout of an `httpx.Timeout`, `max_retries=None`, the new names of the parameter list.
  `S/_inference/calls.py`: the call takes the defaults of its client after the argument checks.
  `S/chat_completion.py` and a new module `S/_chat_dump.py`: the `None` attributes and the three
  dump methods. The `create` signatures of the four surfaces follow. No change in the transport,
  the frames, the error map or the Engine.
- Tests first (RED): MI-40 to MI-44 in `tests/test_model_inference_openai_dropin.py` and
  `tests/test_model_inference_openai_dropin_reply.py`; the sample of
  `tests/test_model_inference_params.py` gets the new names. All these files are new in this PR.
- Docs: a section "Move from the OpenAI SDK" on the Chat API page with the snippet
  `openai_one_line.py` and the list of limits; the parameter table; the README section; the
  changelog entry (MI-45).
- After the build: the surface snapshot and its blob in the approval record (MI-46); the SDK
  gates; an Opus design review. No push before the owner's word.

## 3. Gates for each unit

- SDK: `uv run --script .claude/scripts/run_gates.py screamingface --base origin/main` (ruff,
  format, pyright, pytest with 95 % coverage, the node test, the notebook check).
- Engine (U1 only, and U8 if it changes an Engine file): `run_gates.py screamingface-engine
  --base origin/main --skip-append-only` (see S1).
- Repo: `run_gates.py repo --base origin/main`. `public-docs`: `npm run lint` and
  `npm run build` when a docs file changes.
- After each unit: one design review (Opus, read-only) with the spec as the rubric, one fix
  round, then the commit. After U8: one review of the whole branch.

## 4. Stop points

| Id | When | Question |
|---|---|---|
| S0 | now | Approve this plan in plain words |
| S1 | before U1 | The 40 approved test files of PR #1937 are pinned to the branch name `OME-1963-engine-openai-chat-endpoint`, so the append-only check of the Engine stack fails on this branch. My proposal: run the Engine stack with `--skip-append-only` (as in the build of PR #1937); the SDK stack runs with no skip. At PR-open the question goes away if PR #1937 is merged first |
| S2 | after U8 | A small paid check: the SDK, the local stack, the real gateway and OpenRouter with a cheap model (a plain call, a stream, a tool call, an async call; about 0.05 USD) |
| S3 | PR-open | Linear: one issue for the SDK and the docs (`client-sf`), one for the Engine change (`screamingface-engine`), one small one for the CI filter (`repo-dev-processes`), all under `OME-1297`; the branch rename; the mirrors; the base of the PR (`main` after PR #1937 is merged, or the branch of PR #1937 as a stacked PR) |

## 5. Risks

| Risk | What the plan does |
|---|---|
| The overloads on `self` for the nested `chat` object fail in pyright | MI-1 is the first test of U2; STOP rule in U2 |
| The resend after a sign-in challenge sends a paid call two times | MI-3 proves the resend only for a challenge; MI-2 proves no resend for 408, 429, 5xx |
| The reply that the SDK builds differs from the plain reply | SE-5 in the Engine (U1) and MI-4 in the SDK (U3) use the same cases |
| Coverage of the SDK falls under 95 % | each unit has its own coverage pass before the gates |
| The e2e harness needs Docker or an env flag | MI-28 uses the marker of the other e2e tests; when it cannot run in the gates, the ledger says so and the test runs by hand before PR-open |

## 6. Not in this plan

The out-of-scope list of the spec (overview §5.3). No push, no PR and no Linear issue before S3
and the owner's word.
