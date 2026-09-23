"""Value types and typed refusals of the provider-access port (OME-1200, spec §3.2).

# FEATURE: OME-1138 adapter-first convergence — routes stop reading Profile/Connection rows and
# ask ONE port for a credential target instead.
# INVARIANT: nothing here names an HTTP status or a wire code. A refusal is a typed OUTCOME of
# the read interface; the ONE table that turns it into a response lives at the HTTP edge
# (`routes/provider_access_http.py`). Implementations raise these and never choose codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from ..profile_models import AuthType, ProfileDefaults

# WHY an alias, not a new model: the defaults a request is completed with ARE today's stored
# `ProfileDefaults`, field for field. Naming them at the port lets the backing change (a slot on
# a Connection at A2+) without a second schema; a distinct class would force a copy per read.
RequestDefaults = ProfileDefaults


class ResolvePolicy(Enum):
    """How `resolve` treats a caller with NO stored target at all.

    DISPATCH is chat: no target is a refusal. DATASHEET is the model-parameter contract
    (OME-1167): the DEFAULT selector may answer without a credential — the document is a
    lookup, not a credentialed action. A NAMED selector without a target refuses under both.
    """

    DISPATCH = "dispatch"
    DATASHEET = "datasheet"


# `stored`: a Profile or Connection row backs the target and `credential_name` is set.
# `ambient`: no stored row, but the provider names a runtime credential of its own
#            (`plugin.profileless_auth_mode()` is not None — Gemini's ADC path).
# `none`: no stored row and no ambient credential — either the provider needs none
#         (chatless providers such as Ollama) or the DATASHEET policy admitted the absence.
TargetKind = Literal["stored", "ambient", "none"]


@dataclass(frozen=True)
class CredentialTarget:
    """What `resolve` answers: everything a route needs, nothing a route may mutate.

    `context_stamp` is the opaque, non-secret digest input the contract endpoint folds into
    its ids (today's `_context_identity` string, byte for byte). `_backing` is the
    implementation's private handle to the row it resolved — excluded from equality and repr
    so no consumer can depend on its shape.

    # AIDEV-NOTE: `_backing` is what lets `authorize` and `record_dispatch_failure` mark the
    # RIGHT row without a second lookup. At A2 it becomes a Connection handle and nothing
    # outside this package notices; never read it from a route.
    """

    kind: TargetKind
    auth_type: AuthType
    credential_name: str | None
    context_stamp: str
    reauth_url: str | None
    defaults: RequestDefaults
    _backing: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Authorization:
    """What `authorize` answers: the provider headers that seal one request.

    # INVARIANT: `headers` carries the Bearer token itself, so it is excluded from `repr` —
    # a logged or traced `Authorization` must never print a credential. Equality keeps it.
    """

    headers: dict[str, str] = field(repr=False)
    credential_name: str | None
    auth_type: AuthType


AvailabilityStatus = Literal["not_connected", "pending", "connected", "needs_reauth", "error"]


@dataclass(frozen=True)
class AvailabilityRow:
    """One row of the caller-scoped availability listing (D17): provider and status ONLY.

    Declared at A1 so the port's vocabulary is complete; implemented at A3 and published as
    `GET /v1/provider-access` at A4. No ids, labels, defaults or account labels — ever.
    """

    provider: str
    status: AvailabilityStatus


@dataclass(frozen=True)
class CredentialSummary:
    """Minimal admin-facing description of one stored target (spec §3.2; implemented at A3).

    `legacy_projection` is the ONE opaque window-only projection field (F1, owner decision
    2026-09-18): today's Profile JSON, so the compatibility shells return byte-identical bodies
    without reaching the index themselves. Nothing in the successor reads it; it is excluded from
    equality and repr, and it is REMOVED at Stage E (OME-1209) together with the shells.
    # INVARIANT: masked — a projection carries `account_label` ("API key ····WXYZ"), never a key.
    """

    provider: str
    selector: str
    auth_type: AuthType
    state: str
    legacy_projection: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


# --- refusals -----------------------------------------------------------------------------------


class ProviderAccessRefusal(Exception):
    """Base of every typed refusal the read interface can raise."""


class TargetMissing(ProviderAccessRefusal):
    """No stored target answers this selector, and the policy does not admit the absence."""

    def __init__(self, provider: str, requested: str) -> None:
        super().__init__(f"no credential target {requested!r} for {provider}")
        self.provider = provider
        self.requested = requested


class TargetPending(ProviderAccessRefusal):
    """The target exists but its credential flow has not completed."""

    def __init__(self, provider: str, requested: str) -> None:
        super().__init__(f"credential target {requested!r} for {provider} is still pending")
        self.provider = provider
        self.requested = requested


class TargetReauthRequired(ProviderAccessRefusal):
    """The target exists but its credential is unusable; `reauth_url` is where to fix it.

    Two shapes, both today's: raised at RESOLVE time (`message is None`) it names the target
    (provider + requested); raised at AUTHORIZE time it carries the provider's own message.
    """

    def __init__(
        self,
        provider: str,
        reauth_url: str,
        *,
        requested: str | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message or f"re-authentication required for {provider}")
        self.provider = provider
        self.reauth_url = reauth_url
        self.requested = requested
        self.message = message


class SelectorAmbiguous(ProviderAccessRefusal):
    """The default selector matches more than one active stored target."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"multiple active connections for {provider}")
        self.provider = provider


class SelectorUnknown(ProviderAccessRefusal):
    """A named selector matches no stored target; `valid_labels` are the ones that exist."""

    def __init__(self, provider: str, requested: str, valid_labels: tuple[str, ...]) -> None:
        super().__init__(f"no connection labelled {requested!r} for {provider}")
        self.provider = provider
        self.requested = requested
        self.valid_labels = tuple(valid_labels)


class UnsupportedAuthMode(ProviderAccessRefusal):
    """The target's auth mode is one the provider does not declare."""

    def __init__(self, auth_mode: str, *, provider: str | None = None) -> None:
        super().__init__(f"auth mode {auth_mode!r} is not supported")
        self.auth_mode = auth_mode
        self.provider = provider


WriteConflictKind = Literal["retry_exhausted", "superseded"]
WriteSubject = Literal["profile", "connection"]


class WriteConflict(ProviderAccessRefusal):
    """A compare-and-set on a stored row lost: retries ran out, or the row was superseded."""

    def __init__(
        self,
        kind: WriteConflictKind,
        *,
        subject: WriteSubject,
        provider: str | None = None,
        requested: str | None = None,
    ) -> None:
        super().__init__(f"{subject} write conflict: {kind}")
        self.kind = kind
        self.subject = subject
        self.provider = provider
        self.requested = requested


class SelectorUnsupported(ProviderAccessRefusal):
    """A present `X-Profile` under the REJECT_EXPLICIT policy (Stage D sunset)."""

    def __init__(self, requested: str) -> None:
        super().__init__(f"X-Profile {requested!r} is no longer supported")
        self.requested = requested


class ProviderUnknown(ProviderAccessRefusal):
    """No registered provider carries this id (admin ops 8–9; A3)."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"unknown provider {provider!r}")
        self.provider = provider


class CredentialStoreUnavailable(ProviderAccessRefusal):
    """The credential blob could not be written, and the publication rolled back (op 8; A3).

    # INVARIANT: the message names only WHAT was being stored (`description`), never the
    # credential — store adapters may echo secrets in their own exception text, which is why the
    # cause is chained but never repeated here.
    """

    def __init__(self, description: str) -> None:
        super().__init__(f"could not store {description}")
        self.description = description
