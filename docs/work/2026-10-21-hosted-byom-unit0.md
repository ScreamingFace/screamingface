---
ticket: OME-1712
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-21
finished: 2026-10-22
---

# hosted-byom-unit0 — configured remote-endpoint instances: compatibility proof

## Intent

First bounded slice of hosted bring-your-own-model endpoints in the AI Gateway: prove that an
operator-approved endpoint configuration becomes ordinary provider instances that reuse the
existing Connections, admin key lifecycle and encrypted credential store, with each
`(account, endpoint)` pair isolated. This is a compatibility spike, not a production feature:
no catalog listing, shared-cache projection, guarded egress, Engine, UI, Helm or hot reload.
Decisions come from the owner-held planning pack, kept local by the owner's instruction (not
copied into `docs/spec`/`docs/plan`); the owner approved implementation of this slice directly.

## Planned changes

- `apps/aigateway/src/aigateway/config.py` — optional `AIGW_REMOTE_ENDPOINTS_CONFIG` path.
- `apps/aigateway/src/aigateway/core/endpoint_access.py` — core policy port: operations, the
  default permit policy and the one lookup helper the I/O entry points use.
- `apps/aigateway/src/aigateway/provider_composition.py` — top-level composition: bundled
  plugins stay as loaded; configured instances are validated as a whole, collision-checked and
  registered; returns the policy.
- `apps/aigateway/src/aigateway/plugins/remote_endpoint/` (no `PLUGIN`, outside `*_provider`
  discovery): `definitions.py` (schema v1 validation into immutable definitions plus a separate
  grant view), `reader.py` (bounded TOML file reader), `policy.py` (grant policy adapter),
  `plugin.py` (instance per endpoint), `transport.py` (minimal chat POST), `validation.py`
  (readiness probe).
- `apps/aigateway/src/aigateway/main.py` — call composition after `load_plugins`, before the
  auth-router loop; store the policy on `app.state`.
- Grant check at the entry points that can reach an upstream: `routes/admin_connections.py`
  (PUT, target account), `routes/oauth_connections.py` (self create and replace),
  `routes/api_key_validation.py` (standalone validate), `routes/chat.py` (dispatch). Admin and
  owner DELETE stay unchecked so cleanup survives disable/revoke.
- No schema/model change, so no migration (S1 not triggered). No new dependency (`tomllib`).
- `migrate_profiles.py` unchanged.

## Test plan

New tests under `apps/aigateway/tests/unit/remote_endpoint/`:

- Definitions: accept the selected schema; reject unknown fields at every level, unknown
  version, superseded `base_url`/`models`/`classifiers`, bad IDs, non-HTTPS/non-443/path/userinfo/
  query/fragment/IP/uppercase origins, unsafe request paths, bad aliases, missing upstream model,
  unsupported task/contract, duplicate IDs/aliases/accounts, invalid UUIDs, missing validation
  target, empty targets; diagnostics never echo input values.
- Reader: unset means none; oversized (>1 MiB), non-UTF-8, invalid TOML and unreadable paths
  fail with sanitized errors; TOML and in-memory fixtures yield equal definitions, grants and
  built-instance facts (provider ID, outgoing URL/model, credential service).
- Composition: no config leaves the registry and auth routers unchanged; a bundled-ID collision
  or duplicate registers nothing; two instances of one adapter coexist.
- App-level (real `create_app`, isolated SQLite store, two pre-created accounts, fake HTTP
  transport, real validation service): admin PUT attach for both pairs; probes and dispatch hit
  the exact origin+path with the exact bearer; failed replacement keeps the old key; DELETE of
  one pair leaves the others; concurrent dispatch and readiness checks keep pairs separate;
  ungranted account and disabled endpoint get zero upstream I/O on PUT, self create, validate and
  chat; after restart with a revoked grant, chat sends nothing and admin DELETE still succeeds;
  no-key chat sends nothing.
