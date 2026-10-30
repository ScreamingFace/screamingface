# E14 redesign — frozen copy (supersedes the cache-version design)

**Status:** approved by the owner on 2026-10-08 · **Epic:** OME-1307
**Addendum 2026-10-12:** Q23–Q30 answer the owner's design review of the PR stack (2026-10-12). The
implementer approved them on 2026-10-12; the owner confirms them on the PR that adds this addendum.
Fix plan: `docs/plan/2026-10-06-e14-reproducible-submission/R-2026-10-12-design-review-fixes.md`.
**Supersedes:** `prd/gateway-cache-revision.md` (removed), and every part of `prd/cache-version-capture.md`,
`prd/reproduce.md`, `erd.md` and `contracts.md` that names a cache revision, `only-if-cached`,
`cache-revision`, `X-Cache-Replay` or the revisions endpoint. Where this file and an older file
disagree, this file wins.

## 1. Summary

A run **captures** only when the caller asks: `sf.evaluate(..., capture=True)` (Q22, reversed by
Q31: capture is off by default). The engine then opens a
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
| Q23 | Local capture (review item A, 2026-10-12) | A capture on the local runtime is `partial` with reason `local`. A hosted reproduction refuses it (`not_reproducible`). The upload step (Q14) stays a follow-up. |
| Q24 | Last-edit time (review item B) | Public. The score detail and the portal show `metadata_updated_at`. The edit log stays owner and operator only (Q10). |
| Q25 | Replay access on private boards (review item 1) | Q16 stands. The copy id is a bearer secret: a private board never returns it to a non-owner. No replay grants. |
| Q26 | Trust in web-tool results (review item 2) | "Exact" means internally consistent. The copy stores tool results as the engine run reported them. Hardening (an engine service identity for copy writes) is a follow-up. |
| Q27 | Replay key (review item 5) | Each call is keyed by `(case key, kind, request digest, occurrence)`. The case key names the case and its Attempt (OME-1458). The occurrence counts the earlier logical calls of the same request in the same case key. It is fixed when the call is first sent and never given back. Replay reads that exact key. Replaces the §4.4 "nth success" rule, the interim stated-slot rule (`91b352d7b`, `3e5ee45eb`) and the D2 forgiveness rule. |
| Q28 | Provenance (review item 6) | At seal the engine sends its version. The gateway stores it on the copy. Upgrade-safe replay is a follow-up. |
| Q29 | Per-case exact (review item 3) | The SDK computes a case digest from the graded cases. The board stores it at submit and compares it on reproduction. |
| Q30 | Tavily retrieval cache (found in the review) | The cache key includes the caller's account. Cross-account sharing stops until the engine has a service identity. |
| Q31 | Capture default (2026-10-29) | Reverses Q22. Capture is off by default; it is on only when the caller passes `capture=True`. |
| Q32 | Exact replay is not partial (2026-10-29, OME-1775) | Narrows Q27's "no outcome is forgiven". A no-answer outcome (`error`, or `failed`/`refused`/`missing` on a non-2xx last response) is not counted when its Case's final result is not scored for any Candidate, the Case did not fail on time (a time-based failure code), and no later call of the same lane, digest and case key gave an answer. A `max-age` re-issue with a 2xx last response takes that response's status. A connect-phase transport failure is `error`, not `ambiguous`. Every other outcome keeps Q27. Spec: `docs/spec/2026-10-29-OME-1775-cancelled-call-not-partial.md` §4. |

## 3. Data model (AI Gateway, new)

Core module `aigateway.core.frozen_copy` (registered in the Tortoise model list), one migration.

**`frozen_copies`**

| Column | Type | Rule |
|---|---|---|
| `id` | UUID pk | Made by the gateway. |
| `account` | FK → `Account`, `CASCADE` | The account that opened the copy. Only it may write or seal. |
| `status` | `open` \| `sealed` | `open` on create; `sealed` is final. |
| `entries` | int | Count, set at seal. |
| `entry_seq` | int | The counter that gives each new entry its `seq`. Incremented under the copy-row lock. |
| `provenance` | JSON, nullable | Set at seal (Q28): `{"engine_version": "<string>"}`. Null when the seal sent none. |
| `created_at`, `sealed_at` | datetime | |

