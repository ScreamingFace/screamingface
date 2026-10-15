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
apply the same rules the same way.

INVARIANT: "could not read" is never "judge-free". A scorer the reader cannot follow
(sciknoweval picks its scorer from a lookup table at grading time) is reported ``unread``,
and an unread scorer counts as reaching a judge, so every caller refuses it by name.

What runs: file lookups on the import path and ``ast.parse``. What never runs: an import,
an eval's code, a model.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
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

#: The role a ``get_model(role=...)`` call asks for when it is not a literal (hle passes its
#: ``grader_role`` argument). WHY count it: the reader cannot say which judge fills it, and
#: an unread role is not a judge-free scorer, so the reader fails closed.
UNKNOWN_ROLE: str = "<unknown>"

#: The package whose scorers are inspect's own: ``model_graded_*`` is judged by its name and
#: no other built-in takes a judge, so its source is never read.
_INSPECT_PACKAGE: str = "inspect_ai"

#: inspect's model lookup, the one call every judge goes through.
_GET_MODEL: str = "get_model"

#: The name prefix of inspect's judged scorers (``model_graded_fact``).
_MODEL_GRADED_PREFIX: str = "model_graded_"


@dataclass(frozen=True)
class JudgeShape:
    """How a scorer constructor reaches a judge, read from its source (OME-1602, F2).

    Mental model: the examiner's job description, read without hiring the examiner. Three
    rules, each a different way a judge hides from the scorer kwargs, plus a fourth outcome
    for a description the reader could not finish:

    * signature: the constructor has a judge parameter (``judge_model``), passed or not;
    * body, role: a ``get_model(role="grader")`` call, which a row must bind to its judge;
    * body, model under test: a ``get_model()`` call that names no model, so it grades with
      whatever model is being evaluated. ``get_model(model)`` names one and never matches,
      or math's exact-match scorers would read as judged;
    * unread: the reader could not tell (source not found, a ``model_graded_*`` call, or a
      file that mentions ``get_model`` where no followed call reaches it). Counted as
      reaching a judge: "could not read" is never "judge-free".
    """

    #: The constructor's parameters named like a judge, in signature order.
    parameters: tuple[str, ...] = ()
    #: Each distinct role a ``get_model(role=...)`` call asks for, with where it is first
    #: asked: ``("grader", "scorer.py:108")``.
    roles: tuple[tuple[str, str], ...] = ()
    #: Where each ``get_model()`` that names no model sits: ``file:line``.
    model_under_test: tuple[str, ...] = ()
    #: Why the reader could not tell whether the scorer reaches a judge, in words.
    unread: tuple[str, ...] = ()

    @property
    def reaches_a_judge(self) -> bool:
        """True when any rule matched, or the reader could not finish (fails closed)."""

        return bool(self.parameters or self.roles or self.model_under_test or self.unread)

    def described(self) -> str:
        """The first finding in words, for a refusal: ``parameter judge_model``."""

        found: list[str] = []
        if self.parameters:
            found.append(f"parameter {', '.join(self.parameters)}")
        if self.roles:
            role, where = self.roles[0]
            shown: str = role if role == UNKNOWN_ROLE else repr(role)
            found.append(f"get_model(role={shown}) in {where}")
        if self.model_under_test:
            found.append(f"get_model() in {self.model_under_test[0]}")
        found.extend(f"unread: {reason}" for reason in self.unread[:1])
        return found[0] if found else ""


