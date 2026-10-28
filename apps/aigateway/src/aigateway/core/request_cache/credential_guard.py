"""Keep a response that holds its own call's credential out of the shared cache.

# FEATURE: hosted BYOM Unit 1 — a stored response is replayed to and listed for every account, so
# an upstream that repeats the caller's key must never get that response stored.
# INVARIANT: every non-empty sealed credential counts, however short. `credential_values` keeps
# its floor of eight characters for redacting error text; the cache needs every credential.
# WHY the decoded strings and mapping keys, not the serialized text: JSON escapes `"` and `\\`,
# so a key holding either no longer appears verbatim once serialized.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..provider_error_text import sealed_values


def holds_sealed_credential(response: object, dispatch_body: Mapping[str, Any]) -> bool:
    """Whether ``response`` holds a credential sealed into ``dispatch_body``.

    INVARIANT: fails closed; a body whose credentials cannot be read counts as holding one.
    WHY call it only on a response `json.dumps` accepted: that rules out a cycle, so the walk ends.
    """
    try:
        sealed = {value.strip() for value in sealed_values(dispatch_body) if value.strip()}
    except Exception:
        return True
    if not sealed:
        return False
    pending: list[object] = [response]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if any(credential in value for credential in sealed):
                return True
        elif isinstance(value, Mapping):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list | tuple):
            pending.extend(value)
    return False
