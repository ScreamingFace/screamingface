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

import asyncio
import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol
from weakref import WeakKeyDictionary

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_BINDING
from screamingface_engine.benchmarks.expression_routes import (
    embedded_expressions,
    local_route_paths,
)
from url4 import Attachment
from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.core.nodes import Binding, Expression, Node, RelExpr, Source, Text, walk
from url4.core.parser import build
from url4.peer.server import Url4Node

logger = logging.getLogger(__name__)

IMAGE_MODALITY = "image"
"""The input type a picture needs, in the gateway's closed vocabulary (OME-1537)."""

PDF_MODALITY = "pdf"
"""The input type a PDF needs, in the same vocabulary."""

PART_MODALITIES: Mapping[str, str] = {"image_url": IMAGE_MODALITY, "file": PDF_MODALITY}
"""Each media part type a Case can carry (`candidate_input.py`), to the input type it needs.

INVARIANT (OME-1803, owner 2026-11-03): this is the ONE table. The build-time scan that writes
``board.json``'s ``modalities`` (`board_store.encode_board`) and the rows path below both read
it through :func:`cases_need_modalities`, so a new media format is one row here. A ``file`` part
is always a PDF (`candidate_input.py` refuses any other mime); Office formats become text
before a Case is written (OME-1550), so they are never a modality.
"""


def attachment_modality(media_type: str) -> str | None:
    """The input type a url4 run file of ``media_type`` needs, or ``None`` for text.

    WHY by media type: a url4 attachment carries no content-part type; its frozen media type is
    what the connector turns into a part (`world/attachment_parts.py`), ``image/*`` an image part
    and ``application/pdf`` a file part, so this is the same table seen from the url4 side.
    """

    bare = media_type.split(";", 1)[0].strip().lower()
    if bare.startswith("image/"):
        return IMAGE_MODALITY
    if bare == "application/pdf":
        return PDF_MODALITY
    return None


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


@dataclass
class _RunAdmission:
    """The run's one admission of its files: the in-flight or finished check, shared."""

    check: asyncio.Future[None] | None = None


_RUN_ADMISSION: ContextVar[_RunAdmission | None] = ContextVar(
    "picture_admission_run_files", default=None
)


def register_model_sight(node: Url4Node, reader: ModelSightReader) -> None:
    """Let ``node``'s Cases routes read model input types through ``reader``."""

    _READERS[node] = reader


@contextmanager
def run_expression_scope(url4: str) -> Iterator[None]:
    """Bind the run's own url4 while it runs, so its Cases route can read the Candidate."""

    token = _RUN_EXPRESSION.set(url4)
    # WHY a fresh holder per run: url4's member tasks copy this context, so they all see the
    # SAME holder object, and a finished check (or its failure) dies with the run.
    admission = _RUN_ADMISSION.set(_RunAdmission())
    try:
        yield
    finally:
        _RUN_ADMISSION.reset(admission)
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
                    PART_MODALITIES[part["type"]]
                    for part in content
                    if part["type"] in PART_MODALITIES
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
    """Stages 1-4 over the Cases themselves: a picture or PDF anywhere in ``rows`` is a need.

    Raises:
        ResolutionError: ``intent_error`` (permanent), naming each model; or the reader's own
            retryable error when the model list cannot be read.
    """

    # Stage 1 first, so a run with nothing to check never scans the rows.
    if _RUN_EXPRESSION.get() is None or _READERS.get(node) is None:
        return
    await refuse_blind_candidate(node, needs=cases_need_modalities(rows))


_REFUSALS: Mapping[str, tuple[str, str]] = {
    IMAGE_MODALITY: (
        "picture run refused text_only_models=%s",
        "This Benchmark's Cases carry pictures, and these models cannot take images: "
        "{names}. The gateway reports them as text-only; a model it knows nothing about "
        "counts as text-only too.",
    ),
    PDF_MODALITY: (
        "pdf run refused models_without_pdf=%s",
        "This Benchmark's Cases carry PDFs, and these models cannot take PDFs: {names}. The "
        "gateway does not list pdf among their input types; a model it knows nothing about "
        "cannot take PDFs either.",
    ),
}
"""Each modality's log line and refusal sentence; the picture sentence is OME-1548's, verbatim."""