**`frozen_copy_entries`**

| Column | Type | Rule |
|---|---|---|
| `id` | UUID pk | |
| `frozen_copy` | FK → `frozen_copies`, `CASCADE` | |
| `kind` | `chat` \| `tool` | |
| `case_key` | varchar(32), not null, default `""` | Q27. 32 lowercase hex chars, or `""` for a call outside any case. |
| `occurrence` | int ≥ 0, not null, default 0 | Q27. The logical-call number of this request in this case key. |
| `request_digest` | char(64) | sha256 (see §4.1). Index `(frozen_copy, kind, case_key, request_digest, occurrence, seq)`. Not unique: every transport attempt of one logical call is stored. |
| `request_json` | JSON | The digested request (chat body or tool description). |
| `response_json` | JSON | Chat success: the body returned to the caller. Chat error: `{"detail": ..., "headers": {"Retry-After": "<value>"}}`; `headers` is present only when the live error had `Retry-After`. Tool: `{"result": "<string>"}`. |
| `status_code` | int | 200 for a success; the HTTP status of a captured error. |
| `seq` | int | Capture order inside the copy, from `entry_seq`. Unique per copy (`unique (frozen_copy, seq)`), so a broken row lock fails loudly. It defines "latest" in §4.4. |
| `created_at` | datetime | For information only. The clock is never the order. |

Invariants:
- **F1.** Rows are insert-only. A sealed copy accepts no insert.
- **F2.** Copies and rows are kept forever (Q15). No list endpoint returns stored requests.
- **F3.** One entry is at most `frozen_copy_max_entry_bytes` (request plus response JSON). Its default is
  `max_request_bytes` plus a 2 MiB response headroom, 10 MiB with the 8 MiB request cap (OME-1756; it was
  2,000,000 bytes, which refused picture Cases). That fits every picture Case we run (MMMU's largest is
  3.78 MB), with two exceptions: a provider response over the 2 MiB headroom (the local and remote-endpoint
  transports cap a response at 1,000,000 bytes; cloud providers have no byte bound), and a request that grows
  when re-serialised (the request cap counts wire bytes, the entry counts re-serialised JSON, and Python
  writes `1e9` as `1000000000.0`: a body of such numbers measured 3,400,175 bytes on the wire and 11,050,175
  bytes stored). A larger entry is not stored and is reported as `failed`; the call still answers the caller.

## 4. AI Gateway behaviour

### 4.1 Request digest

`request_digest = canonical_digest({"kind": kind, "request": request})` with the existing
`core/request_cache/canonical.py` helper.
- **chat:** `request` is the body after the `cache` control is popped and the gateway-level dispatch
  controls are stripped (`chat.py`, the body at the step before provider lookup). The replay endpoint
  applies the same two steps, so the same request gives the same digest.
- **Attempt (OME-1458, `1e635c5e0`):** when the `cache` control names Attempt 2 or later, the digest
  input also has `"attempt": N`. This is true also with an opt-out (`"use-cache": false`), which keeps
  the number. Attempt 1 digests as before. The case key (§5.4) also names the Attempt, so two Attempts
  never share a key, even if a malformed `cache` object drops the number from the digest.
- **tool:** `request` is the tool description the engine sends (§4.4).

### 4.2 Capture on `/v1/chat/completions`

- Request headers `X-AIGW-Frozen-Copy: <copy id>`, `X-AIGW-Case-Key: <case key>` (absent = `""`) and
  `X-AIGW-Call-Occurrence: <n>` (Q27).
- Before the cache stage, the gateway checks the copy: it exists, it belongs to the caller's account, and
  it is `open`. It also checks the two key headers: the case key is `""` or 32 lowercase hex chars, and
  the occurrence is present and is 1 to 9 ASCII digits (no sign, no space). If any check fails, the call
  is served as usual and nothing is stored (`refused`).
