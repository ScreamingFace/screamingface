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
from aigateway.core.request_cache.revisions import register_adapter_revision

from .request import is_text_contract

# INVARIANT: bump it whenever what reaches the origin for an unchanged request changes. Rows have
# no expiry, so a bump is the only way to abandon what was stored under the old request shape.
GLOBAL_CACHE_ADAPTER_REVISION = "remote-endpoint-global-cache-2026-10"

# WHY registered: the community pages and the snapshot manifests report the revisions keys were
# computed under, and an importer compares them. Unreported, rows keyed under another revision
# of this adapter would load cleanly and never hit. One name serves every configured endpoint, as
# they share this projection; composition imports this module, so every app reports it.
# WHY the bundled loader still misses it: `load_plugins` never imports this package, so a
# revision set built from it alone, as the SDK's local pull check is, lacks this name.
register_adapter_revision("remote_endpoint_adapter", GLOBAL_CACHE_ADAPTER_REVISION)


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
