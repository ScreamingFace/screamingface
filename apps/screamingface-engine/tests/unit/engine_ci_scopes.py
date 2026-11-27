"""Python's name scopes in one module, for the Engine CI path scan (`engine_ci_support`).

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).
"""

from __future__ import annotations

import ast
from typing import NamedTuple

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


class Imported(NamedTuple):
    """What an import binds a name to: ``module`` itself, or its attribute ``name``."""

    module: str
    name: str | None
    #: The dots of a relative import; 0 for an absolute one.
    level: int


class Scopes:
    """Python's name scopes in one module: the scope each node runs in, and what each one binds.

    WHY: a name a function binds is local to the whole function and leaves the module name of the
    same spelling alone. A method does not see its class body's names. A comprehension has a scope
    of its own, but its first iterable runs in the enclosing one. Assignments, parameters,
    imports, `global` and `nonlocal` are modelled, so a local import hides a module name of the
    same spelling. Another binding form, such as a `def`, an `except` target or a `match`
    capture, lets a lookup reach the enclosing scope. That errs toward more paths: a `def` or
    an `except` target binds no path, and a `match` subject is reported itself.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.module = tree
        self.of: dict[int, ast.AST] = {}
        self.depth: dict[int, int] = {}
        self._parent: dict[int, ast.AST | None] = {}
        self._bound: dict[int, set[str]] = {}
        self._global: dict[int, set[str]] = {}
        #: Names a scope declares `global` or `nonlocal`: they are not its own.
        self._declared: dict[int, set[str]] = {}
        #: What each import binds, by the scope that owns the name and the name.
        self.imports: dict[tuple[int, str], list[Imported]] = {}
        self._pending: list[tuple[ast.AST, str, Imported]] = []
        self._open(tree, None)
        self._enter(tree, tree)
        # WHY after the walk: a `nonlocal` name belongs to the enclosing scope that binds it,
        # which is known only once every scope is open.
        for scope, name, imported in self._pending:
            home = self.home(name, scope) or scope
            self.imports.setdefault((id(home), name), []).append(imported)

    def home(self, name: str, scope: ast.AST) -> ast.AST | None:
        """The scope whose binding ``name`` means in ``scope``; None for a builtin."""
        if name in self._global[id(scope)]:
            return self.module
        current: ast.AST | None = scope
        while current is not None:
            visible = current is scope or not isinstance(current, ast.ClassDef)
            if visible and name in self._bound[id(current)] - self._declared[id(current)]:
                return current
            current = self._parent[id(current)]
        return None

    def _open(self, scope: ast.AST, parent: ast.AST | None) -> None:
        self._parent[id(scope)] = parent
        self.depth[id(scope)] = 0 if parent is None else self.depth[id(parent)] + 1
        self._bound[id(scope)], self._global[id(scope)], self._declared[id(scope)] = (
            set(),
            set(),
            set(),
        )

    def _bind(self, name: str, scope: ast.AST) -> ast.AST:
        home = self.module if name in self._global[id(scope)] else scope
        self._bound[id(home)].add(name)
        return home

    def _enter(self, node: ast.AST, scope: ast.AST) -> None:
        """Records ``node`` and everything under it as running in ``scope``."""
        self.of[id(node)] = scope
        self._note(node, scope)
        if node is not scope and isinstance(node, (*_FUNCTIONS, ast.ClassDef, *_COMPREHENSIONS)):
            self._enter_scope(node, scope)
            return
        for child in ast.iter_child_nodes(node):
            self._enter(child, scope)

    def _enter_scope(self, node: ast.AST, outer: ast.AST) -> None:
        """Opens the scope of ``node``: its body runs inside, its header in ``outer``."""
        self._open(node, outer)
        if isinstance(node, _FUNCTIONS):
            self._bind_arguments(node)
        outside, inside = self._split(node)
        for child in outside:
            self._enter(child, outer)
        for child in inside:
            self._enter(child, node)

    def _split(self, node: ast.AST) -> tuple[list[ast.AST], list[ast.AST]]:
        """The children of the scope ``node`` that run outside it, and those that run inside."""
        match node:
            case (
                ast.ListComp(generators=[first, *_])
                | ast.SetComp(generators=[first, *_])
                | ast.DictComp(generators=[first, *_])
                | ast.GeneratorExp(generators=[first, *_])
            ):
                self.of[id(first)] = node
                rest = [n for n in ast.iter_child_nodes(node) if n is not first]
                return [first.iter], [*rest, first.target, *first.ifs]
            case ast.Lambda(body=body):
                inside: list[ast.AST] = [body]
            case (
                ast.FunctionDef(body=body)
                | ast.AsyncFunctionDef(body=body)
                | ast.ClassDef(body=body)
            ):
                inside = list(body)
            case _:
                inside = []
        ids = {id(n) for n in inside}
        return [n for n in ast.iter_child_nodes(node) if id(n) not in ids], inside

    def _bind_arguments(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        arguments = node.args
        for arg in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            arguments.vararg,
            arguments.kwarg,
        ):
            if arg is not None:
                self._bind(arg.arg, node)

    def _note(self, node: ast.AST, scope: ast.AST) -> None:
        """Records the names ``node`` binds in ``scope``, or declares not its own."""
        match node:
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                self._bind(name, scope)
            case ast.Global(names=names):
                self._global[id(scope)].update(names)
                self._declared[id(scope)].update(names)
            case ast.Nonlocal(names=names):
                self._declared[id(scope)].update(names)
            case ast.Import() | ast.ImportFrom():
                self._note_import(node, scope)
            case _:
                pass

    def _note_import(self, node: ast.Import | ast.ImportFrom, scope: ast.AST) -> None:
        """Binds each name ``node`` imports in ``scope``, and records what it binds it to.

        WHY: `import a.b` binds `a` to the package `a`, and `import a.b as x` binds `x` to `a.b`.
        A star import is not modelled: lint forbids it.
        """
        for alias in node.names:
            if isinstance(node, ast.ImportFrom):
                name = alias.asname or alias.name
                imported = Imported(node.module or "", alias.name, node.level)
            else:
                name = alias.asname or alias.name.partition(".")[0]
                imported = Imported(alias.name if alias.asname else name, None, 0)
            if name != "*":
                self._bind(name, scope)
                self._pending.append((scope, name, imported))