- `stream: true` is never captured (`refused`): the gateway has no assembled body for a stream.
- After the final response is ready (a cache hit or a live success), the gateway inserts one entry with
  status 200 and the body it returns. A provider or dispatch error that ends the call (an
  `HTTPException` after the copy check) is captured too, with its status, `detail` and `Retry-After`
  (when the live error had one). Gateway refusals before the copy check (bad JSON, bad shape, unknown
  provider) are not captured.
- A client disconnect (499) is not captured: no client received that response. The outcome is `failed`.
- The insert is awaited, and a failure never fails the call (best effort, Q18).
- Response header `X-AIGW-Capture: stored | failed | refused` on every call that sent the request
  header (also on the error responses).

### 4.3 Frozen-copy endpoints (all need the usual account auth)

| Route | Who | Result |
|---|---|---|
| `POST /v1/frozen-copies` | any account | 201 `{"id", "status": "open"}` |
| `POST /v1/frozen-copies/{id}/seal` | owner | Optional body `{"provenance": {"engine_version": "<1–64 chars>"}}`; no body, `{}` or `{"provenance": null}` stores no provenance; another key or a bad value → 422. 200 `{"id", "status": "sealed", "entries"}`. Idempotent: a repeat seal keeps the first provenance. Not the owner or unknown → 404. |
| `POST /v1/frozen-copies/{id}/tool-results` | owner, copy `open` | Key headers as in §4.2 (bad → 400 `malformed_call_key`). Body `{"description": {...}, "result": "<string>"}` → 200 `{"outcome": "stored" \| "failed"}`. Sealed → 409 `frozen_copy_sealed`. |
| `POST /v1/frozen-copies/{id}/chat/completions` | anyone (Q16), copy `sealed` | Replay. Key headers as in §4.2 (bad → 400 `malformed_call_key`). Same request and response shape as `/v1/chat/completions`. |
| `POST /v1/frozen-copies/{id}/tool-results/lookup` | anyone, copy `sealed` | Key headers as in §4.2 (bad → 400 `malformed_call_key`). Body `{"description": {...}}` → 200 `{"result": "<string>"}`. |

The copy id is a bearer secret (Q25). The gateway never logs it next to request or response content.

### 4.4 Replay rules

- The copy must exist and be `sealed`; else 404 `{"code": "frozen_copy_unavailable"}`.
- The caller sends `X-AIGW-Case-Key` and `X-AIGW-Call-Occurrence` (Q27, same rules as §4.2).
  `X-AIGW-Replay-Occurrence` is removed.
- Lookup among the entries with the same `(copy, kind, case_key, digest, occurrence)`:
  1. the latest successful entry (status 200, highest `seq`);
  2. if there is no successful entry: the latest captured error with its status, `detail` and stored
     `Retry-After` (sent again as a response header);
  3. if there is no entry: 404 `{"code": "frozen_copy_miss"}`. There is no fallback to another
     occurrence or another case key.
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
2. Every chat call adds `X-AIGW-Frozen-Copy: <id>` and the call key (§5.4), and records the
   `X-AIGW-Capture` value (no header → `missing`, for an older gateway).
3. Every web-tool call: after `_execute_tool` returns its string (before truncation), `POST
   …/tool-results` with the call key, the description and the string, and record the outcome. This
   covers success, "no results" and failure strings alike: the copy stores exactly what the model saw.
4. At run end, `POST …/seal` with `{"provenance": {"engine_version": <installed screamingface-engine
   version>}}` (Q28). On failure the run is `partial` (reason `seal`).
