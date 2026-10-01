"""Shared RFC 9110 conditional-request helpers."""

from __future__ import annotations

import hashlib
import json

from fastapi.responses import Response

_CACHE_CONTROL = "public, max-age=300, must-revalidate"


def validator_matches(if_none_match: str | None, etag: str) -> bool:
    """Weakly compare an ``If-None-Match`` list with one unquoted entity tag."""

    if if_none_match is None:
        return False
    return any(_tag_matches(raw, etag) for raw in if_none_match.split(","))


def _tag_matches(raw: str, etag: str) -> bool:
    candidate = raw.strip()
    if candidate == "*":
        return True
    if candidate.startswith("W/"):
        candidate = candidate[2:]
    return candidate.strip('"') == etag


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def conditional_json_response(value: object, if_none_match: str | None) -> Response:
    """Serve one catalog value as compact JSON with a strong ETag and a 5-minute public cache.

    FEATURE: the discovery reads (``/v1/benchmarks``, ``/v1/operators``) answer 304 when the
    caller's ``If-None-Match`` already names the body. The ETag is ``sha256(body)[:32]``.
    """

    body = _json_bytes(value)
    etag = hashlib.sha256(body).hexdigest()[:32]
    headers = {"ETag": f'"{etag}"', "Cache-Control": _CACHE_CONTROL}
    if validator_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


__all__ = ["conditional_json_response", "validator_matches"]
