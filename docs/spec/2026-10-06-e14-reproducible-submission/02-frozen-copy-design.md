# E14 redesign — frozen copy (supersedes the cache-version design)

**Status:** approved by the owner on 2026-10-08 · **Epic:** OME-1307
**Supersedes:** `prd/gateway-cache-revision.md` (removed), and every part of `prd/cache-version-capture.md`,
`prd/reproduce.md`, `erd.md` and `contracts.md` that names a cache revision, `only-if-cached`,
`cache-revision`, `X-Cache-Replay` or the revisions endpoint. Where this file and an older file
disagree, this file wins.

## 1. Summary

A run **captures** by default: `sf.evaluate(...)` has `capture=True` unless the caller passes
`capture=False` (Q22). The engine then opens a
**frozen copy** in the AI Gateway, and the gateway stores every chat request and its response in that
copy, whether the answer came from the cache or from a live call. The engine also stores every
web-tool result it feeds to the model. At the end of the run the engine **seals** the copy.

To **reproduce** a score, the SDK runs the same url4 with the same answer seed and names the frozen
copy. The engine then sends every chat call to a replay endpoint with the same request and response
shape as `/v1/chat/completions`, and reads every tool result from the copy. Nothing calls a provider
or Tavily.

The frozen copy is an independent table. It does not use the cache, its keys or its revisions. So the
whole cache-revision mechanism (label, registry, `only-if-cached`, `cache-revision`, the revision
header, the revisions endpoint) is removed from the stack. There is no publish step.

## 2. Owner decisions (interview ledger, continued)

| Id | Question | Answer |
|---|---|---|
| Q11 | Reproducibility mechanism | A frozen copy captured during the run, not the cache version (owner and peers, 2026-10-08). |
| Q12 | How a replayed call finds its answer | "it might follow a similar strategy as the current cache logic, any request made computes a hash to maps to the respective answer" |
| Q13 | Web-tool results | "yeah, let`s include it as well" |
| Q14 | Local runs | "Out of the scope, we can solve this later, but i think the actual solution is upload step for a local frozen copy" |
| Q15 | Retention | "keep copies forever" |
| Q16 | Who can replay a copy | Option (a): anyone who holds the copy id and sends the exact request. No extra rule for private boards. |
| Q17 | Link between a copy and a score | "the way scores are today" (self-reported) |
| Q18 | Capture failure | "best effort" |
| Q19 | Option name | `capture` (`evaluate(..., capture=True)`) |
| Q20 | Answer seed | Kept: still stored and sent. |
| Q21 | Remove the cache-revision mechanism from the stack | Yes. |
| Q22 | Capture default (2026-10-09) | "consider the capture flag an optional flag and for it to be true, by default" |

## 3. Data model (AI Gateway, new)

Core module `aigateway.core.frozen_copy` (registered in the Tortoise model list), one migration.

**`frozen_copies`**

| Column | Type | Rule |
|---|---|---|
| `id` | UUID pk | Made by the gateway. |
| `account` | FK → `Account`, `CASCADE` | The account that opened the copy. Only it may write or seal. |
| `status` | `open` \| `sealed` | `open` on create; `sealed` is final. |
| `entries` | int | Count, set at seal. |
| `created_at`, `sealed_at` | datetime | |

**`frozen_copy_entries`**

| Column | Type | Rule |
|---|---|---|
| `id` | UUID pk | |
| `frozen_copy` | FK → `frozen_copies`, `CASCADE` | |
| `kind` | `chat` \| `tool` | |
| `request_digest` | char(64) | sha256 (see §4.1). Index `(frozen_copy, kind, request_digest, created_at)`. |
| `request_json` | JSON | The digested request (chat body or tool description). |
| `response_json` | JSON | Chat: the body returned to the caller, or the error `detail`. Tool: `{"result": "<string>"}`. |
| `status_code` | int | 200 for a success; the HTTP status of a captured error. |
| `created_at` | datetime | Capture order. |

