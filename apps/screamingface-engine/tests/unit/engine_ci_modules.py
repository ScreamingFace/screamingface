"""The modules an Engine test imports: where each lives in the repo, and the paths it gives.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).

INVARIANT: a name an import binds stands for the paths the module-level name of that module can
be, read with the same scan. A module stands for its file, which `Path(module.__file__)` names.
An absolute import is looked up next to the importing file, in each directory of the Engine
tests that holds a module (pytest puts a test's directory on `sys.path`), and in each app's and
package's `src`, even when the standard library has a module of that name. Every match counts,
because which one wins depends on the order of `sys.path`, so a wrong guess can only add paths.
A relative import is looked up from the importing file's package. A module found nowhere in the
repo is outside it; unless the standard library holds it, a name it gives that roots a path
makes that path `<import M>`, after its top package M.

WHY not `importlib.util.find_spec`: it answers for the environment it runs in. A module installed
in one environment and not in another would change what a test depends on; the repo does not.

INVARIANT: modules that import each other in a cycle give the names Python would give them. A
module is registered before it is read, as Python registers it before it runs it, so a cycle
sees what it has bound so far. The scan reads modules in the order a test asks for names, not
the order Python runs them, so it reads the modules of a cycle again until none changes.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from engine_ci_scopes import Imported, Scopes

type Parts = tuple[str, ...]
type Paths = frozenset[Parts]
_NOWHERE: Paths = frozenset()
_FOREIGN = re.compile(r"<import ([\w.]+)>")
#: How many times the scan reads a cycle at most. WHY: each reading can only add paths, so the
#: readings end, unless a cycle builds a longer path each time; that fails instead of hanging.
_READINGS = 32


class Module(Protocol):
    """One repo module as the scan reads it."""

    def rebind(self) -> int:
        """Binds the module's names again from its first statement; how many paths they hold."""
        ...

    def module_value(self, name: str) -> Paths:
        """The paths the module-level ``name`` can be."""
        ...


#: Reads one module, its tree and file, without binding its names yet.
type Reader = Callable[[ast.Module, Parts, Modules], Module]


def is_standard(module: str) -> bool:
    """Whether ``module`` belongs to Python's standard library."""
    return module.partition(".")[0] in sys.stdlib_module_names


def foreign(path: str) -> str | None:
    """The module outside the repo that ``path`` is built on; None for a repo path."""
    found = _FOREIGN.fullmatch(path.partition("/")[0])
    return None if found is None else found[1]


def _dotted(module: str, name: str) -> str:
    return f"{module}.{name}" if module else name