- Regressions: legacy backfill leaves BYOM markers/rows/blobs untouched; no `core/` module
  imports `aigateway.plugins`; only composition imports `plugins.remote_endpoint`.

## Acceptance

- Tests distinguish `(account A, endpoint A)`, `(account A, endpoint B)` and
  `(account B, endpoint A)` under overlapping requests and key replacement.
- All aigateway card gates green; prior tests unmodified.
- Nothing staged, committed or pushed until the owner allowed it (owner instruction for this
  slice). The owner allowed commit, push and PR on 2026-10-22, after the sixth review.

## Review fixes (2026-10-21, second iteration)

The owner's review of the first iteration found two defects; both are fixed in this unit.

1. **Chat grant check before the shared cache.** The agreed contract keeps the cache common
   and adds no pre-cache authorization; the grant restricts NEW upstream calls only. Planned:
   chat restores the plain registry lookup, and the INVOKE grant is checked at the start of the
   miss/bypass stage, before credential resolution and dispatch. A denial keeps the existing
   unknown-provider refusal. `core/endpoint_access.py` gains a boolean check that the lookup
   helper reuses. Tests: a granted account's miss is stored; an ungranted account without a
   key gets the hit with no new upstream request; its miss and its bypass are refused with no
   upstream request. The test gives the instance a test-only pure projection, because the
   production projection is Unit 1 work.
2. **Readiness accepted a malformed completion.** `choices: [null]`, `[42]`, `[{}]` and a
   non-object `message` were VALID. Planned: one structural check of the
   `openai-chat-basic-v1` response (`plugins/remote_endpoint/completion.py`) used by both
   readiness and dispatch. Tests: malformed 200 bodies are UNAVAILABLE in readiness and 502 in
   dispatch; an empty or null content stays valid; an admin replacement answered by a malformed
   200 is refused, and the old key is kept and still serves chat.

## Review fix (2026-10-21, third iteration)

3. **Readiness and dispatch decoded the response under different rules.** Readiness read the
   shared session's lenient `json.loads` payload with no Content-Type, finiteness or structure
   bounds, while dispatch required all three. A well-formed completion served as `text/html`,
   with `NaN` in `usage`, or with metadata deeper than the bound was VALID in readiness and 502
   in dispatch; the owner reproduced an admin replacement that published such a key. Planned:
   one BYOM decoder, `completion.decode_completion(content_type, body)`, owning Content-Type,
   strict finite JSON, depth and node bounds and the completion shape; dispatch and readiness
   both call it on the raw response. The shared `BoundedJsonResponse` gains two defaulted
   fields, `content_type` and `body`, so readiness can see what dispatch sees; other providers
   ignore them and their rules do not change. Readiness keeps its stricter size and time budget.
   Tests: the three cases in both branches; a parity table where readiness VALID holds exactly
   when dispatch succeeds; an admin replacement answered with the wrong Content-Type is refused,
   and the old key is kept and still serves chat.

## Review fixes (2026-10-21, fourth iteration)

A further review reproduced eight findings; the owner chose to fix six in this unit (4–9 below)
and to leave two out: the httpx request log is off in the shipped logging setup and belongs with
the guarded transport in Unit 1, and removing an endpoint from the config is outside the plan's
retirement procedure (delete Connections while registered, then disable, keep the ID reserved).

4. **A kept ID with a new origin sent the stored key to the new origin.** The plan forbids
   rebinding old credentials to another destination. Planned: the instance's API-key strategy
   (plugin-local subclass of the core strategy) writes the origin into the encrypted blob beside
   the key and refuses a blob whose origin differs or is absent, as a missing key. Tests: after
   a restart with the same ID and a new origin, chat sends nothing; an admin replacement
   validates the new key on the new origin and then serves; an admin DELETE still removes the
   pair; removing the ID and adding it back with another origin also sends nothing.
