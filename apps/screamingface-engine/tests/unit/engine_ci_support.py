"""Find the repo paths an Engine test uses, and read the Engine workflow's `paths:` filters.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).

INVARIANT: the scan finds every repo path outside the Engine that a test names, and whether the
test only tests that the path exists. A test names a path in one of these ways:
- a string literal that names an existing path, relative to the Engine directory, where the
  suite runs, or else to the repo root;
- `Path(<string literals>)` whose first segment is an Engine entry, `..` included, or else a
  top-level repo entry, even before the path exists;
- literal segments joined with `/` or `.joinpath()` to a repo path, even before the result
  exists, so a test that waits for a file still depends on it;
- a literal `.glob()` pattern under a repo path, which names the files it matches.
Each path is spelled without `.` or `..`; one above the repo root is no repo path, and a join
that leaves the repo that way builds no path, so its root is not a read of its own.
A repo path is the test file (`Path(__file__)`), its `.parent`, its `.parents[k]`, the first of
its `.parents` that holds a marker file, a name bound to one of those, or such a name, or
`__file__`, of a repo module the test imports. A name means what Python means by it: a name a
function binds, by assignment or import, is that function's own, and a name bound more than
once in one scope stands for every path bound to it. The scan reports the repo root joined with
a run-time name as `ROOT`, because no filter can cover it. A path built on a module outside the
repo and the standard library starts with `<import M>`, because the scan cannot tell whether M
is a repo module it failed to find; the guard accepts it only for a module it lists.

WHY a static scan: it runs in seconds with the unit suite, and it names the line that added the
read. A path finished at run time (a loop or a parameter) is seen only up to its last literal
segment. The scan reports that enclosing directory, which errs toward running the suite. So
does a path bound in a class body: a method reads it as an attribute, which the scan does not
follow. A glob under a module outside the repo reports the module. Not modelled: a path from
a call the scan does not know, such as `Path.cwd()` or `importlib.resources.files()`.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from engine_ci_modules import Imports, Modules, foreign
from engine_ci_paths import (
    ENGINE_PARTS,
    NOWHERE,
    REPO,
    ROOT,
    Parts,
    Paths,
    built_from,
    is_path_call,
    join,
    literal,
    literal_path,
    normal,
    strings,
    up,
)
from engine_ci_scopes import Scopes

WORKFLOW = REPO / ".github" / "workflows" / "screamingface-engine-tests.yml"
_EXISTENCE_CHECKS: dict[str, Callable[[Path], bool]] = {
    "exists": Path.exists,
    "is_dir": Path.is_dir,
    "is_file": Path.is_file,
}
#: Path methods whose arguments only take part in path arithmetic, never in a read.
_ARITHMETIC = frozenset({"relative_to", "is_relative_to"})


class Use(NamedTuple):
    """The first line that names a path, and whether every use only tests that it exists."""

    line: int
    exists_only: bool


type Named = list[tuple[Parts, Use]]


class _Resolver:
    """Resolves the path expressions of one test module to the repo-relative paths they can be."""

    def __init__(self, tree: ast.Module, file_parts: Parts, modules: Modules) -> None:
        self._tree = tree
        self._file = file_parts
        self._scopes = Scopes(tree)
        self._imports = Imports(self._scopes, file_parts, modules)
        self._names: dict[tuple[int, str], Paths] = {}
        #: Each marker file a `.parents` search found, with the line of the search.
        self.markers: dict[Parts, int] = {}
        #: The ids of the joins that leave the repo above its root: they build no repo path.
        self.left: set[int] = set()

    def resolve(self, node: ast.expr) -> Paths:
        """The repo-relative paths ``node`` can evaluate to; empty when it is not a repo path."""
        paths = NOWHERE
        match node:
            # WHY: only a loaded name; the target of `X = ...` is a binding, not a read.
            case ast.Name(id=name, ctx=ast.Load()):
                paths = self._named(name, node)
            case ast.Call():
                paths = self._call(node)
            case ast.Attribute(value=base, attr="parent"):
                paths = up(self._root(base), 1)
            case ast.Subscript(
                value=ast.Attribute(value=base, attr="parents"),
                slice=ast.Constant(value=int() as level),
            ):
                paths = up(self._root(base), level + 1)
            case ast.Attribute(value=base, attr=name):
                paths = self._imports.attribute(base, name)
            case ast.BinOp(left=left, op=ast.Div(), right=ast.Constant(value=str() as segment)):
                paths = self._joined(node, left, [segment])
            case _:
                pass
        return paths

    def module_value(self, name: str) -> Paths:
        """The paths the module-level ``name`` can be."""
        return self._bound(self._scopes.module, name)

    def rebind(self) -> int:
        """Binds every name again from the first statement; how many paths the names hold.

        WHY from the start: `X = X / "a"` would otherwise grow with every reading.
        """
        self._names = {}
        self.bind(self._tree)
        return sum(len(paths) for paths in self._names.values())

    def _named(self, name: str, node: ast.AST) -> Paths:
        """The paths bound to ``name`` in the scope it means at ``node``."""
        home = self._scopes.home(name, self._scopes.of[id(node)])
        return NOWHERE if home is None else self._bound(home, name)

    def _bound(self, home: ast.AST, name: str) -> Paths:
        """The paths ``name`` is bound to in the scope ``home``, by assignment or import."""
        return self._names.get((id(home), name), NOWHERE) | self._imports.value(home, name)

    def _root(self, node: ast.expr) -> Paths:
        """The paths ``node`` can be as the root of a path; `<import M>` for a module outside."""
        match node:
            case ast.Call(func=func, args=[inner]) if is_path_call(func):
                return self.resolve(node) or self._imports.foreign(inner)
        return self.resolve(node) or self._imports.foreign(node)

    def _joined(self, node: ast.expr, base: ast.expr, segments: list[str] | None) -> Paths:
        """``base`` joined with literal ``segments``; notes ``node`` when it leaves the repo."""
        roots = self._root(base)
        paths = join(roots, segments)
        if roots and segments is not None and not paths:
            self.left.add(id(node))
        return paths

    def _call(self, node: ast.Call) -> Paths:
        """The repo-relative paths a call can evaluate to; empty when it is not a repo path."""
        paths = NOWHERE
        match node:
            case ast.Call(func=func, args=args) if is_path_call(func):
                paths = self._path(args)
            case ast.Call(func=ast.Attribute(value=base, attr="resolve"), args=[]):
                paths = self._root(base)
            case ast.Call(func=ast.Attribute(value=base, attr="joinpath"), args=args):
                paths = self._joined(node, base, strings(args))
            case ast.Call(func=ast.Name(id="next"), args=[ast.GeneratorExp() as search]):
                paths = self._marked(search)
            case _:
                pass
        return paths

    def _path(self, args: list[ast.expr]) -> Paths:
        """The repo paths `Path(*args)` can be."""
        match args:
            case [ast.Name(id="__file__")]:
                paths = frozenset({self._file})
            case [ast.Attribute(value=module, attr="__file__")]:
                paths = frozenset(self._imports.files(module))
            case [arg] if not isinstance(arg, ast.Constant):
                paths = self.resolve(arg)
            case _:
                paths = literal_path(strings(args))
        return paths

    def _marked(self, search: ast.GeneratorExp) -> Paths:
        """The first of ``X.parents`` that holds a marker, as the search finds it at run time.

        The search is `next(p for p in X.parents if (p / "marker").is_file())`, with any of the
        existence checks. WHY evaluate it: the guard runs in the same checkout as the test.
        """
        match search:
            case ast.GeneratorExp(
                elt=ast.Name(id=found),
                generators=[
                    ast.comprehension(
                        target=ast.Name(id=each),
                        iter=ast.Attribute(value=base, attr="parents"),
                        ifs=[
                            ast.Call(
                                func=ast.Attribute(
                                    value=ast.BinOp(
                                        left=ast.Name(id=probe),
                                        op=ast.Div(),
                                        right=ast.Constant(value=str() as marker),
                                    ),
                                    attr=check,
                                ),
                                args=[],
                            )
                        ],
                    )
                ],
            ) if found == each == probe and check in _EXISTENCE_CHECKS:
                found_roots: set[Parts] = set()
                for start in self.resolve(base):
                    ancestor = self._ancestor(start, marker, check, search.lineno)
                    if ancestor is not None:
                        found_roots.add(ancestor)
                return frozenset(found_roots)
            case _:
                return NOWHERE

    def _ancestor(self, start: Parts, marker: str, check: str, line: int) -> Parts | None:
        """The first parent of ``start`` that holds ``marker``; records the marker it found."""
        tail = tuple(s for s in marker.split("/") if s)
        for level in range(1, len(start) + 1):
            ancestor = start[: len(start) - level]
            if _EXISTENCE_CHECKS[check](REPO.joinpath(*ancestor, *tail)):
                self.markers.setdefault(ancestor + tail, line)
                return ancestor
        return None

    def bind(self, tree: ast.Module) -> set[int]:
        """Binds each ``NAME = <repo path>``; the ids of the values that only name a path.

        WHY this order: a module's code runs first and a function body only when it is called, so
        each scope's statements bind in source order after those of the scopes around it.
        INVARIANT: a path bound in a class body counts as read, because a method reads it as an
        attribute, which the scan does not follow.
        """
        scopes = self._scopes
        statements = sorted(
            (n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))),
            key=lambda n: (scopes.depth[id(scopes.of[id(n)])], n.lineno, n.col_offset),
        )
        named: set[int] = set()
        for statement in statements:
            match statement:
                case (
                    ast.Assign(targets=[ast.Name(id=name)], value=value)
                    | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
                ):
                    scope = scopes.of[id(statement)]
                    home = scopes.home(name, scope) or scope
                    if paths := self.resolve(value):
                        key = (id(home), name)
                        self._names[key] = self._names.get(key, NOWHERE) | paths
                        if not isinstance(home, ast.ClassDef):
                            named.add(id(value))
                case _:
                    pass
        return named


def _docstrings(tree: ast.Module) -> set[int]:
    """The ids of every docstring constant in ``tree``."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            match node.body:
                case [ast.Expr(value=ast.Constant(value=str()) as docstring), *_]:
                    found.add(id(docstring))
                case _:
                    pass
    return found


