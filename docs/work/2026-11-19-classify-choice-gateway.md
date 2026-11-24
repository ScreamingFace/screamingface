---
ticket: OME-1993
stack: aigateway
status: done
started: 2026-11-19
finished: 2026-11-20
---

# classify-choice-gateway — Gateway structured-choice classification and attempts (Unit 5.1)

## Intent

Implement Unit 5.1 of the Router Recipe extension (epic OME-1306): contract C7 of
`docs/spec/2026-11-16-router-recipe-extension/contracts-replay.md`. The Gateway accepts a versioned
structured-choice input on `POST /v1/classifications` for a target declared `systemone-choice-v1`,
sends one native SystemOne `choice` question that Laya and Jev both accept, and projects the answer to
`classification-scores-v1` unchanged. Classifier catalog rows gain `input_contracts` and
`classifier-limits-v1` limits, `null` for a target that declares none; every non-streaming chat and
classification response carries `X-AIGW-Upstream-Attempts`; seal provenance accepts `routers` and
has a read route. The scalar classification path stays byte-identical. The spec and plan
(`docs/plan/2026-11-16-router-recipe-extension.md` §6) are normative; this unit first pins the five
items the spec left to it by amending C7, then implements. Landing: `app/aigateway`. The
`pkg/client-sf` runtime-compatibility test (test-plan §4 item 11, plan §14) is a separate leaf with
its own ledger and worktree from `origin/main`, started after this Gateway PR merges, because its
test needs the attempt header. No Engine or SDK runtime change, no live call and no hosted readiness
claim.

## Planned changes

- Spec amendment (before code): C7 in `contracts-replay.md` (choice input rules, native request and
  response, target config keys for `limits` and `limits: null`, the limit refusal wire, SystemOne
  budgets); C17 in `contracts-entry.md` (`limits: null` rows); the §9 item in `00-overview.md`; the
  matching rows in `test-plan.md` (§2 transitions, §4 items 1, 4, 5 and 7, §5 C4 and C17 rows); plan
  §6 step 3.
- `apps/aigateway/src/aigateway/plugins/remote_endpoint/definitions.py` and a new limits module beside
  it if the file would pass 450 lines: the `systemone-choice-v1` target kind and the `limits` tables.
- New `apps/aigateway/src/aigateway/plugins/remote_endpoint/systemone.py`: native request builder and
  response decoder.
- `plugins/remote_endpoint/plugin.py`, `validation.py`: dispatch and readiness by declared contract.
- `core/plugin_base/_ports.py`: `ClassifierEntry.input_contracts` and `limits`.
- `routes/classifications.py`, `routes/classifiers.py`: object input, contract check, limits, catalog
  rows.
- New pure-ASGI attempt-header middleware under `middleware/`, wired in `main.py` immediately inside
  `CallIdMiddleware`; send observers on every non-streaming inference transport family (inventoried at
  the base and listed here before code).
- Frozen-copy seal provenance `routers` reader and `GET /v1/frozen-copies/{id}/provenance`.
- New tests under `apps/aigateway/tests/`.

### Inference transport inventory (at base `c403ebd33`, before attempt-header code)

Only the remote endpoint serves `POST /v1/classifications`; the base `classify` raises
(`core/plugin_base/_provider.py:388-395`). Every other row is a non-streaming chat transport.

| Family | Providers | Physical send today | Observer |
|---|---|---|---|
| LiteLLM HTTP handler, accounted | Anthropic, OpenRouter, while taxonomy is enabled | `litellm.acompletion` with the app-lifetime accounting handler as `client` (`plugins/taxonomy/session.py:172-193`) | `_on_request` notes the send before its `active_collector()` early return |
| LiteLLM HTTP handler, not accounted | HuggingFace and Ollama always; Anthropic and OpenRouter while taxonomy is disabled | the base `chat_completion` and the Anthropic and OpenRouter dispatch call `litellm.acompletion` with no `client`, so LiteLLM uses its own cached client, which nothing observes | a second app-lifetime handler of the same class, whose pinned hooks are the attempt hook only, injected next to the accounting injection when that injected nothing and the plugin declares the LiteLLM HTTP path |
| Remote endpoint | each configured endpoint | one shared client per endpoint (`plugins/remote_endpoint/transport.py:55-63`), transport retries `0` | hook on that client |
| Local | local | one client per call (`plugins/local_provider/transport.py:135`) | hook on that client |
| OpenAI | openai | `_openai_http_client()` handed to `AsyncOpenAI(max_retries=0)` (`plugins/openai_provider/plugin.py:50-55`, `:237-251`) | hook on that client |
| Gemini | gemini | inference posts in `_run_oauth` and `_run_api_key` (`plugins/gemini_provider/chat_handler.py:260`, `:297`) | hook on those clients only |
| Codex | codex | `acompletion` (`plugins/codex_provider/chat_handler.py:476`) | hook on that client |
| Antigravity | antigravity | `_post_with_fallback` from the completion paths (`plugins/antigravity_provider/chat_handler.py:555`, `:571`) | hook on those sends only |

