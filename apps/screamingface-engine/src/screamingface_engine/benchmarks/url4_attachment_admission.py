"""Refuse a url4 run's attachments for models that can't read them, before any model call.

FEATURE (OME-1809, spec #1450 C9; owner decisions A + i, 2026-11-03). STORY: as an ensemble author
I attach a picture or a PDF to a url4 run; if any model the run will call can't read it, the run is
refused by that model's name before anything is sent or billed — not after the capable members have
answered and the blind one failed upstream (OME-1551 e2e F4).

Stages, in execution order:

1. **Only a Runner run with files.** The run's url4 is bound by the Runner
   (:func:`~screamingface_engine.benchmarks.picture_admission.run_expression_scope`), the same stage
   1 as picture admission; a call carrying no attachments returns at once and never reads the list.
2. **What the files need.** Each file becomes the content part the connector sends
   (:func:`part_type_for`), and each part type needs an input type (``PART_MODALITIES``).
3. **Up front, once per run (owner A).** The run's FIRST model call compiles the run's url4 with
   url4's own compiler and walks the graph (:func:`run_model_routes`): members, the fan-out reducer
   (the run's processor), literal ``processor=`` routes, lazy fragments, map bodies and a Candidate
   carried as text. One read of ``/v1/models`` then refuses EVERY blind model in one permanent
   ``intent_error`` before any request is sent. Concurrent calls of the run wait on that one
   admission, keyed on the run's frozen files (``RunFiles``).
4. **Per call (owner i).** Every call carrying files re-checks its own model against the same read
   before it sends, so a model only known at run time (a computed ``processor=``) is refused before
   ITS send.

Worked example: ``(/openai/gpt-4o-mini(..)!.., /ollama/llama3~8b(..)!..)!'Merge.'`` over a PNG, node
default processor ``/openai/gpt-4o-mini``. Stage 2 needs ``image``; stage 3 finds both members and
the reducer, the gateway lists llama as ``["text"]``, so the run is refused naming
``ollama/llama3:8b (image)`` — the gateway id, never the provider (e2e N3) — with 0 chat calls.

INVARIANT (owner 2026-10-28, PDFs 2026-11-02): an unreadable model list fails closed, retryable
``resolution_failed``, nothing spent. A model the gateway does not list reads text only (OME-1537).
AIDEV-NOTE: lives in ``benchmarks/`` beside picture admission because the url4 ENGINE may only be
imported by Runner adapters and Benchmark extensions (``test_only_engine_extensions_import_url4``);
the connector calls :func:`admit_attachments` through the ``ModelSightReader`` port it already owns.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from weakref import WeakKeyDictionary

from screamingface_engine.benchmarks.expression_routes import literal_route_path
from screamingface_engine.benchmarks.picture_admission import (
    PART_MODALITIES,
    ModelSightReader,
    current_run_expression,
)
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import compile_expression
from url4.dag.attachments import RunFiles, current_run_files
from url4.dag.nodes import FanoutReduceNode, LazyExprNode, MapNode, ReduceNode, RelUrlNode, TextNode

logger = logging.getLogger(__name__)

IMAGE_PART = "image_url"
FILE_PART = "file"

_MAX_FRAGMENTS = 64
"""How many url4 texts one walk compiles (the run's own plus the fragments it carries).

WHY a cap: the fragments come from the caller's url4; a walk past it is incomplete, never wrong,
because the per-call guard still checks every call that carries files.
"""


class _MediaFile(Protocol):
    @property
    def media_type(self) -> str: ...


def part_type_for(media_type: str) -> str:
    """The content part a file becomes: ``image_url`` for any ``image/*``, else ``file``.

    INVARIANT: the one rule `world/attachment_parts.py` builds its parts with, so the admission
    checks the part a model is actually sent.
    """
    bare = media_type.split(";", 1)[0].strip().lower()
    return IMAGE_PART if bare.startswith("image/") else FILE_PART


def attachment_needs(files: Iterable[_MediaFile]) -> frozenset[str]:
    """The input types the files need, through the shared ``PART_MODALITIES`` table."""
    return frozenset(PART_MODALITIES[part_type_for(file.media_type)] for file in files)


# --- stage 3: which models a run calls ----------------------------------------------------------


@dataclass(frozen=True)
class _Calls:
    """What one graph node tells the walk: routes it calls, url4 it runs later, a reduce."""

    routes: tuple[str, ...] = ()
    fragments: tuple[str, ...] = ()
    reduces: bool = False


def _calls_of(node: object) -> _Calls:
    """The model calls one compiled url4 node makes, read from its url4 node type.

    WHY one table: these are url4's DAG node types (``url4.dag.nodes``), not a published
    contract. Every dependency on their names and fields sits in :data:`_NODE_CALLS`, so a url4
    change to them is one edit, and the walk tests pin each shape. A shape the table does not know
    adds nothing; the per-call guard still checks that call before it sends.
    """
    read: Callable[[Any], _Calls] | None = _NODE_CALLS.get(type(node))
    return _Calls() if read is None else read(node)


def _fetch_calls(node: RelUrlNode) -> _Calls:
    # A templated path (`/m/$name`) resolves at run time: `literal_route_path` gives None.
    routes = [literal_route_path(node.path)]
    routes += [_processor_route(value) for key, value in node.params if key == "processor"]
    return _Calls(routes=tuple(route for route in routes if route is not None))


def _map_calls(node: MapNode) -> _Calls:
    # Each row spawns exactly this text (`MapNode.resolve`), `$item` still in it.
    body = f"({node.body})!{node.intent}" if node.intent else f"({node.body})"
    return _Calls(fragments=(body,))


def _reduce_calls(node: ReduceNode) -> _Calls:
    # A relative-expression reducer (`/reduce(all)`) is a fetch of its route.
    route = literal_route_path(node.reducer)
    return _Calls(routes=() if route is None else (route,))


def _text_calls(node: TextNode) -> _Calls:
    # A text literal holding a whole expression (a linked Candidate) runs later; the same rule
    # as `expression_routes.embedded_expressions`.
    holds_expression = node.template.lstrip().startswith("(")
    return _Calls(fragments=(node.template,) if holds_expression else ())


_NODE_CALLS: Mapping[type, Callable[[Any], _Calls]] = {
    RelUrlNode: _fetch_calls,
    # The reduce fetches the run's processor (`url4.dag.nodes.group.FanoutReduceNode`).
    FanoutReduceNode: lambda _node: _Calls(reduces=True),
    LazyExprNode: lambda node: _Calls(fragments=(node.text,)),
    MapNode: _map_calls,
    ReduceNode: _reduce_calls,
    TextNode: _text_calls,
}


def _processor_route(value: str | None) -> str | None:
    """The route a literal ``processor=`` names; ``None`` for a computed or remote one."""
    if value is None or value.lstrip().startswith("(") or "://" in value:
        return None
    text = value.strip()
    return literal_route_path(text if text.startswith("/") else f"/{text}")


def _children(node: object) -> Iterator[object]:
    """A node's graph children: its ``deps`` and any attribute that is itself a node.

    WHY attributes too: a guard holds its subtree as ``inner``, deliberately not a dependency.
    """
    for value in vars(node).values() if hasattr(node, "__dict__") else ():
        if isinstance(value, Mapping):
            yield from (child for child in value.values() if hasattr(child, "resolve"))
        elif hasattr(value, "resolve"):
            yield value


def _graph(text: str, *, fragment: bool) -> object | None:
    """The compiled sink of ``text``, or ``None`` when it does not compile."""
    try:
        # WHY bare_root_ok for a fragment: url4's spawn boundary compiles its own wrappers (a
        # map row's `(body)`) the same way; the run's own url4 keeps the user grammar.
        return compile_expression(text, bare_root_ok=fragment).sink
    except Exception:  # noqa: BLE001 - best effort: the run reports its own parse failure
        return None


def run_model_routes(
    url4: str, model_routes: frozenset[str], *, default_route: str | None
) -> frozenset[str]:
    """Every model route ``url4`` will call that can be known before it runs.

    ``default_route`` is the run's processor: the node's ``default_processor``, which every
    fan-out reduce fetches. Never raises: a url4 that does not compile names nothing.
    """
    found: set[str] = set()
    reduces = False
    pending: list[tuple[str, bool]] = [(url4, False)]
    compiled: set[str] = set()
    while pending and len(compiled) < _MAX_FRAGMENTS:
        text, fragment = pending.pop()
        if text in compiled:
            continue
        compiled.add(text)
        sink = _graph(text, fragment=fragment)
        if sink is None:
            continue
        for node in _walk(sink):
            calls = _calls_of(node)
            found.update(calls.routes)
            reduces = reduces or calls.reduces
            pending.extend((fragment_text, True) for fragment_text in calls.fragments)
    if reduces and default_route is not None:
        found.add(default_route)
    return frozenset(found) & model_routes


def _walk(sink: object) -> Iterator[object]:
    seen: set[int] = set()
    stack = [sink]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        yield node
        stack.extend(_children(node))


# --- stages 1, 2 and 4: the admission -----------------------------------------------------------


@dataclass(frozen=True)
class _Admission:
    """One run's admission, settled: the model list it read, or the refusal it ended in.

    WHY data, not an exception: the outcome outlives the call that computed it (every later call of
    the run reads it), and a stored exception would pin its traceback's frames — and the run's
    files with them — for as long as the run's entry lives.
    """

    listed: Mapping[str, Sequence[str]]
    refusal: tuple[str, str, bool] | None = None  # message, code, permanent

    def raise_refusal(self) -> None:
        if self.refusal is not None:
            message, code, permanent = self.refusal
            raise ResolutionError(message, code=code, permanent=permanent)


_ADMISSIONS: WeakKeyDictionary[RunFiles, asyncio.Future[_Admission]] = WeakKeyDictionary()
"""Each run's one admission, keyed on its frozen files: every call of the run shares one object."""

_IN_FLIGHT: set[asyncio.Task[None]] = set()
"""Admission reads in progress: asyncio keeps only a weak reference to a task."""


async def admit_attachments(
    reader: ModelSightReader,
    path: str,
    attachments: Sequence[_MediaFile],
    *,
    default_route: str | None,
) -> None:
    """Refuse this model call, and on the run's first call the whole run, for blind models.

    Raises:
        ResolutionError: ``intent_error`` (permanent), naming each blind model and what it lacks;
            or retryable ``resolution_failed`` when the model list cannot be read.
    """
    # Stage 1 — no files, or not a Runner run: nothing to check and no list read.
    if not attachments:
        return
    url4: str | None = current_run_expression()
    if url4 is None:
        return
    # Stage 2.
    needs: frozenset[str] = attachment_needs(attachments)
    # Stage 3 — once per run, shared.
    admission: _Admission = await _run_admission(reader, url4, needs, default_route)
    admission.raise_refusal()
    # Stage 4 — this call's own model, against the same read.
    model_id: str | None = reader.model_routes().get(path)
    if model_id is not None:
        message = _refusal_message([model_id], admission.listed, needs, _NOT_SENT_THIS_CALL)
        if message is not None:
            raise ResolutionError(message, code=ErrorCode.INTENT_ERROR, permanent=True)


async def _run_admission(
    reader: ModelSightReader, url4: str, needs: frozenset[str], default_route: str | None
) -> _Admission:
    pending: asyncio.Future[_Admission] = _shared_admission(reader, url4, needs, default_route)
    # WHY shield: one caller's cancellation must not cancel the admission its siblings wait on.
    return await asyncio.shield(pending)


def _shared_admission(
    reader: ModelSightReader, url4: str, needs: frozenset[str], default_route: str | None
) -> asyncio.Future[_Admission]:
    """The run's admission, started by its first call. Synchronous, so no two calls both start."""
    files: RunFiles | None = current_run_files()
    if files is not None and (existing := _ADMISSIONS.get(files)) is not None:
        return existing
    pending: asyncio.Future[_Admission] = asyncio.get_running_loop().create_future()
    if files is not None:
        _ADMISSIONS[files] = pending
    # WHY a task: the read must finish for the siblings even when the call that started it is
    # cancelled. It runs in a copy of this call's context, so it reads as this run's caller.
    task = asyncio.ensure_future(_settle(pending, reader, url4, needs, default_route))
    _IN_FLIGHT.add(task)
    task.add_done_callback(_IN_FLIGHT.discard)
    return pending


async def _settle(
    pending: asyncio.Future[_Admission],
    reader: ModelSightReader,
    url4: str,
    needs: frozenset[str],
    default_route: str | None,
) -> None:
    try:
        admission = await _admit_run(reader, url4, needs, default_route)
    except ResolutionError as exc:
        admission = _Admission({}, (str(exc), exc.code, exc.permanent))
    except Exception as exc:  # noqa: BLE001 - fail closed: an unchecked run sends nothing
        logger.warning("url4 attachment admission failed error=%s", type(exc).__name__)
        admission = _Admission(
            {},
            (
                "this run's attachments could not be checked against its models; nothing was "
                "sent to a model",
                ErrorCode.RESOLUTION_FAILED,
                False,
            ),
        )
    if not pending.done():
        pending.set_result(admission)


async def _admit_run(
    reader: ModelSightReader, url4: str, needs: frozenset[str], default_route: str | None
) -> _Admission:
    """Stage 3: one read of the list, then one refusal naming every blind model known up front."""
    listed: Mapping[str, Sequence[str]] = await reader.input_modalities()
    model_ids: Mapping[str, str] = reader.model_routes()
    routes = run_model_routes(url4, frozenset(model_ids), default_route=default_route)
    message = _refusal_message(
        [model_ids[route] for route in routes], listed, needs, _NOT_SENT_AT_ALL
    )
    if message is None:
        return _Admission(listed)
    return _Admission(listed, (message, ErrorCode.INTENT_ERROR, True))


_NOT_SENT_AT_ALL = "Nothing was sent to a model."
_NOT_SENT_THIS_CALL = "This call was not sent."


def _refusal_message(
    model_ids: Iterable[str],
    listed: Mapping[str, Sequence[str]],
    needs: frozenset[str],
    closing: str,
) -> str | None:
    """One sentence naming each blind model by gateway id and the input types it lacks.

    INVARIANT (e2e N3): a model is named by its gateway id, never by its provider.
    INVARIANT (OME-1537): a model the gateway does not list reads text only.
    """
    lacking: dict[str, list[str]] = {}
    for model_id in sorted(set(model_ids)):
        missing = sorted(need for need in needs if need not in listed.get(model_id, ()))
        if missing:
            lacking[model_id] = missing
    if not lacking:
        return None
    names = ", ".join(f"{model_id} ({', '.join(missing)})" for model_id, missing in lacking.items())
    logger.info("url4 attachments refused models=%s", names)
    return (
        f"This url4 run's attachments cannot be read by these models: {names}. The gateway does "
        "not list those input types for them, and a model it knows nothing about reads text "
        f"only. {closing}"
    )


__all__ = [
    "FILE_PART",
    "IMAGE_PART",
    "admit_attachments",
    "attachment_needs",
    "part_type_for",
    "run_model_routes",
]
