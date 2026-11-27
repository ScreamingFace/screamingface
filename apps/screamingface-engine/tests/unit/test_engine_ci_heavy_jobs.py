"""Only an Engine change builds the Engine images and runs the real-broker and chart jobs.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).
STORY: as an SDK or Gateway developer, my pull request runs the Engine unit tests against the
contract twins it can break, without a 30 to 45 minute image build it cannot change.

INVARIANT: the `changes` job calls a change an Engine change when a changed path matches its
`ENGINE_PATHS` pattern, or when it cannot tell, and `image`, `conformance` and `chart` run only
then. Every build-context path the Engine Dockerfiles copy, the build context's `.dockerignore`,
and the workflow itself match the pattern, so a change that alters an image always builds it.
`test` runs for every change.
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from engine_ci_support import filters, glob

_REPO = Path(__file__).resolve().parents[4]
_ENGINE = _REPO / "apps" / "screamingface-engine"
_WORKFLOW = _REPO / ".github" / "workflows" / "screamingface-engine-tests.yml"
_HEAVY = ("image", "conformance", "chart")
_GATE = "needs.changes.outputs.engine == 'true'"
_ZERO = "0" * 40


def _jobs() -> dict[str, Any]:
    """The jobs of the Engine workflow."""
    document: dict[Any, Any] = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return document["jobs"]


def _classifier() -> dict[str, Any]:
    """The `changes` job's one step that sets `ENGINE_PATHS`."""
    steps: list[dict[str, Any]] = _jobs()["changes"]["steps"]
    [step] = [s for s in steps if "ENGINE_PATHS" in s.get("env", {})]
    return step


def _engine_change(path: str) -> bool:
    return re.search(_classifier()["env"]["ENGINE_PATHS"], path) is not None


def _starts_the_workflow(path: str) -> bool:
    return any(glob(pattern).fullmatch(path) for pattern in filters()["push"])


def _image_builds() -> list[dict[str, Any]]:
    """The `with:` of each image build step of the `image` job."""
    steps: list[dict[str, Any]] = _jobs()["image"]["steps"]
    return [s["with"] for s in steps if str(s.get("uses", "")).startswith("docker/build-push")]


def _copied_sources() -> list[str]:
    """The build-context paths the Engine Dockerfiles copy; `COPY --from` reads a stage."""
    sources: list[str] = []
    for name in ("Dockerfile", "Dockerfile.benchmark"):
        for line in (_ENGINE / name).read_text(encoding="utf-8").splitlines():
            words = line.split()
            if words[:1] == ["COPY"] and not any(w.startswith("--from") for w in words):
                sources += [w for w in words[1:-1] if not w.startswith("--")]
    return sources


def test_each_heavy_job_waits_for_the_classifier_and_runs_only_for_an_engine_change() -> None:
    jobs = _jobs()

    for name in _HEAVY:
        needs = jobs[name].get("needs", [])
        assert "changes" in ([needs] if isinstance(needs, str) else needs), name
        assert jobs[name].get("if") == _GATE, name


def test_the_unit_test_job_runs_for_every_change() -> None:
    test = _jobs()["test"]

    assert "if" not in test
    assert "needs" not in test


def test_every_path_an_engine_image_is_built_from_is_an_engine_change() -> None:
    sources = _copied_sources()

    assert len(sources) >= 3, f"the Dockerfile COPY parse found too little: {sources}"
    for source in sources:
        # WHY: a directory source matches only with a file under it.
        assert _engine_change(source) or _engine_change(f"{source}/probe"), source
    assert _engine_change(_WORKFLOW.relative_to(_REPO).as_posix())


def test_each_image_build_input_is_an_engine_change_that_starts_the_workflow() -> None:
    """WHY: both images build from the repo root, so its `.dockerignore` decides what they copy."""
    builds = _image_builds()
    inputs = [
        path
        for build in builds
        for path in (posixpath.normpath(f"{build['context']}/.dockerignore"), build["file"])
    ]

    assert len(builds) >= 2, builds
    for path in inputs:
        assert _engine_change(path), path
        assert _starts_the_workflow(path), path
    for source in _copied_sources():
        assert _starts_the_workflow(source) or _starts_the_workflow(f"{source}/probe"), source


