"""OME-884 cycle 2 — ``litellm.modify_params``, the one deliberately ASYMMETRIC hazard.

FEATURE: one global exact-request cache (OME-305). ``max_tokens`` is direct OpenAI's
single enabled and KEYED parameter, and an enabled ``litellm.modify_params`` replaces it
with a locally computed ceiling on the ``acompletion`` path — for every provider, AFTER
this gateway has built the cache key.

STORY: as an operator who set ``LITELLM_MODIFY_PARAMS=false`` (which ENABLES the flag, in
LiteLLM 1.97.0) I still get correct answers: direct OpenAI stops caching, refuses only the
requests LiteLLM would actually rewrite, and tells me why in the log.

INVARIANT under test: the two verdicts are scoped DIFFERENTLY and the asymmetry runs in
the safe direction. Participation is coarse — it sees only the model, so it declines for
the whole provider. Dispatch is precise — it sees the effective body, so it refuses only a
request whose ``max_tokens`` is not ``None``. Participation therefore ends up strictly
stricter than dispatch, and no state exists in which a stored row answers a request that
dispatch would have refused.

WHY both readers live in ONE file: the asymmetry is the behaviour. Splitting the cache
half from the dispatch half would leave two suites each of which looks like an
inconsistency on its own.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import litellm
import pytest
from fastapi import HTTPException
from openai import AsyncOpenAI

from aigateway.core.retry import is_retryable_status
from aigateway.plugins.openai_provider import plugin as plugin_module
from aigateway.plugins.openai_provider.plugin import PLUGIN

# Bound to the original private names so every relocated test body below reads unchanged.
from .ambient_state import safe_runtime as _safe_runtime
from .dispatch_harness import SELECTED_KEY as _SELECTED_KEY
from .dispatch_harness import capture_client_factory as _capture_client_factory
from .dispatch_harness import completion_response as _completion_response

_SEEDED = "openai/gpt-5.6-sol"
_UNLISTED = "openai/gpt-4o-2024-11-20"

# The guard reads the flag with a defaultless ``getattr``, so it must survive a value that
# cannot even be asked whether it is set. Local to this suite: it is the only one that
# poisons the modifier itself.


class _ExplodingTruthiness:
    """An ambient global that cannot even be asked whether it is set."""

    def __bool__(self) -> bool:
        raise RuntimeError("hostile truthiness")


# --- OME-884 review cycle 2: the ambient MUTATOR is cache-only -----------------
#
# WHY this hazard gets its own section rather than joining ``_UNSAFE_RUNTIME_STATES``:
# every member of that table makes DISPATCH unsafe too, so the shared guard refuses the
# request outright. ``litellm.modify_params`` is different in kind. Installed LiteLLM
# 1.97.0 only rewrites a request that actually carries a ceiling
# (``litellm/utils.py:1656`` requires ``kwargs.get("max_tokens") is not None``), so a
# request without one is untouched and refusing it would be a fabricated outage. The
# owner-approved answer is therefore ASYMMETRIC: always decline the cache, refuse only
# the dispatches LiteLLM would actually modify. Participation is the coarse half because
# its port receives only the model and cannot see ``max_tokens``.


def test_a_safe_modifier_flag_still_participates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Anti-vacuity for the refusals below: a hook hard-wired to False would pass them all.
    _safe_runtime(monkeypatch)
    monkeypatch.setattr(litellm, "modify_params", False)

    assert PLUGIN.participates_in_global_cache(_SEEDED) is True
    assert PLUGIN.participates_in_global_cache(_UNLISTED) is True


def test_an_enabled_ambient_modifier_declines_cache_participation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT (OME-884 cycle 2): the KEYED ceiling must be the one that ships.

    ``max_tokens`` is direct OpenAI's one keyed parameter, and an enabled
    ``litellm.modify_params`` replaces it with a locally computed ceiling AFTER the key is
    built. Storing under the caller's number while sending LiteLLM's would poison the row
    for every later reader, so this runtime may neither fill nor replay one.
    """
    _safe_runtime(monkeypatch)
    monkeypatch.setattr(litellm, "modify_params", True)

    assert PLUGIN.participates_in_global_cache(_SEEDED) is False
    assert PLUGIN.participates_in_global_cache(_UNLISTED) is False
    # Not a per-model hazard the way an alias is: the flag is provider-wide.
    assert PLUGIN.participates_in_global_cache("openai/gpt-4o") is False


def test_a_hostile_modifier_flag_refuses_participation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail CLOSED: an unreadable flag counts as ENABLED, not as absent."""
    _safe_runtime(monkeypatch)
    monkeypatch.setattr(litellm, "modify_params", _ExplodingTruthiness())

    assert PLUGIN.participates_in_global_cache(_SEEDED) is False


def test_a_missing_modifier_flag_is_treated_as_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A LiteLLM that MOVED the flag has not proven it off — so stand down.

    This is the direction the sibling ambient reads get wrong on purpose (a missing
    attribute there defaults to a falsy, therefore safe, value). Here the default must be
    the unsafe one: the whole reason the flag is read is that its absence from the guard
    is what let a poisoned row be written in the first place.
    """
    _safe_runtime(monkeypatch)
    monkeypatch.delattr(litellm, "modify_params")

    assert PLUGIN.participates_in_global_cache(_SEEDED) is False


