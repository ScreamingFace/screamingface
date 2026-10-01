#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for .githooks/pre-push — which stacks it gates, and against which base.

Think of the hook as a customs desk: before a push leaves the machine it asks "what did
this branch change?" and inspects only the stacks it touched. The question is answered by
diffing the branch against a base. Each test below builds a throwaway "remote" repo, clones
it, makes a branch, and runs the REAL hook with a stub `uv` on PATH. The stub records each
`uv run .claude/scripts/run_gates.py <stack> --base <ref>` call instead of running gates, so a
test reads exactly which stacks the hook would have gated and with which base.

Worked example of the bug this pins (seen 2026-10-01): the remote is named `upstream`, so
`origin/main` does not exist and the old hook fell back to the LOCAL `main`, which lagged
`upstream/main` by commits touching the engine. A docs-only branch then "changed" the engine,
and the push ran the engine's full test suite. Expected gated stacks: [] — the old hook gave
["screamingface-engine"].

The fixed hook picks the base by history, not by name: among every `<remote>/main`, the one
the branch has the fewest commits on top of is the main it was cut from.

Usage: python3 .claude/scripts/tests/test_pre_push.py
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_HOOK = _REPO_ROOT / ".githooks" / "pre-push"

# The stub records one line per gate call: "<stack> <base>". It always succeeds, so the
# hook's own exit code reflects only its base resolution, never a gate result.
_STUB_UV = """#!/bin/sh
# argv: $1=run $2=.claude/scripts/run_gates.py $3=<stack> $4=--base $5=<ref>
echo "$3 $5" >> "$GATE_LOG"
exit 0
"""

_ENGINE_FILE = "apps/screamingface-engine/README.md"


def _git(cwd: pathlib.Path, *args: str) -> str:
    """Run git in `cwd` with a fixed identity and return its stdout."""

    env: dict[str, str] = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return result.stdout


def _commit_file(repo: pathlib.Path, rel_path: str, text: str) -> None:
    """Write one file and commit it, so the change shows up in a branch diff."""

    path: pathlib.Path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _git(repo, "add", rel_path)
    _git(repo, "commit", "-q", "-m", f"change {rel_path}")


class _Sandbox:
    """A throwaway remote, a clone of it, and a stub `uv` that logs gate calls."""

    def __init__(self, remote_name: str) -> None:
        """Create the remote with one commit, then clone it under `remote_name`."""

        self.root: pathlib.Path = pathlib.Path(
            tempfile.mkdtemp(prefix="pre-push-test-")
        )
        self.remote: pathlib.Path = self.root / "remote"
        self.remote.mkdir()
        _git(self.remote, "init", "-q", "-b", "main")
        _commit_file(self.remote, "README.md", "start\n")
        self.clone: pathlib.Path = self.root / "clone"
        _git(
            self.root,
            "clone",
            "-q",
            "-o",
            remote_name,
            str(self.remote),
            str(self.clone),
        )
        bin_dir: pathlib.Path = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "uv").write_text(_STUB_UV)
        (bin_dir / "uv").chmod(0o755)
        self.bin_dir: pathlib.Path = bin_dir
        self.gate_log: pathlib.Path = self.root / "gates.log"

    def add_frozen_remote(self, name: str) -> None:
        """Add a second remote frozen at the remote's current state; it never sees later commits."""

        frozen: pathlib.Path = self.root / f"frozen-{name}"
        _git(self.root, "clone", "-q", "--bare", str(self.remote), str(frozen))
        _git(self.clone, "remote", "add", name, str(frozen))
        _git(self.clone, "fetch", "-q", name)

    def remote_moves_on(self, rel_path: str) -> None:
        """Land a commit on the remote's main and fetch it, leaving the clone's local main behind."""

        _commit_file(self.remote, rel_path, "remote change\n")
        _git(self.clone, "fetch", "-q", "--all")

    def run_hook(self) -> tuple[int, str, list[str]]:
        """Run the real pre-push hook in the clone; return (exit code, stderr, gate log lines)."""

        env: dict[str, str] = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GATE_LOG": str(self.gate_log),
        }
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sh", str(_HOOK)], cwd=self.clone, env=env, capture_output=True, text=True
        )
        gated: list[str] = (
            self.gate_log.read_text().splitlines() if self.gate_log.exists() else []
        )
        return result.returncode, result.stdout + result.stderr, gated

    def cleanup(self) -> None:
        """Delete the sandbox."""

        shutil.rmtree(self.root, ignore_errors=True)


