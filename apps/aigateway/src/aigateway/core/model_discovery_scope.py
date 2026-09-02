"""OME-1026 — the scope vocabulary for live model discovery.

FEATURE: live model discovery has two trust scopes, and the scope — not a
deployment flag — decides who may see a snapshot.

- ``PUBLIC_GLOBAL``: one process-local catalog per provider, fetched with no
  credential, safe to publish to every account (OpenRouter today; Hugging Face
  next, OME-1035).
- ``PROFILE_CREDENTIAL``: one PRIVATE catalog per authenticated account profile,
  fetched with that profile's own stored credential (Anthropic today; direct
  OpenAI and Gemini next).

INVARIANT (the whole point of this module): a ``PROFILE_CREDENTIAL`` snapshot is
derived from ONE account's credential, so it describes that account's
entitlements and nothing else. It may appear only in that account's OWN
responses — the explicit profile listing and, since OME-1026 U3, the caller's
own ``GET /v1/models`` — and never in a deployment-global cache or any response
another account can read. ``ModelCatalog`` — the shared catalog — refuses this
scope outright rather than trusting every future caller to remember the rule.

WHY the scope replaced a boolean: the rejected OME-1026 design had one
deployment-wide credentialed catalog behind ``AIGW_ANTHROPIC_DISCOVERY_API_KEY``,
which made "whose entitlements are these?" a deployment question. Account
credentials were excluded ONLY because the snapshot was global. Making the scope
explicit inverts that: private data gets a private cache, so account credentials
become the normal input instead of a hazard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .profile_models import AuthType


class DiscoveryScope(StrEnum):
    """Who a provider's live listing may be shown to.

    # WHY a string enum: the value is logged and may appear in an operator-facing
    # response, so a stable wire form matters. ``StrEnum`` (not the older
    # ``(str, Enum)`` shape ``ProfileState`` keeps for pydantic-v1 compatibility) —
    # nothing serialises this through a v1 model.
    """

    NONE = "none"
    PUBLIC_GLOBAL = "public_global"
    PROFILE_CREDENTIAL = "profile_credential"


def discovery_scope_of(plugin: object) -> DiscoveryScope:
    """The provider's declared discovery scope, defaulting to ``PUBLIC_GLOBAL``.

    # WHY a getattr default instead of a required Protocol member: every REAL
    # provider inherits ``model_discovery_scope`` from ``ProviderPluginBase``, so the
    # only objects that can lack it are test doubles written against the pre-scope
    # port. Requiring it structurally would force dozens of unrelated doubles to grow
    # a member that cannot change their behavior.
    # INVARIANT (why the permissive default is still safe): the hazard this guards is
    # a PRIVATE snapshot reaching the shared catalog. A private snapshot can only be
    # produced by ``discover_profile_models``, which is called by
    # ``ProfileModelCatalog`` alone and ONLY for a provider that explicitly declares
    # ``PROFILE_CREDENTIAL``. An object that never declares a scope has no private
    # path at all, so defaulting it to public cannot leak one — while the base hook's
    # own INVARIANT forbids any credential in the public hook.
    """
    declare = getattr(plugin, "model_discovery_scope", None)
    if declare is None:
        return DiscoveryScope.PUBLIC_GLOBAL
    return declare()


@dataclass(frozen=True)
class ProviderAuthContext:
    """The narrowly allowlisted provider-auth headers for ONE private fetch.

    Replaces the rejected deployment ``SecretStr`` setting at the provider fetch
    boundary. Core never reads a raw key: the profile's own
    :class:`~aigateway.core.plugin_base.CredentialStrategy` builds ``headers``,
    and the provider decides which of its own header names are allowed out.

    ``credential_revision`` is a NON-SECRET generation token. It exists so a
    refresh that started under an older credential owner can be recognised as
    superseded and discarded instead of publishing over the new owner's snapshot.
    It is never derived from the credential itself — deriving it from the key
    would make the cache identity credential-dependent, which is exactly what the
    owner brief forbids.

    # INVARIANT: this object holds a LIVE credential in ``headers``. It is passed
    # as a parameter, so it becomes a frame local across the whole discovery call
    # chain — a generated dataclass repr would print the credential into any
    # traceback or log record that formats it. Hence the hand-written ``__repr__``
    # below, which renders header NAMES (useful, non-secret) and never values.
    """

    headers: Mapping[str, str] = field(default_factory=dict)
    auth_type: AuthType = "api_key"
    credential_revision: str = "0"

    def __post_init__(self) -> None:
        # WHY the proxy: ``frozen=True`` protects the ATTRIBUTE, not the dict it
        # points at. A caller (or a provider) could otherwise mutate the headers of
        # a context another coroutine is still using.
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    def __repr__(self) -> str:
        names = ",".join(sorted(self.headers))
        return (
            f"ProviderAuthContext(auth_type={self.auth_type!r}, "
            f"credential_revision={self.credential_revision!r}, headers=[{names}])"
        )

    __str__ = __repr__
