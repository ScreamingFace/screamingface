"""The local routes a url4 names, including the url4 it carries as text.

Two callers read routes out of a url4 without evaluating it:

- ``registry.py`` validates that a benchmark's evaluation protocol names only routes the App
  installs (``as_executed=False``: each template as written).
- The scheduling route (OME-878) admits the models a submitted url4 names BEFORE the run is
  scheduled (``as_executed=True``: also the url4 the executor parses only at run time, such as
  the ``candidate`` binding ``definition.py::link_candidate`` embeds as a text literal).

One walker serves both, so the call-context lowering rule and the route-name rule cannot drift
between install-time validation and schedule-time admission. The url4 parser does the reading —
never a regex over the whole text — so a prompt that merely mentions a model id is not a route.

WHY this lives in ``benchmarks/``: the url4 ENGINE is confined to Runner adapters and Benchmark
extensions (``tests/unit/test_url4_executor.py::test_only_engine_extensions_import_url4``).

AIDEV-NOTE: it returns route PATHS as written and knows nothing of the catalog or the route
codec; the caller decodes and gates them. Parsing is not evaluating: nothing here runs an
expression.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from url4.core.errors import ParseError, Url4Error
from url4.core.nodes import Iteration, Node, RelExpr, RelUrl, Text, walk
from url4.core.parser import build, split_top_level_commas

# WHY an empty intent: ``build`` requires a complete expression around a source list. The
# wrapper is inspected only, never evaluated or published.
_INERT_INTENT = "''"

# A path is only a route name while every segment is literal. url4's segment charset is
# ALPHA / DIGIT / "-" / "_" / "." / "~" (spec §8), and a reference may carry a call, a query or
# parameters after it — `!/reduce()` and `(/cases?limit=2)` both name the route before that tail.
_LITERAL_PATH = re.compile(r"/[A-Za-z0-9\-_.~]+(?:/[A-Za-z0-9\-_.~]+)*")
_PATH_TAILS = frozenset({"", "(", ")", "?", "#", ";", "!", ","})


def local_route_paths(url4: str) -> frozenset[str]:
    """Every literal relative route ``url4`` names on this node, as it will execute.

    INVARIANT (best-effort): never raises. A url4 the parser cannot read names nothing; the run
    then reports its own parse failure on its stream, exactly as before this walk existed.
    """
    try:
        return frozenset(relative_route_paths(build(url4), as_executed=True))
    except (Url4Error, RecursionError):
        # WHY RecursionError too: the url4 is the caller's, and the descent re-parses the text it
        # carries, so a url4 whose OWN parse fit the stack can still nest deeper through its
        # literals. A pathological one must not turn a best-effort lookup into a 500.
        return frozenset()


def relative_route_paths(root: Node, *, as_executed: bool) -> set[str]:
    """Collect literal relative routes in ``root``, including those inside its templates.

    ``as_executed`` widens the descent from the templates as written to everything the executor
    parses at run time (see ``embedded_expressions``). Only relative references count: a
    ``RemoteExpr`` is another node's route, resolved in that node's world, and its context
    executes there too.
    """
    found: set[str] = set()
    pending = [root]
    while pending:
        selected = pending.pop()
        for child in walk(selected):
            # A `/path!intent` call and a bare `(/path)` data reference both resolve against the
            # routes installed on this node, so both count.
            reference = (
                child.path
                if isinstance(child, RelExpr)
                else child.value
                if isinstance(child, RelUrl)
                else None
            )
            if reference is not None and (path := literal_route_path(reference)) is not None:
                found.add(path)
            pending.extend(embedded_expressions(child, as_executed=as_executed))
    return found


def literal_route_path(reference: str) -> str | None:
    """The route a relative reference names, or None when it names none until substitution."""

    match = _LITERAL_PATH.match(reference.strip())
    if match is None:
        return None
    # `/judge/$item` matches only as far as `/judge`, and `/judge` is not the route it will
    # resolve to. A reference whose tail continues the path is unvalidatable, not broken.
    return match.group() if reference.strip()[match.end() :][:1] in _PATH_TAILS else None


def embedded_expressions(node: Node, *, as_executed: bool) -> Iterator[Node]:
    """The url4 a node holds as raw TEXT, parsed. ``nodes.walk`` stops at that text.

    Each template is parsed on its own, so one that does not parse (an unresolved ``$`` template,
    free prose) never hides the routes of its neighbours.
    """
    for source in _embedded_sources(node, as_executed=as_executed):
        try:
            yield build(source)
        except ParseError:
            # WHY: unresolved iteration templates and free-prose contexts may be legal at
            # runtime without being parseable here; do not invent routes from that text.
            continue


def _embedded_sources(node: Node, *, as_executed: bool) -> Iterator[str]:
    match node:
        case Iteration(body=body, intent=intent, reducer=reducer):
            # WHY the body wrap when executed: the executor runs each row as `({body})!{intent}`
            # (url4 ``dag/nodes/iteration.py``), so a body may be a whole source list
            # (`a, b`) that does not parse as written. Validation keeps the templates as
            # written, which is the rule the installed benchmarks were checked against.
            if as_executed and body:
                body = f"({body})!{_INERT_INTENT}"
            yield from (template for template in (body, intent, reducer) if template)
        case RelExpr(context=context) if context and "@" not in context:
            # INVARIANT: local call contexts execute source lists, including the selector's
            # dataset, lowered caller-side (OME-535). Holdings contexts stay opaque in url4;
            # remote contexts execute elsewhere. url4 drops empty source slots (for example a
            # trailing comma) before parsing.
            slots = ",".join(filter(str.strip, split_top_level_commas(context)))
            yield f"({slots})!{_INERT_INTENT}"
        case Text(value=value) if as_executed and value.lstrip().startswith("("):
            # A text literal holding a whole expression (the ``candidate`` binding, a corrective
            # member's intent) is parsed by the executor at run time. Validation does not read
            # text literals; it keeps the scope it had before admission shared this walker.
            # WHY only "(": an embedded expression is always a parenthesised source list; a
            # prompt rarely is, and re-parsing every prompt would be wasted work.
            yield value
        case _:
            pass


__all__ = [
    "embedded_expressions",
    "literal_route_path",
    "local_route_paths",
    "relative_route_paths",
]
