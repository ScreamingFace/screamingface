"""The Gateway declares every error code it can write, and nothing else (spec 3.1, 3.2).

FEATURE: Gateway code provenance (`docs/spec/2026-11-23-gateway-code-provenance.md`).
STORY: as the Engine, I lift a Gateway `detail.code` only when the Gateway declares it, so a
body from anywhere else cannot put a key, an origin or a private ID into a log line.
INVARIANT: `codes` in `tests/fixtures/gateway_error_codes/codes.json` is exactly what the source
can write. A site the scan cannot prove fails here until it is listed below with its reason
and its codes; a new code fails until it is declared; a code no longer written moves to
`retired`, which the Engine keeps lifting because a sealed frozen copy can replay it.
"""

from __future__ import annotations

import json
from pathlib import Path

import aigateway

from ._gateway_error_code_scan import Producer, Review, failures

SOURCE = Path(aigateway.__file__).parent
FIXTURE = Path(__file__).parents[1] / "fixtures" / "gateway_error_codes" / "codes.json"

# Callables whose argument becomes the code (or the whole detail); every call is checked.
PRODUCERS = (
    Producer("core/admission.py", "_timeout", "code"),
    Producer("core/plugin_base/_ports.py", "refused", "code"),
    Producer("plugins/local_provider/transport.py", "_error", "code"),
    Producer("plugins/remote_endpoint/transport.py", "_error", "code"),
    Producer("routes/model_admission.py", "_answer", "code"),
    Producer("routes/tavily_retrieval_cache.py", "_refusal", "code"),
    Producer("core/request_cache/tavily_retrieval.py", "TavilyDescriptionError", "code"),
    Producer("core/oauth/token_service.py", "OAuthConnectionTokenError", "detail", kind="detail"),
)

# A `code` key or argument that is not a response code, with how many the site has.
NOT_CODES = {
    # The OAuth authorization code sent to a provider's token endpoint.
    "plugins/anthropic_provider/auth.py:exchange_authorization_code": 1,
    "plugins/antigravity_provider/auth.py:exchange_authorization_code": 1,
    "plugins/codex_provider/auth.py:exchange_authorization_code": 1,
    "plugins/gemini_provider/auth.py:exchange_authorization_code": 1,
    # The same authorization code, handed to the exchange request model.
    "routes/auth.py:_exchange_oauth_code_for_pending": 1,
    # An extra authorize-URL parameter (`code=true`) the provider's OAuth client sends.
    "plugins/anthropic_provider/settings.py:AnthropicPluginSettings": 1,
}

# Every exception handler the app registers. Each renders through a checked sink or through
# Starlette's own handler, which sends an HTTPException's detail, checked where it is built.
HANDLERS = frozenset(
    {"_accounted_http_exception", "_redact_validation_errors", "unhandled_exception_handler"}
)

_BY_STATUS = ("auth_required", "provider_error", "provider_unavailable", "rate_limited")
_PROVIDER_STATUS = (*_BY_STATUS, "bad_request", "insufficient_credits")