_RUN_REFUSALS: Mapping[str, tuple[str, str]] = {
    IMAGE_MODALITY: (
        "url4 picture run refused text_only_models=%s",
        "This run's attachments include pictures, and these models cannot take images: "
        "{names}. The gateway reports them as text-only; a model it knows nothing about "
        "counts as text-only too. Nothing was sent to a model.",
    ),
    PDF_MODALITY: (
        "url4 pdf run refused models_without_pdf=%s",
        "This run's attachments include PDFs, and these models cannot take PDFs: {names}. The "
        "gateway does not list pdf among their input types; a model it knows nothing about "
        "cannot take PDFs either. Nothing was sent to a model.",
    ),
}
"""The same refusals for a url4 run's own files (OME-1809): there are no Cases to name."""


def _refusal(modality: str, names: str, table: Mapping[str, tuple[str, str]] = _REFUSALS) -> str:
    log_line, sentence = table.get(
        modality,
        (
            f"{modality} run refused models_without_{modality}=%s",
            f"This run needs {modality} input, and these models do not list "
            f"{modality} among their input types: {{names}}.",
        ),
    )
    logger.info(log_line, names)
    return sentence.format(names=names)


async def refuse_blind_candidate(node: Url4Node, *, needs: frozenset[str]) -> None:
    """Stages 1-4 with stage 2 already answered: ``needs`` is the Benchmark's modality set.

    FEATURE (OME-1790, OME-1803): an Imported Board records its ``modalities`` in
    ``board.json`` at build time (schema v3, bound to ``cases.json`` by its digest), so its
    Cases route admits a run without reading any row.

    Raises:
        ResolutionError: ``intent_error`` (permanent), naming each model and what it lacks; or
            the reader's own retryable error when the model list cannot be read.
    """

    # Stage 1 — only a Runner run binds its url4, and only a gateway node has a reader.
    url4: str | None = _RUN_EXPRESSION.get()
    reader: ModelSightReader | None = _READERS.get(node)
    if url4 is None or reader is None:
        return
    # Stage 2 — a text Benchmark stops here, before any gateway call.
    if not needs:
        return
    # Stage 3 — the Candidate's models.
    model_ids: Mapping[str, str] = reader.model_routes()
    routes: frozenset[str] = candidate_model_routes(url4, frozenset(model_ids))
    if not routes:
        return
    # Stage 4 — one read of the model list, then one refusal naming every gap.
    listed: Mapping[str, Sequence[str]] = await reader.input_modalities()
    candidates: list[str] = [model_ids[route] for route in routes]
    reasons: list[str] = [
        _refusal(modality, ", ".join(lacking))
        for modality in sorted(needs)
        if (lacking := models_lacking(candidates, listed, modality))
    ]
    if reasons:
        raise ResolutionError(" ".join(reasons), code=ErrorCode.INTENT_ERROR, permanent=True)


async def admit_run_attachments(
    reader: ModelSightReader,
    attachments: Sequence[Attachment],
    *,
    default_route: str | None,
    private_routes: frozenset[str] = frozenset(),
) -> None:
    """Refuse a url4 run whose files reach a model that cannot take them, before any call.

    FEATURE (OME-1809, spec 2026-11-09 §3): the Cases desk above, for a url4 run's OWN files.
    Every model call of the run awaits one shared check, so the first call admits the run and
    the gateway's model list is read once.

    Stages: (1) only a Runner run binds a holder; (2) a run whose files are all text stops;
    (3) the model routes the run can reach (:func:`run_model_routes`); (4) one list read, one
    refusal naming every gap.

    Raises:
        ResolutionError: ``intent_error`` (permanent) naming each model and what it lacks; or the
            reader's own retryable error when the model list cannot be read (fail closed).
    """

    holder: _RunAdmission | None = _RUN_ADMISSION.get()
    url4: str | None = _RUN_EXPRESSION.get()
    if holder is None or url4 is None:
        return
    needs = frozenset(
        modality
        for attachment in attachments
        if (modality := attachment_modality(attachment.media_type)) is not None
    )
    if not needs:
        return
    if holder.check is None:
        # INVARIANT: created before this coroutine's first await, so a sibling call scheduled
        # in the same run finds it and never starts a second read of the model list.
        holder.check = asyncio.ensure_future(
            _check_run(
                reader, url4, needs, default_route=default_route, private_routes=private_routes
            )
        )
    # WHY shield: one cancelled member must not cancel the check its siblings await.
    await asyncio.shield(holder.check)