Invariants:
- **F1.** Rows are insert-only. A sealed copy accepts no insert.
- **F2.** Copies and rows are kept forever (Q15). No list endpoint returns stored requests.
- **F3.** One entry is at most `frozen_copy_max_entry_bytes` (new setting, default 2,000,000 bytes, request
  plus response JSON). A larger one is not stored and is reported as `failed`.

## 4. AI Gateway behaviour

### 4.1 Request digest

`request_digest = canonical_digest({"kind": kind, "request": request})` with the existing
`core/request_cache/canonical.py` helper.
- **chat:** `request` is the body after the `cache` control is popped and the gateway-level dispatch
  controls are stripped (`chat.py`, the body at the step before provider lookup). The replay endpoint
  applies the same two steps, so the same request gives the same digest.
- **tool:** `request` is the tool description the engine sends (§4.4).

### 4.2 Capture on `/v1/chat/completions`

- Request header `X-AIGW-Frozen-Copy: <copy id>`.
- Before the cache stage, the gateway checks the copy: it exists, it belongs to the caller's account, and
  it is `open`. If not, the call is served as usual and nothing is stored (`refused`).
- `stream: true` is never captured (`refused`): the gateway has no assembled body for a stream.
- After the final response is ready (a cache hit or a live success), the gateway inserts one entry with
  status 200 and the body it returns. A provider or dispatch error that ends the call (an
  `HTTPException` after the copy check) is captured too, with its status and `detail`. Gateway
  refusals before the copy check (bad JSON, bad shape, unknown provider) are not captured.
- The insert is awaited, and a failure never fails the call (best effort, Q18).
- Response header `X-AIGW-Capture: stored | failed | refused` on every call that sent the request
  header (also on the error responses).

### 4.3 Frozen-copy endpoints (all need the usual account auth)

| Route | Who | Result |
|---|---|---|
| `POST /v1/frozen-copies` | any account | 201 `{"id", "status": "open"}` |
| `POST /v1/frozen-copies/{id}/seal` | owner | 200 `{"id", "status": "sealed", "entries"}`. Idempotent. Not the owner or unknown → 404. |
| `POST /v1/frozen-copies/{id}/tool-results` | owner, copy `open` | Body `{"description": {...}, "result": "<string>"}` → 200 `{"outcome": "stored" \| "failed"}`. Sealed → 409 `frozen_copy_sealed`. |
| `POST /v1/frozen-copies/{id}/chat/completions` | anyone (Q16), copy `sealed` | Replay. Same request and response shape as `/v1/chat/completions`. |
| `POST /v1/frozen-copies/{id}/tool-results/lookup` | anyone, copy `sealed` | Body `{"description": {...}}` → 200 `{"result": "<string>"}`. |

### 4.4 Replay rules

- The copy must exist and be `sealed`; else 404 `{"code": "frozen_copy_unavailable"}`.
- The caller sends `X-AIGW-Replay-Occurrence: <n>` (default 0): how many successful answers the caller
  already received for this same request in this replay run.
- Lookup among the entries with the same `(copy, kind, digest)`:
  1. the successful entries (status 200) in capture order: return entry `n`, or the last one when `n`
     is past the end (identical requests under the cache return identical answers);
  2. if there is no successful entry: return the latest captured error with its status and `detail`;
  3. if there is no entry: 404 `{"code": "frozen_copy_miss"}`.
- No credential is resolved, no provider and no plugin is called, no model is validated, no cache is
  read or written. A replay works after a model is retired or a provider plugin is removed.
- A replayed chat body is marked so that accounting shows $0 spend: the gateway sets the body's
  `_aigw` call cost to 0 and adds `"frozen_copy_replay": true` (the engine reads cost from `_aigw`).
- Response header `X-AIGW-Replay: hit | error` on a found entry.

## 5. Engine behaviour

### 5.1 Modes

| Inbound header (start route and sync surface) | Job env | Mode |
|---|---|---|
| `X-Capture: true` | `URL4_CLOUD_CAPTURE=1` | capture |
| `X-Replay-Frozen-Copy: <uuid>` | `URL4_CLOUD_REPLAY_FROZEN_COPY=<uuid>` | replay |
| both | — | 400 `malformed_header` |

