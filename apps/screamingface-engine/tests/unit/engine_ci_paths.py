"""Repo-relative paths built from the literals of a test, for the Engine CI path scan.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).

INVARIANT: a path is the tuple of its segments under the repo root; the root itself is `()`. A
path built on a module outside the repo starts with `<import M>`, and stays at least that. A
path holds no `.` or `..` segment: `normal` takes them out, and a path above the repo root is
no repo path.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from engine_ci_modules import foreign

REPO = Path(__file__).resolve().parents[4]
ENGINE_PARTS = ("apps", "screamingface-engine")
#: The scan's name for the repo root joined with a run-time name.
ROOT = "."
_PATH_LITERAL = re.compile(r"[\w.-]+(?:/[\w.-]+)+")

type Parts = tuple[str, ...]
#: The repo-relative paths an expression can be; empty when it is not a repo path.
type Paths = frozenset[Parts]
NOWHERE: Paths = frozenset()


def up(paths: Paths, levels: int) -> Paths:
    """Each of ``paths`` up ``levels`` segments: above the repo root drops, a module stays."""
    kept: set[Parts] = set()
    for parts in paths:
        if parts and foreign(parts[0]):
            kept.add(parts[: max(len(parts) - levels, 1)])
        elif levels <= len(parts):
            kept.add(parts[: len(parts) - levels])
    return frozenset(kept)


def normal(parts: Parts) -> Parts | None:
    """``parts`` without `.`, each `..` taking the segment before it away; None above the root.

    WHY: the file system resolves `apps/screamingface-engine/../aigateway` to `apps/aigateway`,
    and a filter matches only the resolved spelling. A module outside the repo stays.
    """
    kept: list[str] = []
    for segment in parts:
        if segment == "..":
            if not kept:
                return None
            if len(kept) > 1 or not foreign(kept[0]):
                kept.pop()
        elif segment != ".":
            kept.append(segment)
    return tuple(kept)


def join(paths: Paths, segments: list[str] | None) -> Paths:
    """Each of ``paths`` joined with literal ``segments``; none when a segment is unknown."""
    if segments is None:
        return NOWHERE
    tail = tuple(s for segment in segments for s in segment.split("/") if s)
    joined = (normal(parts + tail) for parts in paths)
    return frozenset(parts for parts in joined if parts is not None)


def strings(nodes: list[ast.expr]) -> list[str] | None:
    """The values of ``nodes`` when every one is a string literal."""
    values = [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return values if len(values) == len(nodes) else None


def is_path_call(func: ast.expr) -> bool:
    """``Path`` or ``pathlib.Path``."""
    match func:
        case ast.Name(id="Path") | ast.Attribute(value=ast.Name(id="pathlib"), attr="Path"):
            return True
        case _:
            return False


def literal_path(segments: list[str] | None) -> Paths:
    """The path `Path(<string literals>)` names, even before it exists; empty for no repo path.

    WHY the first segment decides: a relative path names an Engine path when the Engine holds
    its first segment, and a repo path when the repo root does. So `../aigateway` leaves the
    Engine, where the suite runs. An absolute path is neither.
    """
    text = "/".join(segments or [])
    parts = tuple(segment for segment in text.split("/") if segment)
    if not parts or text.startswith("/"):
        return NOWHERE
    if REPO.joinpath(*ENGINE_PARTS, parts[0]).exists():
        parts = ENGINE_PARTS + parts
    elif not REPO.joinpath(parts[0]).exists():
        return NOWHERE
    found = normal(parts)
    return NOWHERE if found is None else frozenset({found})


def built_from(node: ast.expr) -> list[ast.expr]:
    """The sub-expressions a resolved ``node`` is built from; they are not reads themselves."""
    inner: list[ast.expr] = []
    match node:
        case ast.BinOp(left=left, right=right):
            inner = [left, right]
        case ast.Call(func=func, args=args) if is_path_call(func):
            inner = list(args)
        case ast.Attribute(value=base) | ast.Subscript(value=ast.Attribute(value=base)):
            inner = [base]
        case ast.Call(func=ast.Attribute(value=base) as func, args=args) if not is_path_call(func):
            inner = [base, *args]
        case _:
            pass
    return inner


def literal(node: ast.expr) -> Paths:
    """The repo path a string literal names; empty for anything else.

    WHY only an existing path: a string such as `application/json` is not one. WHY the Engine
    first: the suite runs in the Engine directory, so a path that exists there, or leaves it
    with `..`, starts there; an Engine path is then left out as local.
    """
    match node:
        case ast.Constant(value=str() as text) if _PATH_LITERAL.fullmatch(text):
            parts = tuple(text.split("/"))
            for found in (normal(ENGINE_PARTS + parts), normal(parts)):
                if found is not None and REPO.joinpath(*found).exists():
                    return frozenset({found})
            return NOWHERE
        case _:
            return NOWHERE
