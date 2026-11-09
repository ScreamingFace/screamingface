"""Positive evidence for the narrowly supported frozen-copy failure exception."""

from __future__ import annotations

import httpx

from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.model_response import parse_choice, raise_if_unusable


def replay_failure_code(response: httpx.Response) -> str | None:
    """Identify a deterministic failure using the same classifier as the consuming call.

    WHY: a failed Case or a retryable HTTP error alone proves nothing about replay. Start with
    only the token-cap shape demonstrated by the executor regression; unknown shapes stay strict.
    The caller must separately verify that the gateway stored this exact response.
    """
    try:
        raise_if_unusable(parse_choice(response.json()))
    except RunnerRequestError as exc:
        return exc.code if exc.code == "model_token_cap" else None
    except (ValueError, TypeError, AttributeError):
        # INVARIANT: malformed payloads provide no proof. Normal response handling still raises
        # its original error; this inspection cannot change execution or hide that error.
        return None
    return None