Both travel header → job env → `RequestScope`, the same path as `X-Answer-Seed`. The start response
echoes the header that was accepted (`X-Capture` or `X-Replay-Frozen-Copy`). Only the run route honours
them: the mount routes and the local eval path answer 400 `capture_unsupported` when either header is
present (pinned 2026-10-08, B3 review).

### 5.2 Capture mode

1. At run start (before the first step), `POST /v1/frozen-copies` with the run's identity headers. On
   failure the run continues uncaptured and is `partial` (reason `open`).
2. Every chat call adds `X-AIGW-Frozen-Copy: <id>` and records the `X-AIGW-Capture` value (no header →
   `missing`, for an older gateway).
3. Every web-tool call: after `_execute_tool` returns its string (before truncation), `POST
   …/tool-results` with the description and the string, and record the outcome. This covers success,
   "no results" and failure strings alike: the copy stores exactly what the model saw.
4. At run end, `POST …/seal`. On failure the run is `partial` (reason `seal`).
5. **Rule:** `capture.status = complete` only when the open and the seal worked and every chat and tool
   outcome is `stored`. A failed or cancelled call that a later attempt with the same request replaced
   is forgiven (the request-digest rule, D2). Anything else is `partial`.
6. Run summary attributes: `capture.frozen_copy_id`, `capture.status`, and
   `capture.partial.<reason>` counts (`failed`, `refused`, `missing`, `open`, `seal`, `error`,
   `ambiguous`). A capture run always writes them, even with no model call and also when the run fails.
7. **`ambiguous` (pinned 2026-10-08, B3 review):** in capture mode, a call that the engine re-issued under a
   `max-age` bound, or a call whose transport attempt was retried, may leave a stored answer the model never
   used ahead of the one it used. Such a call records `ambiguous`, which is never forgiven, so the run is
   `partial`.

### 5.3 Replay mode

1. Every chat call goes to `POST /v1/frozen-copies/{id}/chat/completions` with
   `X-AIGW-Replay-Occurrence`. The engine reserves the next occurrence slot for the request digest when it
   sends the call, and gives the slot back if the call does not succeed, so concurrent identical requests
   get distinct entries.
1a. Replay skips the engine's model-admission check (`/v1/models/admit`), so a retired model still
   replays.
2. A found success is used as usual and accounted as $0 (like a cache hit). A captured error is raised as
   usual, so the case fails the same way as in the original run. A 404 `frozen_copy_miss` fails the case
   with `frozen_copy_miss`; a 404 `frozen_copy_unavailable` fails it with `frozen_copy_unavailable`.
3. No `max-age` re-issue and no cache controls in replay mode.
4. Web-tool calls never call Tavily: the engine calls `…/tool-results/lookup` (with the occurrence
   rule). A miss fails the case with `frozen_copy_miss`.
5. The run summary always carries `capture.replay = <id>`.
6. Failure codes `frozen_copy_miss` and `frozen_copy_unavailable` are declared in the engine
   (`error_text.py`, `benchmarks/contract.py`) and in the SDK mirror (`_report_primitives.py`).

## 6. Scoreboard behaviour

- `Score` columns `frozen_copy_id` (UUID string, nullable) and `capture_status` (`complete` |
  `partial`, nullable) replace `cache_revision` and `reproducible`. `answer_seed` stays. All three are
  fill-only on a same-owner resubmit. `frozen_copy_id` requires `capture_status`.
- `score_reproductions.frozen_copy_id` replaces `cache_revision`.
- `POST /v1/scores/{id}/reproductions`: the score must have `capture_status = complete` (else 409
  `not_reproducible`); the body's `score`, `total_questions` and `frozen_copy_id` must equal the stored
  values (else 422 `not_exact`). Everything else is unchanged.

## 7. SDK behaviour