#: WHY made-up names: a real repo path here would read as a test input to the path-filter guard.
@pytest.mark.parametrize(
    "path",
    [
        "packages/screamingface/src/screamingface/example_module.py",
        "apps/aigateway/example.lock",
        "apps/aigateway/tests/fixtures/example_fixture/example.json",
        ".github/workflows/example-tests.yml",
        "apps/screamingface-engine-example/readme.txt",
    ],
)
def test_a_path_only_unit_tests_read_is_not_an_engine_change(path: str) -> None:
    assert not _engine_change(path)


def _git(repo: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    identity = ("-c", "user.name=ci", "-c", "user.email=ci@example.invalid")
    done = subprocess.run(
        ["git", *identity, *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _commit(repo: Path, path: str) -> str:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(path, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", path)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(name="history")
def _history(tmp_path: Path) -> tuple[Path, list[str]]:
    """A throwaway repository: a root commit, then an SDK-only and an Engine commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    shas = [
        _commit(repo, "README.txt"),
        _commit(repo, "packages/screamingface/src/screamingface/example_module.py"),
        _commit(repo, "apps/screamingface-engine/src/screamingface_engine/example_module.py"),
    ]
    return repo, shas


def _classify(repo: Path, event: str, base: str, head: str) -> str:
    """Run the `changes` job's own script and return its `engine` output."""
    step = _classifier()
    output = repo.parent / "github_output"
    env = {
        "PATH": os.environ["PATH"],
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "EVENT": event,
        "BASE": base,
        "HEAD": head,
        "DEFAULT_BRANCH": "main",
        "ENGINE_PATHS": step["env"]["ENGINE_PATHS"],
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(repo.parent),
    }
    output.write_text("", encoding="utf-8")
    subprocess.run(["bash", "-e", "-c", step["run"]], cwd=repo, env=env, check=True)
    [line] = [x for x in output.read_text(encoding="utf-8").splitlines() if x.startswith("engine=")]
    return line.removeprefix("engine=")


def test_an_sdk_only_pull_request_is_not_an_engine_change(history: tuple[Path, list[str]]) -> None:
    repo, (root, sdk, _) = history

    assert _classify(repo, "pull_request", root, sdk) == "false"


@pytest.mark.parametrize(
    ("event", "base", "head"),
    [
        pytest.param("pull_request", 1, 2, id="an-engine-commit"),
        pytest.param("push", 0, 2, id="a-push-spanning-an-engine-commit"),
        pytest.param("workflow_dispatch", 0, 1, id="a-manual-run"),
        pytest.param("push", None, 1, id="a-new-branch-whose-fork-point-git-cannot-find"),
        pytest.param("push", 1, 1, id="an-empty-diff"),
    ],
)
def test_an_engine_change_or_any_doubt_runs_the_heavy_jobs(
    history: tuple[Path, list[str]], event: str, base: int | None, head: int
) -> None:
    repo, shas = history

    engine = _classify(repo, event, _ZERO if base is None else shas[base], shas[head])

    assert engine == "true"


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        pytest.param(1, "false", id="an-sdk-only-branch"),
        pytest.param(2, "true", id="a-branch-with-an-engine-commit"),
    ],
)
def test_a_new_branch_is_compared_with_where_it_left_the_default_branch(
    history: tuple[Path, list[str]], head: int, expected: str
) -> None:
    """WHY: a new branch's first push has an all-zero base; without its fork point every SDK
    branch would build the images once."""
    repo, shas = history
    _git(repo, "update-ref", "refs/remotes/origin/main", shas[0])

    assert _classify(repo, "push", _ZERO, shas[head]) == expected


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        pytest.param("push", "true", id="a-push-that-drops-an-engine-commit"),
        pytest.param("pull_request", "false", id="a-pull-request-whose-base-gained-one"),
    ],
)
def test_a_push_compares_its_two_trees_and_a_pull_request_its_own_commits(
    history: tuple[Path, list[str]], event: str, expected: str
) -> None:
    """WHY: GitHub filters a push by `before..after` and a pull request by `base...head`."""
    repo, (_, sdk, engine) = history
    _git(repo, "checkout", "-q", sdk)
    other = _commit(repo, "packages/screamingface/src/screamingface/other_module.py")

    assert _classify(repo, event, engine, other) == expected
