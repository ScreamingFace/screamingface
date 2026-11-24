"""The Engine CI workflow runs on every repo file an Engine test reads.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).
STORY: as a Gateway, SDK or scoreboard developer, a change that breaks an Engine contract twin
fails its own pull request, instead of merging green and failing the next unrelated Engine change.

INVARIANT: every existing repo path outside the Engine that an Engine test names is matched by the
`paths:` filters of both the `push` and the `pull_request` trigger. A test names a path as a
repo-relative string literal, as literal segments joined with `/` to an expression rooted at the
test file (`Path(__file__).resolve().parents[k]`, `.parent`) or to a name bound to one, or as a
literal `.glob()` pattern under such a path. A directory is covered when the filters match a file
at any depth under it.

WHY a static scan: it runs in milliseconds with the unit suite and names the line that added the
read. A path finished at run time (a loop or a parameter) is seen only up to its last literal
segment, so the scan reports the enclosing directory and errs toward running the suite, unless
`_READ_THROUGH` names the files the test reads there.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[4]
_ENGINE_PARTS = ("apps", "screamingface-engine")
_WORKFLOW = _REPO / ".github" / "workflows" / "screamingface-engine-tests.yml"
#: Files at three depths under a directory; the filters cover the directory when they match all.
_DIR_PROBES = ("probe", "a/probe", "a/b/probe")
#: Receivers of these methods are only tested for existence, never read.
_EXISTENCE_CHECKS = frozenset({"exists", "is_dir", "is_file"})
_PATH_LITERAL = re.compile(r"[\w.-]+(?:/[\w.-]+)+")

#: A directory a test finishes at run time, from a loop or a parameter, mapped to the files under
#: it that test reads. WHY: the scan sees only the directory, and its whole tree in the filters
#: would run the Engine suite on every change under it. INVARIANT: each entry is still a directory
#: the scan reports, and each file exists; a stale entry fails its own test below.
_READ_THROUGH: dict[str, tuple[str, ...]] = {
    # tests/unit/test_tortoise_pin_conformance.py: `project / "pyproject.toml"` and `"uv.lock"`
    "apps/aigateway": ("pyproject.toml", "uv.lock"),
    "packages/screamingface": ("pyproject.toml", "uv.lock"),
    # tests/unit/test_declared_models_match_aigateway.py: `_PLUGINS / relative`, its slug tables
    "apps/aigateway/src/aigateway/plugins": (
        "anthropic_provider/settings.py",
        "antigravity_provider/settings.py",
        "codex_provider/models.py",
        "gemini_provider/models.py",
        "huggingface_provider/settings.py",
        "openrouter_provider/settings.py",
    ),
    # tests/unit/test_benchmark_deployment.py: `workflows / deployed`, the deploying workflows
    ".github/workflows": ("dev-build-screamingface-engine.yml", "release-screamingface-engine.yml"),
}

type Parts = tuple[str, ...]
type Named = list[tuple[Parts, int]]


def _up(parts: Parts | None, levels: int) -> Parts | None:
    """``parts`` without its last ``levels`` segments; None above the repo root."""
    if parts is None or levels > len(parts):
        return None
    return parts[: len(parts) - levels]


def _is_path_call(func: ast.expr) -> bool:
    """``Path`` or ``pathlib.Path``."""
    match func:
        case ast.Name(id="Path") | ast.Attribute(value=ast.Name(id="pathlib"), attr="Path"):
            return True
        case _:
            return False


def _built_from(node: ast.expr) -> list[ast.expr]:
    """The sub-expressions a resolved ``node`` is built from; they are not reads themselves."""
    inner: list[ast.expr] = []
    match node:
        case ast.BinOp(left=left, right=right):
            inner = [left, right]
        case ast.Attribute(value=base) | ast.Subscript(value=ast.Attribute(value=base)):
            inner = [base]
        case ast.Call(func=ast.Attribute(value=base) as func) if not _is_path_call(func):
            inner = [base]
        case _:
            pass
    return inner


class _Resolver:
    """Resolves the path expressions of one test module to repo-relative parts."""

    def __init__(self, file_parts: Parts) -> None:
        self._file = file_parts
        self._names: dict[str, Parts] = {}

    def resolve(self, node: ast.expr) -> Parts | None:
        """The repo-relative parts ``node`` evaluates to, or None when it is not a repo path."""
        parts: Parts | None = None
        match node:
            # WHY: only a loaded name; the target of `X = ...` is a binding, not a read.
            case ast.Name(id=name, ctx=ast.Load()):
                parts = self._names.get(name)
            case ast.Call(func=func, args=[ast.Name(id="__file__")]) if _is_path_call(func):
                parts = self._file
            case ast.Call(func=ast.Attribute(value=base, attr="resolve"), args=[]):
                parts = self.resolve(base)
            case ast.Attribute(value=base, attr="parent"):
                parts = _up(self.resolve(base), 1)
            case ast.Subscript(
                value=ast.Attribute(value=base, attr="parents"),
                slice=ast.Constant(value=int() as level),
            ):
                parts = _up(self.resolve(base), level + 1)
            case ast.BinOp(left=left, op=ast.Div(), right=ast.Constant(value=str() as segment)):
                inner = self.resolve(left)
                parts = None if inner is None else inner + tuple(filter(None, segment.split("/")))
            case _:
                pass
        return parts

    def bind(self, tree: ast.Module) -> set[int]:
        """Binds each ``NAME = <repo path>`` in source order; the ids of the values it bound."""
        bound: set[int] = set()
        statements = sorted(
            (n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))),
            key=lambda n: (n.lineno, n.col_offset),
        )
        for statement in statements:
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            value = statement.value
            parts = None if value is None else self.resolve(value)
            match targets:
                case [ast.Name(id=name)] if value is not None and parts is not None:
                    self._names[name] = parts
                    bound.add(id(value))
                case _:
                    pass
        return bound


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


def _glob_call(node: ast.expr, resolved: dict[int, Parts]) -> tuple[ast.expr, Path, str] | None:
    """``(base, root, pattern)`` when ``node`` globs a literal pattern under a repo path."""
    match node:
        case ast.Call(
            func=ast.Attribute(value=base, attr="glob" | "rglob" as method),
            args=[ast.Constant(value=str() as pattern)],
        ) if id(base) in resolved:
            # WHY: `rglob(p)` is `glob("**/" + p)`.
            return (
                base,
                _REPO.joinpath(*resolved[id(base)]),
                ("**/" if method == "rglob" else "") + pattern,
            )
        case _:
            return None


def _not_reads(node: ast.expr, resolved: dict[int, Parts]) -> list[ast.expr]:
    """The sub-expressions of ``node`` that only build a path, test it, or root a glob."""
    inner = _built_from(node) if id(node) in resolved else []
    if isinstance(node, ast.Attribute) and node.attr in _EXISTENCE_CHECKS:
        # WHY: the whole receiver, so `(p / "marker").is_file()` over a loop's `p` is no read.
        inner.extend(n for n in ast.walk(node.value) if isinstance(n, ast.expr))
    if (glob := _glob_call(node, resolved)) is not None:
        inner.append(glob[0])
    return inner


def _literal(node: ast.expr) -> Parts | None:
    """The parts of a repo-relative path string literal; None for anything else."""
    match node:
        case ast.Constant(value=str() as text) if _PATH_LITERAL.fullmatch(text):
            # WHY: a literal that names an Engine file relative to the Engine root is local.
            local = _REPO.joinpath(*_ENGINE_PARTS, text).exists()
            return None if local else tuple(text.split("/"))
        case _:
            return None


def _outside(named: Named) -> dict[str, int]:
    """The existing paths outside the Engine among ``named``, each with its first line."""
    found: dict[str, int] = {}
    for parts, line in sorted(named, key=lambda entry: entry[1]):
        outside = parts[: len(_ENGINE_PARTS)] != _ENGINE_PARTS
        if parts and outside and _REPO.joinpath(*parts).exists():
            found.setdefault("/".join(parts), line)
    return found


def reads(source: str, file_parts: Parts) -> dict[str, int]:
    """Every existing repo path outside the Engine that ``source`` names, with its first line."""
    tree = ast.parse(source)
    resolver = _Resolver(file_parts)
    consumed = _docstrings(tree) | resolver.bind(tree)
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.expr)]
    resolved = {id(n): parts for n in nodes if (parts := resolver.resolve(n)) is not None}
    named: Named = []
    for node in nodes:
        consumed.update(id(inner) for inner in _not_reads(node, resolved))
        if (glob := _glob_call(node, resolved)) is not None:
            _, root, pattern = glob
            named.extend((m.relative_to(_REPO).parts, node.lineno) for m in root.glob(pattern))
    for node in nodes:
        parts = resolved.get(id(node)) or _literal(node)
        if id(node) not in consumed and parts:
            named.append((parts, node.lineno))
    return _outside(named)


def _glob(pattern: str) -> re.Pattern[str]:
    """A GitHub `paths:` glob as a regex: `**` crosses directories, `*` and `?` do not."""
    out: list[str] = []
    for token in re.split(r"(\*\*|\*|\?)", pattern):
        out.append({"**": ".*", "*": "[^/]*", "?": "[^/]"}.get(token, re.escape(token)))
    return re.compile("".join(out))


def _filters() -> dict[str, list[str]]:
    """The `paths:` list of each trigger of the Engine workflow."""
    document: dict[Any, Any] = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    # WHY: YAML 1.1 reads a bare `on:` key as the boolean True.
    triggers: dict[str, Any] = document["on"] if "on" in document else document[True]
    return {event: list(triggers[event]["paths"]) for event in ("push", "pull_request")}


def _covered(path: str, patterns: list[re.Pattern[str]]) -> bool:
    """Whether the filters match ``path``, or every probe file under it for a directory."""
    probes = [f"{path}/{p}" for p in _DIR_PROBES] if (_REPO / path).is_dir() else [path]
    return all(any(pattern.fullmatch(probe) for pattern in patterns) for probe in probes)


def _engine_test_reads() -> dict[str, list[str]]:
    """Every outside repo path the Engine tests name, with each place that names it."""
    found: dict[str, list[str]] = {}
    for file in sorted(_REPO.joinpath(*_ENGINE_PARTS, "tests").rglob("*.py")):
        # WHY: this module's own self-test sources name paths on purpose; they are not reads.
        if file == Path(__file__).resolve():
            continue
        relative = file.relative_to(_REPO)
        for path, line in reads(file.read_text(encoding="utf-8"), relative.parts).items():
            found.setdefault(path, []).append(f"{relative}:{line}")
    return found


def _expanded_reads() -> dict[str, set[str]]:
    """`_engine_test_reads`, each `_READ_THROUGH` directory replaced by the files it names."""
    expanded: dict[str, set[str]] = {}
    for read, places in _engine_test_reads().items():
        files = _READ_THROUGH.get(read)
        for path in [read] if files is None else [f"{read}/{f}" for f in files]:
            expanded.setdefault(path, set()).update(places)
    return expanded


def test_push_and_pull_request_filter_the_same_paths() -> None:
    filters = _filters()

    assert filters["push"] == filters["pull_request"]
    assert not any(p.startswith("!") for p in filters["push"]), "negated filters are not modelled"


def test_every_repo_path_an_engine_test_reads_runs_the_engine_suite() -> None:
    patterns = [_glob(p) for p in _filters()["push"]]

    uncovered = sorted(
        f"{path}  ({', '.join(sorted(places))})"
        for path, places in _expanded_reads().items()
        if not _covered(path, patterns)
    )

    assert not uncovered, "add these to both `paths:` lists:\n" + "\n".join(uncovered)


def test_each_read_through_directory_is_still_read_and_names_files() -> None:
    reported = _engine_test_reads()

    stale = sorted(directory for directory in _READ_THROUGH if directory not in reported)
    missing = sorted(
        f"{directory}/{file}"
        for directory, files in _READ_THROUGH.items()
        for file in files
        if not (_REPO / directory / file).is_file()
    )

    assert not stale, f"no Engine test reads these through a run-time name any more: {stale}"
    assert not missing, f"these `_READ_THROUGH` files do not exist: {missing}"


_SYNTHETIC = (*_ENGINE_PARTS, "tests", "unit", "test_synthetic.py")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            'X = "apps/aigateway/src/aigateway/config.py"\n',
            {"apps/aigateway/src/aigateway/config.py"},
            id="a-repo-relative-literal",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'RELAY = R / "apps/aigateway/tests/fixtures/provider_error_relay"\n'
            'X = (RELAY / "relayed_detail.json").read_text()\n'
            'Y = (R / "apps" / "aigateway" / "src" / "aigateway" / "config.py").read_text()\n',
            {
                "apps/aigateway/tests/fixtures/provider_error_relay/relayed_detail.json",
                "apps/aigateway/src/aigateway/config.py",
            },
            id="literals-joined-to-the-repo-root",
        ),
        pytest.param(
            'SDK = Path(__file__).resolve().parents[3].parent / "packages" / "screamingface"\n'
            'skip = not SDK.exists()\nX = (SDK / "pyproject.toml").read_text()\n',
            {"packages/screamingface/pyproject.toml"},
            id="a-bound-name-joined-later-and-an-existence-check",
        ),
        pytest.param(
            'SDK = Path(__file__).resolve().parents[4] / "packages" / "screamingface"\n'
            'def f(name):\n    return SDK / "src" / name\n',
            {"packages/screamingface/src"},
            id="a-run-time-suffix-reports-the-directory",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'X = [p.read_text() for p in R.glob("apps/*/src/aigateway/config.py")]\n'
            'Y = list((R / "apps" / "aigateway" / "src").rglob("config.py"))\n',
            {"apps/aigateway/src/aigateway/config.py"},
            id="a-glob-reads-the-files-it-matches",
        ),
        pytest.param(
            '"""Reads apps/aigateway/src/aigateway/config.py."""\n'
            'X = sorted((Path(__file__).resolve().parents[2] / "deploy" / "helm").iterdir())\n'
            'Y = "deploy/helm"\n',
            set(),
            id="engine-local-paths-and-docstrings-are-not-reads",
        ),
        pytest.param(
            "root = next(p for p in Path(__file__).resolve().parents\n"
            '            if (p / ".claude/scripts/check_layering.py").is_file())\n',
            set(),
            id="a-root-marker-tested-for-existence-is-not-a-read",
        ),
    ],
)
def test_the_scan_finds_each_way_a_test_names_a_path(source: str, expected: set[str]) -> None:
    assert set(reads(source, _SYNTHETIC)) == expected
