"""A static scan of every place the Gateway can put a `code` into an error body (spec 3.2).

FEATURE: Gateway code provenance (`docs/spec/2026-11-23-gateway-code-provenance.md`). The
Engine lifts an upstream `detail.code` only when the Gateway declares it in
`tests/fixtures/gateway_error_codes/codes.json`; this scan keeps that declaration exact.

INVARIANT: a site the scan cannot prove is reported, never skipped. It proves only what is
statically certain: a string literal, an if-expression of them, a module-level name bound only
to them (also through an in-package import), the parameter of a declared producer, and, for a
whole detail, a dict literal with no `**` or a helper every return of which is proven.
WHY no local-variable resolution for a code: a flow-insensitive pass would read every literal
ever bound to the name, so `outcome = "success"` would become a code. Such a site is reviewed.
WHY static: it cannot prove a reviewed site's reason, so each review names one.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from ._gateway_error_code_ast import (
    EXCLUDED,
    SINKS,
    Function,
    Kind,
    Module,
    Producer,
    Review,
    call_argument,
    callee,
    is_code_key,
    is_detail_key,
    load_module,
    module_key,
    parameters,
    producer_def,
    scope_bindings,
    walk_scope,
)

__all__ = ["Producer", "Review", "Scan", "failures"]

# Resolution keys already on the path, so a cycle of names resolves to unproven.
Seen = frozenset[tuple[str, str, str]]
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class Scan:
    codes: dict[str, set[str]] = field(default_factory=dict)  # code -> sites that write it
    unproven: Counter[str] = field(default_factory=Counter)  # site -> unproven writes, sinks
    not_codes: Counter[str] = field(default_factory=Counter)  # site -> skipped `code` writes
    handlers: set[str] = field(default_factory=set)  # exception handlers the source registers


class _Bound(NamedTuple):
    spec: Producer
    module: Module
    position: int | None
    default: ast.expr | None


class _Ctx(NamedTuple):
    module: Module
    functions: tuple[Function, ...]
    qual: str


class _Scanner:
    def __init__(
        self, root: Path, package: str, producers: Iterable[Producer], not_codes: Iterable[str]
    ) -> None:
        self.modules: dict[str, Module] = {}
        for path in sorted(root.rglob("*.py")):
            if path.relative_to(root).parts[0] != EXCLUDED:
                module = load_module(path, root, package)
                self.modules[module_key(module.rel)] = module
        self.not_codes = set(not_codes)
        self.scan = Scan()
        self.sinks = self._sink_classes()
        self.producers: dict[str, list[_Bound]] = {}
        self.excused: dict[tuple[str, str], tuple[str, Kind]] = {}
        for spec in producers:
            self._bind(spec)
        self._bound_names: dict[int, set[str]] = {}

    def run(self) -> Scan:
        for module in self.modules.values():
            _Visitor(self, module).visit(module.tree)
        return self.scan

    def _bind(self, spec: Producer) -> None:
        module = self.modules.get(module_key(spec.file))
        found = producer_def(module.tree, spec.name) if module else None
        if module is None or found is None:
            raise ValueError(f"producer not found: {spec.file}:{spec.name}({spec.param})")
        fn, qual, offset = found
        positional = [arg.arg for arg in (*fn.args.posonlyargs, *fn.args.args)]
        keyword_only = [arg.arg for arg in fn.args.kwonlyargs]
        if spec.param in positional:
            index = positional.index(spec.param)
            shift = index - (len(positional) - len(fn.args.defaults))
            default = fn.args.defaults[shift] if shift >= 0 else None
            bound = _Bound(spec, module, index - offset, default)
        elif spec.param in keyword_only:
            bound = _Bound(spec, module, None, fn.args.kw_defaults[keyword_only.index(spec.param)])
        else:
            raise ValueError(f"producer not found: {spec.file}:{spec.name}({spec.param})")
        self.producers.setdefault(spec.name, []).append(bound)
        self.excused[(module.rel, qual)] = (spec.param, spec.kind)

    def _sink_classes(self) -> dict[str, tuple[tuple[str, int], bool]]:
        """Every class that is a sink: its argument spec, and whether it has its own init."""
        classes: list[tuple[str, set[str], bool]] = []
        for module in self.modules.values():
            for node in ast.walk(module.tree):
                if isinstance(node, ast.ClassDef):
                    bases = {module.aliases.get(n, n) for n in map(callee, node.bases)}
                    init = any(
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == "__init__"
                        for item in node.body
                    )
                    classes.append((node.name, bases, init))
        found: dict[str, tuple[tuple[str, int], bool]] = {}
        changed = True
        while changed:  # WHY a fixed point: a subclass of a subclass is a sink too.
            changed = False
            for name, bases, init in classes:
                parent = next((b for b in sorted(bases) if b in SINKS or b in found), None)
                if name in found or parent is None or parent == name:
                    continue
                if parent in SINKS:
                    found[name] = (SINKS[parent], init)
                else:  # WHY inherited: a parent's own `__init__` is what a child call runs.
                    found[name] = (found[parent][0], init or found[parent][1])
                changed = True
        return found

    def resolve(self, value: ast.expr, ctx: _Ctx, kind: Kind, seen: Seen) -> set[str] | None:
        """The codes `value` can be, or None when the scan cannot prove it."""
        if isinstance(value, ast.Constant):
            if value.value is None:
                return set()
            if isinstance(value.value, str):
                return {value.value} if kind == "code" else set()
            return None
        if isinstance(value, ast.IfExp):
            return self._all([value.body, value.orelse], ctx, kind, seen)
        if isinstance(value, ast.Name):
            return self._name(value.id, ctx, kind, seen)
        return self._detail_shape(value, ctx, seen) if kind == "detail" else None

    def _detail_shape(self, value: ast.expr, ctx: _Ctx, seen: Seen) -> set[str] | None:
        """A whole detail that is not a name: a text, a dict literal, or a helper's return."""
        if isinstance(value, ast.JoinedStr):
            return set()
        if isinstance(value, ast.Dict):
            # INVARIANT: a `**` can carry a code; a nested `detail` is what a JSONResponse
            # body's reader takes the code from, so it is proven like any detail.
            if None in value.keys:
                return None
            nested = [v for k, v in zip(value.keys, value.values, strict=True) if is_detail_key(k)]
            return self._all(nested, ctx, "detail", seen)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            return self._returns(value.func.id, ctx, seen)
        return None

    def _all(self, values: list[ast.expr], ctx: _Ctx, kind: Kind, seen: Seen) -> set[str] | None:
        out: set[str] = set()
        for value in values:
            got = self.resolve(value, ctx, kind, seen)
            if got is None:
                return None
            out |= got
        return out

    def _names(self, fn: Function) -> set[str]:
        names = self._bound_names.get(id(fn))
        if names is None:
            names = {arg.arg for arg in parameters(fn)} | {name for name, _ in scope_bindings(fn)}
            self._bound_names[id(fn)] = names
        return names

    def _name(self, name: str, ctx: _Ctx, kind: Kind, seen: Seen) -> set[str] | None:
        if self.excused.get((ctx.module.rel, ctx.qual)) == (name, kind):
            return set()
        holders = [fn for fn in ctx.functions if name in self._names(fn)]
        if not holders:
            return self._global(ctx.module, name, kind, seen)
        inner = ctx.functions[-1]
        if kind == "code" or holders != [inner] or name in {a.arg for a in parameters(inner)}:
            return None
        values = [value for bound, value in scope_bindings(inner) if bound == name]
        if not all(isinstance(value, ast.expr) for value in values):
            return None
        return self._all([v for v in values if isinstance(v, ast.expr)], ctx, kind, seen)

    def _global(self, module: Module, name: str, kind: Kind, seen: Seen) -> set[str] | None:
        key = (kind, module.rel, name)
        if key in seen:
            return None
        if name in module.imports:
            target, original = module.imports[name]
            found = self.modules.get(target)
            return None if found is None else self._global(found, original, kind, seen | {key})
        values = module.bindings.get(name)
        if values is None:
            return None
        return self._all(values, _Ctx(module, (), "<module>"), kind, seen | {key})

    def _function(self, module: Module, name: str) -> tuple[Module, Function] | None:
        if name in module.functions:
            return module, module.functions[name]
        if name in module.imports:
            target, original = module.imports[name]
            found = self.modules.get(target)
            return None if found is None else self._function(found, original)
        return None

    def _returns(self, name: str, ctx: _Ctx, seen: Seen) -> set[str] | None:
        """A helper's detail: proven when every one of its returns is."""
        if any(name in self._names(fn) for fn in ctx.functions):
            return None
        found = self._function(ctx.module, name)
        if found is None:
            return None
        module, fn = found
        key = ("returns", module.rel, fn.name)
        returns = [node for node in walk_scope(fn) if isinstance(node, ast.Return)]
        if key in seen or not returns:
            return None
        values = [node.value or ast.Constant(None) for node in returns]
        return self._all(values, _Ctx(module, (fn,), fn.name), "detail", seen | {key})


