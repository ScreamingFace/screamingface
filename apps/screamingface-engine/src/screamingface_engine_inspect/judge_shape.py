"""The judge-shape reader: how a scorer reaches a judge its kwargs never name.

FEATURE: importer guards (OME-1602, F2). A judged Benchmark pins its judge into its identity,
and the rest of the plugin finds that judge in the scorer's kwargs (``model=...``). Some
scorers reach a judge another way, so a kwargs-only check sees an unjudged row:

* simpleqa's scorer never takes a model; inside it calls ``get_model(role="grader")``.
* niah's takes ``judge_model``, nobody passes it, and it grades with the default.
* infinite_bench's math scorer calls ``get_model()``, which is the model under test.

Think of it as reading the examiner's job description instead of hiring the examiner: this
module reads the scorer constructor's SOURCE and never imports it, because Benchmark
assembly runs on the Engine's run path, which must never load an eval (inspect drags its
whole stack in). The importer and assembly both read through :func:`judge_shape`, so they
apply the same three rules the same way.

What runs: file lookups on the import path and ``ast.parse``. What never runs: an import,
an eval's code, a model.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Every parameter name a scorer constructor takes a judge under: the judge-model kwarg
#: names (the importer's ``_JUDGE_MODEL_KWARG_NAMES``), their panel forms (fortress's
#: ``grader_models``) and inspect's role kwarg.
JUDGE_PARAMETERS: frozenset[str] = frozenset(
    {
        "model",
        "grader_model",
        "judge_model",
        "scorer_model",
        "grader_models",
        "judge_models",
        "model_role",
    }
)

#: How many helper calls below the constructor the body rule follows. WHY 1: persistbench's
#: scorer asks for the grader role one helper down (``_get_judge``); no real package needs 2.
_HELPER_DEPTH: int = 1

#: The role a ``get_model(role=...)`` call asks for when it is not a literal (hle passes its
#: ``grader_role`` argument). WHY count it: the reader cannot say which judge fills it, and
#: an unread role is not a judge-free scorer, so the reader fails closed.
UNKNOWN_ROLE: str = "<unknown>"

#: The package whose scorers are inspect's own: ``model_graded_*`` is judged by its name and
#: no other built-in takes a judge, so its source is never read.
_INSPECT_PACKAGE: str = "inspect_ai"


@dataclass(frozen=True)
class JudgeShape:
    """How a scorer constructor reaches a judge, read from its source (OME-1602, F2).

    Mental model: the examiner's job description, read without hiring the examiner. Three
    rules, each a different way a judge hides from the scorer kwargs:

    * signature: the constructor has a judge parameter (``judge_model``), passed or not;
    * body, role: a ``get_model(role="grader")`` call, which a row must bind to its judge;
    * body, model under test: a ``get_model()`` call that names no model, so it grades with
      whatever model is being evaluated. ``get_model(model)`` names one and never matches,
      or math's exact-match scorers would read as judged.
    """

    #: The constructor's parameters named like a judge, in signature order.
    parameters: tuple[str, ...] = ()
    #: Each literal role a ``get_model(role=...)`` call asks for, with where: ``file:line``.
    roles: tuple[tuple[str, str], ...] = ()
    #: Where each ``get_model()`` that names no model sits: ``file:line``.
    model_under_test: tuple[str, ...] = ()

    @property
    def reaches_a_judge(self) -> bool:
        """True when any of the three rules matched."""

        return bool(self.parameters or self.roles or self.model_under_test)

    def described(self) -> str:
        """The first finding in words, for a refusal: ``parameter judge_model``."""

        if self.parameters:
            return f"parameter {', '.join(self.parameters)}"
        if self.roles:
            role, where = self.roles[0]
            shown: str = role if role == UNKNOWN_ROLE else repr(role)
            return f"get_model(role={shown}) in {where}"
        return f"get_model() in {self.model_under_test[0]}" if self.model_under_test else ""


def judge_shape(reference: str) -> JudgeShape:
    """Read how the scorer a row's dotted ``module:constructor`` reference names reaches a
    judge, from its source file, without importing anything.

    WHY source, not the live object: Benchmark assembly runs on the Engine's run path,
    which must never import an eval (inspect drags its whole stack in), and the importer
    and assembly must read the same three rules the same way.

    Stages, in execution order:

        Stage 1 — locate the def: the module's file by import-path search only, then the
                  def by name, following one ``from x import name`` re-export inside the
                  eval's own package.
        Stage 2 — signature rule: the def's parameters named in ``JUDGE_PARAMETERS``.
        Stage 3 — body rule: every ``get_model`` call in the def, nested functions
                  included, then in each same-package helper it calls by name, down to
                  ``_HELPER_DEPTH`` levels.

    Example: ``inspect_evals.simpleqa.scorer:simpleqa_scorer`` has no judge parameter, and
    its inner ``score`` calls ``get_model(role="grader")`` at scorer.py:108 →
    ``JudgeShape(roles=(("grader", "scorer.py:108"),))``.

    Returns:
        The findings; an empty shape for inspect's own scorers and for a source that cannot
        be located or parsed (nothing more is known than before).
    """

    module_name, _, name = reference.partition(":")
    if module_name == _INSPECT_PACKAGE or module_name.startswith(f"{_INSPECT_PACKAGE}."):
        return JudgeShape()
    package: str = _eval_package(module_name)
    reader: _SourceReader = _SourceReader(package)
    # Stage 1
    constructor: _LocatedDef | None = reader.located_def(module_name, name)
    if constructor is None:
        return JudgeShape()
    # Stage 2
    arguments: ast.arguments = constructor.node.args
    parameters: tuple[str, ...] = tuple(
        argument.arg
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        if argument.arg in JUDGE_PARAMETERS
    )
    # Stage 3
    roles: list[tuple[str, str]] = []
    model_under_test: list[str] = []
    reader.read_model_calls(constructor, roles, model_under_test)
    return JudgeShape(
        parameters=parameters, roles=tuple(roles), model_under_test=tuple(model_under_test)
    )


def _eval_package(module_name: str) -> str:
    """The package a scorer's helpers must share: ``inspect_evals.simpleqa`` for
    ``inspect_evals.simpleqa.scorer``; a top-level module is its own package."""

    return ".".join(module_name.split(".")[:2])


def _in_package(module_name: str, package: str) -> bool:
    """True when the module is the package or lives inside it."""

    return module_name == package or module_name.startswith(f"{package}.")


@dataclass(frozen=True)
class _LocatedDef:
    """A function def found in a module's source: which module, which file, which node."""

    module: str
    path: Path
    node: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _ParsedModule:
    """One module's parsed source and whether it is a package's ``__init__``."""

    path: Path
    tree: ast.Module
    is_package: bool