class Modules:
    """Where each module a test imports lives in the repo, and the paths its names can be."""

    def __init__(self, repo: Path, engine: Parts, read: Reader) -> None:
        self._repo = repo
        self._read = read
        self._modules: dict[Parts, Module | None] = {}
        self._located: dict[tuple[str, int, Parts], list[Parts]] = {}
        #: The modules read since the outermost read began, and the files still in their first.
        self._reading: list[Module] = []
        self._first: set[Parts] = set()
        #: Whether a module asked a module still in its first reading for a name.
        self._partial = False
        #: The names being looked up, so a module that imports a name from itself ends.
        self._asking: set[tuple[Parts, str]] = set()
        tests = repo.joinpath(*engine, "tests")
        roots = {file.parent for file in tests.rglob("*.py")}
        roots.update((*repo.glob("apps/*/src"), *repo.glob("packages/*/src")))
        self._roots = [root.relative_to(repo).parts for root in sorted(roots)]

    def locate(self, module: str, level: int, importer: Parts) -> list[Parts]:
        """The repo files ``module`` can be, as ``importer`` imports it; empty outside the repo.

        A package is its `__init__.py`, and a namespace package its directory. WHY the cache:
        the scan asks for every name and attribute a test reads, and each asks the file system.
        """
        key = (module, level, importer[:-1])
        if key not in self._located:
            self._located[key] = self._locate(*key)
        return self._located[key]

    def _locate(self, module: str, level: int, package: Parts) -> list[Parts]:
        names = [name for name in module.split(".") if name]
        if level:
            return self._found(package[: len(package) - level + 1], names)
        # WHY no standard-library shortcut: pytest puts a test's directory first on `sys.path`,
        # so a module there hides the standard one of the same name.
        roots = dict.fromkeys([package, *self._roots])
        return [file for root in roots for file in self._found(root, names)]

    def value(self, file: Parts, name: str) -> Paths:
        """The paths the module-level ``name`` of the module in ``file`` can be.

        WHY the guard: a module that imports a name from itself, or two modules that import it
        from each other, would ask for it forever. The second ask finds it empty; the first holds
        what the module binds it to.
        """
        if file not in self._modules:
            self._load(file)
        module = self._modules[file]
        asking = (file, name)
        if module is None or asking in self._asking:
            return _NOWHERE
        self._partial = self._partial or file in self._first
        self._asking.add(asking)
        try:
            return module.module_value(name)
        finally:
            self._asking.discard(asking)

    def _load(self, file: Parts) -> None:
        """Reads the module in ``file``; the outermost read settles every module it read."""
        self._modules[file] = None
        path = self._repo.joinpath(*file)
        if path.suffix != ".py" or not path.is_file():
            return
        module = self._read(ast.parse(path.read_text(encoding="utf-8")), file, self)
        self._modules[file] = module
        outermost = not self._reading
        self._reading.append(module)
        self._first.add(file)
        module.rebind()
        self._first.discard(file)
        if outermost:
            try:
                self._settle()
            finally:
                self._reading.clear()
                self._partial = False

    def _settle(self) -> None:
        """Reads the modules read so far again until none changes, when a cycle read one early.

        INVARIANT: with no cycle every module read the final names of the modules it asked, so
        one reading is the answer.
        """
        sizes: list[int] = []
        for _ in range(_READINGS if self._partial else 0):
            again = [module.rebind() for module in list(self._reading)]
            if again == sizes:
                return
            sizes = again
        if self._partial:
            msg = f"an import cycle builds ever longer paths; {len(self._reading)} modules read"
            raise RecursionError(msg)

    def _found(self, base: Parts, names: list[str]) -> list[Parts]:
        """The module ``names`` spell under ``base``; the package ``base`` when they are none."""
        stem = self._repo.joinpath(*base, *names)
        files = [stem.with_name(f"{stem.name}.py")] if names else []
        files.append(stem / "__init__.py")
        found = next((file for file in files if file.is_file()), None)
        if found is None and names and stem.is_dir():
            found = stem
        return [] if found is None else [found.relative_to(self._repo).parts]


class Imports:
    """What the imports of one module bind its names to, for the scan of that module."""

    def __init__(self, scopes: Scopes, file: Parts, modules: Modules) -> None:
        self._scopes = scopes
        self._file = file
        self._modules = modules

    def value(self, home: ast.AST, name: str) -> Paths:
        """The paths the imports of the scope ``home`` bind ``name`` to."""
        paths = _NOWHERE
        for imported in self._scopes.imports.get((id(home), name), []):
            if imported.name is not None:
                paths |= self._value([(imported.module, imported.level)], imported.name)
        return paths

    def attribute(self, base: ast.expr, name: str) -> Paths:
        """The paths ``base.name`` can be when ``base`` names a repo module."""
        return self._value(self._module_names(base), name)

    def files(self, node: ast.expr) -> list[Parts]:
        """The repo files of the modules ``node`` can name."""
        return self._files(self._module_names(node))

    def foreign(self, node: ast.expr) -> Paths:
        """`<import M>` when ``node``, or the name an attribute chain starts at, is bound by an
        import from module M outside the repo and the standard library; empty otherwise.
        """
        while isinstance(node, ast.Attribute):
            node = node.value
        return frozenset(
            (f"<import {imported.module.partition('.')[0]}>",)
            for imported in self._imported(node)
            if not imported.level
            and not is_standard(imported.module)
            and not self._files([(imported.module, 0)])
        )

    def _value(self, modules: list[tuple[str, int]], name: str) -> Paths:
        return frozenset().union(*(self._modules.value(f, name) for f in self._files(modules)))

    def _files(self, modules: list[tuple[str, int]]) -> list[Parts]:
        return [f for name, level in modules for f in self._modules.locate(name, level, self._file)]

    def _imported(self, node: ast.expr) -> list[Imported]:
        """What the imports bind the name ``node`` to; empty for a name no import binds."""
        if not isinstance(node, ast.Name):
            return []
        home = self._scopes.home(node.id, self._scopes.of[id(node)])
        return [] if home is None else self._scopes.imports.get((id(home), node.id), [])

    def _module_names(self, node: ast.expr) -> list[tuple[str, int]]:
        """The dotted modules ``node`` can name, each with its import level."""
        if isinstance(node, ast.Attribute):
            within = self._module_names(node.value)
            return [(_dotted(module, node.attr), level) for module, level in within]
        return [
            (
                imported.module
                if imported.name is None
                else _dotted(imported.module, imported.name),
                imported.level,
            )
            for imported in self._imported(node)
        ]
