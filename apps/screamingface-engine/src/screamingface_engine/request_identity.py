"""Payload-free identity for one authored model request."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import NewType

ModelRequestKey = NewType("ModelRequestKey", str)


def model_request_key(
    *,
    path: str,
    params: Mapping[str, str],
    context: str | None,
    intent: str | None,
) -> ModelRequestKey:
    """Hash the exact URL4 model request fields shared by author and connector."""

    payload = json.dumps(
        {
            "path": path,
            "params": sorted(params.items()),
            "context": context,
            "intent": intent,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return ModelRequestKey(hashlib.sha256(payload).hexdigest())


__all__ = ["ModelRequestKey", "model_request_key"]
