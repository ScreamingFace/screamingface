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

## Outcome (fill at the end — required before COMMIT)

Not started.
