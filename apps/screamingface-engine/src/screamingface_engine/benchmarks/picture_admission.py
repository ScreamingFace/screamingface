"""Refuse a picture Benchmark run whose Candidate has a model that can't see pictures.

FEATURE (OME-1548): think of the Cases route as the exam desk. Before the first paper goes out it
looks at the papers, and if any of them carries a picture it checks that everyone sitting the exam
can see. One blind model fails the whole run by name, and nothing has been paid for.

Stages, in execution order:

1. **The run says what it is.** The Runner binds the run's url4 for the length of the run
   (:func:`run_expression_scope`); the Cases route reads it back. Only a Runner run binds one, so
   the local sync eval path (a development shape, never deployed) is not checked.
2. **Does the Benchmark need pictures?** Any Case in the WHOLE file with an ``image_url`` part, not
   just the selected ones (owner, 2026-10-28: HLE is 14% pictures, and a smoke run that happens to
   draw only text Cases gets the same answer). A text Benchmark stops here and never calls the
   gateway, so no text run changes.
3. **Which models does the Candidate name?** Every model route inside the linked Candidate:
   members, synthesizer, reducer, nested Fusions. Benchmark graders are outside it and are text
   only (spec D6), so they are never checked.
4. **Which of them can't take images?** The node's gateway lists each model's input types; a model
   missing from that list counts as text-only, the gateway's own rule (OME-1537: unknown never
   means vision). Any such model fails the run with the permanent ``intent_error`` (spec §3.4,
   C9), naming each by its gateway id.

Worked example: FigQA (180 Cases, every one with a figure) with a Fusion of member
``ollama/llama3:8b`` and synthesizer ``anthropic/claude-sonnet-4-5``. Stage 2 finds a picture,
stage 3 names both routes, the gateway lists the member as ``["text"]``, so stage 4 refuses the run
naming ``ollama/llama3:8b`` — before the first of the 360 chat calls.

AIDEV-NOTE: this module never imports the connector. The gateway is reached through the
:class:`ModelSightReader` port, which the aigateway world registers for its node
(`world/connector.py`), so a node with no gateway (a test node, a read-side-only world) has no
reader and nothing to check.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol
from weakref import WeakKeyDictionary

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_BINDING
from screamingface_engine.benchmarks.expression_routes import local_route_paths
from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.core.nodes import Expression, Source, Text
from url4.core.parser import build
from url4.peer.server import Url4Node

logger = logging.getLogger(__name__)

IMAGE_MODALITY = "image"
"""The input type a picture needs, in the gateway's closed vocabulary (OME-1537)."""

_IMAGE_PART = "image_url"


class ModelSightReader(Protocol):
    """What a node's gateway can say about the models it serves."""

    def model_routes(self) -> Mapping[str, str]:
        """Every route path on the node that calls a model, mapped to that model's gateway id.

        WHY the adapter maps them: a route spells ``:`` as ``~`` (OME-873), and that rule lives
        in the world, which this shared leaf may not import.
        """
        ...

    async def input_modalities(self) -> Mapping[str, Sequence[str]]:
        """Each model's input types, keyed by its gateway id (``ollama/llama3:8b``).

        Raises:
            ResolutionError: the list could not be read; retryable, so the run spends nothing
                and a later run may find the gateway answering.
        """
        ...


_READERS: WeakKeyDictionary[Url4Node, ModelSightReader] = WeakKeyDictionary()
"""The reader of each node, keyed by the node itself (the `_GATEWAY_CLIENTS` idiom)."""

_RUN_EXPRESSION: ContextVar[str | None] = ContextVar("picture_admission_run", default=None)


def register_model_sight(node: Url4Node, reader: ModelSightReader) -> None:
    """Let ``node``'s Cases routes read model input types through ``reader``."""

    _READERS[node] = reader


@contextmanager
def run_expression_scope(url4: str) -> Iterator[None]:
    """Bind the run's own url4 while it runs, so its Cases route can read the Candidate."""

    token = _RUN_EXPRESSION.set(url4)
    try:
        yield
    finally:
        _RUN_EXPRESSION.reset(token)