def judge_shape(reference: str) -> JudgeShape:
    """Read how the scorer a row's dotted ``module:constructor`` reference names reaches a
    judge, from its source file, without importing anything.

    WHY source, not the live object: Benchmark assembly runs on the Engine's run path,
    which must never import an eval (inspect drags its whole stack in), and the importer
    and assembly must read the same rules the same way.

    Stages, in execution order:

        Stage 1 — locate the def: the module's file by import-path search only, then the
                  def by name, following ``from x import name`` re-exports anywhere inside
                  the scorer's root package (aime2025 imports its scorer from
                  ``inspect_evals.utils``). Not found → unread, never judge-free.
        Stage 2 — signature rule: the def's parameters named in ``JUDGE_PARAMETERS``.
        Stage 3 — body rule: every ``get_model`` call in the def, nested functions
                  included, then in every root-package helper it calls (``helper()``,
                  ``module.helper()``), helpers of helpers included: cti_realm asks for
                  its judge two helpers down. A ``model_graded_*`` call is unread.
        Stage 4 — mention rule: with no judge found, a file the reader parsed that still
                  mentions ``get_model`` or ``model_graded_*`` means a judge may sit
                  behind code the reader cannot follow (sciknoweval's lookup table), so
                  the scorer is unread.

    Example: ``inspect_evals.simpleqa.scorer:simpleqa_scorer`` has no judge parameter, and
    its inner ``score`` calls ``get_model(role="grader")`` at scorer.py:108 →
    ``JudgeShape(roles=(("grader", "scorer.py:108"),))``.

    Returns:
        The findings; an empty shape only for inspect's own scorers and for a scorer read in
        full that reaches no judge.
    """

    module_name, _, name = reference.partition(":")
    if _in_package(module_name, _INSPECT_PACKAGE):
        return JudgeShape()
    reader: _SourceReader = _SourceReader(module_name.split(".")[0])
    # Stage 1
    constructor: _LocatedDef | None = reader.located_def(module_name, name)
    if constructor is None or isinstance(constructor.node, ast.ClassDef):
        return JudgeShape(unread=(f"the source of {name} in {module_name} was not found",))
    return _read_constructor(reader, constructor, constructor.node)


