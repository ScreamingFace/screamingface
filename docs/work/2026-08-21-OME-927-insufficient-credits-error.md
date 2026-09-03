---
ticket: OME-927
stack: aigateway
status: done
started: 2026-08-21
finished: 2026-08-21
---

# OME-927 — Surface a meaningful upstream error when a run runs out of credits

## Intent

When a run exhausts the upstream provider's credits, the client currently reports
`candidate · case_execution_failed — The upstream provider returned an error.` — a generic
string that hides the real cause. Ship the ticket's Option 2 fallback: map HTTP 402
(insufficient credits) to a dedicated `insufficient_credits` code + message, so the client
renders `The upstream provider reported insufficient credits.` instead of the generic
`provider_error` text. Never serialize `str(exc)` (FINDING B invariant stays intact).

## Root-cause tracing (beyond the ticket's own root-cause note)

The ticket's "Root cause" section names one mapping function —
`apps/aigateway/src/aigateway/routes/chat_dispatch.py::_provider_error_code()` — as the sole
place a `402` falls through to the generic `provider_error` code. Tracing the actual dispatch
paths shows there are **two independent status→code mappings**, and the ticket's own primary
example (OpenRouter) is produced by the *second* one, not the first:

1. `chat_dispatch.py::_provider_error_code()` (called from `_litellm_http_exception`) — the
   generic path for a genuine LiteLLM/transport exception carrying `status_code`. This is what
   a raw-HTTP-402 provider (e.g. Anthropic's `billing_error`, which litellm surfaces via a
   caught exception type) goes through.
2. `apps/aigateway/src/aigateway/plugins/openrouter_provider/dispatch_errors.py::_embedded_error_exception()`
   — a **second, separate** status→code mapping, hardcoded in the OpenRouter plugin. OpenRouter
   reports insufficient-credits as a `payment_required`/`402` error **embedded in an HTTP-200
   response body** (`response_errors.py::find_converted_error`/`find_raw_error`), not as a raw
   HTTP 402 status. `plugin.py::chat_completion` routes that embedded error through
   `_embedded_error_exception(status)`, which has its own independent `if/elif` status ladder
   that also falls through to `provider_error` for 402 today.

Confirmed by the existing test
`apps/aigateway/tests/unit/openrouter/test_openrouter_toplevel_conversion_retry.py::test_toplevel_billing_and_client_statuses_single_dispatch_sanitized`
which already parametrizes `(402, 402, "provider_error")` for exactly this embedded-402 shape.

**Consequence:** fixing only `chat_dispatch.py` (as the ticket's own "Suggested fix" section
describes) would NOT fix the OpenRouter case the ticket cites as its lead example — it would
only fix a raw-transport 402 from some other provider. Both mappings must be updated together,
or the fix is incomplete for the primary scenario.