class _SourceReader:
    """Reads one eval package's source by module name, never importing a module; parses
    each file once."""

    def __init__(self, package: str) -> None:
        """Read inside ``package`` only: an import from anywhere else (inspect_ai's
        ``Score``) is never followed, so no file outside the eval is parsed."""

        self._package: str = package
        self._parsed: dict[str, _ParsedModule | None] = {}

    def located_def(self, module_name: str, name: str) -> _LocatedDef | None:
        """The top-level def ``name`` of the module, or of the same-package module it
        imports ``name`` from (one hop: a row names a scorer by the Task module that imports
        it, as simpleqa's Task module imports ``simpleqa_scorer`` from ``.scorer``)."""

        parsed: _ParsedModule | None = self._module(module_name)
        if parsed is None:
            return None
        source: tuple[str, str] | None = self._imported_from(module_name, parsed, name)
        imported: _ParsedModule | None = None if source is None else self._module(source[0])
        return _def_named(parsed, module_name, name) or (
            None if source is None or imported is None else _def_named(imported, *source)
        )

    def _imported_from(
        self, module_name: str, parsed: _ParsedModule, name: str
    ) -> tuple[str, str] | None:
        """``(module, name there)`` of a ``from x import name`` inside the package; None
        when the module binds the name no such way."""

        for node in parsed.tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    target: str | None = _absolute_module(module_name, parsed.is_package, node)
                    in_package: bool = target is not None and _in_package(target, self._package)
                    return (target, alias.name) if target is not None and in_package else None
        return None

    def read_model_calls(
        self,
        located: _LocatedDef,
        roles: list[tuple[str, str]],
        model_under_test: list[str],
        depth: int = 0,
    ) -> None:
        """Stage 3 of :func:`judge_shape` — sort each ``get_model`` call in the def, then
        read each same-package helper it calls by name, one level deeper."""

        for node in ast.walk(located.node):
            if not isinstance(node, ast.Call):
                continue
            callee: ast.expr = node.func
            called: str | None = (
                callee.id
                if isinstance(callee, ast.Name)
                else callee.attr
                if isinstance(callee, ast.Attribute)
                else None
            )
            where: str = f"{located.path.name}:{node.lineno}"
            if called == "get_model":
                _sort_model_call(node, where, roles, model_under_test)
            elif isinstance(callee, ast.Name) and depth < _HELPER_DEPTH:
                helper: _LocatedDef | None = self.located_def(located.module, callee.id)
                if helper is not None:
                    self.read_model_calls(helper, roles, model_under_test, depth + 1)

    def _module(self, module_name: str) -> _ParsedModule | None:
        """The module's parsed source, or None when it cannot be found or parsed."""

        if module_name not in self._parsed:
            path: Path | None = _module_file(module_name)
            parsed: _ParsedModule | None = None
            if path is not None:
                try:
                    tree: ast.Module = ast.parse(path.read_text(encoding="utf-8"), str(path))
                except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                    tree = ast.Module(body=[], type_ignores=[])
                parsed = _ParsedModule(path, tree, path.name == "__init__.py")
            self._parsed[module_name] = parsed
        return self._parsed[module_name]