Outside the counter, because none is an inference send: OAuth and token clients (`plugins/*/auth.py`,
`core/google_code_assist.py`), project setup in Gemini and Antigravity (`_ensure_setup`,
`gemini_provider/chat_handler.py:202`, `antigravity_provider/chat_handler.py:460`), readiness
(`core/api_key_validation_http.py`; remote-endpoint readiness runs on the admin route, where no
counter is bound), catalog and discovery (`core/parameter_discovery.py`, Ollama discovery),
OpenRouter credits and the object store.

LiteLLM seam, read from installed source in both shipped locks (Gateway 1.102.1; SDK `[runtime]`
1.104.5): `_complete_huggingface` and `_complete_ollama_chat` pass `ctx.client` to
`base_llm_http_handler.completion(client=client)`, whose async path uses a given client instead of
`get_async_httpx_client`. A real-Gateway test must still prove the injected hooks fire for both; if
either provider ignores the injected client, that is a C7 stop condition, never a header of `0`.

WHY a second handler rather than widening the accounting injection: prior tests pin that the
accounting handler is injected only for an accounted provider
(`tests/unit/usage_accounting/test_accounting_seam.py:466-476`) and that a disabled taxonomy plugin
builds no handler (`tests/unit/usage_accounting/test_taxonomy_plugin.py:57`). The second handler
reuses the accounting handler's class, so LiteLLM's hidden resend and the pinned TLS and hooks on its
replacement client come from the same code; no retry logic is copied.

### Attempt header as built (slice 2)

- `core/upstream_attempts.py` owns the request counter, the send hook and the two send-path names.
  `middleware/upstream_attempts.py` binds one counter per counted request and writes the header at
  `http.response.start`; it shares `body_cap.route_path` (renamed from `_route_path`, no test used it).
- Each provider plugin declares its send path as the class attribute `upstream_send_path`:
  `litellm_http` (Anthropic, OpenRouter, HuggingFace, Ollama) or `plugin_http` (OpenAI, Gemini, Codex,
  Antigravity, Local, remote endpoint). The base leaves it `None`; a fitness test fails for any
  built-in plugin that does not declare one, so a new provider cannot ship with an unobserved send.
- The chat route injects the attempt handler only when the accounting step injected no client and the
  plugin declares `litellm_http`. The accounting hook counts the send before its collector check.
- `plugin_http` plugins put the hook on the client of each inference send only. Gemini and Antigravity
  project setup (`loadCodeAssist`) is not counted; Antigravity's host fallback counts every host it
  tried.
- Seam proof: with the unobserved LiteLLM client path made to fail, all four `litellm_http` providers
  send only through the injected client, under LiteLLM 1.102.1 and 1.104.5.
- The middleware also counts `/v1/frozen-copies/{id}/chat/completions` and
  `/v1/frozen-copies/{id}/classifications` (one non-empty id segment, as Starlette routes it). A
  replay sends nothing upstream, so it answers `0`, including the replay of a captured call that sent
  twice. Chat replay is tested now (hit, replayed error, miss, unavailable); the classification
  replay path is covered by the matcher test until Unit 6 adds the route and its own cases.

### Seal provenance as built (slice 3)

- `Provenance` gains optional `routers`: 1-256 strict `RouterRevision` entries, `binding` matching
  `^router_[0-9]+$` and `revision` matching `^sha256:[0-9a-f]{64}$`, no other key. An explicit
  `null` means none sent, as `SealRequest.provenance` already treats it. The seal stores the list as
  sent and drops an absent list, so a seal without `routers` stores exactly what it stored before.
- `GET /v1/frozen-copies/{copy_id}/provenance` answers `{"engine_version", "routers"}` through
  `_sealed_copy`: `null` and `[]` when the seal sent nothing, and `frozen_copy_unavailable` for an
  unknown, open or malformed id. Any authenticated account reads a sealed copy, as it may replay it.
