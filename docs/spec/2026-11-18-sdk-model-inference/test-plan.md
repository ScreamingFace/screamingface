# SDK model inference — test plan

## 1. Strategy

- **Most tests are unit tests of the SDK** with `httpx.MockTransport`. The mock Engine is a
  hand-written handler that plays stream frames, as the classify tests do
  `[existing packages/screamingface/tests/test_classify.py:59]`.
- **The frame reader is pure** (bytes in, chunks or one reply out). It has table tests with no
  transport.
- **Typing is a test.** A file with `assert_type` pins the six result types of `create`, the
  two constructor forms and the two results of `endpoint`. The pyright gate (basic mode) reads it
  `[existing packages/screamingface/pyrightconfig.json:6]`.
- **One integration test** uses the e2e harness of the SDK (a real local Engine and the fake
  gateway of the harness) `[existing packages/screamingface/tests/e2e/harness/fake_gateway.py]`.
  It makes no paid call.
- **The Engine change** has unit tests in `apps/screamingface-engine`, with the stream tests of
  PR #1937 as the pattern.
- **No paid call** is part of the gates. A paid check through OpenRouter is a stop point for the
  owner, as in PR #1937.

## 2. Order (risk first)

1. MI-1 (typing), MI-2 and MI-3 (the resend rule on the new POST seam). These three decide the
   design; a failure there changes the plan before other code exists.
2. SE-1 … SE-7 (the Engine event, the reply equality, the null content). The SDK reader depends
   on them.
3. MI-4, MI-5 (the frame reader).
4. MI-6 … MI-19 (the sync call: request, compile, errors, retry, parameters).
5. MI-20 … MI-24 (streams, async, concurrency).
6. EB-1 … EB-7 (`endpoint()`), EB-1 first.
7. MI-25 … MI-27 and MI-29 … MI-31 (privacy, reply types, public surface, default client,
   evaluation URL4, an Engine with no flag).
8. MI-28 (integration), then the docs tests.

## 3. Test count

| PRD | Scenarios | TDD cases |
|---|---|---|
| `prd/model-inference.md` | 23 | 31 |
| `prd/endpoint-bridge.md` | 8 | 7 |
| `prd/stream-error-retry-flag.md` | 7 | 7 |

## 4. Constraints of the owner, each pinned by a test

| Constraint | Tests |
|---|---|
| `sf.InferenceClient(ensemble)` and `.chat.completions.create(...)` (ans:Q1, Q2) | MI-6, MI-7, MI-27 |
| OpenAI field names on the reply (ans:Q2) | MI-4, MI-26 |
| Sync, async and streaming (ans:Q2) | MI-6, MI-20, MI-22 |
| A sampling parameter: accept, warn, ignore (ans:Q3) | MI-16 |
| No retry by default (ans:Q4) | MI-15, MI-2, MI-31 |
| Always streamed on the wire (ans:Q5) | MI-6, MI-4, SE-5 |
| One method name; the mode follows the client (ans:Q7) | MI-1, MI-22, EB-5 |
| `sf.InferenceClient` and the OpenAI path `chat.completions.create`; `model` on the client or on each call (D11, D12; team review 2026-11-23) | MI-32 (the path), MI-33 (the model of a call, sync and async), MI-34 (no model: `TypeError` before a request), MI-35 (`endpoint(model=...)`) — `tests/test_model_inference_openai_shape.py` |

## 5. Existing tests

- `packages/screamingface/tests/public_surface_snapshot.json` changes (new names). This file is
  made to change with the surface; the test asks for a changelog entry
  `[existing packages/screamingface/tests/test_public_surface.py]`.
- No other test of `main` must change. If the seam of risk R1 needs an edit to a current test,
  the work stops and the owner decides.
- `apps/screamingface-engine/tests/unit/test_chat_docs_page.py` (a test of PR #1937, not of
  `main`) gets entries for the new docs text.

## 6. Docs tests

- The Python examples of the new API page are files in
  `public-docs/src/snippets/model-inference/`. An SDK test runs each file against the mock
  Engine. The SDK test workflow gets those paths in its filter (risk R6).
- The guide page of PR #1937 keeps its Engine tests.
- `public-docs/CLAUDE.md` names the new snippet directory, the new page, its route and its
  navigation entry. The SDK test workflow has two path blocks; both get the snippet path
  `[existing .github/workflows/screamingface-tests.yml:5]`.

## 7. Gates

- SDK: `run_gates.py screamingface --base <base>` (ruff, format, pyright, pytest with 95 %
  coverage, the node test, the notebook check) `[existing .claude/sdlc.local.md:85]`.
- Engine: `run_gates.py screamingface-engine --base <base>`.
- Repo: `run_gates.py repo --base <base>`. `public-docs`: lint and build.
- The base for the append-only check is `origin/main`. Until PR #1937 is merged, the approval
  record of that PR covers its 40 test files only on its own branch name, so the gates of the
  variant branch run with `--skip-append-only` for the Engine stack, and with no skip for the
  SDK stack. The plan states this as a stop point.
