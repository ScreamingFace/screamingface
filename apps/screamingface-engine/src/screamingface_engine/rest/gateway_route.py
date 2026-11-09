"""What every gateway-backed REST route shares: the caller it forwards, and how it documents its
problems.

Used by the routes that forward one caller to AI Gateway (``connections``, ``cache_entries``).
Each route keeps its own typed service lookup, whose 503 wording is its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request

from screamingface_engine import job_env
from screamingface_engine.auth import PROBLEM_MEDIA_TYPE
from screamingface_engine.connections.port import Caller
from url4.streaming.trace import valid_traceparent


def caller_from_request(request: Request) -> Caller:
    """The caller a route forwards: its verified identity and, when valid, its trace context.

    WHY `valid_traceparent` and not the raw header (OME-1119): this value is forwarded to
    aigateway, and a malformed one is worse than none — it would be rejected or, worse, parsed
    into a trace joining nothing. Same rule the run path applies at `adapters/k8s.py:591`, so a
    caller cannot get a different answer depending on which Engine surface they entered through.
    Invalid degrades to absent, never to an error: a bad trace header must not fail an otherwise
    valid request.
    """
    return Caller(
        job_env.identity_from_headers(request.headers),
        traceparent=valid_traceparent(request.headers.get("traceparent")),
    )


def problem_responses(descriptions: Mapping[int, str]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` for a route's problem+json failures, one per status."""
    return {
        status: {
            "description": description,
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status, description in descriptions.items()
    }


__all__ = ["caller_from_request", "problem_responses"]
