---
ticket: OME-1136
stack: aigateway
status: in_progress
started: 2026-10-02
finished:
---

# ome-1136-relay-sanitized-provider-error — Relay the provider's sanitized error message

## Intent

Every rejected model call today renders the same "The upstream provider returned an error."
The provider's own explanation (unsupported `temperature`, an account gate, credits) is
discarded, so a researcher cannot tell causes apart. Relay a sanitized, capped upstream message
plus the upstream status as ADDITIVE detail fields and a composed `message`, so the text reaches
the engine report's `source_error.message`. Owner decisions (Linear comment, 2026-10-02) bind.

## Planned changes

- NEW `apps/aigateway/src/aigateway/core/provider_error_text.py` — body extraction allowlist,
  character policy, in-place redaction, 140-char cap, Gate 1 (engine `public_message` parity),
  Gate 2 (call credential), `enrich_detail(...)`.
- `routes/chat_dispatch.py::_litellm_http_exception` — optional `forbidden` credential values;
  enrich detail on relayable codes (minimal hunk; PRs #1153/#1230 also touch this file).
- `routes/chat.py` — pass the dispatch credential values to `_litellm_http_exception`.
- `plugins/openrouter_provider/response_errors.py` / `dispatch_errors.py` / `plugin.py` —
  embedded-200 path carries the allowlisted `error.message`.
- `plugins/codex_provider/plugin.py`, `plugins/gemini_provider/plugin.py` — raw `exc.message`
  through the same sanitizer.
- Engine: one contract test (no engine code change expected).

## Test plan

Design §4 cases 1-10 (relay, OpenRouter `metadata.raw` wrapper, embedded 200, garbage bodies,
poisoned body, cap, no relay on 401/429, Gate-1 parity fixture, engine contract, plugins).

## Acceptance

- Ticket acceptance: unsupported-parameter 400 → gateway message contains the sanitized text and
  status; same text in `source_error.message`; garbage body → generic byte-identical detail;
  poisoned body leaks nothing.
- All prior tests unmodified and green; `run_gates.py aigateway` and `screamingface-engine` green.

## Outcome (BLOCKED — append-only test conflict, 2026-10-02)

- **State:** implementation + 86 new tests GREEN in the lane worktree, NOT committed. The full
  aigateway suite has **13 prior tests red**, all for one reason: they put a benign-looking
  string in an upstream `error.message` on a relay code (400/402/403/404/408/5xx) and assert it
  never reaches the client. That is the exact behaviour this ticket reverses. Owner decision
  needed before any prior test is touched (append-only rule).
- **Failing prior tests:**
  - `openrouter/test_openrouter_toplevel_conversion_retry.py` — `test_toplevel_overload_converts_to_single_dispatch[503,529]` (:170),
    `test_toplevel_billing_and_client_statuses_single_dispatch_sanitized[400,402,403,408,500,502]` (:255),
    `test_toplevel_402_surfaces_a_dedicated_insufficient_credits_message` (:284).
  - `openrouter/test_openrouter_error_policy.py` — `test_embedded_top_level_error_is_sanitized_and_does_not_invalidate` (:357),
    `test_embedded_choice_error_with_native_finish_reason_maps_status` (:406).
  - `openrouter/test_openrouter_no_eligible_endpoint.py::test_no_eligible_endpoint_embedded_in_a_200_body_surfaces_sanitized` (:168).
  - `openrouter/test_openrouter_routing_policy_routes.py::test_a_zdr_refusal_embedded_in_a_200_body_still_keeps_the_key_valid` (:284).
- **Actual files (uncommitted):** NEW `core/provider_error_text.py`; `routes/chat_dispatch.py`
  (`_litellm_http_exception` + import, one hunk), `routes/chat.py` (one call + import);
  OpenRouter `response_errors.py`, `provenance.py`, `dispatch_errors.py`, `plugin.py`;
  `codex_provider/plugin.py`, `gemini_provider/plugin.py`. Tests: `core/test_provider_error_text.py`,
  `openrouter/test_openrouter_error_relay.py`, `codex/test_codex_error_relay.py`, engine
  `tests/unit/test_gateway_error_relay_contract.py`; fixtures `tests/fixtures/provider_error_relay/`.
- **Gates:** aigateway ruff/format/pyright/no-enterprise green; pytest 5148 pass / 13 fail
  (above). Engine contract tests 3/3 green with NO engine code change. Not run through
  `run_gates.py` to completion (red by construction until the decision).
- **Deviations from the design:**
  1. Body source: litellm 1.87 OpenRouter exceptions carry a SYNTHETIC empty `exc.response` and
     `exc.body=None`; the wire body exists only on the chained `httpx.HTTPStatusError`
     (measured against real `litellm.acompletion`). The extractor walks the cause chain
     (bounded 8, cycle-safe) — still structured carriers only, never `str(exc)`.
  2. Converter-raised embedded 200s: litellm keeps only `str(error.message)` on the context
     exception; `metadata.raw` does not survive that path.
  3. Dropped the `[via <provider_name>]` suffix: outside the owner allowlist, and prior tests
     pin `provider_name` as never echoed.
  4. Relay requires a VALIDATED upstream status (no `upstream_status` is invented for a
     malformed/absent status).
  5. Codex/Gemini: message screened for every status (incl. 429 — it was relayed raw before);
     no `upstream_*` fields added there.

## Update 2026-10-02 (owner decisions via coordinator)

- Option A approved: the 13 prior tests' assertions were flipped (4 files, 18+/8-), recorded byte-exact in
  `.claude/test-change-approvals/OME-1136.json`. `test_openrouter_toplevel_conversion_retry.py`
  now proves a credential-shaped (`secret: …`) upstream message is WITHHELD.
- Antigravity added to scope: RED (3 failing) → GREEN in `antigravity/test_antigravity_error_relay.py`;
  the gateway-authored activation message bypasses the screen (it exceeds the 140-char cap).
- Gates: `run_gates.py aigateway` normal run flags ONLY the 4 approved files. The
  `--skip-append-only` rerun was DENIED by the session permission classifier — pending owner.
  `run_gates.py screamingface-engine`: ALL GATES GREEN.

## Design (copied from the approved draft)

# OME-1136: relay the provider's sanitized error message (design proposal)

Base: `origin/main` @ `db6757bc5` (2026-10-02, includes #1204 and #1209). Read-only investigation.

## 1. Current path, traced

**Gateway** (`apps/aigateway`)
- `routes/chat.py::_dispatch_and_finalize_accounting` has three except branches, and all of them funnel into `routes/chat_dispatch.py::_safe_dispatch_failure_response`:
  - **A.** A plugin-raised `HTTPException` keeps its curated detail.
  - **B.** A known litellm family goes through `_litellm_http_exception(exc)`.
  - **C.** Anything else becomes `_unknown_provider_exception()`.
- In Branch B, `_litellm_http_exception` maps status to a code. The mapping is 400→`bad_request`, 401→`auth_required`, 402→`insufficient_credits`, 429→`rate_limited` and validated 5xx→`provider_unavailable`. Everything else (403, 404, a malformed status) becomes `provider_error`. The message is a fixed sentence from `_PROVIDER_ERROR_MESSAGE`, and `str(exc)` is deliberately discarded (FINDING B).
  - The Muse Spark account gate is a 403 from OpenRouter. litellm raises it as `APIError(status_code=403)`, which maps to `provider_error`. That is the ticket's case.
  - A temperature rejection is a 400, which maps to `bad_request` ("rejected the request"). The relay has to cover every code, not only `provider_error`.
- OpenRouter's embedded errors (an error inside an HTTP-200 body) are built by `plugins/openrouter_provider/dispatch_errors.py::_embedded_error_exception(status)`. Only the status survives, and the message is the fixed "OpenRouter reported a provider error". `response_errors.py` already parses `error.{status,code,metadata.error_type}` but never reads `message`.
- Response body today: `{"detail": {"code": <code>, "message": <fixed sentence>}}`, plus `Retry-After` when present.
- **Existing leak, out of the ticket but on this path:** `codex_provider/plugin.py:154` and `gemini_provider/plugin.py::_detail_for_error` already relay `exc.message` raw and unsanitized. `antigravity_provider` follows the same pattern.
- The 401 path is a hazard. `_dispatch_failure_response` passes `exc.detail` to `record_dispatch_failure(...)`, which persists it into the connection's error state. Any relayed text on that path ends up in the DB.
- Logs: `log_dispatch_failure` (#1204) writes the class name and code only. The `failure_classification` INVARIANT echoes only `detail.code`.

**Engine** (`apps/screamingface-engine`)
- `world/connector.py::_raise_for_status` sets `code = detail.code` unless that code is in `ENGINE_RESERVED_CODES`, and `message = detail.get("message")`. Nothing else in the detail is read.
- `benchmarks/aggregation.py::public_error` produces the `source_error` that lands in report.json:
  - `code` must pass `public_identifier`. It is not declared, so it folds to `upstream_error` with `source_code=bad_request|provider_error`.
  - `message` must pass `error_text.public_message`. That function caps at 200 characters, collapses whitespace to one line, and **withholds the whole message** when it sees a path (`(^|[\s'"(])/…`), a traceback, `key|token|secret…[:=]`, `bearer …`, `sk-…`, `AKIA…` or a PEM header. It does not redact parts of the message.
- The benchmark path has **no authorship screen**, so a gateway message survives into `source_error.message` as long as the content screen passes.
- The REST transactional problem body (`rest/routes.py::_sanitized_error`) scrubs every code outside `ENGINE_ERROR_CODES` to `internal_error` and drops the message. The relay never appears there. That follows OME-941's design and is not changed here.

Conclusion: the change is gateway-only, which matches the ticket. One condition: the gateway text must never trip `public_message`, because a trip silently replaces the whole message with the generic default in the report.

## 2. Proposal

New module `aigateway/core/provider_error_text.py` with one public function:

`relayable_upstream_message(exc) -> str | None`

It is pure, never raises (it is wrapped in `try/except Exception: return None`), and is unit-tested in isolation.

### 2.1 Fields read (allowlist)
**Body source**, first hit wins:
1. litellm `exc.response`, only if it is a real `httpx.Response` (non-minimal, `_request` set). Read `content`, and skip it if it is over 16 KiB.
2. `exc.body`, if it is a dict.

There is no regex-parsing of `exc.message`/`str(exc)`. That text is litellm's wrapper ("litellm.BadRequestError: OpenrouterException - …") and is the known leak vector.

**Fields taken from the JSON object:**
- `error.message` (string).
- If that value is in a vacuous set (`""`, `"Provider returned error"`, case-insensitive), read `error.metadata.raw` instead. It must be a string of 8 KiB or less that parses as a JSON object, and only its `error.message` is taken. This goes **one level only, with no recursion**. `raw` is never relayed verbatim, because OpenRouter tucks the real OpenAI text there.
- Optional: `error.metadata.provider_name`, passed through `public_identifier`. It is rendered as a suffix, e.g. "… [via OpenAI]".

**Never read:** `metadata.flagged_input`, `metadata.reasons`, headers, `request_id`/`x-request-id`, `param`/`type` free text, or any other key.

**Embedded-200 path:** extend `EmbeddedOpenRouterError` with `message: str | None`, filled from the same allowlist. `_embedded_error_exception(status, message)` then uses it.

### 2.2 Character policy
1. Apply NFKC.
2. Drop Unicode categories `Cc`, `Cf` (bidi overrides, zero-width characters, BOM), `Co`, `Cs` and `Cn`.
3. Map `Zl`/`Zp` (U+2028/2029) and all whitespace to a single space, then strip.
4. Keep non-ASCII letters, because providers may answer in other languages.

### 2.3 Stripping rules (in place, applied in this order)
| Pattern | Replacement |
|---|---|
| URL `\b[a-z][a-z0-9+.-]*://\S+`, plus bare `www.\S+` | `[url]` |
| email | `[email]` |
| `bearer\s+\S+`, `sk-[\w-]{8,}` (covers `sk-or-v1-`, `sk-proj-`), `AKIA[0-9A-Z]{16}`, `AIza[\w-]{35}`, `gh[pousr]_\w{20,}`, `xox[abprs]-\S+`, JWT `eyJ[\w-]+\.[\w-]+\.[\w-]+` | `[redacted]` |
| OpenAI org/project ids `\b(org|proj)-[A-Za-z0-9]{8,}` | `[account]` |
| hex/base62 runs of 32+ characters (request ids, other keys) | `[id]` |
| absolute/relative path token `(?<=^|[\s'"(])\.{0,2}/\S+` | `[path]` |
| **request echo:** any quoted span (`'…'`, `"…"`, `` `…` ``) longer than 40 characters | `'[…]'` |

Short quoted spans such as `'temperature'` stay.

Then there are **two gates that withhold the whole message**. When either fires, the result is `None`, which means the generic message:
- **Gate 1:** the text still matches the engine's `public_message` withhold predicate (a sensitive `key[:=]`, a traceback). The predicate is ported verbatim, and a shared fixture pins parity in both test suites, because the apps do not import each other. Without this gate, the engine would silently drop the message.
- **Gate 2:** the text contains the dispatch credential value itself. The gateway holds it in the body: `api_key`, or the bearer in `extra_headers`. This catches a credential echo even when it does not look like a known key format.

Gate 2 is an exact substring check on the resolved value. That needs a small plumbing change: the plugin has the body, so the sanitizer takes `forbidden: Iterable[str]`.

The existing `core/auth/log_filter.py` only redacts `x-aigw-provisioning-token`. It is **not** a usable general scrubber, so reusing it gives nothing beyond also redacting that header name. The engine's `_SENSITIVE_ERROR_PATTERNS` is the real precedent, and Gate 1 mirrors it.

### 2.4 Length cap
- The longest generic prefix plus status is `"The upstream provider reported insufficient credits (402): "`, which is 59 characters (computed).
- That leaves an upstream cap of **140 characters** after sanitization, truncated on a word boundary with `…`. 59 + 140 = 199, which is within the engine's 200, so the engine never truncates further.
- Sanitize first, then truncate. Truncating first could split a token and leave half a key unmatched.

### 2.5 Where the text goes
```json
{"detail": {
  "code": "bad_request",                       // unchanged taxonomy
  "message": "The upstream provider rejected the request (400): Unsupported parameter: 'temperature' is not supported with this model. [via OpenAI]",
  "upstream_status": 400,
  "upstream_message": "Unsupported parameter: 'temperature' is not supported with this model. [via OpenAI]"
}}
```
- `message` carries the composed text. That field is what the engine already transports into `source_error.message`, so no engine change is needed.
- `upstream_message` and `upstream_status` are structured fields for the UI, SDK and a future OME-302.
- Fallback when `relayable_upstream_message` is `None`: today's exact detail, byte-identical with no new keys. Existing characterisation tests stay green.

### 2.6 Which codes relay (recommended)
- **Relay:** `bad_request`, `provider_error` (403, 404, other 4xx), `insufficient_credits` and `provider_unavailable`.
- **Do not relay:** `auth_required` (401), because that detail is persisted into connection state and auth bodies are where keys get echoed. Also not `rate_limited` (429): those messages carry org ids and limits, add little, and retries hit them.

Retry, permanence and accounting are unchanged. `core/retry.py`, the taxonomy collector and the engine's `permanent` flag all read the status, type or code, never the message.

### 2.7 Invariants kept
- `log_dispatch_failure` / `failure_classification` stay class-name-only. The relayed text **must not** be logged; a test pins that the record contains no `upstream_message`.
- `record_dispatch_failure` receives the un-enriched detail (moot under §2.6, but defended anyway).
- Branch C (unknown exception) and conversion failures stay generic.

## 3. Engine side (no code change; verify only)
- `_raise_for_status`: `bad_request` and `provider_error` are not in `ENGINE_RESERVED_CODES`, so they pass, and the message passes as-is.
- `public_error`: the code folds to `upstream_error` with `source_code` kept. The message passes `public_message` because Gate 1 guarantees it does, and it is 200 characters or less.
- The REST problem body still shows `internal_error` with no message. This is by design (OME-941) and documented as a known limit.
- Optional hardening, recommended as a separate small PR: `_raise_for_status` should `str`-check `detail.message`, since today it accepts any JSON type. `public_message` already defaults non-strings, so this is not a bug.

## 4. Tests (gateway unit tests, plus one engine contract test)
1. **The relay itself.** A fake litellm `BadRequestError` with a real `httpx.Response` and body `{"error":{"message":"Unsupported parameter: 'temperature' is not supported with this model."}}` gives `code=bad_request`, `upstream_status=400`, and `message` containing the text.
2. **The OpenRouter wrapper.** A 403 `APIError` whose body is `{"error":{"message":"Provider returned error","metadata":{"raw":"{\"error\":{\"message\":\"This model requires age verification\"}}","provider_name":"Meta"}}}` relays the inner message with `[via Meta]`, and `code=provider_error`.
3. **Embedded 200.** The same body inside an HTTP-200 relays via `_embedded_error_exception`, and the error stays non-retryable.
4. **Garbage body.** `b"<html>502 Bad Gateway</html>"`, invalid JSON, a JSON array, a body over 16 KiB, and `metadata.raw` that is not JSON all give a byte-identical legacy detail with no `upstream_*` keys.
5. **Poisoned body (the key test).** The body's `error.message` holds:
   - `Bearer sk-or-v1-<64hex>`
   - `api_key=abc`
   - an `AIza…` key
   - a JWT
   - `https://internal.openrouter/x?token=…`
   - `ops@openai.com`
   - `org-AbCdEf123456`
   - `/var/run/secrets/…`
   - a 300-character quoted user prompt
   - a U+202E bidi override and a zero-width joiner

   It also has `metadata.flagged_input` set to the prompt, and the dispatch `api_key` value embedded verbatim. The assertions:
   - No secret substring, prompt fragment, `flagged_input` value, URL host or email appears in the response body, in the logs (caplog), or in `record_dispatch_failure` arguments.
   - The result is either fully redacted text or the generic fallback (Gate 1 or Gate 2).
6. **Cap.** A 1,000-character benign message gives `len(message) <= 200` and `upstream_message <= 140` characters, ending in `…`.
7. **No relay on 401 or 429**, even with a benign body.
8. **Parity fixture.** A shared JSON list of strings is run through the gateway Gate 1 and the engine `public_message`, and both must agree on withhold or keep.
9. **Engine contract.** The connector receives the new detail. `public_error` then yields `source_error.message` equal to the gateway message, and `source_code=bad_request`.
10. **Plugins.** Codex and Gemini `CustomLLMError.message` goes through the same sanitizer, and the poisoned-body test is repeated for them.

## 5. Conflicts and overlaps
- **OME-302 (unified taxonomy).** It is assigned to Sergey, but Sergey asked Dmitry today (2026-10-02 14:18Z) whether he is working on it, with no reply yet. 302's "map each provider's raw errors… keep the original for debugging" overlaps directly.
  - Mitigation: 1136 adds **only** additive `upstream_status`/`upstream_message` keys and composes `message`. It does not touch codes. 302 can later own the wording of `message` and add a category without breaking the 1136 fields.
  - Risk: if Dmitry has an in-flight detail-shape change, the two collide in `chat_dispatch.py` and `dispatch_errors.py`. Confirm before starting.
- **#1204 (OME-968, merged).** Its class-name-only log INVARIANT is preserved and pinned by test 5. There is no conflict, but the new code sits next to `log_dispatch_failure`, so watch for merge contention only.
- **#1209 (OME-939, merged).** The catch-all returns `gateway_internal_error`, which is unaffected. Branch C stays generic, so there is no overlap.
- **OME-577** (SSE stream error frames): out of scope. The stream error frame stays generic.
