"""Core-owned registry of the adapter revision constants cache keys embed (OME-952).

A global cache key is a hash over the request PLUS revision constants: the parameter contract
(``global_keys.PARAMETER_CONTRACT_REVISION``, core's own) and each provider adapter's
projection revision (a PLUGIN constant). A snapshot produced under different constants would
load cleanly and then NEVER be served — a 100% miss with no error anywhere — which is why the
admin upload compares revisions before loading anything (spec invariant 8).

WHY a registry rather than an import: core must not import plugins (hexagonal rule), so the
plugin side registers its constant here at plugin load — the same direction of dependence the
provider registry itself uses. ``main.load_plugins`` imports every provider package, so by the
time any route can run, the registrations are in place.
"""

from __future__ import annotations

from typing import Final

from .global_keys import PARAMETER_CONTRACT_REVISION
from .tavily_retrieval import TAVILY_RETRIEVAL_CONTRACT_REVISION

_ADAPTER_REVISIONS: dict[str, str] = {}

#: The key under which the parameter-contract constant is reported. Final because both the
#: manifest (OME-954) and the seed generator write it verbatim.
PARAMETER_CONTRACT_KEY: Final = "parameter_contract"

#: The key under which the Tavily retrieval contract constant is reported. Final because
#: the manifest writes it verbatim.
TAVILY_RETRIEVAL_KEY: Final = "tavily_retrieval"


def register_adapter_revision(name: str, revision: str) -> None:
    """Record one provider adapter's cache-key revision. Called at plugin load."""
    _ADAPTER_REVISIONS[name] = revision


def active_adapter_revisions() -> dict[str, str]:
    """A copy of the registered adapter revisions (safe to hand to callers)."""
    return dict(_ADAPTER_REVISIONS)


def active_cache_revisions() -> dict[str, str]:
    """Every revision constant a snapshot's manifest must agree with, keyed by manifest name.

    The Tavily retrieval contract is core's own, like the parameter contract, so it is
    reported here directly rather than registered by a plugin. It must be: the revision
    is inside the Tavily key hash, and snapshots move ``provider='tavily'`` rows, so a
    manifest that does not cover it would let rows keyed under different constants load
    cleanly and then never be served (OME-1044 review F3).
    """
    return {
        PARAMETER_CONTRACT_KEY: PARAMETER_CONTRACT_REVISION,
        TAVILY_RETRIEVAL_KEY: TAVILY_RETRIEVAL_CONTRACT_REVISION,
        **_ADAPTER_REVISIONS,
    }
