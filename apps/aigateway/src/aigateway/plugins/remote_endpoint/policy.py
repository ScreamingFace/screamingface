"""The configured-endpoint grant policy behind the core endpoint-access port.

# INVARIANT: grants come from the validated config's grant view only; definitions, transports and
# credential keys never carry them. Unit 0 policy is the startup snapshot — no hot reload.
"""

from __future__ import annotations

from collections.abc import Mapping

from aigateway.core.endpoint_access import EndpointOperation

from .definitions import EndpointGrant


class RemoteEndpointAccess:
    def __init__(self, grants: Mapping[str, EndpointGrant]) -> None:
        self._grants = grants

    def permits(self, operation: EndpointOperation, *, account_id: str, provider: str) -> bool:
        # WHY one rule for every operation: probing, attaching and invoking a key all reach the
        # endpoint, and each needs a live grant; seeing it in the catalog needs the same grant,
        # so a listing never offers an endpoint the caller could not use. The port names the
        # operation so a later surface can differ without changing callers.
        del operation
        grant = self._grants.get(provider)
        if grant is None:
            # A provider this config does not declare is a bundled one: today's open behavior.
            return True
        return grant.enabled and account_id in grant.account_ids
