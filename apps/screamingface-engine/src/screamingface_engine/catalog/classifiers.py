"""The Gateway's classifier list, read fresh, bounded and strict (contract C17, Unit 5.2).

FEATURE: Router Recipe extension. The SDK preflights a Router Recipe against classifier metadata
it reads only through the Engine (`GET /v1/classifiers`). This module reads the caller's own
Gateway list once per request and projects each usable row to `id`, `input_contracts` and
`limits`, in the Gateway's order.

INVARIANT: no inference and no repair. A row is kept only when `world.classifier_limits` reads it
as valid C7 metadata and no other row shares its ID; nothing is intersected with the Engine's
routes, named profiles or admission overlay, and no readiness or inference call is made.

INVARIANT: bounded before decoding. The body is read raw, identity-encoded, and refused once it
passes 1,000,000 bytes; an encoded, oversized or malformed body is one fixed 502, never a
truncated or empty success.
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from collections.abc import Mapping
from typing import Never

import httpx

from screamingface_engine.catalog.port import (
    CatalogRejected,
    CatalogUnavailable,
    ClassifierBadResponse,
)
from screamingface_engine.world.classifier_limits import read_capability

logger = logging.getLogger(__name__)

CLASSIFIERS_PATH = "/v1/classifiers"
MAX_BODY_BYTES = 1_000_000
"""The largest successful list body read, inclusive."""

_REJECTION_STATUSES = frozenset({401, 403})
_IDENTITY = "identity"


async def read_classifier_rows(
    client: httpx.AsyncClient, headers: Mapping[str, str]
) -> list[dict[str, object]]:
    """One fresh Gateway list for the identity in ``headers``, as strict C17 rows.

    WHY one attempt: the list is cheap and uncached on both sides; the model-detail timeout retry
    exists to let a slow datasheet fill the Gateway's cache, which does not apply here.

    Raises:
        CatalogRejected: the Gateway refused the caller's identity (401 or 403).
        CatalogUnavailable: the request timed out.
        ClassifierBadResponse: any other failure.
    """
    try:
        body = await _read(client, {**headers, "Accept-Encoding": _IDENTITY})
    except httpx.TimeoutException as exc:
        logger.warning("aigateway classifier request timed out")
        raise CatalogUnavailable(CatalogUnavailable.detail) from exc
    except httpx.HTTPError as exc:
        logger.warning("aigateway classifier request failed at the transport layer")
        raise ClassifierBadResponse(ClassifierBadResponse.detail) from exc
    return _project(_decode(body))


async def _read(client: httpx.AsyncClient, headers: dict[str, str]) -> bytes:
    async with client.stream("GET", CLASSIFIERS_PATH, headers=headers) as response:
        if response.status_code in _REJECTION_STATUSES:
            logger.info(
                "aigateway refused the classifier request (status=%d)", response.status_code
            )
            raise CatalogRejected(CatalogRejected.detail)
        encoding = response.headers.get("content-encoding", _IDENTITY).strip().lower()
        if response.status_code != 200 or encoding != _IDENTITY:
            logger.warning("aigateway classifier list unusable (status=%d)", response.status_code)
            raise ClassifierBadResponse(ClassifierBadResponse.detail)
        body = bytearray()
        # WHY these are the wire bytes: every encoding but `identity` was refused above, so the
        # bound applies to what was sent, and the read stops at the first chunk past it.
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > MAX_BODY_BYTES:
                logger.warning("aigateway classifier list exceeded %d bytes", MAX_BODY_BYTES)
                raise ClassifierBadResponse(ClassifierBadResponse.detail)
        return bytes(body)


def _decode(body: bytes) -> list[object]:
    """The list envelope's `data`, or the fixed 502.

    INVARIANT (C17): an object that repeats a key, or a number that is not finite, is
    read as `_UNUSABLE`: the envelope is then malformed (502) and a row unusable (omitted), never
    settled by "last wins" or read as an infinite limit.
    """
    try:
        document = json.loads(
            body.decode("utf-8"),
            parse_constant=_refuse_constant,
            parse_float=_finite,
            object_pairs_hook=_unique,
        )
    except (ValueError, RecursionError) as exc:
        # WHY `RecursionError`: a body nested past the decoder's depth is unreadable too, and it
        # is not a `ValueError`; uncaught, it would end the request as the Engine's own fault.
        raise ClassifierBadResponse(ClassifierBadResponse.detail) from exc
    data = document.get("data") if isinstance(document, dict) else None
    if not (isinstance(document, dict) and document.get("object") == "list"):
        raise ClassifierBadResponse(ClassifierBadResponse.detail)
    if not isinstance(data, list):
        raise ClassifierBadResponse(ClassifierBadResponse.detail)
    return data


def _project(data: list[object]) -> list[dict[str, object]]:
    """The usable rows, in order: valid C7 metadata under an ID no other row repeats."""
    # INVARIANT: only string IDs are counted, so no row value can end the list as a 500.
    ids = Counter(
        row["id"] for row in data if isinstance(row, dict) and isinstance(row.get("id"), str)
    )
    rows: list[dict[str, object]] = []
    for row in data:
        if not isinstance(row, dict) or "input_contracts" not in row or "limits" not in row:
            continue
        model = row.get("id")
        capability = read_capability(row["input_contracts"], row["limits"])
        if isinstance(model, str) and model and ids[model] == 1 and capability is not None:
            rows.append({"id": model, **capability.projection()})
    return rows


def _refuse_constant(value: str) -> Never:
    raise ValueError(f"{value} is not valid JSON")


class _Unusable:
    """A JSON value that decodes but is never usable metadata (see `_decode`)."""


_UNUSABLE = _Unusable()


def _finite(text: str) -> float | _Unusable:
    value = float(text)
    return value if math.isfinite(value) else _UNUSABLE


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object] | _Unusable:
    decoded = dict(pairs)
    return decoded if len(decoded) == len(pairs) else _UNUSABLE


__all__ = ["CLASSIFIERS_PATH", "MAX_BODY_BYTES", "read_classifier_rows"]