def _read_constructor(
    reader: _SourceReader,
    constructor: _LocatedDef,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> JudgeShape:
    """Stages 2 to 4 of :func:`judge_shape`, on the located constructor def."""

    # Stage 2
    arguments: ast.arguments = node.args
    parameters: tuple[str, ...] = tuple(
        argument.arg
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        if argument.arg in JUDGE_PARAMETERS
    )
    # Stage 3
    findings: _Findings = _Findings()
    reader.read_model_calls(constructor, findings, is_constructor=True)
    if findings.variable_models and not parameters:
        findings.unread.append(
            f"a judge model held in a variable at {findings.variable_models[0]}, which no "
            "judge parameter of the scorer names"
        )
    shape: JudgeShape = JudgeShape(
        parameters=parameters,
        roles=tuple(findings.roles.items()),
        model_under_test=tuple(findings.model_under_test),
        unread=tuple(findings.unread),
    )
    # Stage 4
    mentioned: str | None = None if shape.reaches_a_judge else reader.first_judge_mention()
    if mentioned is not None:
        shape = JudgeShape(unread=(f"{mentioned} as a value, a call the reader cannot follow",))
    return shape


def _in_package(module_name: str, package: str) -> bool:
    """True when the module is the package or lives inside it."""

    return module_name == package or module_name.startswith(f"{package}.")


@dataclass(frozen=True)
class _LocatedDef:
    """A function def found in a module's source: which module, which file, which node."""

    module: str
    path: Path
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass(frozen=True)
class _ParsedModule:
    """One module's parsed source and whether it is a package's ``__init__``."""

    path: Path
    tree: ast.Module
    is_package: bool


@dataclass
class _Findings:
    """What Stage 3 found so far; each role kept once, at the first place it is asked."""

    roles: dict[str, str] = field(default_factory=dict)
    model_under_test: list[str] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    #: Where a judge model arrives in a variable (``get_model(judge_model)``): fine when the
    #: constructor has a judge parameter, unread when nothing says where it comes from.
    variable_models: list[str] = field(default_factory=list)


#: The parameters a call can see, by name: each one's default (None when it has none) and
#: whether it is the scorer constructor's own (which a row's kwargs fill).
_Scope = dict[str, tuple[ast.expr | None, bool]]


class _SourceReader:
    """Reads one root package's source by module name, never importing a module; parses
    each file once."""

    def __init__(self, root: str) -> None:
        """Read inside ``root`` only (``inspect_evals``): an import from anywhere else
        (inspect_ai's ``Score``) is never followed, so no file outside it is parsed."""

        self._root: str = root
        self._parsed: dict[str, _ParsedModule | None] = {}
        self._visited: set[tuple[str, str]] = set()

    def located_def(self, module_name: str, name: str) -> _LocatedDef | None:
        """The top-level def ``name`` of the module, or of the root-package module it is
        imported from, re-export by re-export (a row names a scorer by the Task module that
        imports it, as simpleqa's Task module imports ``simpleqa_scorer`` from ``.scorer``)."""

        seen: set[tuple[str, str]] = set()
        current: tuple[str, str] | None = (module_name, name)
        found: _LocatedDef | None = None
        while current is not None and current not in seen and found is None:
            seen.add(current)
            parsed: _ParsedModule | None = self._module(current[0])
            if parsed is None:
                break
            found = _def_named(parsed, *current)
            current = None if found is not None else self._imported_from(*current, parsed)
        return found

    def _imported_from(
        self, module_name: str, name: str, parsed: _ParsedModule
    ) -> tuple[str, str] | None:
        """``(module, name there)`` of a ``from x import name`` inside the root package;
        None when the module binds the name no such way."""

        for node in parsed.tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    target: str | None = _absolute_module(module_name, parsed.is_package, node)
                    in_root: bool = target is not None and _in_package(target, self._root)
                    return (target, alias.name) if target is not None and in_root else None
        return None

    def _imported_module(self, module_name: str, parsed: _ParsedModule, name: str) -> str | None:
        """The root-package module a top-level name is bound to (``import a.b as name`` or
        ``from a import b as name`` where ``a.b`` is a module), for ``name.helper()``."""

        candidates: list[str] = []
        for node in parsed.tree.body:
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names if alias.asname == name)
            elif isinstance(node, ast.ImportFrom):
                target: str | None = _absolute_module(module_name, parsed.is_package, node)
                candidates.extend(
                    f"{target}.{alias.name}"
                    for alias in node.names
                    if target is not None and (alias.asname or alias.name) == name
                )
        return next(
            (
                module
                for module in candidates
                if _in_package(module, self._root) and _module_file(module) is not None
            ),
            None,
        )

    def read_model_calls(
        self, located: _LocatedDef, findings: _Findings, *, is_constructor: bool = False
    ) -> None:
        """Stage 3 of :func:`judge_shape` — sort each ``get_model`` call in the def, then
        read each root-package helper it calls, helpers of helpers included (each def once,
        so a recursive helper ends)."""

        if (located.module, located.node.name) in self._visited:
            return
        self._visited.add((located.module, located.node.name))
        parsed: _ParsedModule | None = self._module(located.module)
        get_model_names: frozenset[str] = (
            _get_model_names(parsed.tree) if parsed is not None else frozenset({_GET_MODEL})
        )
        scopes: dict[int, _Scope] = _call_scopes(located.node, is_constructor)
        for node in ast.walk(located.node):
            if isinstance(node, ast.Call):
                where: str = f"{located.path.name}:{node.lineno}"
                scope: _Scope = scopes.get(id(node), {})
                self._read_call(node, located, parsed, get_model_names, where, scope, findings)

    def _read_call(
        self,
        call: ast.Call,
        located: _LocatedDef,
        parsed: _ParsedModule | None,
        get_model_names: frozenset[str],
        where: str,
        scope: _Scope,
        findings: _Findings,
    ) -> None:
        """One call in a walked def: a judge lookup to sort, or a helper to read."""

        callee: ast.expr = call.func
        called: str = (
            callee.id
            if isinstance(callee, ast.Name)
            else callee.attr
            if isinstance(callee, ast.Attribute)
            else ""
        )
        if (isinstance(callee, ast.Name) and called in get_model_names) or (
            isinstance(callee, ast.Attribute) and called == _GET_MODEL
        ):
            _sort_model_call(call, where, scope, findings)
        elif called.startswith(_MODEL_GRADED_PREFIX):
            _sort_model_graded_call(call, called, where, scope, findings)
        elif called:
            helper: _LocatedDef | None = self._helper(located.module, parsed, callee)
            if helper is not None:
                self.read_model_calls(helper, findings)

    def _helper(
        self, module_name: str, parsed: _ParsedModule | None, callee: ast.expr
    ) -> _LocatedDef | None:
        """The root-package def a call reaches: ``helper()`` by its name in the calling
        module, or ``module.helper()`` through a module the caller imported."""

        if isinstance(callee, ast.Name):
            return self.located_def(module_name, callee.id)
        attribute: ast.Attribute | None = callee if isinstance(callee, ast.Attribute) else None
        owner: ast.Name | None = (
            attribute.value
            if attribute is not None and isinstance(attribute.value, ast.Name)
            else None
        )
        target: str | None = (
            None
            if parsed is None or owner is None
            else self._imported_module(module_name, parsed, owner.id)
        )
        return (
            None
            if target is None or attribute is None
            else self.located_def(target, attribute.attr)
        )

    def first_judge_mention(self) -> str | None:
        """Stage 4 of :func:`judge_shape` — the first ``get_model`` or ``model_graded_*``
        name used in any file read so far, in words; None when no file mentions one.

        WHY passed as a value, not called or imported: a call is either walked or sits in a
        def nothing walked reaches (math's judged helper beside its exact-match scorers);
        a value handed around (sciknoweval's lookup table holding ``model_graded_fact``)
        is a call the reader cannot follow.
        """

        for parsed in self._parsed.values():
            if parsed is None:
                continue
            get_model_names: frozenset[str] = _get_model_names(parsed.tree)
            callees: set[int] = {
                id(node.func) for node in ast.walk(parsed.tree) if isinstance(node, ast.Call)
            }
            for node in ast.walk(parsed.tree):
                if id(node) in callees:
                    continue
                used: str | None = (
                    node.id
                    if isinstance(node, ast.Name)
                    else node.attr
                    if isinstance(node, ast.Attribute)
                    else None
                )
                if used is not None and (
                    used in get_model_names
                    or used == _GET_MODEL
                    or used.startswith(_MODEL_GRADED_PREFIX)
                ):
                    return f"{parsed.path.name}:{getattr(node, 'lineno', 0)} passes {used} on"
        return None

    def _module(self, module_name: str) -> _ParsedModule | None:
        """The module's parsed source, or None when it cannot be found or parsed."""

        if module_name not in self._parsed:
            path: Path | None = _module_file(module_name)
            parsed: _ParsedModule | None = None
            if path is not None:
                try:
                    tree: ast.Module = ast.parse(path.read_text(encoding="utf-8"), str(path))
                    parsed = _ParsedModule(path, tree, path.name == "__init__.py")
                except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                    parsed = None
            self._parsed[module_name] = parsed
        return self._parsed[module_name]


