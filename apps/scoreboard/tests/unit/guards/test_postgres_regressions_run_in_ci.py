"""The PostgreSQL-only regressions must actually execute somewhere.

WHY this guard exists: `test_idempotency_postgres.py` is skipped unless
`SCOREBOARD_TEST_DATABASE_URL` is set. While no CI job set it, the module was green-by-skip
everywhere anyone looked, and it silently stopped reaching PostgreSQL at all — it submitted to a
private board without a verified identity, so `submit()` refused before opening a transaction.
The test that exists to catch a production-only bug (PostgreSQL rejects NUL in char types) had
itself become a production-only failure (review of PR #719).

The fix was to run it in CI. This guard is what stops the arrangement rotting: a new PostgreSQL
module that no job names would reintroduce exactly the same silence.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml

_SCOREBOARD = Path(__file__).resolve().parents[3]
_WORKFLOW = _SCOREBOARD.parents[1] / ".github" / "workflows" / "scoreboard-tests.yml"
_DATABASE_URL_VAR = "SCOREBOARD_TEST_DATABASE_URL"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(_WORKFLOW.read_text())


def _postgres_job() -> dict[str, Any]:
    jobs = _workflow()["jobs"]
    named = [
        job
        for job in jobs.values()
        if any(_DATABASE_URL_VAR in (step.get("env") or {}) for step in job.get("steps", []))
    ]
    assert len(named) == 1, (
        f"expected exactly one job setting {_DATABASE_URL_VAR}; found {len(named)}. "
        "Two jobs would race on the same database; none means the PostgreSQL regressions "
        "are skipped in CI."
    )
    return named[0]


def _modules_that_skip_without_postgres() -> set[str]:
    """Test modules that opt out of themselves when no database is configured.

    WHY the rule is "reads the URL *and* can skip" rather than a filename pattern: the risk
    being guarded is a module that goes quiet, and self-skipping is precisely what going quiet
    looks like. A filename match would also flag this guard, which needs no database and must
    never be listed in the job it is checking.
    """
    tests = _SCOREBOARD / "tests"
    found = set()
    for path in sorted(tests.rglob("test_*.py")):
        tree = ast.parse(path.read_text())
        if not _mentions(tree, _DATABASE_URL_VAR):
            continue
        if not _can_skip_itself(tree):
            continue
        found.add(str(path.relative_to(_SCOREBOARD)))
    return found


def _mentions(tree: ast.Module, value: str) -> bool:
    return any(isinstance(node, ast.Constant) and node.value == value for node in ast.walk(tree))


def _can_skip_itself(tree: ast.Module) -> bool:
    """A `skipif` decorator or a `pytest.skip()` call — read from the AST, never from text.

    WHY the AST: a substring search for those names matches this very module, which writes them
    down in order to look for them. Detecting the syntax instead of the spelling means a guard
    can describe what it hunts without becoming its own quarry.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted(node.func).endswith("pytest.skip"):
            return True
        for decorator in getattr(node, "decorator_list", []):
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if _dotted(target).endswith("skipif"):
                return True
    return False


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def test_a_ci_job_supplies_a_real_postgres_database() -> None:
    job = _postgres_job()
    services = job.get("services") or {}
    images = [str(service.get("image", "")) for service in services.values()]

    assert any(image.startswith("postgres:") for image in images), (
        f"the job setting {_DATABASE_URL_VAR} has no `postgres:` service, so the URL would "
        f"point at nothing and every test would fail to connect. Services: {images}"
    )


def test_every_postgres_test_module_is_named_in_that_job() -> None:
    # INVARIANT: the modules are NAMED, never globbed. `pytest tests/unit/scores/` would run them
    # under the default SQLite settings too, and a glob that matches nothing exits 0 — both leave
    # the step green while covering less than it claims. An explicitly named file that has been
    # renamed makes pytest exit non-zero, which is the failure mode worth having.
    job = _postgres_job()
    commands = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))

    on_disk = _modules_that_skip_without_postgres()
    assert on_disk, (
        "no module skips itself without a database, so this guard is watching nothing. Either "
        "the PostgreSQL regressions were deleted or the detection rule no longer matches them."
    )

    missing = sorted(module for module in on_disk if module not in commands)
    assert not missing, (
        f"{missing} exist but no CI step runs them, so they are skipped everywhere. "
        f"Add each to the pytest invocation in the {_DATABASE_URL_VAR} job of "
        f"{_WORKFLOW.name}."
    )