def test_the_modifier_decline_is_diagnosable_without_leaking_the_request(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The 503 a caller sees is deliberately sanitized, so the OPERATOR needs a log line.

    WHY this matters more than it looks: ``modify_params`` is
    ``bool(os.getenv("LITELLM_MODIFY_PARAMS", False))`` in LiteLLM 1.97.0, so
    ``LITELLM_MODIFY_PARAMS=false`` ENABLES it. Without a diagnostic naming the variable,
    an operator who typed ``false`` sees direct OpenAI stop caching with no way to tell why.
    """
    _safe_runtime(monkeypatch)
    monkeypatch.setattr(litellm, "modify_params", True)

    with caplog.at_level("WARNING", logger="aigateway.plugins.openai_provider.runtime_guard"):
        assert PLUGIN.participates_in_global_cache(_SEEDED) is False

    records = [r for r in caplog.records if "modify_params" in r.getMessage()]
    assert records, "an operator was given no way to diagnose the cache decline"
    message = records[0].getMessage()
    assert "litellm.modify_params" in message
    assert "LITELLM_MODIFY_PARAMS" in message
    # INVARIANT: a diagnostic, not a transcript. No caller-controlled value may appear.
    for secret in (_SEEDED, _UNLISTED, "ping", "sk-"):
        assert secret not in message


# --- OME-884 review cycle 2: the modifier refuses ONLY what LiteLLM would rewrite ---


@pytest.mark.asyncio
async def test_an_enabled_modifier_refuses_a_ceiling_before_any_upstream_work(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """INVARIANT: never accept one ceiling and send another.

    With ``litellm.modify_params`` enabled, LiteLLM replaces ``max_tokens`` with its own
    computed value before the provider call. ``max_tokens`` is this provider's single
    enabled, KEYED parameter, so silently sending a different number would both break the
    published parameter contract and make two benchmark runs incomparable. The refusal is
    the existing sanitized, non-retryable 503, and it lands before the client exists.
    """
    monkeypatch.setattr(litellm, "modify_params", True)

    def forbidden_client(**_kwargs: Any) -> AsyncOpenAI:
        raise AssertionError("a modified-ceiling request reached client construction")

    monkeypatch.setattr(plugin_module, "AsyncOpenAI", forbidden_client)

    async def forbidden_acompletion(**_kwargs: Any) -> Any:
        raise AssertionError("a modified-ceiling request reached litellm.acompletion")

    monkeypatch.setattr(litellm, "acompletion", forbidden_acompletion)

    with caplog.at_level("WARNING", logger="aigateway.plugins.openai_provider.runtime_guard"):
        with pytest.raises(HTTPException) as raised:
            await PLUGIN.chat_completion(
                {
                    "model": "openai/gpt-4o",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 999999,
                    "api_key": _SELECTED_KEY,
                    "api_base": "https://api.openai.com/v1",
                }
            )

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "code": "unsafe_openai_environment",
        "provider": "openai",
        "message": "direct OpenAI dispatch is unavailable",
    }
    assert is_retryable_status(raised.value) is False

    messages = [r.getMessage() for r in caplog.records if "modify_params" in r.getMessage()]
    assert messages, "the operator got no diagnostic for a refused request"
    assert "LITELLM_MODIFY_PARAMS" in messages[0]
    # The 503 is sanitized on purpose; the LOG must not undo that.
    for leaked in ("999999", "ping", _SELECTED_KEY, "gpt-4o"):
        assert leaked not in messages[0], leaked


@pytest.mark.asyncio
async def test_an_enabled_modifier_still_dispatches_a_request_it_cannot_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the flag is NOT in the shared ambient tuple.

    LiteLLM 1.97.0 only rewrites a request whose ``max_tokens`` is not ``None``. A request
    without a ceiling is untouched, so refusing it would be an outage this gateway invented
    — which is precisely what putting the flag in ``_LITELLM_GLOBAL_TRUTHY_FIELDS`` would
    have caused, for the majority of real traffic.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_response("gpt-4o"))

    _capture_client_factory(monkeypatch, handler)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)
    monkeypatch.setattr(litellm, "modify_params", True)

    body = PLUGIN.prepare_chat_body(
        {"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "ping"}]}
    )
    body["api_key"] = _SELECTED_KEY

    result = await PLUGIN.chat_completion(body)
    await asyncio.sleep(0.05)

    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert "max_tokens" not in payload
    assert "max_completion_tokens" not in payload


@pytest.mark.asyncio
async def test_an_explicit_null_ceiling_follows_the_absent_value_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``max_tokens: None`` is ABSENT, not "a ceiling of None".

    The gate tests ``is not None`` for the same reason LiteLLM does, so the two agree on
    the one case where an explicit null could otherwise be read as a value and refused.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_response("gpt-4o"))

    _capture_client_factory(monkeypatch, handler)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)
    monkeypatch.setattr(litellm, "modify_params", True)

    result = await PLUGIN.chat_completion(
        {
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": None,
            "api_key": _SELECTED_KEY,
            "api_base": "https://api.openai.com/v1",
        }
    )
    await asyncio.sleep(0.05)

    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(requests) == 1