def _get_model_names(tree: ast.Module) -> frozenset[str]:
    """The names a module binds inspect's ``get_model`` to: ``get_model`` itself, plus any
    ``from inspect_ai.model import get_model as fetch`` alias."""

    names: set[str] = {_GET_MODEL}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and _in_package(node.module or "", _INSPECT_PACKAGE):
            names.update(
                alias.asname for alias in node.names if alias.name == _GET_MODEL and alias.asname
            )
    return frozenset(names)


def _def_named(parsed: _ParsedModule, module_name: str, name: str) -> _LocatedDef | None:
    """The module's own top-level def or class ``name``, if it has one (a class is read
    whole: agentharm's scorer builds a judge class whose ``__init__`` fetches the judge)."""

    for node in parsed.tree.body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            return _LocatedDef(module_name, parsed.path, node)
    return None


def _call_scopes(node: ast.AST, is_constructor: bool) -> dict[int, _Scope]:
    """The parameters each call inside ``node`` can see: those of every def around it
    (a scorer's inner ``score`` sees its constructor's ``judge_model``)."""

    scopes: dict[int, _Scope] = {}
    for function in ast.walk(node):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        own: bool = is_constructor and function is node
        arguments: ast.arguments = function.args
        positional: list[ast.arg] = [*arguments.posonlyargs, *arguments.args]
        defaults: list[ast.expr | None] = [None] * (
            len(positional) - len(arguments.defaults)
        ) + list(arguments.defaults)
        visible: _Scope = {
            argument.arg: (default, own)
            for argument, default in [
                *zip(positional, defaults, strict=True),
                *zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True),
            ]
        }
        for inner in ast.walk(function):
            if isinstance(inner, ast.Call):
                scopes.setdefault(id(inner), {}).update(visible)
    return scopes


