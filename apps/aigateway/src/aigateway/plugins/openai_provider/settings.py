"""Direct OpenAI's operator settings and the ONE model-ID grammar the plugin shares.

FEATURE (OME-864): direct `openai/*` API-key dispatch. FEATURE (OME-884): that same
traffic participates in the global exact-request cache.

INVARIANT (OME-884, owner-approved MVP semantics): ``default_models`` is the bootstrap
catalog ``/v1/models`` publishes. It is NOT a dispatch allowlist and NOT a cache
allowlist. Removing a model from it removes the listing and nothing else — a direct
call still dispatches, and a row stored earlier still replays. OpenAI remains the only
authority on whether a syntactically valid model exists and whether the selected
credential may use it, and it answers that question on a cache MISS.
"""

from __future__ import annotations

import string
from typing import Final

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from aigateway.core.plugin_base import PluginSettings

# LiteLLM's own provider prefix. It selects the OpenAI route and is stripped exactly
# once at the wire, so the remainder is the upstream model id OpenAI resolves.
GATEWAY_MODEL_PREFIX: Final = "openai/"

# The official API base, pinned by ``prepare_chat_body`` and by dispatch, and therefore
# projected into the global cache key. It lives HERE rather than in ``plugin.py`` so the
# pure projection module can name it without importing anything impure.
OFFICIAL_API_BASE: Final = "https://api.openai.com/v1"

_MODEL_TOKEN_START: Final = frozenset(string.ascii_letters + string.digits)
_MODEL_TOKEN_CHARS: Final = frozenset(string.ascii_letters + string.digits + "._-")
_MODEL_TOKEN_MAX: Final = 128


def is_route_valid_model_id(model: object) -> bool:
    """Whether ``model`` is a route-legal direct OpenAI id, as a PURE total predicate.

    The grammar: the ``openai/`` prefix plus exactly ONE bounded ASCII token — 1..128
    characters from ``[A-Za-z0-9._-]``, first character alphanumeric.

    # INVARIANT: this is the SINGLE reader of that grammar. Settings validation,
    # ``prepare_chat_body``, the global-cache projection and the parameter rules all
    # call it, so none of them can drift into accepting an id another one refuses —
    # and a request the projection keys is necessarily one dispatch would forward.
    # WHY the bound and the character set (OME-864): the token reaches a URL path and a
    # JSON payload, so `/`, whitespace, control characters, percent-escapes, query and
    # fragment syntax and non-ASCII must never survive. An unbounded token is a
    # denial-of-service surface in the same place.
    # WHY it is TOTAL over ``object`` and not ``str``: the cache stage adjudicates the
    # body the caller actually sent, so ``model`` may legitimately be absent, a number
    # or a list. Those are bypasses, never TypeErrors.
    # AIDEV-NOTE (OME-884): fine-tuned/private ids such as ``ft:gpt-4o:acme::abc123``
    # are REFUSED by this grammar and stay out of scope on purpose. They name
    # account-specific models, so admitting them would need its own cross-account replay
    # decision — the global cache would otherwise let one account replay another's
    # private model.
    """
    if not isinstance(model, str) or not model.startswith(GATEWAY_MODEL_PREFIX):
        return False
    upstream = model[len(GATEWAY_MODEL_PREFIX) :]
    return (
        1 <= len(upstream) <= _MODEL_TOKEN_MAX
        and upstream[0] in _MODEL_TOKEN_START
        and all(char in _MODEL_TOKEN_CHARS for char in upstream)
    )


def upstream_model_id(model: str) -> str:
    """The id OpenAI resolves — the caller's model with LiteLLM's provider prefix removed."""
    return model[len(GATEWAY_MODEL_PREFIX) :]


def _default_models() -> list[str]:
    return [
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-terra",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.5",
        "openai/gpt-5.1",
        "openai/gpt-5",
        "openai/gpt-5-mini",
        "openai/gpt-5-nano",
        "openai/gpt-4.1",
        "openai/gpt-4.1-mini",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/o3",
        "openai/o4-mini",
    ]


def _validate_model_id(model: str) -> str:
    if not model.startswith(GATEWAY_MODEL_PREFIX):
        raise ValueError(f"OpenAI model must start with {GATEWAY_MODEL_PREFIX!r}: {model!r}")
    if not is_route_valid_model_id(model):
        raise ValueError(f"malformed direct OpenAI model: {model!r}")
    return model


class OpenAIPluginSettings(PluginSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIGW_OPENAI_",
        extra="ignore",
        populate_by_name=True,
    )

    # The BOOTSTRAP CATALOG, not an allowlist — see the module docstring.
    default_models: list[str] = Field(default_factory=_default_models)
    validation_model: str = "openai/gpt-5-nano"

    @field_validator("default_models")
    @classmethod
    def _validate_models(cls, value: list[str]) -> list[str]:
        validated = [_validate_model_id(model) for model in value]
        if not validated:
            raise ValueError("direct OpenAI requires at least one default model")
        if len(set(validated)) != len(validated):
            raise ValueError("direct OpenAI default models must be unique")
        return validated

    @field_validator("validation_model")
    @classmethod
    def _validate_validation_model(cls, value: str) -> str:
        # WHY syntax ONLY (OME-884): membership in ``default_models`` used to be
        # required here. That coupling made the published catalog govern an operational
        # readiness probe, so an operator who unpublished a model also broke API-key
        # validation for every profile. The probe still has to be route-legal, because a
        # malformed id could never reach OpenAI at all — but which models are PUBLISHED
        # is not a fact about which models can be PROBED.
        return _validate_model_id(value)
