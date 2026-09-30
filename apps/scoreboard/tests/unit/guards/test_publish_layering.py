"""PB-20a — only adapters reach GitHub and the bucket; the publish core is pure (C11).

FEATURE: OME-1307 (E14). Same AST walk as `test_scoreboard_layering.py`, whose helpers it reuses.
INVARIANT: the walk reads the syntax tree, never the text, so a docstring that names a banned
module is not a violation. The one text scan (`api.github.com`) reads string constants only.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.unit.guards.test_scoreboard_layering import (
    SRC,
    _forbidden_imports,
    _package_of,
    _violations,
)

ADAPTERS = SRC / "adapters"
CORE_PUBLISH = SRC / "core" / "publish"
CORE_ADMIN = SRC / "core" / "auth" / "admin.py"
MAIN = SRC / "main.py"
# WHY a regex: the check looks for the GitHub API host as a whole name inside any string constant.
# A bare substring test would also match a longer host such as `api.github.com.evil`, and CodeQL
# flags that form (py/incomplete-url-substring-sanitization).
GITHUB_HOST = re.compile(r"(?<![\w.-])api\.github\.com(?![\w.-])")

# WHY these two: they imported `httpx` before E14 (`git grep -l httpx` at the merge base with
# `e14-reproducible-submission-spec`). `seed.py` reads the engine catalogue over HTTP.
# AIDEV-NOTE: a NEW module outside `adapters/` that needs `httpx` belongs in `adapters/`; do not
# add it here.
HTTPX_BEFORE_E14 = {SRC / "seed.py"}

GITHUB_ADAPTERS = (
    "scoreboard.adapters.github_releases",
    "scoreboard.adapters.s3_archive_reader",
    "scoreboard.adapters.fs_archive_reader",
)
PURE_BANNED = {
    "tortoise",
    "fastapi",
    "pydantic",
    "httpx",
    "jwt",
    "scoreboard.scores",
    "scoreboard.adapters",
}


def _sources() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files, "no scoreboard sources found; the guard is watching nothing"
    return files


def test_only_adapters_reach_github_and_the_bucket() -> None:
    outside = [
        path for path in _sources() if ADAPTERS not in path.parents and path not in HTTPX_BEFORE_E14
    ]

    assert _violations(outside, {"httpx"}) == {}
    # The adapters really import it: the guard is not vacuously green.
    assert _violations(sorted(ADAPTERS.glob("*.py")), {"httpx"})


def test_the_github_host_is_named_only_in_config() -> None:
    hits = []
    for path in _sources():
        constants = [
            node.value
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        if any(GITHUB_HOST.search(value) for value in constants):
            hits.append(path.name)

    assert hits == ["config.py"]


def test_only_main_imports_the_github_and_bucket_adapters() -> None:
    others = [path for path in _sources() if path != MAIN]

    assert _violations(others, set(GITHUB_ADAPTERS)) == {}
    # main.py really imports all three.
    imported = _forbidden_imports(MAIN.read_text(), set(GITHUB_ADAPTERS), _package_of(MAIN))
    assert set(imported) == set(GITHUB_ADAPTERS)


def test_the_publish_core_and_the_admin_decision_are_pure() -> None:
    files = [*sorted(CORE_PUBLISH.rglob("*.py")), CORE_ADMIN]
    assert len(files) > 2, "no publish core sources found; the guard is watching nothing"

    assert _violations(files, PURE_BANNED) == {}