Confirmed the message is safe to reach the client end-to-end:
`chat_dispatch.py` detail dict → `screamingface_engine/runner/connector.py::_raise_for_status`
(reads `detail.code`/`detail.message` into `ResolutionError`) →
`screamingface_engine/benchmarks/aggregation.py::public_error()` (passes through a `code`
matching `_public_identifier`'s `[A-Za-z0-9_.:-]+` regex) →
`screamingface_engine/benchmarks/draco/aggregate.py::_row_failure` (stage="candidate") →
`packages/screamingface/src/screamingface/_ui/report_view.py` (prints `stage · code — message`
verbatim). `insufficient_credits` is a valid identifier for every hop; no changes needed outside
`apps/aigateway`.

Verified out of scope / unaffected by this change:
- `apps/aigateway/src/aigateway/plugins/taxonomy/classify.py::outcome_for_status` — the
  usage-accounting outcome bucket is derived from the raw HTTP status only, never from the
  client-facing `code` string, so accounting/taxonomy is untouched.
- `_should_mark_profile_error_on_dispatch_status` / OAuth-connection-error marking — keyed on
  the HTTP status (still 402), not on the code string, so credential-health behavior is
  unchanged.
- `core/api_key_validation.py` `NO_QUOTA` detection (OpenRouter `payment_required` / Anthropic
  `billing_error`) — a separate, pre-existing feature (proactive credential health check), not
  the live-dispatch error path this ticket is about.

## Planned changes

- `apps/aigateway/src/aigateway/routes/chat_dispatch.py`
  - `_provider_error_code()`: add a `status == 402` branch returning `"insufficient_credits"`.
  - `_PROVIDER_ERROR_MESSAGE`: add `"insufficient_credits": "The upstream provider reported insufficient credits."`.
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/dispatch_errors.py`
  - `_embedded_error_exception()`: add the same `402 → insufficient_credits` branch, with the
    same client-facing message text (kept as a local literal — this module already authors its
    own strings independently of `chat_dispatch._PROVIDER_ERROR_MESSAGE`, and unifying that is
    a larger refactor out of scope here).

## Test plan

- `apps/aigateway/tests/unit/core/test_litellm_http_exception_sanitize.py`: update the existing
  `(402, "provider_error")` parametrized case to `(402, "insufficient_credits")` — it already
  asserts no secret leak and a non-empty message, so the parametrize update covers the new
  branch under the same invariants.
- `apps/aigateway/tests/unit/openrouter/test_openrouter_toplevel_conversion_retry.py`: update
  the existing `(402, 402, "provider_error")` case in
  `test_toplevel_billing_and_client_statuses_single_dispatch_sanitized` to
  `(402, 402, "insufficient_credits")`.
- New assertions (in one of the above, or a new focused test) confirming the exact client-facing
  message text `"The upstream provider reported insufficient credits."` is returned for a 402,
  through both dispatch paths, with no secret/raw-provider-text leak.

## Acceptance

- A raw-transport 402 (any provider) and an OpenRouter embedded-402 both surface
  `{"code": "insufficient_credits", "message": "The upstream provider reported insufficient credits."}`
  to the aigateway caller.
- No other status code's mapping changes (400/401/429/5xx/unclassified all keep their existing
  code + message).
- `str(exc)` / raw provider text is never present in the response (existing sanitizer tests
  keep passing unmodified).
- Full aigateway gate suite green: ruff check, ruff format --check, pyright,
  check_no_enterprise.py, pytest (--cov-fail-under=80).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** exactly as planned —
  `apps/aigateway/src/aigateway/routes/chat_dispatch.py`,
  `apps/aigateway/src/aigateway/plugins/openrouter_provider/dispatch_errors.py`, plus 3 test
  files (`tests/unit/core/test_litellm_http_exception_sanitize.py`,
  `tests/unit/openrouter/test_openrouter_toplevel_conversion_retry.py`,
  `tests/unit/openrouter/test_openrouter_error_policy.py`).
- **Commits:** filed as a PR from branch `ome-927-insufficient-credits` off `origin/main`
  (base `0323a7bc`) — see PR link in the docs/tasks mirror once opened.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` → ALL GATES
  GREEN (ruff check, ruff format --check, pyright, check_no_enterprise.py, pytest
  --cov=aigateway --cov-fail-under=80 — 892 passed). `--skip-append-only` used with explicit
  user confirmation (see Deviations).
  **Live verification (beyond the gate suite):** ran the fixed build locally
  (`AIGW_AUTH_MODE=disabled`, `AIGW_OPENROUTER_ENABLED=true`, scratch SQLite DB, migrations
  applied), registered a real OpenRouter API key confirmed to carry zero credit, and sent a
  genuine `/v1/chat/completions` request through it. Response: `HTTP 402`,
  `{"code": "insufficient_credits", "message": "The upstream provider reported insufficient
  credits."}` — confirms the fix end-to-end against the real provider, not just mocked tests.
  Scratch DB and server torn down after the check; no credential persisted anywhere durable.
- **Deviations:**
  1. Root-cause tracing found the fix needed **two** source files, not the one the ticket's
     "Suggested fix" section names — see the ledger's "Root-cause tracing" section above.
     OpenRouter (the ticket's own lead example) reports insufficient-credits through a
     *separate* status→code mapping (`openrouter_provider/dispatch_errors.py`) than the one
     the ticket cites (`chat_dispatch.py`); both were updated together.
  2. Three **prior** tests asserted the literal `402 → "provider_error"` bug behavior and had
     to change to `"insufficient_credits"` to reflect the ticket's requested fix. This tripped
     the repo's automated append-only-test gate (sdlc rule 5), which is a hard STOP by design.
     Paused and asked the user for explicit confirmation before overriding with
     `--skip-append-only`; user confirmed "Yes, update all 3" before the gate was re-run.
  3. One incidental `ruff format` line-length fix in
     `test_openrouter_error_policy.py` (wrapping a long assert), unrelated to the logic change.