5. **Rule:** `capture.status = complete` only when the open and the seal worked, every chat and tool
   outcome is `stored` or forgiven, and the run is not on the local runtime. Anything else is
   `partial`. Q27 removes D2: a call that left no entry at its key would be a replay miss. Q32 forgives
   only a no-answer outcome (`error`, or `failed`/`refused`/`missing` whose last response was not 2xx)
   that meets all three of these conditions:
   - Its Case's final result (after the Attempt fold) is not scored, and the Case scored for no
     Candidate in the run.
   - Its Case did not fail on time: no failure of the Case, or of one of its Attempts, has a
     time-based code or `source_code` (a timeout or a deadline). A replay serves stored answers at
     once, so it may score such a Case.
   - No later call with the same lane, request digest and case key, at a higher occurrence, gave
     the model an answer.

   A replay of such a Case misses or never sends the call, and the Case fails again either way. A
   no-answer outcome in a scored Case, or outside any Case, is never forgiven.
6. Run summary attributes: `capture.frozen_copy_id`, `capture.status`, and
   `capture.partial.<reason>` counts (`failed`, `refused`, `missing`, `open`, `seal`, `error`,
   `ambiguous`, `local`). A forgiven outcome (Q32) is not counted. A capture run always writes them,
   even with no model call and also when the run fails.