- The read declares the `ProvenanceRead` response model and decodes the stored row field by field
  with the seal's own `EngineVersion` and `RouterManifest` types: a stored value the seal refuses
  today reads `null` or `[]`, never a 500 and never raw JSON, so a replay run with a Router meets a
  manifest mismatch instead of a broken row.
- No migration: `provenance` is already a JSON column. No prior test changes.

### Review fixes (2026-11-20)

- SystemOne decoder: a non-null `error` on the envelope or on the choice answer makes the answer
  invalid (502 `provider_error`, and no readiness), as a chat completion already does; `null` stays
  allowed.
- Shutdown: the usage accounting and attempt handlers close through
  `core/shutdown.close_through_cancellation`, one owned task behind `asyncio.shield`. A cancelled
  shutdown waits once more for the close and then raises; a second cancellation stops the wait but
  not the close. The failure messages are unchanged. Superseded in round 3 below.
- Provenance read: the response model and the defensive decode above.
- Overload retry: a real-app test sends a true `529` then a `200` (HuggingFace and OpenRouter) and
  reads two sends and `2`; with `529` removed from the retryable set the same answer is one send.
- Base: fast-forwarded from `c403ebd33` to `f7153ee5e`; no commit in between touches
  `apps/aigateway`, and both approved base blobs are unchanged.
- Spec: the three fixed behaviors are normative, not only built. `contracts-replay.md` gains the
  SystemOne `error` rule (Native response), the close of both app-lifetime handlers (C7, Upstream
  attempts) and the strict provenance read of a malformed stored row (C9, Gateway reader).
  `test-plan.md` §4 item 4 names both `error` cases and readiness, item 10 the malformed stored
  rows and the response schema, and a new item 12 the cancelled shutdown. Items are appended, not
  renumbered, because code and this ledger cite §4 items 8-10. The readiness test gained the
  answer-level `error` case so it covers what item 4 now states.

### Review fixes, round 3 (2026-11-20, on PR #1988)

- Shutdown: the "second cancellation stops the wait" rule could not keep its own promise. The
  loop cancels every pending task when it ends, which follows a cancelled shutdown at once, so the
  detached close was cut short (`finished: False, cancelled: True` under `asyncio.run`). Owner
  decision: the close always ends. `close_through_cancellation` now waits through every
  cancellation and raises the first one only after the close ends; the detached-task set and its
  done callback are gone. Only external process termination can stop an unfinished close (round
  4 corrected the first wording, which also named a second interrupt). C7 and test-plan item 12
  say so. The test that released the close by hand
  before the loop ended is replaced by one that cancels three times, and by one that cancels twice
  under `asyncio.run` with nothing releasing the close and finds it ended.
- Provenance read: `ProvenanceRead` is a closed record (`extra="forbid"`); its schema publishes
  `additionalProperties: false`, and an unknown key is refused, not dropped. C9 and test-plan
  item 10 say so; a new test checks the schema and the refusal.
- Ollama: the real-app attempt matrix lacked Ollama, which test-plan item 8 names. A new
  `tests/unit/upstream_attempts/test_app_ollama_wiring.py` drives a real Ollama chat through the
  Gateway with accounting enabled and disabled: one send reads `1`, LiteLLM's hidden resend `2`.
  A fake model listing and the fake transport replace a live host, on the loopback default host
  (a remote host needs the allow-remote switch). Production already injected the observed client;
  removing Ollama's `LITELLM_HTTP` declaration makes all four cases fail, so the test observes the
  route's injection. Item 8 now names both providers and both accounting modes.
- Ledger: the Commits line below no longer reads as if the PR had merged.
- Process: on 2026-11-20 the owner confirmed the exact mirror path
  `docs/tasks/2026-11-20-OME-1993-classify-choice-gateway.md`, approved earlier as
  `docs/tasks/2026-11-20-OME-<N>-classify-choice-gateway.md`.

### Review fixes, round 4 (2026-11-20, on PR #1988)

- Shutdown text: C7, the `core/shutdown.py` docstring and a test comment said a second interrupt
  could end the loop and so stop a close. Uvicorn 0.52.1, which serves the Gateway (`uv.lock`),
  does not allow that: a second Ctrl+C only sets `force_exit`, the server reads it only before it
  starts the lifespan shutdown, and the lifespan shutdown waits for the app without cancelling it.
  A close that never ends therefore holds the shutdown, a second Ctrl+C included, until the process
  is killed from outside. The owner decision "the close always ends" stands, so no code changed.
  The text now says that delivered shutdown cancellations are deferred until the close completes,
  and only external process termination can stop an unfinished close. A bounded close (a timeout)
  would be a new contract and would need a new owner decision.