def _def_named(parsed: _ParsedModule, module_name: str, name: str) -> _LocatedDef | None:
    """The module's own top-level def ``name``, if it has one."""

    for node in parsed.tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return _LocatedDef(module_name, parsed.path, node)
    return None


def _sort_model_call(
    call: ast.Call, where: str, roles: list[tuple[str, str]], model_under_test: list[str]
) -> None:
    """One ``get_model`` call: a literal role, the model under test, or neither.

    ``get_model(role="grader")`` → a role; a role held in a variable → ``UNKNOWN_ROLE``.
    ``get_model()`` naming no model → the model under test. ``get_model(model)`` or
    ``get_model(model=...)`` names its model → neither (math's helper, frontierscience).
    """

    keywords: dict[str | None, ast.expr] = {keyword.arg: keyword.value for keyword in call.keywords}
    role: ast.expr | None = keywords.get("role")
    if role is not None:
        named: str = (
            role.value
            if isinstance(role, ast.Constant) and isinstance(role.value, str)
            else UNKNOWN_ROLE
        )
        roles.append((named, where))
        return
    if call.args or "model" in keywords:
        return
    model_under_test.append(where)


def _absolute_module(module_name: str, is_package: bool, node: ast.ImportFrom) -> str | None:
    """The absolute module a ``from ... import`` names, relative dots resolved against the
    importing module (``from .scorer import x`` in ``inspect_evals.simpleqa.simpleqa`` →
    ``inspect_evals.simpleqa.scorer``)."""

    if node.level == 0:
        return node.module
    base: list[str] = module_name.split(".") if is_package else module_name.split(".")[:-1]
    parts: list[str] = base[: len(base) - (node.level - 1)] + ([node.module] if node.module else [])
    return ".".join(parts) or None


def _module_file(module_name: str) -> Path | None:
    """The module's ``.py`` file, found by looking at the import path's folders: nothing is
    executed.

    WHY not ``importlib.util.find_spec``: for a dotted name it IMPORTS every parent package,
    running its ``__init__`` (inspect_evals' pulls in inspect_ai). A module already loaded
    is read from its ``__file__``.
    """

    loaded: Any = sys.modules.get(module_name)
    if loaded is not None:
        file: str | None = getattr(loaded, "__file__", None)
        return Path(file) if file is not None and file.endswith(".py") else None
    parent, _, leaf = module_name.rpartition(".")
    folders: list[Path] | None = _package_folders(parent) if parent else _import_path()
    for folder in folders or []:
        for candidate in (folder / leaf / "__init__.py", folder / f"{leaf}.py"):
            if candidate.is_file():
                return candidate
    return None


def _package_folders(package: str) -> list[Path] | None:
    """The folders a package's submodules live in (several for a namespace package)."""

    loaded: Any = sys.modules.get(package)
    if loaded is not None:
        locations: Any = getattr(loaded, "__path__", None)
        return None if locations is None else [Path(location) for location in locations]
    parent, _, leaf = package.rpartition(".")
    folders: list[Path] | None = _package_folders(parent) if parent else _import_path()
    found: list[Path] = [folder / leaf for folder in folders or [] if (folder / leaf).is_dir()]
    return found or None


def _import_path() -> list[Path]:
    """The folders a top-level module is searched in, in import order."""

    return [Path(entry) for entry in sys.path if isinstance(entry, str)]