def _sort_model_call(call: ast.Call, where: str, scope: _Scope, findings: _Findings) -> None:
    """One ``get_model`` call: a literal role, the model under test, or neither.

    ``get_model(role="grader")`` → a role; a role held in a variable → ``UNKNOWN_ROLE``.
    ``get_model()`` naming no model → the model under test. ``get_model(model)`` or
    ``get_model(model=...)`` passes a judge in a variable → a variable model, which the
    constructor's judge parameter must account for (math's helper, frontierscience);
    ``get_model("openai/gpt-4o")`` hard-codes its own judge → unread.
    """

    keywords: dict[str | None, ast.expr] = {keyword.arg: keyword.value for keyword in call.keywords}
    role: ast.expr | None = keywords.get("role")
    if role is not None:
        named: str = (
            role.value
            if isinstance(role, ast.Constant) and isinstance(role.value, str)
            else UNKNOWN_ROLE
        )
        findings.roles.setdefault(named, where)
        return
    model: ast.expr | None = call.args[0] if call.args else keywords.get("model")
    if model is None or _is_none(model):
        findings.model_under_test.append(where)
    else:
        _sort_named_model(model, where, scope, findings)


def _sort_model_graded_call(
    call: ast.Call, called: str, where: str, scope: _Scope, findings: _Findings
) -> None:
    """One call to inspect's ``model_graded_*``, sorted by inspect's own rule: an explicit
    ``model=`` wins, else the ``model_role`` (default ``"grader"``), else the model under
    test (``model_role=None``).

    Example: niah's ``model_graded_qa(..., model=judge_model)`` → a variable model;
    ``model_graded_fact()`` → the ``"grader"`` role.
    """

    keywords: dict[str | None, ast.expr] = {keyword.arg: keyword.value for keyword in call.keywords}
    if None in keywords:
        findings.unread.append(f"{called}(**...) in {where}")
        return
    model: ast.expr | None = keywords.get("model")
    if model is not None and not _is_none(model):
        _sort_named_model(model, where, scope, findings)
        return
    role: ast.expr | None = keywords.get("model_role")
    if role is not None and _is_none(role):
        findings.model_under_test.append(where)
        return
    named: str = (
        "grader"
        if role is None
        else role.value
        if isinstance(role, ast.Constant) and isinstance(role.value, str)
        else UNKNOWN_ROLE
    )
    findings.roles.setdefault(named, where)


def _sort_named_model(model: ast.expr, where: str, scope: _Scope, findings: _Findings) -> None:
    """The model a judge call names, in the order it is checked:

    * its own ``get_model(...)`` call → nothing here; the walk sorts that call itself;
    * a judge parameter of the constructor → nothing here; the signature rule reports it
      and a row's kwargs pin it;
    * a literal, or a parameter whose default is one (agentharm's ``judge_model=
      "openai/gpt-4o"`` on a helper class) → a judge of its own that no row pins: unread;
    * a parameter of the constructor not named like a judge → a judge no kwarg check
      sees: unread;
    * a helper's parameter → its callers pass it, and they are walked too (math's
      ``score_helper(model)``); nothing here;
    * anything else (a local, an attribute) → a variable model.
    """

    if isinstance(model, ast.Constant):
        findings.unread.append(f"a judge named in the code ({model.value!r}) in {where}")
    elif isinstance(model, ast.Name) and model.id in scope:
        _sort_parameter_model(model.id, scope[model.id], where, findings)
    elif not isinstance(model, ast.Call):
        findings.variable_models.append(where)


def _sort_parameter_model(
    name: str, seen: tuple[ast.expr | None, bool], where: str, findings: _Findings
) -> None:
    """A judge model passed in through parameter ``name``; see :func:`_sort_named_model`."""

    default, constructor_parameter = seen
    judge_parameter: bool = constructor_parameter and name in JUDGE_PARAMETERS
    if not judge_parameter and isinstance(default, ast.Constant) and isinstance(default.value, str):
        findings.unread.append(
            f"a judge named in the code ({default.value!r}, the default of {name}) in {where}"
        )
    elif not judge_parameter and constructor_parameter:
        findings.unread.append(
            f"a judge passed in through parameter {name} in {where}, a name no judge check reads"
        )


def _is_none(node: ast.expr) -> bool:
    """True for the literal ``None``."""

    return isinstance(node, ast.Constant) and node.value is None


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
