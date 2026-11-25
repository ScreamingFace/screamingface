"""What one Gateway module binds and imports, read with `ast` for the error-code scan.

FEATURE: Gateway code provenance (`docs/spec/2026-11-23-gateway-code-provenance.md`). These
helpers answer one question for `_gateway_error_code_scan`: what a name in a module can be.
INVARIANT: a binding the helpers cannot read as plain (`x = <expr>`, a def, an in-package
`from` import) is kept as unknown, so a name bound any other way never resolves.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NamedTuple

Kind = Literal["code", "detail"]
Function = ast.FunctionDef | ast.AsyncFunctionDef
# A binding's value: an expression, a def, a `from` import, or None for any other binding.
Value = ast.expr | Function | tuple[ast.ImportFrom, ast.alias] | None

# The response classes whose argument becomes the body: (keyword, position).
SINKS: dict[str, tuple[str, int]] = {
    "HTTPException": ("detail", 1),
    "JSONResponse": ("content", 0),
    "ORJSONResponse": ("content", 0),
}
# WHY: the migrations' `RunPython(code=...)` names a migration function, not a response code.
EXCLUDED = "migrations"


class Producer(NamedTuple):
    """A callable whose `param` carries a code (or a whole detail) into an error body.

    The scan checks the argument at every call, and accepts the parameter inside the callable.
    """

    file: str
    name: str
    param: str
    kind: Kind = "code"


class Review(NamedTuple):
    """A site the scan cannot prove: its unproven count, the codes it writes, and why."""

    count: int
    codes: tuple[str, ...]
    why: str


@dataclass
class Module:
    rel: str
    tree: ast.Module
    bindings: dict[str, list[ast.expr]] = field(default_factory=dict)
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    functions: dict[str, Function] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)


def walk_scope(node: ast.AST) -> Iterator[ast.AST]:
    """`node`'s subtree, without entering a nested def, class or lambda."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from walk_scope(child)


def scope_bindings(scope: ast.AST) -> Iterator[tuple[str, Value]]:
    """Every name `scope` binds, with its value when the binding is a plain one."""
    simple: set[int] = set()
    for node in walk_scope(scope):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name):
                    simple.add(id(target))
                    yield target.id, node.value
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                yield alias.asname or alias.name, (node, alias)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.asname or alias.name.split(".")[0], None
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if id(node) not in simple:
                yield node.id, None
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                yield name, None
        elif isinstance(node, (ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            if node.name:
                yield node.name, None


def parameters(fn: Function) -> list[ast.arg]:
    args = fn.args
    rest = [arg for arg in (args.vararg, args.kwarg) if arg is not None]
    return [*args.posonlyargs, *args.args, *args.kwonlyargs, *rest]


def callee(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def is_code_key(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value == "code"


def is_detail_key(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value == "detail"


def module_key(rel: str) -> str:
    """A module's import key: `routes/chat.py` -> `routes/chat`, `x/__init__.py` -> `x`."""
    key = rel.removesuffix(".py").removesuffix("__init__").removesuffix("/")
    return key


def import_target(rel: str, node: ast.ImportFrom, package: str) -> str | None:
    """The in-package module a `from ... import` reads, or None outside the package."""
    parts = node.module.split(".") if node.module else []
    if node.level == 0:
        return "/".join(parts[1:]) if parts and parts[0] == package else None
    base = rel.split("/")[:-1]
    if node.level - 1 > len(base):
        return None
    return "/".join([*base[: len(base) - (node.level - 1)], *parts])


def load_module(path: Path, root: Path, package: str) -> Module:
    rel = path.relative_to(root).as_posix()
    module = Module(rel, ast.parse(path.read_text(), filename=rel))
    grouped: dict[str, list[Value]] = {}
    for name, value in scope_bindings(module.tree):
        grouped.setdefault(name, []).append(value)
    rebound = {n for g in ast.walk(module.tree) if isinstance(g, ast.Global) for n in g.names}
    for name, values in grouped.items():
        only = values[0] if len(values) == 1 else None
        if isinstance(only, tuple) and only[1].name in SINKS:
            module.aliases[name] = only[1].name
        if name in rebound:
            continue
        if isinstance(only, tuple):
            target = import_target(rel, only[0], package)
            if target is not None:
                module.imports[name] = (target, only[1].name)
        elif isinstance(only, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions[name] = only
        elif all(isinstance(value, ast.expr) for value in values):
            module.bindings[name] = [value for value in values if isinstance(value, ast.expr)]
    return module


def producer_def(tree: ast.Module, name: str) -> tuple[Function, str, int] | None:
    """The def a producer runs, its qualified name, and how many leading params it binds."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node, name, 0
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == name and item.name == "__init__":
                return item, f"{name}.__init__", 1
            if item.name == name:
                static = any(callee(d) == "staticmethod" for d in item.decorator_list)
                return item, f"{node.name}.{name}", 0 if static else 1
    return None


def call_argument(
    call: ast.Call, keyword: str, position: int | None
) -> tuple[bool, ast.expr | None]:
    """(known, value) of one argument; unknown when a `*` or `**` could carry it."""
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return False, None
    for kw in call.keywords:
        if kw.arg is None:
            return False, None
        if kw.arg == keyword:
            return True, kw.value
    if position is not None and position < len(call.args):
        return True, call.args[position]
    return True, None