5. **A compressed response was decompressed before the size bound.** Planned: dispatch asks for
   `identity` encoding and refuses any other `Content-Encoding` before reading, as readiness
   does. Tests: a gzip answer is refused without its body being read; an `identity` answer
   still serves.
6. **Readiness probed a request shape dispatch never sends, and dispatch could not carry
   `max_tokens`.** The plan's chat contract is text messages plus `max_tokens`. Planned: one
   request builder used by both branches, and a `max_tokens` parameter rule with the shared
   integer schema and `bypass` cache behavior (the cache projection is Unit 1 work). Readiness
   sends the builder's request with `max_tokens` 1 and no `stream`. Tests: the probe body equals
   the builder's; dispatch forwards a valid `max_tokens`; an invalid one is refused before any
   upstream call.
7. **Message content was not checked against the text-only contract.** Planned:
   `prepare_chat_body` refuses media and unknown parts through the shared `check_messages`, and
   any message that is not a `system`, `user` or `assistant` message with only `role` and a text
   `content`, before credentials are read. Tests: each refused shape gets 422 with no upstream
   call, even for an account with no key; a plain text conversation is forwarded unchanged.
8. **The decoder accepted a non-text `finish_reason` and non-count `usage` values.** Planned:
   the shared decoder also requires `finish_reason` to be text or null and the three token counts,
   when present, to be non-negative integers. Tests: new rows in the response-contract table,
   refused by both branches; well-formed metadata still accepted by both.
9. **Dispatch copied an unbounded numeric `Retry-After`.** Planned: the value passes the core
   bound before it is forwarded. Tests: an oversized or zero value is dropped; a valid one kept.

## Review fixes (2026-10-21, fifth iteration)

A fifth review confirmed the two High findings closed and raised five more. The owner chose to
fix all five in this unit: readiness probes the ordinary request shape, and the plaintext error
body is fixed in the shared core session.

10. **Readiness probed with `max_tokens` 1, which an ordinary chat does not send.** An endpoint
    that requires `max_tokens` passed attach and then refused ordinary chat. Planned: the probe
    sends `chat_request(target, PING)` with no optional field, the request an ordinary chat
    builds. Tests: two prior expectations change with the owner's approval (`test_readiness`
    and `test_request_contract` no longer expect `max_tokens` in the probe); a new app-level
    test attaches a key and sends an ordinary chat, and the two upstream bodies are equal. The
    fake upstream's probe flag was derived from `max_tokens`; it now comes from a transport
    the harness gives only to the validator, so the assertions that use it are unchanged.
11. **A completion carrying `error` was accepted.** Planned: the shared decoder refuses a
    non-null `error` at the top level or inside any choice, so readiness is UNAVAILABLE and
    dispatch 502. Tests: refused rows in the parity table; null `error` rows still accepted;
    the 502 echoes no upstream text.
12. **Readiness accepted only 200, dispatch any 2xx.** Planned: dispatch also accepts exactly
    200; any other status goes through the same upstream-error mapping. Tests: 201, 202, 203
    and 206 with a valid completion are refused by both branches, dispatch with 502.
13. **Token counts had no upper bound.** Planned: a count above `2**53 - 1` is refused, the
    bound the gateway's usage accounting already uses, kept local because plugins do not import
    each other. Tests: `2**53 - 1` accepted; `2**53` and a 1001-digit count refused by both.