## Test plan

- First failing test (test-plan §3): a choice target receives a native SystemOne body whose criteria
  follow `options` order, and the response projects to `classification-scores-v1` in returned order.
- Then the test-plan §4 acceptance, items 1-10 and 12, all against fake upstreams or none.
- Prior tests run unchanged except these, inventoried at base `c403ebd33` and each needing the
  owner's exact approval before it changes:

  | Path | Reason | Base blob |
  |---|---|---|
  | `apps/aigateway/tests/unit/remote_endpoint/test_app_classifier_catalog.py` | Its exact rows gain `input_contracts` and `limits: null` | `d71d7abcbe95` |
  | `apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json` | Regenerated by `tests/unit/test_cache_hit_contract_fixture.py`, which records every header of a chat cache hit; the hit gains `x-aigw-upstream-attempts: 0` | `f935a58399c7` |

  Approved by the owner on 2026-11-20: in `test_app_classifier_catalog.py`, the expected rows of
  `test_each_account_lists_exactly_the_classifiers_granted_to_it` and
  `test_the_details_read_missing_until_that_account_attaches_a_key` gain exactly
  `"input_contracts": ["text"]` and `"limits": None`; nothing else changes. Blob `d71d7abcbe95` →
  `2b675d227c4d`. The approval manifest `.claude/test-change-approvals/OME-1993.json` pins it.

  Approved by the owner on 2026-11-20: `openrouter_hit.json` gains exactly the line
  `"x-aigw-upstream-attempts": "0"` in its recorded headers; nothing else changes. Blob
  `f935a58399c7` → `de998a556686`, produced by the fixture test's own regeneration switch. The
  same manifest lists both approved files.

  The Engine's `tests/unit/test_cache_hit_contract.py` replays that fixture's headers; the Engine
  ignores the new header until Unit 5.2, so its stored run events must stay unchanged; it passes
  unchanged on both the base and the regenerated fixture. No other test pins an exact response header set, a classifier entry or an object `input`
  refusal.
- Dependency sync per plan §4 step 7 (Python 3.12 and 3.13) before any probe or RED test.

## Acceptance

- The C7 amendment is approved by the owner before any code.
- The plan §6 exit holds for this landing: the Unit 5.1 fake-HTTP matrix passes, and scalar
  classification stays byte-compatible.
- `uv run .claude/scripts/run_gates.py aigateway` green, and the Engine cache-hit contract test above
  passes unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** all under `apps/aigateway/` unless named.
  - Spec and plan: `docs/spec/2026-11-16-router-recipe-extension/` (`00-overview.md`,
    `contracts-entry.md`, `contracts-replay.md`, `test-plan.md`) and
    `docs/plan/2026-11-16-router-recipe-extension.md`.
  - New source: `core/classification_input.py`, `core/shutdown.py`, `core/upstream_attempts.py`,
    `middleware/upstream_attempts.py`, `plugins/remote_endpoint/limits.py`,
    `plugins/remote_endpoint/systemone.py`.
  - Changed source: `core/frozen_copy/models.py` (comment), `core/frozen_copy/store.py`,
    `core/plugin_base/_ports.py`, `core/plugin_base/_provider.py`, `core/usage_accounting/hooks.py`,
    `main.py`, `middleware/__init__.py`, `middleware/body_cap.py`, the `plugin.py` of every provider
    plugin, the Antigravity, Codex and Gemini `chat_handler.py`, `local_provider/transport.py`,
    `remote_endpoint/{classification,completion,definitions,plugin,transport,validation}.py`,
    `routes/{chat,classifications,classifiers,frozen_copies}.py`.
  - New tests: `tests/unit/remote_endpoint/` (`choice_upstream.py`,
    `test_app_choice_classification.py`, `test_app_choice_limits.py`,
    `test_app_shutdown_close.py`, `test_app_upstream_attempts.py`, `test_choice_definitions.py`, `test_choice_readiness.py`,
    `test_systemone_decoder.py`), `tests/unit/upstream_attempts/` (whole package),
    `tests/unit/test_frozen_copy_provenance.py`.
  - Owner-approved prior-test transitions: `tests/unit/remote_endpoint/test_app_classifier_catalog.py`
    (`d71d7abcbe95` → `2b675d227c4d`) and `tests/fixtures/cache_hit_contract/openrouter_hit.json`
    (`f935a58399c7` → `de998a556686`).