def cases_need_pictures(rows: Sequence[Mapping[str, object]]) -> bool:
    """Whether any Case hands the Candidate a picture.

    Only ``input`` is the Candidate's view of a Case. A Case whose envelope the reader refuses is
    not counted: it fails its own Case at the connector (OME-1271 PR 4), and nothing in it reaches
    a model.
    """

    for row in rows:
        value: object = row.get("input")
        if not isinstance(value, str):
            continue
        try:
            messages = parse_candidate_input(value)
        except CandidateInputError:
            continue
        for message in messages or ():
            content: object = message["content"]
            if isinstance(content, list) and any(
                part.get("type") == _IMAGE_PART for part in content
            ):
                return True
    return False


def candidate_model_routes(url4: str, model_routes: frozenset[str]) -> frozenset[str]:
    """The model routes the run's linked Candidate names, nested Fusions included.

    The Candidate rides in the run as an inert text source named ``candidate``
    (`definition.link_candidate`); anything outside it (the protocol, the graders) is not the
    Candidate's. A run with no linked Candidate names none.
    """

    try:
        root = build(url4)
    except (Url4Error, RecursionError):
        # WHY: an unreadable url4 fails on its own stream, as before this check existed.
        return frozenset()
    if not isinstance(root, Expression):
        return frozenset()
    candidates: list[str] = [
        source.value.value
        for source in root.sources
        if isinstance(source, Source)
        and source.name == CANDIDATE_BINDING
        and isinstance(source.value, Text)
    ]
    found: set[str] = set()
    for recipe in candidates:
        found |= local_route_paths(recipe) & model_routes
    return frozenset(found)


def text_only_models(
    model_ids: Iterable[str], modalities: Mapping[str, Sequence[str]]
) -> tuple[str, ...]:
    """The gateway ids, sorted, of the models that cannot take images.

    INVARIANT: a model the gateway does not list counts as text-only (OME-1537).
    """

    return tuple(
        sorted(
            {
                model_id
                for model_id in model_ids
                if IMAGE_MODALITY not in modalities.get(model_id, ())
            }
        )
    )


async def refuse_blind_models(node: Url4Node, rows: Sequence[Mapping[str, object]]) -> None:
    """Stages 1-4 over the Cases themselves: a picture anywhere in ``rows`` needs sight.

    Raises:
        ResolutionError: ``intent_error`` (permanent), naming each model; or the reader's own
            retryable error when the model list cannot be read.
    """

    # Stage 1 first, so a run with nothing to check never scans the rows.
    if _RUN_EXPRESSION.get() is None or _READERS.get(node) is None:
        return
    await refuse_blind_candidate(node, needs_pictures=cases_need_pictures(rows))


async def refuse_blind_candidate(node: Url4Node, *, needs_pictures: bool) -> None:
    """Stages 1-4 with stage 2 already answered: ``needs_pictures`` is the Benchmark's flag.

    FEATURE (OME-1790): an Imported Board records ``has_pictures`` in ``board.json`` at build
    time, so its Cases route admits a run without reading any row.

    Raises:
        ResolutionError: ``intent_error`` (permanent), naming each model; or the reader's own
            retryable error when the model list cannot be read.
    """

    # Stage 1 — only a Runner run binds its url4, and only a gateway node has a reader.
    url4: str | None = _RUN_EXPRESSION.get()
    reader: ModelSightReader | None = _READERS.get(node)
    if url4 is None or reader is None:
        return
    # Stage 2 — a text Benchmark stops here, before any gateway call.
    if not needs_pictures:
        return
    # Stage 3 — the Candidate's models.
    model_ids: Mapping[str, str] = reader.model_routes()
    routes: frozenset[str] = candidate_model_routes(url4, frozenset(model_ids))
    if not routes:
        return
    # Stage 4 — one read of the model list, then the refusal.
    blind: tuple[str, ...] = text_only_models(
        (model_ids[route] for route in routes), await reader.input_modalities()
    )
    if blind:
        names: str = ", ".join(blind)
        logger.info("picture run refused text_only_models=%s", names)
        raise ResolutionError(
            "This Benchmark's Cases carry pictures, and these models cannot take images: "
            f"{names}. The gateway reports them as text-only; a model it knows nothing about "
            "counts as text-only too.",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        )


__all__ = [
    "IMAGE_MODALITY",
    "ModelSightReader",
    "candidate_model_routes",
    "cases_need_pictures",
    "refuse_blind_candidate",
    "refuse_blind_models",
    "register_model_sight",
    "run_expression_scope",
    "text_only_models",
]
