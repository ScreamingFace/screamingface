"""The `url4-cloud` entrypoint dispatches to the right mode.

One image ships both halves, and ARGV is the only thing that decides which one runs — so this
is the seam where a mistake is silent and expensive: a Job that boots a web server would sit
there holding its `activeDeadlineSeconds` while an attached client sees heartbeats forever and
never a terminal frame.
"""

import subprocess
import sys

import pytest

from screamingface_engine import cli


@pytest.fixture
def modes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which mode `main` selects, without entering either for real."""
    called: list[str] = []
    monkeypatch.setattr(cli, "_serve", lambda: called.append("serve"))
    monkeypatch.setattr(cli, "_run", lambda: called.append("run"))
    monkeypatch.setattr(cli, "_worker", lambda: called.append("worker"))
    return called


def test_no_subcommand_serves(modes: list[str]) -> None:
    # INVARIANT: this is the image's `CMD ["url4-cloud"]` and the chart's Deployment command.
    # If bare argv ever stopped meaning `serve`, every deployment would break at once.
    cli.main([])
    assert modes == ["serve"]


def test_serve_subcommand_serves(modes: list[str]) -> None:
    cli.main(["serve"])
    assert modes == ["serve"]


def test_run_subcommand_runs(modes: list[str]) -> None:
    # INVARIANT: this is what the worker pool's children enter (`screamingface-engine run`).
    cli.main(["run"])
    assert modes == ["run"]


def test_worker_subcommand_workers(modes: list[str]) -> None:
    # INVARIANT: the worker pool (OME-1086) starts every Pod with this subcommand.
    cli.main(["worker"])
    assert modes == ["worker"]


def test_an_unknown_mode_exits_loudly_rather_than_serving(modes: list[str]) -> None:
    """A typo'd mode must be exit-2, never a silent fallback to serving.

    `add_subparsers` is not `required`, so `main` treats "no mode" as serve — this pins that the
    permissiveness stops there and does not extend to a mode that was asked for but misspelled.
    """
    with pytest.raises(SystemExit) as exc:
        cli.main(["srve"])
    assert exc.value.code == 2
    assert modes == []


def test_run_resolves_the_real_runner_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_run` itself, unshimmed — so the lazy import is proven to resolve.

    The tests above replace `cli._run` wholesale, which would keep passing even if
    its import line named a module that no longer exists. This one patches the far
    side instead, so a rename under `screamingface_engine.runner` fails here rather
    than at a Job's first boot in-cluster.
    """
    import screamingface_engine.runner.main as runner_main

    called: list[bool] = []
    monkeypatch.setattr(runner_main, "main", lambda: called.append(True))

    cli._run()

    assert called == [True]


def test_worker_resolves_the_real_worker_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_worker` itself, unshimmed — so the lazy import is proven to resolve."""
    import screamingface_engine.worker.loop as worker_loop

    called: list[bool] = []
    monkeypatch.setattr(worker_loop, "run_worker", lambda: called.append(True))

    cli._worker()

    assert called == [True]


def test_worker_mode_does_not_import_the_run_half() -> None:
    """The worker spawns the run as a child process; it never imports it.

    `check_layering.py` proves it over the import GRAPH; this proves it over what a real
    interpreter actually loads — the worker's import graph is the serving half's plus the
    queue, and the engine-bearing run half stays out of the worker's process.
    """
    probe = (
        "import sys, screamingface_engine.worker.loop;"
        "print(','.join(sorted(m for m in sys.modules if "
        "m.startswith('screamingface_engine.runner.') or m == 'screamingface_engine.runner' "
        "or m == 'url4.streaming.lifecycle')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", (
        f"`screamingface-engine worker` loaded the run half: {result.stdout.strip()}"
    )


def test_run_mode_does_not_import_the_serving_stack() -> None:
    """The run path must not load FastAPI/uvicorn/the kubernetes client.

    This is the cold-start budget the separate slim runner image used to guarantee structurally.
    `check_layering.py` proves it over the import GRAPH; this proves it over what a real
    interpreter actually loads, which is what a Job pays for. A subprocess because the in-test
    interpreter has already imported the whole app.
    """
    probe = (
        "import sys, screamingface_engine.runner.main;"
        "print(','.join(sorted({m.split('.')[0] for m in sys.modules} & "
        "{'fastapi','uvicorn','starlette','kubernetes','jwt','prometheus_client'})))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", (
        f"`url4-cloud run` loaded serving-side packages: {result.stdout.strip()}"
    )
