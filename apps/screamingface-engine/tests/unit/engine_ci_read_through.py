"""What a read-through directory stands for: the paths its readers reach through it.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).

INVARIANT: a reader reaches a path through a directory in one of these ways, and each counts even
before the path exists:
- a `/` or `.joinpath()` join on the directory with a literal tail, as in `D / "uv.lock"`,
  reaches that path;
- a join with one name after the tail, as in `D / name`, reaches the paths that name can be when
  each binding of it gives string literals: a `for` loop or a comprehension over a literal table,
  or over a name bound to a tuple of literals and tuples, with its unpacking, or an assignment of
  a literal. WHY a tuple: a list grows in place or through another name the scan cannot see;
- any other join reaches the directory under its literal tail, because a run-time value can
  finish it with any path under it;
- a reader that passes the directory on, to a call, a container or anything but a join, reaches
  all of it, unless it is reviewed: a reviewed reader also reaches what `named_under` finds.
A tail with `..` reaches the path it resolves to, which can be outside the directory. The repo
root, `ROOT`, is read through like any directory.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable

from engine_ci_paths import ENGINE_PARTS, REPO, ROOT, Parts, normal
from engine_ci_scopes import Scopes
from engine_ci_support import scan

#: A module that reads a directory: its repo-relative file and its source.
type Reader = tuple[Parts, str]
#: Where a name sits in the target it is unpacked from, and the statement that binds it.
type Binding = tuple[list[int], ast.AST | None]
_RELATIVE = re.compile(r"[\w.-]+(?:/[\w.-]+)*")
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _chain(node: ast.expr) -> tuple[ast.expr, list[ast.expr]]:
    """The root of a `/` or `.joinpath()` join, and the operands joined to it in order."""
    match node:
        case ast.BinOp(left=left, op=ast.Div(), right=right):
            root, joined = _chain(left)
            return root, [*joined, right]
        case ast.Call(func=ast.Attribute(value=base, attr="joinpath"), args=args):
            root, joined = _chain(base)
            return root, [*joined, *args]
        case _:
            return node, []


def _joined_on(tree: ast.Module) -> set[int]:
    """The ids of the expressions in ``tree`` that a `/` or `.joinpath()` joins more onto."""
    found: set[int] = set()
    for node in ast.walk(tree):
        match node:
            case (
                ast.BinOp(left=left, op=ast.Div())
                | ast.Call(func=ast.Attribute(value=left, attr="joinpath"))
            ):
                found.add(id(left))
            case _:
                pass
    return found


def _step(node: ast.AST, parents: dict[int, ast.AST]) -> tuple[ast.AST, list[ast.expr]] | None:
    """The join that adds onto ``node``, and the operands it adds; None when none does."""
    parent = parents.get(id(node))
    match parent:
        case ast.BinOp(left=left, op=ast.Div(), right=right) if left is node:
            return parent, [right]
        case ast.Attribute(value=base, attr="joinpath") if base is node:
            call = parents.get(id(parent))
            if isinstance(call, ast.Call) and call.func is parent:
                return call, list(call.args)
        case _:
            pass
    return None


def _joined_onto(node: ast.AST, parents: dict[int, ast.AST]) -> list[ast.expr]:
    """The operands the joins on ``node`` add, in order; empty when nothing joins on it."""
    joined: list[ast.expr] = []
    step = _step(node, parents)
    while step is not None:
        node, operands = step
        joined.extend(operands)
        step = _step(node, parents)
    return joined


def _leading_strings(nodes: list[ast.expr]) -> list[str]:
    """The values of the string literals that ``nodes`` start with."""
    strings: list[str] = []
    for node in nodes:
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            break
        strings.append(node.value)
    return strings


def _path(directory: str, segments: list[str]) -> str | None:
    """``directory`` joined with ``segments``, as a repo path; None for none."""
    if any(segment.startswith("/") for segment in segments):
        return None
    split = (s for segment in segments for s in segment.split("/") if s)
    parts = normal((*directory.split("/"), *split))
    return None if parts is None else "/".join(parts) or ROOT


def _picked(items: list[ast.expr], positions: list[int]) -> list[str] | None:
    """The string at ``positions`` in each of ``items``; None when one holds none there."""
    found: list[str] = []
    for item in items:
        value = item
        for position in positions:
            elements = value.elts if isinstance(value, (ast.Tuple, ast.List)) else []
            if position >= len(elements) or any(isinstance(e, ast.Starred) for e in elements):
                return None
            value = elements[position]
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            return None
        found.append(value.value)
    return found


def _unpacked(store: ast.Name, parents: dict[int, ast.AST]) -> Binding:
    """Where ``store`` sits in the target it is part of, and the statement that binds it."""
    positions: list[int] = []
    node: ast.AST = store
    parent = parents.get(id(node))
    while isinstance(parent, (ast.Tuple, ast.List)):
        positions.insert(0, next(i for i, e in enumerate(parent.elts) if e is node))
        node, parent = parent, parents.get(id(parent))
    return positions, parent


def _parameters(scope: ast.AST) -> set[str]:
    """The names the parameters of the function ``scope`` bind; none for another scope."""
    if not isinstance(scope, _FUNCTIONS):
        return set()
    a = scope.args
    every = (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg)
    return {arg.arg for arg in every if arg is not None}


def _binds_otherwise(node: ast.AST, name: str) -> bool:
    """Whether ``node`` binds ``name`` other than as an assignment or loop target."""
    match node:
        case (
            ast.FunctionDef(name=bound)
            | ast.AsyncFunctionDef(name=bound)
            | ast.ClassDef(name=bound)
            | ast.ExceptHandler(name=str() as bound)
            | ast.MatchAs(name=str() as bound)
            | ast.MatchStar(name=str() as bound)
            | ast.MatchMapping(rest=str() as bound)
        ):
            return bound == name
        case _:
            return False


def _frozen(table: ast.expr) -> bool:
    """Whether ``table`` is a tuple of constants and of tuples of them, which nothing can change."""
    return isinstance(table, ast.Tuple) and all(
        isinstance(node, (ast.Tuple, ast.Constant, ast.expr_context)) for node in ast.walk(table)
    )


def _inside(name: str) -> bool:
    """Whether ``name`` is a relative path that stays under the directory it is joined to."""
    return bool(_RELATIVE.fullmatch(name)) and ".." not in name.split("/")


class _Read:
    """One reader of ``directory`` as the scan sees it."""

    def __init__(self, directory: str, reader: Reader) -> None:
        parts, source = reader
        self._directory = directory
        self._scanned = scan(source, parts)
        self._scopes = Scopes(self._scanned.tree)
        self._parents = {
            id(child): node
            for node in ast.walk(self._scanned.tree)
            for child in ast.iter_child_nodes(node)
        }
        #: The reader's file under the Engine, as `_READ_THROUGH` reviews it.
        self.relative = "/".join(parts[len(ENGINE_PARTS) :])
        #: The expressions that read the directory itself; `ROOT` is the repo root, `()`.
        self.sites = self._scanned.sites.get(normal(tuple(directory.split("/"))) or (), [])

    def reached(self, reviewed: frozenset[str]) -> set[str]:
        """What the reader reaches through the directory; all of it for a read the scan lost."""
        found: set[str] = set() if self.sites else {self._directory}
        for site in self.sites:
            joined = _joined_onto(site, self._parents)
            if joined:
                found |= self._reach(joined)
            elif self.relative in reviewed:
                found |= self.conflated()
            else:
                found.add(self._directory)
        return found

    def passes_on(self) -> bool:
        """Whether the reader uses the directory other than by joining onto it."""
        return any(not _joined_onto(site, self._parents) for site in self.sites)

    def conflated(self) -> set[str]:
        """The files under the directory the reader's string literals name, and what each join
        on a root the scan cannot resolve reaches as a join on the directory.
        """
        tree = self._scanned.tree
        found = {
            path
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _inside(node.value)
            and (REPO / self._directory / node.value).is_file()
            and (path := _path(self._directory, [node.value])) is not None
        }
        joined_on = _joined_on(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.expr) and id(node) not in joined_on:
                root, joined = _chain(node)
                if joined and not self._scanned.resolve(root):
                    found |= self._reach(joined)
        return found

    def _reach(self, joined: list[ast.expr]) -> set[str]:
        """What a join of ``joined`` onto the directory reaches."""
        tail = _leading_strings(joined)
        rest = joined[len(tail) :]
        ends: list[list[str]] = [[]]
        if len(rest) == 1 and isinstance(rest[0], ast.Name):
            names = self._strings(rest[0])
            ends = [[]] if names is None else [[name] for name in names]
        reached = (_path(self._directory, [*tail, *end]) for end in ends)
        return {path for path in reached if path is not None}

    def _strings(self, name: ast.Name) -> list[str] | None:
        """The string literals ``name`` can be; None when a binding of it gives another value."""
        bindings = self._bindings(name)
        if bindings is None:
            return None
        found: list[str] = []
        for positions, statement in bindings:
            match statement:
                case ast.For(iter=table) | ast.AsyncFor(iter=table) | ast.comprehension(iter=table):
                    items = self._items(table)
                case ast.Assign(value=value) | ast.AnnAssign(value=ast.expr() as value):
                    items = [value]
                case _:
                    items = None
            picked = None if items is None else _picked(items, positions)
            if picked is None:
                return None
            found += picked
        return found

    def _bindings(self, name: ast.Name) -> list[Binding] | None:
        """Each binding of ``name`` in the scope it means; None when one binds it otherwise,
        such as a parameter or an import, or none binds it.
        """
        scopes = self._scopes
        home = scopes.home(name.id, scopes.of[id(name)])
        if home is None or (id(home), name.id) in scopes.imports or name.id in _parameters(home):
            return None
        found: list[Binding] = []
        for node in ast.walk(self._scanned.tree):
            if _binds_otherwise(node, name.id) and scopes.of.get(id(node)) is home:
                return None
            if (
                isinstance(node, ast.Name)
                and node.id == name.id
                and isinstance(node.ctx, ast.Store)
                and scopes.home(node.id, scopes.of[id(node)]) is home
            ):
                found.append(_unpacked(node, self._parents))
        return found or None

    def _items(self, node: ast.expr) -> list[ast.expr] | None:
        """The elements of the literal table ``node`` is, or of the tuples the name ``node`` is
        bound to; None for anything else.
        """
        match node:
            case ast.Tuple(elts=elements) | ast.List(elts=elements) | ast.Set(elts=elements):
                starred = any(isinstance(e, ast.Starred) for e in elements)
                return None if starred else list(elements)
            case ast.Name():
                return self._table(node)
            case _:
                return None

    def _table(self, name: ast.Name) -> list[ast.expr] | None:
        """The elements of the tuples ``name`` is assigned; None when one is not a `_frozen` one."""
        bindings = self._bindings(name)
        if bindings is None:
            return None
        items: list[ast.expr] = []
        for positions, statement in bindings:
            match statement:
                case (
                    ast.Assign(value=ast.Tuple() as value)
                    | ast.AnnAssign(value=ast.Tuple() as value)
                ) if not positions and _frozen(value):
                    table: list[ast.expr] | None = list(value.elts)
                case _:
                    table = None
            if table is None:
                return None
            items += table
        return items


def named_under(directory: str, readers: Iterable[Reader]) -> set[str]:
    """The paths under ``directory`` that its readers name, each join on a run-time root taken
    for a join on ``directory``.

    A string literal names a file under it that exists. WHY only under it: a tail with `..`
    leaves it.
    """
    found: set[str] = set()
    for reader in readers:
        found |= _Read(directory, reader).conflated()
    return {path for path in found if path == directory or path.startswith(f"{directory}/")}


def reached(directory: str, readers: Iterable[Reader], reviewed: frozenset[str]) -> set[str]:
    """What the readers reach through ``directory``; ``reviewed`` names the readers, under the
    Engine, reviewed to pass it on only to joins on a root the scan cannot resolve.
    """
    found: set[str] = set()
    for reader in readers:
        found |= _Read(directory, reader).reached(reviewed)
    return found


def passes_on(directory: str, reader: Reader) -> bool:
    """Whether ``reader`` passes ``directory`` on to a value the scan cannot follow."""
    return _Read(directory, reader).passes_on()