14. **A plaintext error body hid the status from readiness classification.** The shared session
    parsed JSON before any provider saw the status, so a plaintext 429 became UNAVAILABLE and
    lost its Retry-After. Planned: in `core/api_key_validation_http.py`, a body that is not JSON
    on a non-2xx response yields `payload = None`, as an empty body does; a 2xx body that is not
    JSON still raises. Blast radius: Anthropic, Gemini and OpenAI need structured error evidence
    and keep UNAVAILABLE; Hugging Face and OpenRouter classify by status, so a plaintext error
    now gets the same state as an empty one. Tests: core rows for plaintext and too-deep error
    bodies, a non-JSON 2xx still raising, and BYOM readiness turning a plaintext 429 into
    RATE_LIMITED with the hint.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Modified: `config.py`, `main.py`, `routes/admin_connections.py`,
  `routes/oauth_connections.py`, `routes/api_key_validation.py`, `routes/chat.py`,
  `core/api_key_validation_http.py` (third iteration). New:
  `core/endpoint_access.py`, `provider_composition.py`, `plugins/remote_endpoint/` (`__init__`,
  `definitions`, `reader`, `policy`, `plugin`, `transport`, `validation`, `completion`, and in
  the fourth iteration `credential`, `request`), and `tests/unit/remote_endpoint/` (`conftest`,
  `fixtures`, `test_definitions`, `test_reader`, `test_policy`, `test_plugin`,
  `test_readiness`, `test_composition`, `test_app_isolation`, `test_app_access`,
  `test_app_regressions`, `test_app_cache_order`, `test_response_contract`, and in the fourth
  iteration `test_origin_binding`, `test_request_contract`, `test_transport_bounds`).
  `migrate_profiles.py` unchanged. No schema change, no migration, no new dependency. The
  fourth iteration changes no core module. The fifth iteration modifies `completion.py`,
  `transport.py`, `validation.py`, the `request.py` docstring and the core module
  `core/api_key_validation_http.py`; in tests `fixtures`, `conftest`, `test_readiness`,
  `test_request_contract`, `test_response_contract`, and it appends six cases to the prior core
  test `tests/unit/test_api_key_validation_http.py`.
- **Commits:** none until the owner allowed commit, push and PR on 2026-10-22. Then
  `feat(aigateway): serve configured remote endpoints as provider instances` holds the unit,
  and a second commit holds the two approved test lines, the approval file, the task mirror
  and this ledger. The branch is `OME-1712-remote-endpoint-instances`.
- **Gates (after the fifth iteration):** `run_gates.py aigateway` gave ALL GATES GREEN on the
  first attempt. A separate run of the same pytest command: 6309 passed, 103 skipped, 0 failed;
  total coverage 93.82%. BYOM tests: 296 passed; core session tests: 32 passed. New code
  coverage 100% (481 statements under `plugins/remote_endpoint`, `core/endpoint_access.py` and
  `provider_composition.py`); the new lines in `core/api_key_validation_http.py` are covered.
  Every fifth-iteration test ran RED first: 23 failures, each for the reason it targets.
  `git diff --check` clean; 0 files staged.
- **Sixth review:** READY for Unit 0, no findings. A review in between reported the five
  fifth-iteration findings again against the code before the fix; a script replaying its exact
  scenarios on the current bytes and a fresh `run_gates.py aigateway` showed them closed, with no
  code change. The sixth reviewer also ran the full gate with `--base 2de320a8c`: green.
- **Branch state at the sixth review:** 69 commits behind `origin/main`. A merge of the tracked
  changes onto `origin/main`, built without touching the branch, index or stash list, is clean.
  Main changed two of the modified files, `main.py` (legacy bootstrap and profile index removed,
  a cache-entries router added) and `oauth_connections.py` (one docstring); it changed none of
  the core contracts the adapter uses, and the new code references no removed name. Before a
  PR: move the work onto current main and rerun the full gate against that base.
