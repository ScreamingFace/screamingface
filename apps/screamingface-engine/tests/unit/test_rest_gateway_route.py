"""The helpers every gateway-backed REST route shares.

Pinned here: each documented failure is a problem+json response. The forwarded caller's trace
rule (OME-1119) is pinned in ``test_traceparent_propagation``.
"""

from __future__ import annotations

from screamingface_engine.auth import PROBLEM_MEDIA_TYPE
from screamingface_engine.rest.gateway_route import problem_responses


def test_each_documented_failure_is_problem_json() -> None:
    responses = problem_responses({401: "Who are you?", 503: "Not here."})

    assert responses == {
        status: {
            "description": description,
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status, description in [(401, "Who are you?"), (503, "Not here.")]
    }