def _glob_call(
    node: ast.expr, resolved: dict[int, Paths]
) -> tuple[ast.expr, list[Path], str] | None:
    """``(base, roots, pattern)`` when ``node`` globs a literal pattern under a repo path."""
    match node:
        case ast.Call(
            func=ast.Attribute(value=base, attr="glob" | "rglob" as method),
            args=[ast.Constant(value=str() as pattern)],
        ) if id(base) in resolved and not any(p and foreign(p[0]) for p in resolved[id(base)]):
            # WHY: `rglob(p)` is `glob("**/" + p)`.
            roots = [REPO.joinpath(*parts) for parts in sorted(resolved[id(base)])]
            return base, roots, ("**/" if method == "rglob" else "") + pattern
        case _:
            return None


def _not_reads(node: ast.expr, resolved: dict[int, Paths], left: set[int]) -> list[ast.expr]:
    """The sub-expressions of ``node`` that only build a path, relate two, or root a glob."""
    inner = built_from(node) if id(node) in resolved or id(node) in left else []
    match node:
        case ast.Call(func=ast.Attribute(attr=method), args=args) if method in _ARITHMETIC:
            inner.extend(args)
        case _:
            pass
    if (globbed := _glob_call(node, resolved)) is not None:
        inner.append(globbed[0])
    return inner


