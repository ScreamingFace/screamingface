"""Dynamic OpenRouter model admission — engine-side vocabulary (OME-880).

FEATURE: run any OpenRouter model (OME-878). The engine's declared world is
frozen at boot; this module is the mutable overlay beside it, plus the shape
gate and the answer type for the gateway's `POST /v1/models/admit`.

Think of the overlay as a guest-list annex: the printed list (compiled seeds +
url4.toml) never changes, but the doorman may pencil in a name the gateway has
vouched for — in memory only, so a restart starts from the printed list again
and a saved notebook simply re-admits at its next lookup.

AIDEV-NOTE: like `catalog/port.py`, this is a dependency-free leaf — no httpx,
no FastAPI. The adapter implements `ModelAdmissionSource`; the executable
projection consumes `AdmittedModels`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from screamingface_engine.catalog.port import Credential
from screamingface_engine.world.models.registry import is_route_legal

_OPENROUTER_PREFIX = "openrouter/"


def is_dynamically_admissible(model_id: str) -> bool:
    """True when ``model_id`` is a shape the gateway could dynamically admit.

    Exactly ``openrouter/<author>/<model>``: three segments, none empty, no
    ``~`` (the OME-873 colon escape — an encoding, never a model) and no ``:``
    (which no url4 route may carry). Everything else refuses locally without an
    admission round trip — the gate exists so a typo'd anthropic id never costs
    a gateway call.
    """
    if not model_id.startswith(_OPENROUTER_PREFIX):
        return False
    if "~" in model_id or ":" in model_id:
        return False
    segments = model_id.split("/")
    return len(segments) == 3 and all(segments) and is_route_legal(model_id)


class AdmittedModels:
    """The runtime overlay of dynamically admitted model ids (deployment lifetime).

    INVARIANT: in-memory, and never allowed to contradict the gateway's latest
    answer. Nothing persists an admission — a restart empties the overlay, which
    is the whole teardown contract. The one removal path is the heal on a
    forwarded 404 (see ``ExecutableModelParameterSource``): a gateway that
    restarted has forgotten its admissions, so the stale overlay entry is
    discarded and re-admission decides afresh.
    """

    def __init__(self) -> None:
        self._ids: set[str] = set()

    def __contains__(self, model_id: object) -> bool:
        return model_id in self._ids

    def add(self, model_id: str) -> None:
        self._ids.add(model_id)

    def discard(self, model_id: str) -> None:
        self._ids.discard(model_id)

    @property
    def ids(self) -> tuple[str, ...]:
        """The admitted ids, sorted — a stable rendering for run-env injection."""
        return tuple(sorted(self._ids))


@dataclass(frozen=True, slots=True)
class AdmissionAnswer:
    """The gateway's answer to one admission ask.

    ``admitted`` — serve it; ``refused`` — the gateway said no and named why
    (``code``/``message`` reach the caller pre-spend); ``unsupported`` — the
    gateway could not answer at all (endpoint missing, unreachable, or
    unreadable), which the engine treats exactly like today's world: a plain
    not-installed refusal, never a crash.
    """

    outcome: Literal["admitted", "refused", "unsupported"]
    code: str | None = None
    message: str | None = None


@runtime_checkable
class ModelAdmissionSource(Protocol):
    """Anything that can ask the gateway to admit one model for a caller."""

    async def admit_model(self, credential: Credential, model: str) -> AdmissionAnswer: ...


__all__ = [
    "AdmissionAnswer",
    "AdmittedModels",
    "ModelAdmissionSource",
    "is_dynamically_admissible",
]
