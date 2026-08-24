"""Strict caller-profile projection for hosted provider availability."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from screamingface_engine.connections.port import ConnectionBadResponse, ConnectionStatus
from screamingface_engine.connections.provider_id import is_provider_id

_STATES = frozenset({"pending", "authenticated", "error"})


def decode_profile_statuses(body: dict[str, Any]) -> dict[str, ConnectionStatus]:
    profiles = body.get("profiles")
    if not isinstance(profiles, list):
        raise ConnectionBadResponse()

    states_by_provider: dict[str, set[str]] = defaultdict(set)
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ConnectionBadResponse()
        provider = profile.get("provider")
        state = profile.get("state")
        if not is_provider_id(provider) or not isinstance(state, str) or state not in _STATES:
            raise ConnectionBadResponse()
        states_by_provider[provider].add(state)

    return {provider: _public_status(states) for provider, states in states_by_provider.items()}


def _public_status(states: set[str]) -> ConnectionStatus:
    if "authenticated" in states:
        return "connected"
    if "pending" in states:
        return "pending"
    return "error"


__all__ = ["decode_profile_statuses"]