- `evaluate(..., capture: bool = True)` (sync, async, module level). Capture is on by default (Q22).
  `True` sends `X-Capture: true`. `capture=False` sends no header. `sf.reproduce` never sends
  `X-Capture`.
- `CandidateResult.frozen_copy_id` and `capture_status` (from the run summary; absent → `None`).
- `submit` sends `frozen_copy_id`, `capture_status` and `answer_seed` when set.
- `LeaderboardScore.frozen_copy_id`, `capture_status` replace `cache_revision`, `reproducible`.
- `sf.reproduce(score, *, record=True)`, in check order:

| Outcome | Reason | When |
|---|---|---|
| not_reproducible | `partial` | `capture_status == "partial"`. No run. |
| not_reproducible | `unknown` | No `capture_status`, no `frozen_copy_id`, or no `benchmark_revision`. No run. |
| failed | `replay_unsupported` | The start response does not echo `X-Replay-Frozen-Copy`, or the summary lacks `capture.replay` and no replay failure code proves replay mode. |
| failed | `frozen_copy_miss` | A case failed with `frozen_copy_miss`; `missed_cases` lists them. |
| failed | `frozen_copy_unavailable` | The copy is unknown or not sealed. |
| failed | `run_failed` | A candidate-level failure that is not a replay code. |
| failed | `benchmark_revision_changed` | The replay ran on another benchmark revision. |
| failed | `score_differs` | The score or the case count differs. |
| exact | — | Recorded with `frozen_copy_id` when `record=True`. |

## 8. Removed from the stack

- **B1 (gateway):** all of the cache-revision PR: the revision label and registry, golden vectors,
  `register_key_revision`, `only-if-cached`, `cache-revision`, `X-AIGW-Cache-Revision`, the Tavily
  `cache_revision`, `GET /v1/cache/revisions`, the regenerated hit-contract fixture. B1 becomes the
  frozen-copy PR (§3, §4).
- **B3 (engine):** the cache-revision capture and replay: `X-Cache-Replay`, `cache.revision`,
  `cache.reproducible`, `cache.replay`, the cache tally rule, the K10 pre-check, the replay cache
  body, `replay_cache_miss`, `unknown_cache_revision`. B3 becomes the capture/replay PR (§5). The
  generic pieces are reused under new names: the header → env → scope plumbing, the start-route echo,
  the run-scoped tally with D1/D2, the always-written summary for special runs, the failure-code
  declarations.
- **B4, B5, C1:** renamed fields, codes and texts as in §6, §7.
- **B2 (Tavily cache through the gateway):** unchanged. It still saves money on normal runs; it is no
  longer needed for reproducibility.

## 9. Edge cases

| Case | Behaviour |
|---|---|
| Cache hit vs live call | Both captured the same way (the body returned to the caller). |
| Retry after a 429/5xx | Every attempt is captured. Replay of the identical request returns the success directly. |
| Final error (the case failed) | Captured with its status and `detail`; replay returns it, so the case fails the same way. |
| Identical requests, different answers (sampling, cache off) | Served in capture order via the occurrence counter. Concurrent branches can take them in another order: a known limit. |
| Provider-native web search | Inside the chat response, so captured with it. |
| LLM judges | Through the gateway, so captured. |
| Streaming request under capture | Not captured (`refused`) → the run is `partial`. |
| Capture insert fails | The call is served; `failed` → the run is `partial`. |
| Gateway older than B1 | No `X-AIGW-Capture` header → `missing` → `partial`. A replay gets 404 on the replay route → `frozen_copy_unavailable`. |
| Engine crashes mid-run | The copy stays `open`; replay refuses it (`frozen_copy_unavailable`). |
| Replay of a run that offered no web tools (no Tavily connection) on an engine that offers them | The request bodies differ → `frozen_copy_miss`. Known limit. |
| Different engine/SDK version renders prompts differently | Different digests → `frozen_copy_miss`, visible. |
| Model retired, plugin removed, cache key rules changed | Replay still works. |
| Local runs | Out of scope (Q14). Future: upload a local frozen copy. |
