"""A configured endpoint's PURE projection of a chat, for the shared response cache.

# FEATURE: hosted BYOM — chats to a configured target join the one shared cache, so an identical
# request from any account is answered from the first account's stored row.
# INVARIANT: the key material is the request body alone. The canonical model ID stands for one
# fixed upstream binding; no definition field (origin, request path, upstream model) is read, so
# serving a different model under the same ID needs a new ID, not a new key.
# WHY a module of its own: the projection must be pure, while `plugin.py` holds the definition,
# the `enabled` flag and the transport. Nothing in this file can reach them.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass

from .request import is_text_contract

# INVARIANT: bump it whenever what reaches the origin for an unchanged request changes. Rows have
# no expiry, so a bump is the only way to abandon what was stored under the old request shape.
GLOBAL_CACHE_ADAPTER_REVISION = "remote-endpoint-global-cache-2026-10"


def project_global_cache_request(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
    """The requested model and this adapter's revision, or a bypass; never raises.

    # WHY a bypass outside the text contract: the cache is read before `prepare_chat_body`, which
    # then refuses the request with its own 422.
    # INVARIANT: a fresh dict on every call, so no caller can change the next one's result.
    """
    model = body.get("model")
    if not isinstance(model, str) or not is_text_contract(body.get("messages")):
        return CacheBypass(PROJECTION_BYPASS_REASON)
    return {
        "resolved_model": model,
        "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
        "prepared": {},
    }