# Sites the scan cannot prove, with the unproven count, the codes they write, and why.
REVIEWED = {
    "core/admission.py:_dispatch": Review(
        1,
        ("caller_deadline_exceeded",),
        "`_timeout(outcome, ...)` right after `outcome` is set to that literal; elsewhere the"
        " local holds the non-codes `error` and `success`",
    ),
    "core/content_parts.py:UnsupportedContentPart.__init__": Review(
        1, (), "`dict(self.info)` copies the dict literal built just above, its code a literal"
    ),
    "core/provider_access/connection_authority.py:record_dispatch_failure_migrated": Review(
        1,
        ("auth_required",),
        "rewrites the dispatch failure's own detail: keeps the code the Gateway wrote on it,"
        " else `auth_required`",
    ),
    "core/provider_access/connection_authority.py:record_dispatch_outcome_migrated": Review(
        1, ("auth_required",), "the same rewrite, for a classified dispatch outcome"
    ),
    "main.py:_redact_validation_errors": Review(
        1, (), "a validation error list (`type`, `loc`, `msg`) under `detail`, never a code"
    ),
    "plugins/antigravity_provider/plugin.py:_detail_for_error": Review(
        1, _BY_STATUS, "a local `code` bound only to these literals, by status"
    ),
    "plugins/gemini_provider/plugin.py:_detail_for_error": Review(
        1, _BY_STATUS, "a local `code` bound only to these literals, by status"
    ),
    "plugins/openrouter_provider/dispatch_errors.py:_embedded_error_exception": Review(
        2,
        _PROVIDER_STATUS,
        "a local `code` bound only to these literals, by status; `relayed_detail` adds the"
        " screened upstream text beside that code and keeps it",
    ),
    "plugins/taxonomy/session.py:accounting_error_response": Review(
        1, (), "echoes an HTTPException's detail, built under the sink rule, beside `_aigw`"
    ),
    "routes/api_key_validation.py:require_valid_api_key": Review(
        1,
        (
            "api_key_expired",
            "api_key_invalid",
            "api_key_no_quota",
            "api_key_permission_denied",
            "api_key_validation_misconfigured",
            "api_key_validation_rate_limited",
            "api_key_validation_unavailable",
        ),
        "the code comes from `_MUTATION_ERRORS`, a fixed state-to-(status, code) map",
    ),
    "routes/chat_dispatch.py:_dispatch_failure_response": Review(
        2, (), "re-raises the dispatch failure's detail as the two rewrites above return it"
    ),
    "routes/chat_dispatch.py:_litellm_http_exception": Review(
        2,
        _PROVIDER_STATUS,
        "the code is `_provider_error_code(status)`, every return of which is one of these;"
        " `relayed_detail` keeps it",
    ),
    "routes/frozen_copies.py:replay_chat_completions": Review(
        1,
        (),
        "replays a captured error's detail, which a Gateway build wrote; a code it no longer"
        " writes stays in `retired`",
    ),
    "routes/model_admission.py:admit_model": Review(
        2,
        ("auth_required", "profile_pending_auth"),
        "relays the (code, message) `_credential_verdict` returns, these literals, and a"
        " plugin's `ModelAdmission.code`, set only through the `refused` producer",
    ),
    "routes/oauth_connections.py:get_connection_token": Review(
        1, (), "forwards `OAuthConnectionTokenError.detail`, a detail producer"
    ),
    "routes/provider_access_http.py:pair_conflict_detail": Review(
        1,
        ("credential_pair_ambiguous", "credential_pair_unresolved"),
        "the code comes from `_PAIR_CONFLICT_MESSAGES`, a fixed kind-to-(code, message) map",
    ),
    "routes/tavily_retrieval_cache.py:_key_hash": Review(
        1, (), "relays `TavilyDescriptionError.code`, a producer"
    ),
}

# INVARIANT (spec 3.1): the audited `retired` list, exactly: every code written on `main` since
# frozen-copy capture began (`f06860621`) and no longer written. A sealed copy keeps its captured
# detail with no end date, so none of them may leave, and the Engine lifts each one, so nothing
# else may join. A code the Gateway stops writing is added here and to the fixture in one change.
RETIRED_SINCE_CAPTURE = frozenset(
    {
        "credential_write_conflict",
        "invalid_profile_defaults",
        "profile_auth_conflict",
        "profile_conflict",
        "profile_index_conflict",
    }
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def test_the_declared_codes_are_exactly_what_the_gateway_can_write() -> None:
    found = failures(
        SOURCE,
        package="aigateway",
        fixture=_fixture(),
        producers=PRODUCERS,
        reviewed=REVIEWED,
        not_codes=NOT_CODES,
        handlers=HANDLERS,
        retired=RETIRED_SINCE_CAPTURE,
    )
    assert found == []


def test_retired_is_exactly_the_codes_retired_since_capture() -> None:
    retired = _fixture()["retired"]
    assert isinstance(retired, list)
    assert set(retired) == RETIRED_SINCE_CAPTURE