def _docs_only_branch_on_fresh_remote_main(remote_name: str) -> _Sandbox:
    """The bug's setup: local main lags the remote by an engine commit; the branch only edits docs."""

    box: _Sandbox = _Sandbox(remote_name)
    box.remote_moves_on(_ENGINE_FILE)
    _git(box.clone, "checkout", "-q", "-b", "docs-only", f"{remote_name}/main")
    _commit_file(box.clone, "docs/note.md", "docs\n")
    return box


def test_docs_only_branch_with_upstream_remote_gates_no_stack() -> None:
    """A lagging local main must not make the remote's engine commit look like this branch's change."""

    box: _Sandbox = _docs_only_branch_on_fresh_remote_main("upstream")
    try:
        code, output, gated = box.run_hook()
        assert code == 0, output
        assert gated == [], gated
    finally:
        box.cleanup()


def test_docs_only_branch_with_origin_remote_gates_no_stack() -> None:
    """The same push from a clone whose remote is the default `origin` gates nothing either."""

    box: _Sandbox = _docs_only_branch_on_fresh_remote_main("origin")
    try:
        code, output, gated = box.run_hook()
        assert code == 0, output
        assert gated == [], gated
    finally:
        box.cleanup()


def test_docs_only_branch_with_any_remote_name_gates_no_stack() -> None:
    """The base is found by history, not by name: a remote called `sc-remote` works too."""

    box: _Sandbox = _docs_only_branch_on_fresh_remote_main("sc-remote")
    try:
        code, output, gated = box.run_hook()
        assert code == 0, output
        assert gated == [], gated
    finally:
        box.cleanup()


def test_a_stale_second_remote_never_wins_by_its_name() -> None:
    """With two remotes, the main the branch was cut from wins, even when the stale one is `upstream`.

    Example: `origin/main` has the engine commit and the branch is cut from it, so the branch
    is 1 commit ahead of `origin/main` but 2 ahead of the frozen `upstream/main`. Comparing
    against `upstream/main` would count the engine commit as this branch's change.
    """

    box: _Sandbox = _Sandbox("origin")
    try:
        box.add_frozen_remote("upstream")
        box.remote_moves_on(_ENGINE_FILE)
        _git(box.clone, "checkout", "-q", "-b", "docs-only", "origin/main")
        _commit_file(box.clone, "docs/note.md", "docs\n")
        code, output, gated = box.run_hook()
        assert code == 0, output
        assert gated == [], gated
    finally:
        box.cleanup()


def test_engine_change_gates_exactly_the_engine_against_the_remote_main() -> None:
    """A branch that really edits the engine still gets the engine's gates, based on the remote's main."""

    box: _Sandbox = _Sandbox("upstream")
    try:
        _git(box.clone, "checkout", "-q", "-b", "engine-change", "upstream/main")
        _commit_file(box.clone, _ENGINE_FILE, "branch change\n")
        code, output, gated = box.run_hook()
        assert code == 0, output
        assert gated == ["screamingface-engine upstream/main"], gated
    finally:
        box.cleanup()


def test_no_remote_main_stops_the_push_and_gates_nothing() -> None:
    """With no remote main to compare against, the hook refuses rather than guess from a local branch."""

    box: _Sandbox = _Sandbox("upstream")
    try:
        _git(box.clone, "remote", "remove", "upstream")
        _git(box.clone, "checkout", "-q", "-b", "orphaned")
        _commit_file(box.clone, "docs/note.md", "docs\n")
        code, output, gated = box.run_hook()
        assert code == 1, output
        assert "git fetch" in output, output
        assert gated == [], gated
    finally:
        box.cleanup()


def main() -> int:
    """Run every test_ function in this file and report failures; exit non-zero on any."""

    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures: int = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as error:
            failures += 1
            print(f"FAIL {test.__name__}: {error}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