- **Rebase and PR (2026-10-22):** filed as OME-1712 under OME-1306. The unit was committed and
  rebased onto `origin/main` twice, last onto `40908acdd`; both rebases were clean. Main brought
  three changes that touch this unit:
  - E4c (#1523) added a guard test that requires one `OVERRIDES` row per provider plugin.
    `RemoteEndpointPlugin` gets the row `set()`, since it overrides none of the four neutral
    hooks. Without it, two guard tests fail.
  - The Codex change (#1441) added `configure_discovery` to the plugin base with a no-op
    default. The plugin inherits it; it opens no discovery connection outside the runtime.
  - The same Codex change merged after E4c and still called the retired hook name in
    `test_codex_plan_unsupported.py`, so `main` failed Pyright and that test, in CI as well as
    locally. The call now uses `should_mark_credential_error_on_dispatch_status`.
  Both one-line edits to prior tests are owner-approved in
  `.claude/test-change-approvals/OME-1712.json`, which pins each file's blob before and after.
  `main.py` and `config.py` merged without conflict.
- **Gates against `40908acdd` (2026-10-22):** `run_gates.py aigateway --base 40908acdd` gave
  ALL GATES GREEN, with both approved test transitions accepted by the append-only check. A
  separate run of the same pytest command: 6532 passed, 109 skipped, 0 failed; total coverage
  93.89%. `AIGW_TEST_PG=1 pytest -m needs_postgres`: 64 passed, 5 failed; the five are the
  untouched cache snapshot upload tests, which fail because the local `pg_dump` 15 cannot dump
  the PostgreSQL 16 test container.
- **Gates (after the fourth iteration and the `credential_name` rename):** `run_gates.py
  aigateway` gave ALL GATES GREEN. The first full run of the fourth iteration had one failure,
  `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password` (timing
  difference 11.4% against a 10% tolerance under full-suite load; it passed 5 of 5 runs alone,
  and no auth code is touched); every later run was green. A separate run of the same pytest
  command on the final tree: 6281 passed, 103 skipped, 0 failed; total coverage 93.82%. BYOM
  tests: 274 passed; new code coverage 100% (478 statements under `plugins/remote_endpoint`,
  `core/endpoint_access.py` and `provider_composition.py`). `git diff --check` clean; 0 files
  staged.
- **Naming:** the owner asked whether the adapter package should be `remote_provider`. Kept
  `remote_endpoint`: a `*_provider` package is auto-discovered and must export one `PLUGIN`
  (`core/loader.py`), `test_registry_discovery_is_non_vacuous` counts those packages, and the
  design keeps this config-composed factory outside discovery. The owner agreed.
- **Gates (after the third iteration):** `run_gates.py aigateway` gave ALL GATES GREEN on the
  first attempt (append-only, ruff check, ruff format --check, pyright 0 errors,
  check_no_enterprise, pytest with coverage at least 80). Full suite: 6215 passed, 103 skipped,
  0 failed; total coverage 93.79%. BYOM tests: 208 passed. New code coverage 100% (390
  statements under `plugins/remote_endpoint`, `core/endpoint_access.py` and
  `provider_composition.py`); the two new lines in `core/api_key_validation_http.py` are
  covered. `git diff --check` clean. After the second iteration the same gates were green with
  6197 passed and 190 BYOM tests.
- **Review fixes, as done:**
  - Chat keeps the plain registry lookup before the cache stage, unchanged from the base. The
    INVOKE grant is checked inside `_resolve_credential_target`, which runs only on a miss or a
    bypass, before any credential is resolved. Placing it there keeps `chat_completions` at its
    base statement count. `core/endpoint_access.py` gained `permits`, reused by
    `accessible_plugin`; the other four entry points keep their checks.
  - Proven by `test_app_cache_order.py` against the real cache store: a granted account's miss
    is stored; an ungranted account without a key is served the hit with no new upstream call;
    its miss and its bypass are refused with zero upstream calls. The bypass refusal equals an
    absent provider's in status, body and headers. The miss refusal differs in one field only:
    the accounting block reports `cache.status: miss` where an absent provider reports
    `bypass`. That is the existing cache stage reporting its own outcome; hiding it would need
    a private-endpoint switch in the cache path, which the contract forbids.
  - The completion shape check (now private to `completion.py`) is the one structural check
    for readiness and dispatch: an object with a non-empty `choices` list; each choice an
    object with a `message` object; `role`, when present, `assistant`; `content` present, a
    string or null. Text is not required. Malformed 200 bodies are UNAVAILABLE in readiness and
    502 in dispatch; an admin replacement answered by one is refused with 503
    `api_key_validation_unavailable`, and the old key is kept and still serves chat.
  - The fake upstream now sends `finish_reason: "stop"`, as a finished answer does; the shared
    cache stores only finished answers. No prior assertion depended on its absence.
  - Third iteration: `completion.decode_completion(content_type, body)` is the one BYOM
    response decoder. It requires an `application/json` media type (parameters such as
    `charset` allowed), parses strictly with non-finite constants refused, applies the depth
    16 and 50,000 node bounds with finite numbers, then the shape check. Dispatch calls it on
    the bounded raw body; readiness calls it on the raw body the shared session now returns,
    instead of the session's lenient `payload`. Readiness stays stricter only in its own
    budget: 64 KiB, identity encoding, its time limits and exactly status 200. Proven by
    `test_response_contract.py`: 17 responses, each with a fixed expected verdict that both
    branches must return, including the three reproduced cases (`text/html`, `NaN` in
    `usage`, metadata 40 levels deep), all refused by both. An admin replacement answered with
    `text/html` is refused with 503 `api_key_validation_unavailable`; the old key is kept and
    the next chat succeeds with it.
  - Fourth iteration, origin binding (`credential.py`): `OriginBoundApiKeyStrategy` writes
    `origin` into the encrypted blob beside the key and serves the key only when the blob's
    origin equals the instance's, from one read. Any other blob, including one written before
    this change with no origin, is a missing key: 401 `auth_required`, no upstream call, the
    Connection not marked errored, and no origin in the message. Every attach and replacement
    path persists through the strategy, so only a validated replacement rebinds. Proven by
    `test_origin_binding.py`: a restart with the same ID and a new origin sends nothing and
    keeps the key; restoring the origin serves again; a replacement is probed and served on the
    new origin; admin DELETE still works after the move; removing the ID and adding it back
    elsewhere sends nothing.
  - Fourth iteration, encoding: dispatch sends `Accept-Encoding: identity` and refuses any
    other `Content-Encoding` with 502 before reading, exactly as readiness does. Proven with a
    body stream that records whether it was read.
  - Fourth iteration, request shape: `request.chat_request` builds the upstream body for both
    branches. Readiness sends `max_tokens` 1 and no `stream`; dispatch forwards `max_tokens`
    through a `direct_rule` with the shared integer schema and `bypass`. Proven: the probe body
    equals the dispatched body; `max_tokens` 5 is forwarded; 0, -1, `"5"` and 1.5 are refused
    with 400 `unsupported_parameters` and zero upstream calls.
  - Fourth iteration, text contract: `prepare_chat_body` calls `request.check_text_messages`.
    Media and unknown typed parts get the shared 422 `unsupported_content_part`; a text-part
    list, a `tool` or unknown role, `tool_calls`, an extra field, non-text content or an empty
    list get 422 `unsupported_message`, which echoes no value. Each costs no key read and no
    upstream call, proven with a spy on the store reads of a keyed account, whose positive
    control sees the read on a served text conversation.
  - Fourth iteration, metadata: the one decoder also requires `finish_reason` to be text or null
    and `usage` to be null or an object whose three token counts, when present, are
    non-negative integers, booleans excluded. Five refused and three accepted rows were added to
    the parity table; both branches agree on every row.
  - Fourth iteration, Retry-After: only an ASCII decimal of at most ten digits within
    `bounded_retry_after_seconds` is forwarded, as the normalized integer. Zero, 2147483648,
    1000 digits, a fraction and an HTTP-date are dropped for 429 and 503.
  - Alignment with OME-1209 Stage E (E4c, not merged at the time): the hook
    `api_key_strategy_for` takes `credential_name` as its first parameter, the name E4c gives
    it. Every current caller passes it by position, and pyright accepts the override against
    the current base, so nothing changes before E4c lands. A new test calls the hook with
    `credential_name=` by keyword; it fails on the old name with `TypeError` and passes on the
    new one. The plugin defines none of the four hooks E4c renames. The strategy constructor
    keeps `profile_name`, since it is not a hook.
  - Fifth iteration, probe shape: readiness sends `chat_request(target, PING)`, the request an
    ordinary chat sends with no optional field. Proven through the routes: an admin attach and
    an ordinary chat send equal upstream bodies with no `max_tokens`. The probe is bounded by
    the session's 64 KiB and time budget, not by a token cap.
  - Fifth iteration, decoder: a non-null `error` on the envelope or on any choice, or a token
    count above `2**53 - 1`, is refused by both branches; a null `error` and `2**53 - 1` are
    accepted. The parity table now has 33 rows; a refused completion is 502 `provider_error`
    and echoes no upstream text.
  - Fifth iteration, status: dispatch accepts exactly 200. A completion under 201, 202, 203 or
    206 is UNAVAILABLE in readiness and 502 `provider_error` in dispatch.
  - Fifth iteration, core: a non-2xx body that is not JSON, or nests too deeply, yields
    `payload = None` with status and Retry-After intact; a 2xx body that is not JSON still
    raises. BYOM readiness gives a plaintext 429 RATE_LIMITED with hint 30 and a plaintext 401
    INVALID, the same as empty bodies. Other providers: Anthropic, Gemini and OpenAI need
    structured error evidence, so their outcomes do not change; Hugging Face and OpenRouter
    classify by status, so a plaintext error now gets the state an empty one already got. Their
    results carry only state, stage, Retry-After and probe model; no body text.
- **Deviations:**
  - Grant checks also cover self create, self replace and standalone validate, not only admin
    PUT and chat. Those three can reach the upstream with a caller-supplied key, so leaving them
    open would let an ungranted account probe a private endpoint. A denial reuses each route's
    unknown-provider refusal.
  - The first iteration put the chat grant check before the shared cache stage. The owner's
    review showed that this contradicts the agreed contract; it is fixed above, not deferred.
  - The first iteration's readiness accepted any non-empty `choices` list; fixed above.
  - The `role` rule is lenient by design: a prior test's upstream omits `role`, and the review
    asked for a valid structure, not a mandatory role.
  - The first iteration's policy tests and their implementation were written in one step
    without a separate RED run. All three review fixes ran RED first.
  - The third iteration touches one shared core module: `BoundedJsonResponse` gained two
    defaulted fields, `content_type` and `body`, filled by the one constructor call in
    `ValidationHttpSession.request_json`. Its `payload`, bounds and errors are unchanged, so
    other providers' readiness rules do not change; the full suite proves no consumer broke.
  - The second iteration's readiness accepted any JSON media type, `NaN` and unbounded depth
    while dispatch refused them; fixed above.
  - Fourth iteration, two prior tests changed with the owner's approval: `test_readiness`
    no longer expects `stream: false` in the probe body, and `test_plugin`'s fake blob records
    `origin`, since a blob without one is now refused.
  - Fourth iteration, item 7 was planned with a no-key account. That cannot prove the order,
    because the Connection is resolved before `prepare_chat_body`. The tests use a keyed account
    and a spy on key reads instead. A message that is not an object is refused earlier by the
    route's shared check with 400; its own test pins that this costs no key read either.
  - Fourth iteration: the plugin's Retry-After parse repeats five lines of the private parser in
    `core/api_key_validation_http.py` and uses its public bound, as the Gemini plugin does.
    Making the core parser public would remove the copy at the cost of another core change.
  - Not fixed by the owner's choice: the httpx INFO request log names the private origin when a
    deployment enables that logger (off in the shipped setup; Unit 1, with the guarded
    transport); admin DELETE of a pair whose endpoint was removed from the config returns 404
    (the plan's retirement procedure deletes Connections while the endpoint is registered).
  - The local provider shares the patterns behind findings 2, 6 and 8; it is outside this unit
    and unchanged.
  - Fifth iteration, prior tests changed with the owner's approval of the probe shape:
    `test_readiness` and `test_request_contract` no longer expect `max_tokens` in the probe. The
    fake upstream's `probe` flag, derived from `max_tokens`, now comes from a transport the
    harness gives only to the validator; every assertion that reads it is unchanged and green.
  - Fifth iteration, the probe is no longer token-capped; the owner chose parity with ordinary
    chat over the cap.
- **Known limits carried to Unit 1:** provider existence is still observable for an ungranted
  account through the availability listing, `/v1/models/admit` and `/v1/model-parameters`; no
  catalog listing; the transport has no DNS or private-address guard; no production cache
  projection (the instance inherits `CacheBypass`; the order test uses a test-only projection);
  a cacheable instance will also need `cache_reference_from_cached_response`, since the hit
  path logs a mapper warning without it; no streaming; upstream 401 is not mapped to an
  operational outcome or fencing; one httpx client per request.

## PR #1527 follow-up — Unicode response validation (2026-10-22)

Status: verified; owner authorized committing and pushing this correction to PR #1527 after
review of head `5ea9a3db`.

Intent: reject isolated Unicode surrogate code points in every response string, including
object keys, before readiness publishes a key or dispatch returns the result. Python's JSON
decoder accepts these escapes, but the installed Starlette JSON response cannot encode the
result as UTF-8. The review reproduced a successful key replacement followed by HTTP 500.

Planned changes: add a bounded-tree Unicode check to the existing BYOM completion decoder and
a new regression test module. Preserve valid Unicode, including escaped surrogate pairs that
decode to a valid non-BMP character; never replace or normalize model text silently. Keep other
providers, cache policy and Unit 1 scope unchanged. No dependency or schema change is needed.

Test plan: RED first for isolated high/low surrogates in content, metadata keys/values and nested
containers; exercise the decoder and both inference paths. Exercise admin replacement against
the real application/isolated store: reject invalid Unicode, preserve the old key and serve the
next chat with it. Positive controls cover raw UTF-8, escaped Unicode, emoji, combining marks,
controls and literal backslash text. Then run AIGateway gates and inspect the actual diff.

Outcome:

- `completion.py` now checks strict UTF-8 representability of all strings and object keys after
  the existing depth/node bounds. `UnicodeEncodeError` follows the existing `ValueError` refusal
  path; accepted text is returned unchanged. Both readiness and dispatch use this same decoder.
- Added `tests/unit/remote_endpoint/test_unicode_response.py`: 30 regression cases. RED was
  18 failures for the reproduced decoder/readiness/replacement defects and 12 passing positive
  controls. GREEN: all 326 BYOM tests passed, including the 30 additions.
- Full `run_gates.py aigateway --base 40908acdd5f2521ed255ae2226393ef4151faa92` passed: append-only,
  Ruff, format, Pyright, no-Enterprise guard and full pytest/coverage. Overall coverage 93.90%;
  the modified completion module has 53 statements, all covered (100%). Live/PG opt-in flags
  were unset; no live keys, paid calls or external test infrastructure were used.
- Gate attempts: `--base origin/main` first rejected two tests changed/added on main after the
  PR base, not by this fix. Verified merge-base `40908acdd` and reran against it. The next run
  found two typing errors in the NEW test file (Response.body may be memoryview; exception
  detail annotation); fixed by converting the body to bytes and narrowing detail. The final
  complete gate run was green. No existing test was modified or weakened.
- Reviewed source/test diff: no core or dependency changes, new source/test files stay below
  450 lines, and the only production change is the response Unicode check. The publication
  commit includes this fix, the new regression module and this verification record.
