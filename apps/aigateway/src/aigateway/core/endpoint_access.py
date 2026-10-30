"""Which account may use which provider for which upstream-reaching operation.

# FEATURE: hosted BYOM — an operator-approved endpoint is usable only by the accounts it is granted
# to, while every bundled provider keeps today's open behavior through the default policy.
# INVARIANT: core owns this port and never imports an adapter; the app's composition installs the
# policy on `app.state.endpoint_access` in the same step that registers configured instances.
# INVARIANT: only operations that can reach an upstream (a key probe, a key attach/replace, a
# dispatch) and the working catalog (VIEW: listings, the model contract, admission) consult it.
# Cleanup (admin or owner disconnect) never does, so a disabled endpoint or a revoked grant can
# still be cleaned up.
# INVARIANT: the shared chat cache is not one of those operations. A hit sends nothing, so chat
# asks only on a miss or a bypass, after the cache stage and before any credential is resolved.
# WHY the community cache is not filtered by VIEW (owner decision, 2026-10-27): grants govern the
# working catalog and new upstream calls; they do not make identifiers in published cache entries
# confidential.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol


class EndpointOperation(StrEnum):
    VALIDATE = "validate"
    ATTACH = "attach"
    INVOKE = "invoke"
    VIEW = "view"


class EndpointAccessPolicy(Protocol):
    def permits(self, operation: EndpointOperation, *, account_id: str, provider: str) -> bool: ...


class _PermitAll:
    def permits(self, operation: EndpointOperation, *, account_id: str, provider: str) -> bool:
        del operation, account_id, provider
        return True


PERMIT_ALL: EndpointAccessPolicy = _PermitAll()


def permits(app: Any, provider: str, *, account_id: str, operation: EndpointOperation) -> bool:
    """Whether ``account_id`` may use ``provider`` for ``operation``.

    # INVARIANT: a missing `app.state.endpoint_access` raises; it is never read as a permit.
    """
    policy: EndpointAccessPolicy = app.state.endpoint_access
    return policy.permits(operation, account_id=account_id, provider=provider)


def accessible_plugin(
    app: Any, provider: str, *, account_id: str, operation: EndpointOperation
) -> Any | None:
    """The registered plugin for ``provider`` if ``account_id`` may use it for ``operation``.

    # WHY None for a denial too: each caller already answers an unregistered provider with its own
    # refusal, so these routes answer a denied endpoint as an absent one and add no signal of their
    # own. Identifiers in published community-cache entries stay shared on purpose.
    """
    plugin = app.state.providers.get(provider)
    if plugin is None:
        return None
    if not permits(app, provider, account_id=account_id, operation=operation):
        return None
    return plugin