def _checked(nodes: list[ast.expr]) -> set[int]:
    """The ids of each path only tested for existence: the checked path, and a literal in it.

    WHY not its other parts: in `(SDK / "src" / name).is_file()` the run-time `name` leaves
    `SDK / "src"` as the deepest known part of an unknown path, so it counts as a read.
    """
    found: set[int] = set()
    for node in nodes:
        if isinstance(node, ast.Attribute) and node.attr in _EXISTENCE_CHECKS:
            found.add(id(node.value))
            found.update(id(n) for n in ast.walk(node.value) if isinstance(n, ast.Constant))
    return found


def _outside(named: Named) -> dict[str, Use]:
    """The paths outside the Engine among ``named``, each with its first use."""
    found: dict[str, Use] = {}
    for parts, use in sorted(named, key=lambda entry: entry[1].line):
        if parts[: len(ENGINE_PARTS)] == ENGINE_PARTS:
            continue
        path = "/".join(parts) or ROOT
        first = found.setdefault(path, use)
        # INVARIANT: a path that any use reads is read.
        found[path] = first._replace(exists_only=first.exists_only and use.exists_only)
    return found


def _read(tree: ast.Module, file_parts: Parts, modules: Modules) -> _Resolver:
    """A module a test imports, read by the same scan; `Modules` binds its names."""
    return _Resolver(tree, file_parts, modules)


