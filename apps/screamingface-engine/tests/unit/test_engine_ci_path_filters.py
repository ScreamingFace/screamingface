"""The Engine CI workflow runs on every repo file an Engine test reads.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).
STORY: as a Gateway, SDK or scoreboard developer, a change that breaks an Engine contract twin
fails its own pull request, instead of merging green and failing the next unrelated Engine change.

INVARIANT: every repo path outside the Engine that an Engine test uses, as
`engine_ci_support.uses` finds it, is matched by the `paths:` filters of both the `push` and the
`pull_request` trigger. A file is covered when the filters match it. A directory a test reads is
covered when they match a file at any depth under it. A directory `_READ_THROUGH` lists is covered
when they cover what its readers reach through it (`engine_ci_read_through.reached`). A directory
a test only tests for existence is covered when they match one file under it: it disappears only
when that file does. A path that does not exist yet is covered when they match it and every file
under it, because it can appear as either. The repo root is read through like a listed
directory with no reviewed reader, and the root itself, a join on it with a run-time name, is
never covered. A path built on a module outside the repo (`<import M>`) is covered only when
`_FOREIGN_MODULES` lists M.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import cache
from pathlib import Path

import engine_ci_paths
import engine_ci_read_through
import engine_ci_support
from engine_ci_modules import foreign
from engine_ci_read_through import Reader, named_under, passes_on, reached
from engine_ci_support import ENGINE_PARTS, REPO, ROOT, Use, filters, glob, uses

#: Files at three depths under a directory; the filters cover the directory when they match all.
_DIR_PROBES = ("probe", "a/probe", "a/b/probe")
#: WHY: the guard's own modules name paths on purpose; they are not reads.
_GUARD = frozenset(
    {
        Path(__file__).resolve(),
        Path(__file__).with_name("test_engine_ci_path_scan.py").resolve(),
        Path(__file__).with_name("test_engine_ci_import_scan.py").resolve(),
        Path(engine_ci_support.__file__).resolve(),
        Path(engine_ci_paths.__file__).resolve(),
        Path(engine_ci_read_through.__file__).resolve(),
    }
)
#: Where the guard's own cases place a reader's source.
_BESIDE = (*ENGINE_PARTS, "tests", "unit", "test_reader.py")

#: Reviewed: it keeps each project in `_PROJECTS` and reads one only by the literal joins of
#: `_pin` and `_locked`, so each join on a root the scan cannot resolve is a join to the project.
_TORTOISE = frozenset({"tests/unit/test_tortoise_pin_conformance.py"})
#: Directories a test finishes at run time, each with the readers reviewed to pass it on to a value
#: the scan cannot follow. WHY: the scan sees only the directory, and its whole tree in the filters
#: would run the Engine suite on every change under it. INVARIANT: a listed directory stands for
#: what its readers reach through it, so a new name is checked too. A listed directory no test
#: reads, a reader that names no file in it, and a reviewed reader that no longer passes it on
#: each fail their own test.
_READ_THROUGH: dict[str, frozenset[str]] = {
    # tests/unit/test_tortoise_pin_conformance.py: `project / "pyproject.toml"`, `"uv.lock"`
    "apps/aigateway": _TORTOISE,
    "packages/screamingface": _TORTOISE,
    # tests/unit/test_declared_models_match_aigateway.py: `_PLUGINS / relative`, its tables
    "apps/aigateway/src/aigateway/plugins": frozenset(),
    # tests/unit/test_benchmark_deployment.py: `workflows / deployed`, the deploying workflows
    ".github/workflows": frozenset(),
}
#: Modules outside the repo that an Engine test builds a path on, each reviewed: none is a repo
#: module the scan failed to find, so no change in the repo can change the files it gives.
_FOREIGN_MODULES = {
    # tests/unit/inspect/test_cyse4_threat_intelligence_prefetch.py: the installed evaluations.
    "inspect_evals": "a third-party package of evaluations, installed from its index",
}


def _matched(path: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.fullmatch(path) for pattern in patterns)


def _covered(path: str, exists_only: bool, patterns: list[re.Pattern[str]]) -> bool:
    """Whether a change to ``path`` that its test can see starts the Engine workflow."""
    target = REPO / path
    every_file = all(_matched(f"{path}/{probe}", patterns) for probe in _DIR_PROBES)
    module = foreign(path)
    if module is not None or path == ROOT:
        # WHY: no filter covers the repo root joined with a run-time name, or a module outside
        # the repo; the module is covered when it is reviewed and listed.
        return module in _FOREIGN_MODULES
    if not target.is_dir():
        # WHY: a path that does not exist yet can appear as a file or as a directory.
        return _matched(path, patterns) and (target.exists() or every_file)
    return _one_file_under(target, patterns) if exists_only else every_file


def _one_file_under(directory: Path, patterns: list[re.Pattern[str]]) -> bool:
    """Whether the filters match at least one file under ``directory``."""
    return any(
        _matched((folder / name).relative_to(REPO).as_posix(), patterns)
        for folder, _, names in directory.walk()
        for name in names
    )


def _named_under(directory: str, sources: Iterable[str]) -> set[str]:
    """`named_under` for readers placed beside the guard."""
    return named_under(directory, [(_BESIDE, source) for source in sources])


def _reached(directory: str, source: str, reviewed: frozenset[str] = frozenset()) -> set[str]:
    """`reached` for one reader placed beside the guard."""
    return reached(directory, [(_BESIDE, source)], reviewed)


def _reader(file: Path) -> Reader:
    return file.relative_to(REPO).parts, file.read_text(encoding="utf-8")


@cache
def _engine_test_uses() -> dict[str, dict[Path, Use]]:
    """Every outside repo path the Engine tests use, with each module that uses it and how.

    WHY the cache: two tests read it, and the scan of the whole suite takes seconds.
    """
    found: dict[str, dict[Path, Use]] = {}
    for file in sorted(REPO.joinpath(*ENGINE_PARTS, "tests").rglob("*.py")):
        if file in _GUARD:
            continue
        parts = file.relative_to(REPO).parts
        for path, use in uses(file.read_text(encoding="utf-8"), parts).items():
            found.setdefault(path, {})[file] = use
    return found


def _expanded_uses() -> dict[tuple[str, bool], set[str]]:
    """`_engine_test_uses` by path and kind, each read-through directory replaced by its files."""
    expanded: dict[tuple[str, bool], set[str]] = {}
    for path, users in _engine_test_uses().items():
        for exists_only in {use.exists_only for use in users.values()}:
            readers = [f for f, use in users.items() if use.exists_only == exists_only]
            places = {f"{f.relative_to(REPO)}:{users[f].line}" for f in readers}
            # WHY the root too: it is read through like a listed directory, with no reader
            # reviewed, so a join on it with a name the scan can read reaches what it spells.
            through = not exists_only and (path in _READ_THROUGH or path == ROOT)
            files = [path]
            if through:
                reviewed = _READ_THROUGH.get(path, frozenset())
                files = sorted(reached(path, map(_reader, readers), reviewed))
            for file in files:
                expanded.setdefault((file, exists_only), set()).update(places)
    return expanded


def test_push_and_pull_request_filter_the_same_paths() -> None:
    lists = filters()

    assert lists["push"] == lists["pull_request"]
    assert not any(p.startswith("!") for p in lists["push"]), "negated filters are not modelled"


def test_every_repo_path_an_engine_test_uses_runs_the_engine_suite() -> None:
    patterns = [glob(p) for p in filters()["push"]]

    uncovered = sorted(
        f"{'exists' if exists_only else 'reads'} {path}"
        f"{'' if (REPO / path).exists() or foreign(path) else ' (not there yet)'}"
        f"  ({', '.join(sorted(places))})"
        for (path, exists_only), places in _expanded_uses().items()
        if not _covered(path, exists_only, patterns)
    )

    assert not uncovered, (
        "add these to both `paths:` lists; a path not there yet needs itself and `<path>/**`; "
        "`.` is the repo root joined with a run-time name, which no filter covers, so name that "
        "path with literals; `<import M>` is a module the scan finds neither in the repo nor in "
        "the standard library: import it from the repo, or review it and list it in "
        "`_FOREIGN_MODULES`:\n" + "\n".join(uncovered)
    )


def test_each_read_through_directory_is_still_read_and_its_readers_name_a_file_there() -> None:
    found = _engine_test_uses()

    readers = {
        directory: [f for f, use in found.get(directory, {}).items() if not use.exists_only]
        for directory in _READ_THROUGH
    }
    stale = sorted(directory for directory, files in readers.items() if not files)
    empty = sorted(
        directory
        for directory, files in readers.items()
        if files and not _named_under(directory, (f.read_text(encoding="utf-8") for f in files))
    )

    assert not stale, f"no Engine test reads these through a run-time name any more: {stale}"
    assert not empty, f"the readers of these name no file in them as a literal: {empty}"


def test_a_read_through_directory_stands_for_the_files_its_readers_name() -> None:
    source = 'T = ("pyproject.toml", "uv.lock", "src", "absent.txt", "../CLAUDE.md", 3)\n'

    named = _named_under("apps/aigateway", [source])

    assert named == {"apps/aigateway/pyproject.toml", "apps/aigateway/uv.lock"}


def test_a_directory_tested_for_existence_needs_one_matched_file_under_it() -> None:
    one = [glob("packages/screamingface/pyproject.toml")]
    everything = [glob("**")]

    assert _covered("packages/screamingface", True, one)
    assert not _covered("packages/screamingface", False, one)
    assert not _covered("packages/url4", True, one)
    assert _covered("packages/screamingface/pyproject.toml", True, one)
    assert not _covered(ROOT, False, everything)


def test_a_read_through_directory_stands_for_the_literal_tail_of_each_join() -> None:
    source = (
        "def f(project, name):\n"
        '    return (project / "pyproject.toml", project / "src" / "aigateway" / "main.py",\n'
        '            project.joinpath("tests", "fixtures"), project / "src" / name,\n'
        '            project / ".." / "url4" / "pyproject.toml")\n'
    )

    named = _named_under("apps/aigateway", [source])

    # WHY the directories: a tail that a run-time name finishes, or that names a directory,
    # stands for every file under it.
    assert named == {
        "apps/aigateway/pyproject.toml",
        "apps/aigateway/src/aigateway/main.py",
        "apps/aigateway/tests/fixtures",
        "apps/aigateway/src",
    }


def test_a_path_that_does_not_exist_yet_needs_itself_and_every_file_under_it_matched() -> None:
    absent = "apps/aigateway/tests/fixtures/new_contract"

    assert not (REPO / absent).exists()
    assert not _covered(absent, True, [glob(f"{absent}/**")])
    assert not _covered(absent, True, [glob(absent)])
    assert _covered(absent, True, [glob(absent), glob(f"{absent}/**")])
    assert _covered(absent, False, [glob("apps/aigateway/tests/fixtures/**")])


def test_a_join_a_run_time_value_interrupts_stands_for_the_whole_directory() -> None:
    sources = [
        "def f(project, name):\n"
        '    return (project / "pyproject.toml", project / name / "main.py")\n',
        'def f(project, name):\n    return project / f"{name}/main.py"\n',
        'def f(project, name):\n    return project.joinpath(name, "main.py")\n',
    ]

    named = [_named_under("apps/aigateway", [source]) for source in sources]

    assert named == [
        {"apps/aigateway/pyproject.toml", "apps/aigateway"},
        {"apps/aigateway"},
        {"apps/aigateway"},
    ]


def test_a_path_built_on_an_unresolved_import_needs_a_reviewed_module() -> None:
    everything = [glob("**")]

    assert _covered("<import inspect_evals>/data.json", False, [])
    assert not _covered("<import engine_ci_absent_helper>/apps/x.json", False, everything)


def test_in_a_reviewed_reader_a_join_counts_before_its_file_exists() -> None:
    sources = [
        'def f(project):\n    return (project / "future.toml").read_text()\n',
        "def f(project, name):\n"
        '    return (project / "pyproject.toml").read_text(), (project / name).read_text()\n',
        "def f(project):\n"
        '    for name in ("pyproject.toml", "future.toml"):\n'
        "        (project / name).read_text()\n",
        'TABLE = (("names", "a/settings.py"), ("slugs", "b/models.py"))\n'
        "def f(project):\n"
        "    for _, relative in TABLE:\n"
        "        (project / relative).read_text()\n",
        'R = Path(__file__).resolve().parents[4]\nX = (R / "apps" / "absent.toml").read_text()\n',
    ]

    named = [_named_under("apps/aigateway", [source]) for source in sources]

    # WHY the last: a join the scan resolves is not a join to the directory.
    assert named == [
        {"apps/aigateway/future.toml"},
        {"apps/aigateway/pyproject.toml", "apps/aigateway"},
        {"apps/aigateway/pyproject.toml", "apps/aigateway/future.toml"},
        {"apps/aigateway/a/settings.py", "apps/aigateway/b/models.py"},
        set(),
    ]


def test_a_join_on_a_name_the_scan_cannot_read_reaches_the_whole_directory() -> None:
    sources = [
        "def f(project, name):\n"
        "    if not name:\n"
        '        name = "b.toml"\n'
        "    return (project / name).read_text()\n",
        'from elsewhere import name\nif not name:\n    name = "b.toml"\n'
        "def f(project):\n    return (project / name).read_text()\n",
        "def f(project, value):\n"
        '    for name in ("a.toml",):\n'
        "        pass\n"
        "    match value:\n"
        "        case str(name):\n"
        "            (project / name).read_text()\n",
        "def f(project):\n"
        '    for _, name in enumerate(("a.toml",)):\n'
        "        (project / name).read_text()\n",
    ]

    named = [_named_under("apps/aigateway", [source]) for source in sources]

    # WHY: a parameter, an import, a `match` capture or a call can be any name.
    assert named == [{"apps/aigateway"}] * len(sources)


_WORKFLOWS = 'WORKFLOWS = Path(__file__).resolve().parents[4] / ".github" / "workflows"\n'


def test_a_reader_reaches_the_names_it_joins_to_the_directory() -> None:
    looped = (
        f"{_WORKFLOWS}def test(tmp_path):\n"
        '    for deployed in ("release-screamingface-engine.yml", "future.yml"):\n'
        "        (WORKFLOWS / deployed).read_text()\n"
        '    for extra in ("extra.yml",):\n'
        "        WORKFLOWS.joinpath(extra).read_text()\n"
        '    (tmp_path / "alpha").mkdir()\n'
    )
    joined = f"{_WORKFLOWS}def f(name):\n    return (WORKFLOWS / name).read_text()\n"
    nested = (
        f"{_WORKFLOWS}def f():\n"
        '    for kind in ("a", "b"):\n'
        '        (WORKFLOWS / kind / "main.yml").read_text()\n'
    )
    globbed = 'R = Path(__file__).resolve().parents[4]\nX = list(R.glob(".github/workflow?"))\n'

    assert _reached(".github/workflows", looped) == {
        ".github/workflows/release-screamingface-engine.yml",
        ".github/workflows/future.yml",
        ".github/workflows/extra.yml",
    }
    assert not passes_on(".github/workflows", (_BESIDE, looped))
    assert _reached(".github/workflows", joined) == {".github/workflows"}
    # WHY: a run-time name followed by more of the path can reach any file under it.
    assert _reached(".github/workflows", nested) == {".github/workflows"}
    # WHY: a reader that names the directory only by a glob match is read as a whole.
    assert _reached(".github/workflows", globbed) == {".github/workflows"}


def test_a_reader_that_passes_the_directory_on_reaches_all_of_it_unless_reviewed() -> None:
    source = (
        'PROJECTS = [Path(__file__).resolve().parents[4] / "apps" / "aigateway"]\n'
        "def read(project):\n"
        '    return (project / "future.toml").read_text()\n'
    )
    reviewed = frozenset({"tests/unit/test_reader.py"})

    assert _reached("apps/aigateway", source) == {"apps/aigateway"}
    assert _reached("apps/aigateway", source, reviewed) == {"apps/aigateway/future.toml"}
    assert passes_on("apps/aigateway", (_BESIDE, source))


def test_each_reviewed_reader_still_passes_its_directory_on() -> None:
    stale = sorted(
        f"{directory}: {reader}"
        for directory, readers in _READ_THROUGH.items()
        for reader in readers
        if not passes_on(directory, _reader(REPO.joinpath(*ENGINE_PARTS, reader)))
    )

    assert not stale, f"these readers no longer pass the directory on; drop their review: {stale}"


def test_the_repo_root_is_read_through_with_no_reviewed_reader() -> None:
    root = "R = Path(__file__).resolve().parents[4]\n"
    looped = (
        f"{root}"
        'FILES = ("apps/aigateway/pyproject.toml", "apps/aigateway/future.toml")\n'
        "def test():\n"
        "    for name in FILES:\n"
        "        assert (R / name).is_file()\n"
    )
    joined = f"{root}def f(name):\n    return (R / name).read_text()\n"

    assert _reached(ROOT, looped) == {
        "apps/aigateway/pyproject.toml",
        "apps/aigateway/future.toml",
    }
    # WHY: no filter covers the root itself, so a name the scan cannot read fails the guard.
    assert _reached(ROOT, joined) == {ROOT}


def test_a_name_from_a_table_that_can_change_reaches_the_whole_directory() -> None:
    sources = [
        'FILES = ["a.toml"]\nFILES.append(name())\n'
        "def f(project):\n    for each in FILES:\n        (project / each).read_text()\n",
        'FILES = (["a.toml"],)\n'
        "def f(project):\n    for (each,) in FILES:\n        (project / each).read_text()\n",
    ]

    named = [_named_under("apps/aigateway", [source]) for source in sources]

    # WHY: a list grows in place or through another name; only a tuple of literals stays put.
    assert named == [{"apps/aigateway"}] * len(sources)