- **Commits:** [PR #1988](https://github.com/ScreamingFace/screamingface/pull/1988) (branch
  `OME-1993-classify-choice-gateway`, head `38400954d` on `90483dcb2`), squash-merged 2026-11-20
  as `9ef7c150c`. It holds `d30eb6ff3` (PR-open), `cf90c0339` (round 3 review fixes) and
  `38400954d` (round 4 shutdown text). At that head all 24 CI checks passed; 4 path-filtered jobs
  were skipped. The Linear close comment is posted and Linear is Done. No hosted readiness claim:
  the hosted proof is plan Unit 9, and the `pkg/client-sf` test (test-plan §4 item 11) is a
  separate landing.
- **Gates:** 2026-11-20, on the final diff after the review fixes and the spec amendments:
  `run_gates.py aigateway --skip-append-only` green on Python 3.13 and 3.12 (ruff, format,
  pyright, no-enterprise, pytest with the 80 coverage floor); full suite 8270 passed, 119 skipped,
  coverage 94.31%. The append-only check flags only the two owner-approved transitions above,
  resolved by `.claude/test-change-approvals/OME-1993.json`: the append-only check passes with it
  (2026-11-20, at PR-open). The attempt, replay, frozen-copy, remote endpoint
  and lifespan suites also pass under the SDK runtime set (LiteLLM 1.104.5, FastAPI 0.162.4,
  pydantic 2.14.3): 1050 passed. Engine `tests/unit/test_cache_hit_contract.py` passes unchanged
  on the regenerated fixture.
  Round 3 (2026-11-20, after the review fixes on PR #1988, base `90483dcb2`, the branch point the
  pre-push hook also uses): `run_gates.py aigateway --base 90483dcb2` green on Python 3.13 and 3.12,
  the append-only check included; 8395 tests collected, coverage 94.30% (18190 statements, 1036
  missed). The shutdown, provenance and attempt suites under the SDK runtime set: 176 passed.
  Round 4 (2026-11-20, text only): ruff format and lint pass on the two changed Python files, and
  the shutdown suites pass on Python 3.13 (11 passed). A live Uvicorn 0.52.1 probe served an app
  whose close never ends through `close_through_cancellation`: the server was still running after
  the first and after the second SIGINT, and stopped only on SIGKILL. The full gate run is left to
  CI.
- **Deviations:**
  - `EndpointDefinition.classifier_targets` keeps its base meaning and type (HF targets only). The
    catalog walks `targets` and lists HF and choice targets together in declaration order, so a
    prior test that reads `response_envelope` from that property still type-checks unchanged.
  - The structured-choice input rules live in a new core module,
    `core/classification_input.py`, because a route must not import a plugin; the limits documents
    and value type live in a new `plugins/remote_endpoint/limits.py`, which keeps `definitions.py`
    under 450 lines.
  - The readiness probe of a target with limits is clipped to them: an HF probe text to
    `max_text_chars`, a choice probe's text, instructions, label and description to their limits.
  - The send path is declared per plugin (`upstream_send_path`) rather than inferred, so the chat
    route needs no provider list and an undeclared built-in plugin fails a test.
  - C7 amended (owner-approved 2026-11-20): the header promise named only the two live routes, while
    its origin table required `0` on a frozen-copy replay, and C8 reads a missing header as unknown.
    The replay routes are now named in C7, and test-plan §4 item 9 and the Unit 6 C9 row say which
    replay cases each Unit tests.
  - C9 and test-plan §4 item 10 no longer name a "foreign" copy as unavailable (owner decision
    2026-11-20). The Gateway reader text already gave the provenance read the chat replay
    route's access: the copy id is the bearer secret (Q16) and replay checks no owner. An
    owner-only read would leave one sealed copy half usable, its chat replay working and its
    Router replay refused, while the route exposes only the engine version and Router
    revisions, never a request or response.
  - No runtime guard for a plugin without `upstream_send_path` (owner decision 2026-11-20): the
    Gateway loads only its built-in plugins, the fitness test requires the declaration from each,
    and the provider-family tests prove the observer fires; a runtime check of the declaration alone
    would not prove a send was observed. Revisit if dynamically loaded plugins arrive.
  - Finding, not changed: LiteLLM maps an Anthropic `529` to a `500` before the Gateway sees it, so
    the Gateway's overload retry (`429`, `503`, `529`) never retries an Anthropic `529`. The
    test-plan's outer `529` retry is tested where LiteLLM passes the `529` through (HuggingFace
    and OpenRouter); the Anthropic `429` outer retry test stays beside it.