7. **`ambiguous` (pinned 2026-10-08, B3 review):** in capture mode, a call that the engine re-issued under a
   `max-age` bound, or a call whose transport attempt was retried, may leave a stored answer the model never
   used ahead of the one it used. Such a call records `ambiguous`, which is never forgiven, so the run is
   `partial`. A call whose every transport attempt lost its reply is `ambiguous` too (#1332 review).
   Q32 narrows this:
   - A `max-age` re-issue whose last response is 2xx takes that response's `X-AIGW-Capture` status.
   - A transport failure in the connect phase (`ConnectError`, `ConnectTimeout`, `PoolTimeout`) sent
     no request byte, so the gateway stored nothing for that try. It does not make the call
     `ambiguous`; if every try failed that way and the call read no 2xx before, the call is
     `error`.
   - A call that read a 2xx response and then did not return stays `ambiguous`. Examples: its
     `max-age` re-issue failed in the connect phase on every try, had no deadline left, or was
     cancelled. The copy holds a 200 that the model never used, and a replay serves it.
8. **`local` (Q23):** a capture on the local runtime (`create_local_app`) counts `capture.partial.local =
   1`. Its copy lives only in the local gateway, so a hosted board can never replay it.

### 5.3 Replay mode

1. Every chat call goes to `POST /v1/frozen-copies/{id}/chat/completions` with the call key (§5.4).
1a. Replay skips the engine's model-admission check (`/v1/models/admit`), so a retired model still
   replays.
2. A found success is used as usual and accounted as $0 (like a cache hit). A captured error is raised as
   usual, so the case fails the same way as in the original run. A 404 `frozen_copy_miss` fails the case
   with `frozen_copy_miss`; a 404 `frozen_copy_unavailable` fails it with `frozen_copy_unavailable`.
2a. A failure that the copy did not serve is permanent and fails the case with
   `frozen_copy_unavailable`, with no higher-level retry. This covers a call whose every transport
   attempt failed, a gateway answer without `X-AIGW-Replay`, and a tool lookup with a transport error
   or a 200 answer whose body is not a valid result. A `frozen_copy_miss` is permanent too (no retry).
   Transport attempts inside one logical call still reuse its occurrence. Reason: the occurrence is
   never given back (§5.4), so a retry would read the next occurrence and replay the wrong entry.
3. No `max-age` re-issue and no cache controls in replay mode.
4. Web-tool calls never call Tavily: the engine calls `…/tool-results/lookup` with the call key (§5.4).
   A miss fails the case with `frozen_copy_miss`.
5. The run summary always carries `capture.replay = <id>`.
6. Failure codes `frozen_copy_miss` and `frozen_copy_unavailable` are declared in the engine
   (`error_text.py`, `benchmarks/contract.py`) and in the SDK mirror (`_report_primitives.py`).

### 5.4 Call key (Q27)

The engine sends the same key in capture and in replay, so both runs name each call the same way.

- **Case key:** the first 32 hex chars of
  `sha256(json.dumps(["case", case_id, attempt], separators=(",", ":")))`, where `attempt` is
  `current_case_attempt()` or 1 (OME-1458). The case id comes from `case_scope` for a candidate call.
  For a grading or judge call it comes from the grading case when the engine can resolve it. Otherwise
  the case key is `""`.
- **Occurrence:** the run tally keeps a counter per `(case key, kind, request digest)`. A logical call
  takes the next value when it is first sent. Every transport attempt of that call sends the same value.
  The value is never given back, in capture or in replay. A gathered group of calls takes its values in
  task-creation order, before the first `await` of each task.
- **Tool calls:** the occurrence is taken before `_execute_tool` runs, not when the result is stored.
  So capture numbers identical tool calls in send order, the same order that replay uses.
- A higher-level retry (a new logical call) takes a new occurrence. In replay, the captured error of the
  first call comes back, so the same retry happens and takes the same next occurrence.
- A `max-age` re-issue stays `ambiguous` (§5.2 item 7), on purpose. "Latest success" would serve the
  re-issued answer, but we keep the strict rule until a run shows that this costs too many `complete`
  captures.

## 6. Scoreboard behaviour

- `Score` columns `frozen_copy_id` (UUID string, nullable) and `capture_status` (`complete` |
  `partial`, nullable) replace `cache_revision` and `reproducible`. `answer_seed` stays. All three are
  fill-only on a same-owner resubmit. `frozen_copy_id` requires `capture_status`.
- `score_reproductions.frozen_copy_id` replaces `cache_revision`.
- `Score.case_digest` (64 lowercase hex, nullable, Q29): it requires `capture_status`. It fills on a
  same-owner resubmit only together with the status and the copy id, because all three must describe
  the same run. The content hash does not cover the cases, so a different run can dedup to the same
  row. The score read returns it (omitted when null). Leaderboard and history rows carry no capture
  fields, so they do not return it.
- `POST /v1/scores/{id}/reproductions`: the score must have `capture_status = complete` (else 409
  `not_reproducible`); the body's `score`, `total_questions` and `frozen_copy_id` must equal the stored
  values (else 422 `not_exact`). When the score has a `case_digest`, the body must carry an equal
  `case_digest` (else 422 `not_exact`; the message names the digest). Everything else is unchanged.
- The score read is public on a public board, so it shows `metadata_updated_at`, and the portal shows
  "Metadata edited <date>" next to the paper link (Q24).
- A private board never returns `frozen_copy_id` to a non-owner (Q25).

## 7. SDK behaviour

- `evaluate(..., capture: bool = False)` (sync, async, module level). Capture is off by default
  (Q31). `True` sends `X-Capture: true`. `False` (the default) sends no header. `sf.reproduce` never sends
  `X-Capture`.
- `CandidateResult.frozen_copy_id` and `capture_status` (from the run summary; absent → `None`).
- `CandidateResult.capture_partial_reasons: tuple[str, ...]`: the `capture.partial.<reason>` names with a
  non-zero count, sorted (empty when complete or not captured). A local capture shows `("local",)`.
  `to_dict()` always includes it, as a list. A count that is not a non-negative integer fails closed
  (`ExecutionError`, like the cache-hit count).
- **Case digest (Q29):** for each case in `CandidateResult.cases`, the entry
  `[case_id, status, score]`, where `score` is `grade.score`, or `null` only when the case has no grade
  (a score of 0.0 stays 0.0). Serialize each entry with `json.dumps(entry, separators=(",", ":"))`. Sort
  the strings, join them with `"\n"`, and take the sha256 hex. It is not a public attribute of
  `CandidateResult`.
- `submit` sends `frozen_copy_id`, `capture_status`, `answer_seed` and `case_digest` when set.
- `LeaderboardScore.frozen_copy_id`, `capture_status` replace `cache_revision`, `reproducible`.
  `LeaderboardScore.case_digest: str | None` (64 lowercase hex, needs `capture_status`, validated like
  `frozen_copy_id`). Only the score read carries it; leaderboard rows (`LeaderboardEntry`) carry no
  capture fields.
- The reproduction record always sends the replay's `case_digest`. The board compares it only when the
  score has one (§6) and does not store it.
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
| failed | `cases_differ` | Score and count are equal, the score has a `case_digest`, and the replay's digest differs. |
| exact | — | Recorded with `frozen_copy_id` and the replay's `case_digest` when `record=True`. |

The board does not store the partial reasons, so `sf.reproduce` cannot name them: a local capture is
`not_reproducible` with reason `partial`, like any partial capture. The reason `local` shows only on the
submitter's own `CandidateResult.capture_partial_reasons` (Q23).

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
- **B2 (Tavily cache through the gateway):** it still saves money on normal runs; it is no longer
  needed for reproducibility. Q30: the cache key includes the caller's account, so one account can never
  fill a row that another account reads.

## 9. Edge cases

| Case | Behaviour |
|---|---|
| Cache hit vs live call | Both captured the same way (the body returned to the caller). |
| Transport retry after a 429/5xx | Every attempt is captured under the same call key. Replay returns the latest success at that key. A retried attempt makes the call `ambiguous`, so the run is `partial`. |
| Final error (the case failed) | Captured with its status and `detail`; replay returns it, so the case fails the same way. |
| Identical requests, different answers (sampling, cache off) | Each logical call has its own key (Q27), so concurrent cases never swap answers. Inside one case, concurrent identical calls take their occurrences in task-creation order. |
| Replay call lost on the way to the gateway, then retried as a new logical call | The retry takes the next occurrence, which the capture run did not use → a miss or another answer → `failed`. A false "failed", never a false "exact". |
| Same prompt in two cases | Different case keys, so each case gets its own answer. |
| Provider-native web search | Inside the chat response, so captured with it. |
| LLM judges | Through the gateway, so captured. |
| Streaming request under capture | Not captured (`refused`) → the run is `partial`. |
| Capture insert fails | The call is served; `failed` → the run is `partial`. |
| Gateway older than B1 | No `X-AIGW-Capture` header → `missing` → `partial`. A replay gets 404 on the replay route → `frozen_copy_unavailable`. |
| Engine crashes mid-run | The copy stays `open`; replay refuses it (`frozen_copy_unavailable`). |
| Replay of a run that offered no web tools (no Tavily connection) on an engine that offers them | The request bodies differ → `frozen_copy_miss`. Known limit. |
| Different engine/SDK version renders prompts differently | Different digests → `frozen_copy_miss`, visible. The copy keeps the engine version (Q28) so a follow-up can make our own upgrades safe. |
| Model retired, plugin removed, cache key rules changed | Replay still works. |
| Local runs | Capture is `partial` with reason `local` (Q23). Future: upload a local frozen copy. |
| A submitter posts a made-up tool result to an open copy | Stored; a replay is still exact (Q26). Follow-up: only the engine's service identity may write. |

## 10. Follow-ups from the 2026-10-12 review (not in E14)

- **FU-1:** an engine service identity for copy writes (open, tool results, seal) and Tavily fills.
- **FU-2:** deleting copies: owner and operator delete; `delete_scores` and the private-board purge also
  delete copies; a tombstone answers 410 `frozen_copy_deleted` and marks the score; a TTL removes
  unsealed copies; reconcile Q15 with the account CASCADE.
- **FU-3:** consistency across runs of one url4 over time (OME-1319).
- **FU-4:** upgrade-safe replay from `provenance` (match by call position, or replay on the engine
  version that captured the copy).
- **FU-5:** upload a local frozen copy to the hosted gateway (Q14, Q23).
- **FU-6:** grading calls carry the Attempt they grade. Today `case_attempt_scope` opens only around the
  candidate call, so judge calls for Attempts 1..k of one case share a case key. When identical judge
  bodies run at the same time, replay can swap their verdicts. Also pin that the engine's counter
  digest never keeps a field the gateway digest strips, except the Attempt number.
