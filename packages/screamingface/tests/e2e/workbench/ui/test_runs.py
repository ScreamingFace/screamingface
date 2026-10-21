"""Workbench UI run manager (unit 4 plan, Task 4): one pytest run at a time, streamed, cancellable.

The fast tests inject a ``spawn`` that runs a tiny Python script (no pytest-in-pytest, no stack).
``test_cancel_runs_pytest_teardown`` runs a real pytest child: it pins Review Focus 2's premise
that a cancel lets fixture teardown (``targets.local_stack``'s ``down``) run.
``test_cancelling_a_local_boot_frees_its_ports`` boots the real keyless local stack (opt-in).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from harness._gating import E2E_ENV

from workbench.ui import runs
from workbench.ui.runs import (
    KNOWN_UI_TARGETS,
    Run,
    RunBusy,
    RunManager,
    RunRejected,
    RunRequest,
    runtime_data_dir,
    track_progress,
)

Spawn = Callable[[list[str], dict[str, str], Path], "subprocess.Popen[str]"]


def _script_spawn(script: str, calls: list[list[str]] | None = None) -> Spawn:
    def spawn(argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
        if calls is not None:
            calls.append(argv)
        return subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

    return spawn


def _manager(
    tmp_path: Path,
    script: str = "print('a'); print('b')",
    environ: Mapping[str, str] | None = None,
    *,
    interrupt_grace: float = 30.0,
    terminate_grace: float = 15.0,
    drain_grace: float = 2.0,
) -> RunManager:
    return RunManager(
        tmp_path,
        workdir=tmp_path,
        environ=environ or {},
        spawn=_script_spawn(script),
        interrupt_grace=interrupt_grace,
        terminate_grace=terminate_grace,
        drain_grace=drain_grace,
    )


def _no_process_matches(marker: str, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        out = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
        if out.stdout.strip() == "":
            return True
        time.sleep(0.1)
    return False


# --- command(): argv, env, gating ------------------------------------------------------------


def test_targets_are_the_keyless_and_the_paid_local_one() -> None:
    assert KNOWN_UI_TARGETS == ("replay", "local")


def test_command_sets_the_workbench_env_and_filters_notebooks(tmp_path: Path) -> None:
    argv, env = _manager(tmp_path).command(RunRequest("replay", ("quickstart",)), tmp_path / "o")
    assert argv[:3] == [sys.executable, "-m", "pytest"]
    assert argv[-1] == "tests/e2e/workbench/test_notebooks.py::test_notebook[replay-quickstart]"
    assert "-k" not in argv
    assert env["SCREAMINGFACE_TEST_E2E"] == "1"
    assert env["SCREAMINGFACE_WORKBENCH_TARGET"] == "replay"
    assert env["SCREAMINGFACE_WORKBENCH_REQUIRE_ALL"] == "1"
    assert env["SCREAMINGFACE_WORKBENCH_OUT"] == str(tmp_path / "o")
    assert "SCREAMINGFACE_TEST_PAID" not in env


def test_command_selects_exact_node_ids_and_the_whole_file_when_none_given(
    tmp_path: Path,
) -> None:
    # WHY node ids, not -k: a -k substring "quickstart" also selects "quickstart-v2", and a
    # stem named like a -k operator ("not") breaks the expression.
    m = _manager(tmp_path, environ={"OPENROUTER_API_KEY": "k"})
    argv, _ = m.command(RunRequest("replay", ("quickstart", "judge-panel")), tmp_path)
    node = "tests/e2e/workbench/test_notebooks.py::test_notebook"
    assert argv[-2:] == [f"{node}[replay-quickstart]", f"{node}[replay-judge-panel]"]
    argv_local, _ = m.command(RunRequest("local", ("not",), confirm_paid=True), tmp_path)
    assert argv_local[-1] == f"{node}[local-not]"
    argv_all, _ = m.command(RunRequest("replay", ()), tmp_path)
    assert argv_all[-1] == "tests/e2e/workbench/test_notebooks.py"
    assert not any("::" in a for a in argv_all)


def test_pytest_temp_dirs_live_under_the_run_out_dir(tmp_path: Path) -> None:
    # WHY: the local target's runtime data dir is a pytest temp dir; under the run's own out
    # dir the UI can name it in the stop command after a cancel (and its logs stay on disk).
    out = tmp_path / "runs" / "r"
    argv, _ = _manager(tmp_path).command(RunRequest("replay", ()), out)
    assert f"--basetemp={out / 'pytest-tmp'}" in argv


def test_the_runtime_data_dir_is_found_only_when_unambiguous(tmp_path: Path) -> None:
    run = Run("r", RunRequest("local", (), confirm_paid=True), tmp_path / "out")
    assert runtime_data_dir(run) is None
    data = run.out_dir / "pytest-tmp" / "workbench-target0" / "data"
    data.mkdir(parents=True)
    assert runtime_data_dir(run) == data
    (run.out_dir / "pytest-tmp" / "workbench-target1" / "data").mkdir(parents=True)
    assert runtime_data_dir(run) is None


def test_a_replay_run_never_inherits_the_provider_key(tmp_path: Path) -> None:
    # WHY: replay is keyless by contract; a key in the UI's environment must not reach a replay
    # child, where the notebook would connect it (and any stray call could spend).
    environ = {"OPENROUTER_API_KEY": "sk-or-v1-secret", "PATH": "/x"}
    _, env = _manager(tmp_path, environ=environ).command(RunRequest("replay", ()), tmp_path)
    assert "OPENROUTER_API_KEY" not in env and env["PATH"] == "/x"
    _, local = _manager(tmp_path, environ=environ).command(
        RunRequest("local", (), confirm_paid=True), tmp_path
    )
    assert local["OPENROUTER_API_KEY"] == "sk-or-v1-secret"


def test_command_keeps_the_inherited_env(tmp_path: Path) -> None:
    _, env = _manager(tmp_path, environ={"PATH": "/x", "HOME": "/h"}).command(
        RunRequest("replay", ()), tmp_path
    )
    assert env["PATH"] == "/x" and env["HOME"] == "/h"


def test_a_replay_run_never_inherits_the_paid_opt_in(tmp_path: Path) -> None:
    # WHY: the UI process's own SCREAMINGFACE_TEST_PAID must not turn a keyless replay launch
    # into one that may spend; only a confirmed `local` request sets it.
    _, env = _manager(tmp_path, environ={"SCREAMINGFACE_TEST_PAID": "1"}).command(
        RunRequest("replay", ()), tmp_path
    )
    assert "SCREAMINGFACE_TEST_PAID" not in env


def test_a_confirmed_local_run_with_a_key_is_paid(tmp_path: Path) -> None:
    _, env = _manager(tmp_path, environ={"OPENROUTER_API_KEY": "k"}).command(
        RunRequest("local", (), confirm_paid=True), tmp_path
    )
    assert env["SCREAMINGFACE_TEST_PAID"] == "1"
    assert env["SCREAMINGFACE_WORKBENCH_TARGET"] == "local"


@pytest.mark.parametrize(
    ("request_", "environ", "reason"),
    [
        (RunRequest("local", (), confirm_paid=False), {"OPENROUTER_API_KEY": "k"}, "spends"),
        (RunRequest("local", (), confirm_paid=True), {}, "OPENROUTER_API_KEY"),
        (RunRequest("local", (), confirm_paid=True), {"OPENROUTER_API_KEY": ""}, "OPENROUTER"),
        (RunRequest("prod", ()), {}, "target"),
        (RunRequest("replay", ("x or y",)), {}, "notebook"),
        (RunRequest("replay", ("Quickstart",)), {}, "notebook"),
        (RunRequest("replay", ("",)), {}, "notebook"),
        (RunRequest("replay", ("quick]start",)), {}, "notebook"),
        (RunRequest("replay", ("a::b",)), {}, "notebook"),
    ],
)
def test_invalid_or_ungated_requests_are_rejected_with_the_reason(
    tmp_path: Path, request_: RunRequest, environ: dict[str, str], reason: str
) -> None:
    calls: list[list[str]] = []
    m = RunManager(tmp_path, workdir=tmp_path, environ=environ, spawn=_script_spawn("", calls))
    with pytest.raises(RunRejected, match=reason):
        m.start(request_)
    assert calls == []


# --- start / follow / get ---------------------------------------------------------------------


def test_output_is_streamed_and_the_exit_code_recorded(tmp_path: Path) -> None:
    m = _manager(tmp_path)
    run = m.start(RunRequest("replay", ()))
    assert list(m.follow(run.id, 0)) == ["a", "b"]
    done = m.get(run.id)
    assert done.returncode == 0 and not done.cancelled


def test_a_run_writes_under_runs_its_id(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="import os; print(os.environ['SCREAMINGFACE_WORKBENCH_OUT'])")
    run = m.start(RunRequest("replay", ()))
    assert run.out_dir == tmp_path / "runs" / run.id
    assert list(m.follow(run.id, 0)) == [str(run.out_dir)]
    assert run.out_dir.is_dir()


def test_follow_resumes_from_an_absolute_line_index(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="print('a'); print('b'); print('c')")
    run = m.start(RunRequest("replay", ()))
    list(m.follow(run.id, 0))
    assert list(m.follow(run.id, 2)) == ["c"]
    assert list(m.follow(run.id, 99)) == []


def test_follow_sees_lines_live_before_the_run_ends(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="import time; print('first', flush=True); time.sleep(30)")
    run = m.start(RunRequest("replay", ()))
    stream = m.follow(run.id, 0)
    assert next(stream) == "first"
    assert m.get(run.id).returncode is None
    m.cancel(run.id)
    # The stream ends with the run; the interrupt's traceback is part of the output.
    assert list(stream)[-1] == "KeyboardInterrupt"


def test_unknown_run_is_a_key_error(tmp_path: Path) -> None:
    m = _manager(tmp_path)
    with pytest.raises(KeyError):
        m.get("nope")
    with pytest.raises(KeyError):
        m.cancel("nope")
    with pytest.raises(KeyError):
        list(m.follow("nope", 0))


def test_run_ids_are_timestamped_and_distinct(tmp_path: Path) -> None:
    m = _manager(tmp_path)
    first = m.start(RunRequest("replay", ()))
    list(m.follow(first.id, 0))
    second = m.start(RunRequest("replay", ()))
    list(m.follow(second.id, 0))
    assert first.id != second.id
    assert time.strftime("%Y%m%d-") in first.id


def test_output_is_capped_and_the_dropped_lines_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs, "LINE_CAP", 5)
    m = _manager(tmp_path, script="for i in range(12): print(i)")
    run = m.start(RunRequest("replay", ()))
    list(m.follow(run.id, 0))
    done = m.get(run.id)
    assert done.lines == ["7", "8", "9", "10", "11"]
    assert done.dropped == 7
    # A reader that fell behind the cap resumes at the oldest line still held.
    assert list(m.follow(run.id, 0)) == ["7", "8", "9", "10", "11"]
    assert list(m.follow(run.id, 10)) == ["10", "11"]


def test_undecodable_output_does_not_stall_the_run(tmp_path: Path) -> None:
    script = "import sys; sys.stdout.buffer.write(b'bad \\xff\\xfe byte\\n'); print('after')"
    argv_spawn = runs._spawn  # the real spawn: it decides the decoding
    m = RunManager(
        tmp_path,
        workdir=tmp_path,
        environ=dict(os.environ),
        spawn=lambda _argv, env, cwd: argv_spawn([sys.executable, "-c", script], env, cwd),
    )
    run = m.start(RunRequest("replay", ()))
    lines = list(m.follow(run.id, 0))
    assert lines[-1] == "after" and lines[0].startswith("bad ")
    assert m.get(run.id).returncode == 0


# --- live progress ---------------------------------------------------------------------------


def _progress_run(stems: tuple[str, ...] = ("quickstart", "judge-panel")) -> Run:
    return Run("r", RunRequest("replay", ()), Path("/o"), stems=stems)


_NODE = "tests/e2e/workbench/test_notebooks.py::test_notebook"


def test_progress_starts_at_collection_and_follows_the_result_lines() -> None:
    run = _progress_run()
    track_progress(run, "platform darwin -- Python 3.13", now=1.0)
    assert run.running is None
    track_progress(run, "collecting ... collected 2 items", now=2.0)
    assert (run.running, run.running_since) == ("quickstart", 2.0)
    track_progress(run, f"{_NODE}[replay-quickstart] PASSED   [ 50%]", now=9.0)
    assert (run.running, run.running_since) == ("judge-panel", 9.0)
    # A teardown ERROR for the same node after its PASSED does not skip a notebook.
    track_progress(run, f"{_NODE}[replay-quickstart] ERROR    [ 50%]", now=9.5)
    assert (run.running, run.running_since) == ("judge-panel", 9.0)
    track_progress(run, f"{_NODE}[replay-judge-panel] FAILED   [100%]", now=20.0)
    assert run.running is None


def test_progress_without_known_stems_says_notebooks() -> None:
    run = _progress_run(stems=())
    track_progress(run, "collected 1 item", now=3.0)
    assert (run.running, run.running_since) == ("notebooks", 3.0)
    track_progress(run, f"{_NODE}[replay-quickstart] PASSED   [100%]", now=5.0)
    assert (run.running, run.running_since) == ("notebooks", 3.0)  # until the run ends


def test_a_run_tracks_progress_live_and_clears_it_at_the_end(tmp_path: Path) -> None:
    script = "import time; print('collected 1 item', flush=True); time.sleep(30)"
    m = RunManager(
        tmp_path,
        workdir=tmp_path,
        environ={},
        spawn=_script_spawn(script),
        notebooks=("quickstart", "judge-panel"),
    )
    run = m.start(RunRequest("replay", ("judge-panel",)))
    assert run.stems == ("judge-panel",)  # the request's own selection wins
    next(m.follow(run.id, 0))
    assert run.running == "judge-panel" and run.running_since is not None
    m.cancel(run.id)
    assert m.get(run.id).running is None
    everything = m.start(RunRequest("replay", ()))
    assert everything.stems == ("quickstart", "judge-panel")
    m.cancel(everything.id)


# --- one at a time ---------------------------------------------------------------------------


def test_a_second_run_while_one_is_active_is_busy(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="import time; time.sleep(30)")
    first = m.start(RunRequest("replay", ()))
    with pytest.raises(RunBusy):
        m.start(RunRequest("replay", ()))
    m.cancel(first.id)
    # Once the first one ended, the slot is free again.
    second = m.start(RunRequest("replay", ()))
    m.cancel(second.id)


def test_a_failed_spawn_frees_the_slot(tmp_path: Path) -> None:
    def broken(_argv: list[str], _env: dict[str, str], _cwd: Path) -> subprocess.Popen[str]:
        raise OSError("no such interpreter")

    m = RunManager(tmp_path, workdir=tmp_path, environ={}, spawn=broken)
    with pytest.raises(OSError):
        m.start(RunRequest("replay", ()))
    with pytest.raises(OSError):  # not RunBusy
        m.start(RunRequest("replay", ()))
    # No empty runs/<id> is left behind for the bundle list to show as a run.
    assert list((tmp_path / "runs").glob("*")) == []


# --- ends and cancels (Review Focus 1, 2) ------------------------------------------------------


def test_a_crashing_run_ends_with_its_exit_code(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="print('x'); raise SystemExit(3)")
    run = m.start(RunRequest("replay", ()))
    assert list(m.follow(run.id, 0)) == ["x"]
    assert m.get(run.id).returncode == 3


def test_a_run_whose_leftover_child_holds_the_pipe_still_ends(tmp_path: Path) -> None:
    # Review Focus 1: pytest exits but a straggler (a kernel, say) keeps stdout open. The run
    # must still end with pytest's exit code, and the straggler is reaped with the group.
    marker = f"straggler-{uuid.uuid4().hex}"
    script = textwrap.dedent(
        f"""
        import subprocess, sys
        subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', '{marker}'])
        print('parent done', flush=True)
        raise SystemExit(1)
        """
    )
    m = _manager(tmp_path, script=script, drain_grace=0.5)
    run = m.start(RunRequest("replay", ()))
    started = time.monotonic()
    assert list(m.follow(run.id, 0)) == ["parent done"]
    assert time.monotonic() - started < 10
    assert m.get(run.id).returncode == 1
    assert _no_process_matches(marker)


def test_cancel_kills_the_process_group(tmp_path: Path) -> None:
    marker = f"grandchild-{uuid.uuid4().hex}"
    script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', '{marker}']); "
        "print('child', flush=True); time.sleep(60)"
    )
    m = _manager(tmp_path, script=script)
    run = m.start(RunRequest("replay", ()))
    next(m.follow(run.id, 0))
    done = m.cancel(run.id)
    assert done.cancelled and done.returncode is not None
    # The grandchild is in the same session, so it is gone too.
    assert _no_process_matches(marker)


def test_cancel_escalates_when_the_interrupt_is_ignored(tmp_path: Path) -> None:
    script = (
        "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); print('stubborn', flush=True); "
        "time.sleep(60)"
    )
    m = _manager(tmp_path, script=script, interrupt_grace=0.3, terminate_grace=0.3)
    run = m.start(RunRequest("replay", ()))
    next(m.follow(run.id, 0))
    started = time.monotonic()
    done = m.cancel(run.id)
    assert time.monotonic() - started < 10
    assert done.cancelled and done.returncode == -9
    assert done.killed  # the run page warns that teardown may not have run


def test_a_cancel_that_ends_on_the_interrupt_is_not_killed(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="import time; print('up', flush=True); time.sleep(30)")
    run = m.start(RunRequest("replay", ()))
    next(m.follow(run.id, 0))
    done = m.cancel(run.id)
    assert done.cancelled and not done.killed


def test_shutdown_cancels_the_active_run_and_waits_for_its_end(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="import time; print('up', flush=True); time.sleep(30)")
    run = m.start(RunRequest("replay", ()))
    next(m.follow(run.id, 0))
    m.shutdown()
    done = m.get(run.id)
    assert done.cancelled and done.returncode is not None and not done.killed
    m.shutdown()  # nothing active: a no-op


def test_kill_active_ends_a_run_that_ignores_signals_at_once(tmp_path: Path) -> None:
    marker = f"stubborn-{uuid.uuid4().hex}"
    script = (
        "import signal, subprocess, sys, time; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', '{marker}']); "
        "print('up', flush=True); time.sleep(60)"
    )
    m = _manager(tmp_path, script=script, interrupt_grace=30.0)
    run = m.start(RunRequest("replay", ()))
    next(m.follow(run.id, 0))
    waiter = threading.Thread(target=m.shutdown)
    waiter.start()  # stuck in the 30 s interrupt grace
    time.sleep(0.5)
    started = time.monotonic()
    m.kill_active()
    waiter.join(10)
    assert not waiter.is_alive() and time.monotonic() - started < 10
    done = m.get(run.id)
    assert done.killed and done.returncode == -9
    assert _no_process_matches(marker)


def test_cancelling_a_finished_run_changes_nothing(tmp_path: Path) -> None:
    m = _manager(tmp_path)
    run = m.start(RunRequest("replay", ()))
    list(m.follow(run.id, 0))
    done = m.cancel(run.id)
    assert done.returncode == 0 and not done.cancelled


def test_cancel_runs_pytest_teardown(tmp_path: Path) -> None:
    # Review Focus 2's premise: the local target's `down` lives in a fixture `finally`. pytest
    # runs that on SIGINT (KeyboardInterrupt) but NOT on SIGTERM (the default action kills it
    # outright) — so cancel must interrupt first. A real pytest child proves it.
    torn_down = tmp_path / "torn_down"
    test_file = tmp_path / "test_slow.py"
    test_file.write_text(
        textwrap.dedent(
            f"""
            import pathlib, time
            import pytest

            @pytest.fixture
            def stack():
                try:
                    yield
                finally:
                    pathlib.Path({str(torn_down)!r}).write_text("down")

            def test_slow(stack):
                print("booted", flush=True)
                time.sleep(60)
            """
        )
    )

    def spawn(_argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
        argv = [sys.executable, "-m", "pytest", "-s", "-q", "-p", "no:cacheprovider"]
        return runs._spawn([*argv, str(test_file)], env, cwd)

    m = RunManager(tmp_path, workdir=tmp_path, environ=dict(os.environ), spawn=spawn)
    run = m.start(RunRequest("replay", ()))
    assert any("booted" in line for line in m.follow(run.id, 0))
    done = m.cancel(run.id)
    assert done.cancelled
    assert torn_down.read_text() == "down"


def test_a_second_cancel_does_not_interrupt_the_teardown(tmp_path: Path) -> None:
    # A double-clicked Cancel (or a retried POST) must not send a second SIGINT: pytest treats
    # it as an abort of fixture teardown, and the local target's `down` would never run.
    torn_down = tmp_path / "torn_down"
    test_file = tmp_path / "test_slow_teardown.py"
    test_file.write_text(
        textwrap.dedent(
            f"""
            import pathlib, time
            import pytest

            @pytest.fixture(scope="session")
            def stack():
                try:
                    yield
                finally:
                    time.sleep(3)
                    pathlib.Path({str(torn_down)!r}).write_text("down")

            def test_slow(stack):
                print("booted", flush=True)
                time.sleep(60)
            """
        )
    )

    def spawn(_argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
        argv = [sys.executable, "-m", "pytest", "-s", "-q", "-p", "no:cacheprovider"]
        return runs._spawn([*argv, str(test_file)], env, cwd)

    m = RunManager(tmp_path, workdir=tmp_path, environ=dict(os.environ), spawn=spawn)
    run = m.start(RunRequest("replay", ()))
    assert any("booted" in line for line in m.follow(run.id, 0))
    results: list[Run] = []
    first = threading.Thread(target=lambda: results.append(m.cancel(run.id)))
    second = threading.Thread(target=lambda: results.append(m.cancel(run.id)))
    first.start()
    time.sleep(1)  # the first cancel's SIGINT is in, the teardown is sleeping
    second.start()
    first.join(60)
    second.join(60)
    assert len(results) == 2 and all(r.cancelled and r.returncode is not None for r in results)
    assert torn_down.read_text() == "down"


_LOCAL_PORTS = (9105, 9106, 9108)


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.mark.e2e
def test_cancelling_a_local_boot_frees_its_ports(tmp_path: Path) -> None:
    # Review Focus 2 against the real stack, keyless: the run is the un-paid local boot check
    # (`screamingface up` + Engine), cancelled once the stack listens. Its teardown must run
    # `down`, which is the only thing that stops the runtime (it detaches into its own session).
    if os.environ.get(E2E_ENV) != "1":
        pytest.skip(f"{E2E_ENV}=1 not set (boots the real local stack)")
    if any(_listening(p) for p in _LOCAL_PORTS):
        pytest.skip(f"a local stack already holds one of {_LOCAL_PORTS}")
    package = Path(__file__).resolve().parents[4]

    def spawn(_argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
        argv = [sys.executable, "-m", "pytest", "-s", "-q", "-p", "no:cacheprovider"]
        return runs._spawn([*argv, "tests/e2e/workbench/test_local_boot.py"], env, cwd)

    m = RunManager(tmp_path, workdir=package, environ=dict(os.environ), spawn=spawn)
    run = m.start(RunRequest("replay", ()))
    deadline = time.monotonic() + 600
    while not all(_listening(p) for p in _LOCAL_PORTS):
        assert m.get(run.id).returncode is None, "\n".join(m.get(run.id).lines[-40:])
        assert time.monotonic() < deadline, "the local stack never came up"
        time.sleep(1)
    done: Run = m.cancel(run.id)
    assert done.cancelled and done.returncode is not None
    stuck = [p for p in _LOCAL_PORTS if _listening(p)]
    assert stuck == [], "\n".join(done.lines[-40:])
