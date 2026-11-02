"""Refuse a picture or PDF Benchmark run whose Candidate has a model that can't take them.

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

FEATURE (OME-1803, spec OME-1760 §3.4): PDFs take the same desk. A Case with a ``file`` part makes
it a PDF Benchmark, and stage 4 also refuses each Candidate model whose list lacks ``pdf``, on the
same single read of the list. The key is the published list, never a model's name; the gateway's
422 ``unsupported_content_part`` stays the backstop when this check misses.

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

PDF_MODALITY = "pdf"
"""The input type a PDF needs, in the same vocabulary."""

_IMAGE_PART = "image_url"
_PART_MODALITIES: Mapping[str, str] = {_IMAGE_PART: IMAGE_MODALITY, "file": PDF_MODALITY}
"""Each media part type a Case can carry (`candidate_input.py`), to the input type it needs."""


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
    """Whether any Case hands the Candidate a picture."""

    return IMAGE_MODALITY in cases_need_modalities(rows)


def cases_need_modalities(rows: Sequence[Mapping[str, object]]) -> frozenset[str]:
    """The media input types (``image``, ``pdf``) any Case hands the Candidate.

    Only ``input`` is the Candidate's view of a Case. A Case whose envelope the reader refuses is
    not counted: it fails its own Case at the connector (OME-1271 PR 4), and nothing in it reaches
    a model.
    """

    needed: set[str] = set()
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
            if isinstance(content, list):
                needed.update(
                    _PART_MODALITIES[part["type"]]
                    for part in content
                    if part["type"] in _PART_MODALITIES
                )
    return frozenset(needed)


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
    """The gateway ids, sorted, of the models that cannot take images."""

    return models_lacking(model_ids, modalities, IMAGE_MODALITY)


def models_lacking(
    model_ids: Iterable[str], modalities: Mapping[str, Sequence[str]], modality: str
) -> tuple[str, ...]:
    """The gateway ids, sorted, of the models whose list does not carry ``modality``.

    INVARIANT: a model the gateway does not list counts as text-only (OME-1537).
    """

    return tuple(
        sorted({model_id for model_id in model_ids if modality not in modalities.get(model_id, ())})
    )


async def refuse_blind_models(node: Url4Node, rows: Sequence[Mapping[str, object]]) -> None:
    """Stages 1-4: fail the run when a picture or PDF Benchmark's Candidate has a model that
    can't take them.

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
    needed: frozenset[str] = cases_need_modalities(rows)
    if not needed:
        return
    # Stage 3 — the Candidate's models.
    model_ids: Mapping[str, str] = reader.model_routes()
    routes: frozenset[str] = candidate_model_routes(url4, frozenset(model_ids))
    if not routes:
        return
    # Stage 4 — one read of the model list, then one refusal naming every gap.
    listed: Mapping[str, Sequence[str]] = await reader.input_modalities()
    candidates: list[str] = [model_ids[route] for route in routes]
    reasons: list[str] = []
    if IMAGE_MODALITY in needed and (blind := models_lacking(candidates, listed, IMAGE_MODALITY)):
        logger.info("picture run refused text_only_models=%s", ", ".join(blind))
        reasons.append(
            "This Benchmark's Cases carry pictures, and these models cannot take images: "
            f"{', '.join(blind)}. The gateway reports them as text-only; a model it knows "
            "nothing about counts as text-only too."
        )
    if PDF_MODALITY in needed and (pdfless := models_lacking(candidates, listed, PDF_MODALITY)):
        logger.info("pdf run refused models_without_pdf=%s", ", ".join(pdfless))
        reasons.append(
            "This Benchmark's Cases carry PDFs, and these models cannot take PDFs: "
            f"{', '.join(pdfless)}. The gateway does not list pdf among their input types; a "
            "model it knows nothing about cannot take PDFs either."
        )
    if reasons:
        raise ResolutionError(" ".join(reasons), code=ErrorCode.INTENT_ERROR, permanent=True)


__all__ = [
    "IMAGE_MODALITY",
    "PDF_MODALITY",
    "ModelSightReader",
    "candidate_model_routes",
    "cases_need_modalities",
    "cases_need_pictures",
    "models_lacking",
    "refuse_blind_models",
    "register_model_sight",
    "run_expression_scope",
    "text_only_models",
]