class _Visitor(ast.NodeVisitor):
    def __init__(self, scanner: _Scanner, module: Module) -> None:
        self.s = scanner
        self.module = module
        self.stack: list[Function | ast.ClassDef] = []
        self.handled: set[int] = set()

    @property
    def site(self) -> str:
        return f"{self.module.rel}:{'.'.join(n.name for n in self.stack) or '<module>'}"

    def _ctx(self) -> _Ctx:
        fns = tuple(n for n in self.stack if not isinstance(n, ast.ClassDef))
        return _Ctx(self.module, fns, self.site.split(":", 1)[1])

    def _check(self, value: ast.expr | None, kind: Kind, ctx: _Ctx | None = None) -> None:
        got = self.s.resolve(value or ast.Constant(None), ctx or self._ctx(), kind, frozenset())
        if got is None:
            self.s.scan.unproven[self.site] += 1
        for code in got or ():
            self.s.scan.codes.setdefault(code, set()).add(self.site)

    def _write(self, value: ast.expr | None) -> None:
        if self.site in self.s.not_codes:
            self.s.scan.not_codes[self.site] += 1
        else:
            self._check(value, "code")

    def _scope(self, node: Function | ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and callee(decorator.func) == "exception_handler":
                self.s.scan.handlers.add(node.name)
        self.stack.append(node)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if is_code_key(key):
                self._write(value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._store(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._store(node.target, node.value)
        self.generic_visit(node)

    def _store(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Subscript) and is_code_key(target.slice):
            self.handled.add(id(target))
            self._write(value)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        stored = isinstance(node.ctx, ast.Store) and is_code_key(node.slice)
        if stored and id(node) not in self.handled:
            self.s.scan.unproven[self.site] += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self.module.aliases.get(callee(node.func), callee(node.func))
        self._producer_call(node, name)
        for kw in node.keywords:
            if kw.arg == "code" and id(kw) not in self.handled:
                self._write(kw.value)
            if kw.arg == "exception_handlers":
                self.s.scan.handlers.add(ast.unparse(kw.value))
        if name == "setdefault" and node.args and is_code_key(node.args[0]):
            self._write(node.args[1] if len(node.args) > 1 else None)
        if name == "add_exception_handler" and len(node.args) > 1:
            self.s.scan.handlers.add(ast.unparse(node.args[1]))
        spec = self._sink_spec(node, name)
        if spec is not None:
            known, value = call_argument(node, *spec)
            if known:
                self._check(value, "detail")
            else:
                self.s.scan.unproven[self.site] += 1
        self.generic_visit(node)

    def _producer_call(self, node: ast.Call, name: str) -> None:
        candidates = self.s.producers.get(name, [])
        local = [bound for bound in candidates if bound.module is self.module]
        if len(local or candidates) != 1:
            if candidates:  # WHY: one name, several producers, called from a third module.
                self.s.scan.unproven[self.site] += 1
            return
        bound = (local or candidates)[0]
        self.handled.update(id(kw) for kw in node.keywords if kw.arg == bound.spec.param)
        known, value = call_argument(node, bound.spec.param, bound.position)
        if not known:
            self.s.scan.unproven[self.site] += 1
        elif value is None:
            self._check(bound.default, bound.spec.kind, _Ctx(bound.module, (), "<module>"))
        else:
            self._check(value, bound.spec.kind)

    def _sink_spec(self, node: ast.Call, name: str) -> tuple[str, int] | None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "__init__"
            and isinstance(func.value, ast.Call)
            and callee(func.value.func) == "super"
        ):
            owner = next((n for n in reversed(self.stack) if isinstance(n, ast.ClassDef)), None)
            found = self.s.sinks.get(owner.name) if owner else None
            return found[0] if found else None
        if name in SINKS:
            return SINKS[name]
        found = self.s.sinks.get(name)
        return found[0] if found and not found[1] else None


def _fixture_failures(fixture: Mapping[str, object], audited: set[str]) -> list[str]:
    out: list[str] = []
    if set(fixture) != {"codes", "retired"}:
        return [f"fixture: keys are {sorted(fixture)}, expected codes and retired"]
    lists: dict[str, list[str]] = {}
    for name in ("codes", "retired"):
        entries = fixture[name]
        if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
            out.append(f"fixture: {name} is not a list of strings")
            continue
        lists[name] = [e for e in entries if isinstance(e, str)]
        if lists[name] != sorted(lists[name]):
            out.append(f"fixture: {name} not sorted")
        if len(set(lists[name])) != len(lists[name]):
            out.append(f"fixture: {name} has duplicates")
        out += [
            f"fixture: {name} entry not a plain identifier: {e!r}"
            for e in lists[name]
            if not _IDENTIFIER.fullmatch(e)
        ]
    retired = set(lists.get("retired", ()))
    # INVARIANT: the Engine lifts every retired code, so `retired` is exactly the audited set.
    out += [f"retired not audited: {code}" for code in sorted(retired - audited)]
    out += [f"audited retired missing: {code}" for code in sorted(audited - retired)]
    both = set(lists.get("codes", ())) & retired
    return out + [f"in both lists: {code}" for code in sorted(both)]


def _count_failures(label: str, found: Counter[str], listed: Mapping[str, int]) -> list[str]:
    return [
        f"{label}: {site} has {found.get(site, 0)}, listed {listed.get(site, 0)}"
        for site in sorted(set(found) | set(listed))
        if found.get(site, 0) != listed.get(site, 0)
    ]


def _review_failures(root: Path, reviewed: Mapping[str, Review]) -> list[str]:
    out: list[str] = []
    for site, review in sorted(reviewed.items()):
        rel = site.split(":", 1)[0]
        path = root / rel
        if not review.codes or not path.is_file():
            continue
        tree = ast.parse(path.read_text())
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
        missing = [code for code in review.codes if code not in literals]
        out += [f"reviewed code not a literal in {rel}: {code}" for code in missing]
    return out


def failures(
    root: Path,
    *,
    package: str,
    fixture: Mapping[str, object],
    producers: Iterable[Producer] = (),
    reviewed: Mapping[str, Review] | None = None,
    not_codes: Mapping[str, int] | None = None,
    handlers: Iterable[str] = (),
    retired: Iterable[str] = (),
) -> list[str]:
    """Every way the source and the fixture disagree; empty when the vocabulary is exact.

    `retired` is the audited list the fixture's `retired` must equal.
    """
    reviewed, not_codes = reviewed or {}, not_codes or {}
    try:
        scan = _Scanner(root, package, producers, not_codes).run()
    except ValueError as exc:
        return [str(exc)]
    out = _fixture_failures(fixture, set(retired))
    out += _count_failures("unproven", scan.unproven, {s: r.count for s, r in reviewed.items()})
    out += _count_failures("not-code", scan.not_codes, not_codes)
    out += [f"handler not reviewed: {h}" for h in sorted(scan.handlers - set(handlers))]
    out += [f"reviewed handler gone: {h}" for h in sorted(set(handlers) - scan.handlers)]
    out += _review_failures(root, reviewed)
    written = set(scan.codes) | {code for review in reviewed.values() for code in review.codes}
    codes = fixture.get("codes")
    declared = {c for c in codes if isinstance(c, str)} if isinstance(codes, list) else set()
    for code in sorted(written - declared):
        sites = ", ".join(sorted(scan.codes.get(code, {"reviewed"})))
        out.append(f"not declared: {code} ({sites})")
    return out + [f"declared but not written: {code}" for code in sorted(declared - written)]