async def _check_run(
    reader: ModelSightReader,
    url4: str,
    needs: frozenset[str],
    *,
    default_route: str | None,
    private_routes: frozenset[str],
) -> None:
    model_ids: Mapping[str, str] = reader.model_routes()
    routes = run_model_routes(url4, frozenset(model_ids), default_route=default_route)
    if not routes:
        return
    listed: Mapping[str, Sequence[str]] = await reader.input_modalities()
    # INVARIANT (OME-1770): a non-public route the caller's list does not carry is one the
    # caller may not know exists. Naming it would confirm it; it is left to its own call, which
    # answers url4's undeclared-route error (`world/connector.py` `_undeclared_route`).
    models = [
        model_ids[route]
        for route in routes
        if route not in private_routes or model_ids[route] in listed
    ]
    reasons: list[str] = [
        _refusal(modality, ", ".join(lacking), _RUN_REFUSALS)
        for modality in sorted(needs)
        if (lacking := models_lacking(models, listed, modality))
    ]
    if reasons:
        raise ResolutionError(" ".join(reasons), code=ErrorCode.INTENT_ERROR, permanent=True)


def run_model_routes(
    url4: str, model_routes: frozenset[str], *, default_route: str | None
) -> frozenset[str]:
    """The model routes a url4 run's files can reach.

    - A run with a linked Candidate (a Benchmark run): exactly the Candidate's routes. The
      protocol and graders are outside it, and a grading call carrying a file is refused by
      name in the connector (spec D6), so a text-only judge never refuses the run.
    - Otherwise every literal model route the url4 names, as it will execute.
    - Plus the node's default processor when some group fans out and reduces on it
      (:func:`_reduces_on_default`); a group that merges locally sends it nothing.

    INVARIANT (best-effort, as :func:`local_route_paths`): an unreadable url4 names nothing and
    fails on its own stream; a route only chosen at run time is left to the gateway backstop
    (owner Q3, 2026-11-09).
    """

    candidate = candidate_model_routes(url4, model_routes)
    found: set[str] = set(candidate or (local_route_paths(url4) & model_routes))
    recipes = _candidate_recipes(url4) if candidate else [url4]
    if default_route in model_routes and any(_reduces_on_default(r) for r in recipes):
        found.add(default_route)
    return frozenset(found)


def _candidate_recipes(url4: str) -> list[str]:
    try:
        root = build(url4)
    except (Url4Error, RecursionError):
        return []
    if not isinstance(root, Expression):
        return []
    return [
        source.value.value
        for source in root.sources
        if isinstance(source, Source)
        and source.name == CANDIDATE_BINDING
        and isinstance(source.value, Text)
    ]


def _reduces_on_default(url4: str) -> bool:
    """Whether some group in ``url4`` fans out and reduces on the node's default processor.

    Mirrors url4's lowering (``dag/_wiring.py`` ``_reduce_graph``): a parenthesised group whose
    every source is a relative-expression call, at least one contributing (weight not 0.0),
    fans out; its reduce is fetched from the default processor. Any other group merges its
    sources locally (``default_process``) and calls no model.
    """

    try:
        pending: list[Node] = [build(url4)]
    except (Url4Error, RecursionError):
        return False
    while pending:
        for child in walk(pending.pop()):
            if isinstance(child, Expression) and _fans_out(child):
                return True
            pending.extend(embedded_expressions(child, as_executed=True))
    return False


def _fans_out(group: Expression) -> bool:
    if group.intent is None or not group.sources:
        return False
    calls = [_call_weight(source) for source in group.sources]
    return all(call is not None for call in calls) and any(
        call is not None and call[0] != 0.0 for call in calls
    )


def _call_weight(source: Node) -> tuple[object] | None:
    """``(weight,)`` when ``source`` is a relative-expression call url4 can fan out, else None."""

    weight: object = None
    value: Node = source
    if isinstance(value, Source):
        if value.expand:  # an expansion changes the source count: never a fan-out
            return None
        weight, value = value.weight, value.value
    if isinstance(value, Binding):
        value = value.value
    return (weight,) if isinstance(value, RelExpr) else None


__all__ = [
    "IMAGE_MODALITY",
    "PART_MODALITIES",
    "PDF_MODALITY",
    "ModelSightReader",
    "admit_run_attachments",
    "attachment_modality",
    "candidate_model_routes",
    "cases_need_modalities",
    "cases_need_pictures",
    "models_lacking",
    "refuse_blind_candidate",
    "refuse_blind_models",
    "register_model_sight",
    "run_expression_scope",
    "run_model_routes",
    "text_only_models",
]