def scan_modules(repo: Path) -> Modules:
    """The modules of the repo at ``repo``, each read once by this scan for every test."""
    return Modules(repo, ENGINE_PARTS, _read)


_MODULES = scan_modules(REPO)


class Scanned(NamedTuple):
    """One test module as the scan sees it."""

    tree: ast.Module
    #: The repo paths an expression of ``tree`` can be.
    resolve: Callable[[ast.expr], Paths]
    #: The expressions that read each repo path, existence checks left out.
    sites: dict[Parts, list[ast.expr]]


def _reads(tree: ast.Module, resolver: _Resolver) -> list[tuple[Parts, Use, ast.expr | None]]:
    """Each repo path ``tree`` names, its use, and the expression that names it, if one does."""
    consumed = _docstrings(tree) | resolver.bind(tree)
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.expr)]
    resolved = {id(n): paths for n in nodes if (paths := resolver.resolve(n))}
    checked = _checked(nodes)
    found: list[tuple[Parts, Use, ast.expr | None]] = [
        (marker, Use(line, True), None) for marker, line in resolver.markers.items()
    ]
    for node in nodes:
        consumed.update(id(inner) for inner in _not_reads(node, resolved, resolver.left))
        if (globbed := _glob_call(node, resolved)) is not None:
            _, roots, pattern = globbed
            use = Use(node.lineno, id(node) in checked)
            # WHY normal: `glob("../x")` spells each match with the `..` in it.
            matches = (normal(m.relative_to(REPO).parts) for r in roots for m in r.glob(pattern))
            found.extend((parts, use, None) for parts in matches if parts is not None)
    for node in nodes:
        if id(node) not in consumed:
            use = Use(node.lineno, id(node) in checked)
            found.extend((parts, use, node) for parts in resolved.get(id(node)) or literal(node))
    return found


def scan(source: str, file_parts: Parts, modules: Modules = _MODULES) -> Scanned:
    """``source``, a test module at ``file_parts``, as the scan sees it."""
    tree = ast.parse(source)
    resolver = _Resolver(tree, file_parts, modules)
    sites: dict[Parts, list[ast.expr]] = {}
    for parts, use, node in _reads(tree, resolver):
        if node is not None and not use.exists_only:
            sites.setdefault(parts, []).append(node)
    return Scanned(tree, resolver.resolve, sites)


def uses(source: str, file_parts: Parts, modules: Modules = _MODULES) -> dict[str, Use]:
    """Every repo path outside the Engine that ``source`` uses, with its first use."""
    tree = ast.parse(source)
    found = _reads(tree, _Resolver(tree, file_parts, modules))
    return _outside([(parts, use) for parts, use, _ in found])


#: GitHub's filter pattern tokens, from its "Filter pattern cheat sheet".
_GLOB_TOKEN = re.compile(r"\*\*/|\*\*|\*|\[[A-Za-z0-9-]+\]|[?+]")
_GLOB_REGEX = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*"}


def glob(pattern: str) -> re.Pattern[str]:
    """A GitHub `paths:` filter pattern as a regex.

    `**/` matches no directory or any number of them, `**` any characters, `*` any but `/`. `?`
    and `+` repeat the character before them zero-or-one and one-or-more times, and `[...]` is a
    character class. Every other character matches itself.
    """
    out: list[str] = []
    end = 0
    for token in _GLOB_TOKEN.finditer(pattern):
        out += [re.escape(pattern[end : token.start()]), _GLOB_REGEX.get(token[0], token[0])]
        end = token.end()
    out.append(re.escape(pattern[end:]))
    return re.compile("".join(out))


def filters() -> dict[str, list[str]]:
    """The `paths:` list of each trigger of the Engine workflow."""
    document: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # WHY: YAML 1.1 reads a bare `on:` key as the boolean True.
    triggers: dict[str, Any] = document["on"] if "on" in document else document[True]
    return {event: list(triggers[event]["paths"]) for event in ("push", "pull_request")}
