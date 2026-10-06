#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Python-test and JSON-fixture approvals stay fail-closed and byte-exact (OME-1468).

FEATURE: blob-pinned owner approvals in the append-only gate.
STORY: as an owner who approved one exact test-contract change, I want the gate to
pass that change and nothing else, so nobody runs `--skip-append-only` for a stack.

Usage: uv run .claude/scripts/tests/test_approved_py_json_change.py
"""

import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "run_gates.py"
_spec = importlib.util.spec_from_file_location("run_gates", _SCRIPT)
assert _spec is not None and _spec.loader is not None
run_gates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_gates)

_BRANCH = "bershadsky/ome-1136-every-rejected-model-call"
_ISSUE = "OME-1136"
_STACK = "apps/aigateway"
_PY = f"{_STACK}/tests/unit/test_errors.py"
_OTHER_PY = f"{_STACK}/tests/unit/test_other.py"
_JSON = f"{_STACK}/tests/public_surface_snapshot.json"
_OUTSIDE_JSON = f"{_STACK}/data/snapshot.json"
_GLOBS = ["tests/**", "data/**"]

_PY_OLD = 'def test_message():\n    assert render() == "upstream provider failed"\n'
# WHY: the edit flips an assertion INSIDE an existing test body — exactly what the AST
# range check rejects, so only an approval can let it through.
_PY_NEW = 'def test_message():\n    assert render() == "model rejected the call"\n'
_JSON_OLD = "{\"ConnectionStatus\": \"Literal['connected', 'disconnected']\"}\n"
_JSON_NEW = (
    "{\"ConnectionStatus\": \"Literal['connected', 'disconnected', 'unavailable']\"}\n"
)


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def setup(root: pathlib.Path) -> str:
    """Commit the old contract on the approved branch; tests write the new one."""
    git(root, "init", "-q")
    git(root, "checkout", "-qb", _BRANCH)
    for rel, content in (
        (_PY, _PY_OLD),
        (_OTHER_PY, _PY_OLD),
        (_JSON, _JSON_OLD),
        (_OUTSIDE_JSON, _JSON_OLD),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", "apps")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "base",
    )
    return git(root, "rev-parse", "HEAD")


def write(root: pathlib.Path, rel: str, content: str) -> None:
    (root / rel).write_text(content)


def approve(
    root: pathlib.Path,
    base: str,
    paths: list[str],
    *,
    branch: str = _BRANCH,
    reason: str | None = "Owner approved the rejected-call message contract",
) -> pathlib.Path:
    """Pin each path at its base blob and its CURRENT on-disk blob."""
    approval: dict = {
        "issue": _ISSUE,
        "branch": branch,
        "files": {
            rel: {
                "base_blob": git(root, "rev-parse", f"{base}:{rel}"),
                "approved_blob": git(root, "hash-object", rel),
            }
            for rel in paths
        },
    }
    if reason is not None:
        approval["reason"] = reason
    manifest = root / f".claude/test-change-approvals/{_ISSUE}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(approval))
    return manifest


def check(root: pathlib.Path, base: str) -> tuple[bool, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ok = run_gates.append_only_check(root / _STACK, base, _GLOBS)
    return ok, out.getvalue()


class ApprovedPythonChangeTests(unittest.TestCase):
    def test_an_approved_python_edit_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            self.assertFalse(check(root, base)[0])  # the edit IS a range violation
            approve(root, base, [_PY])
            ok, out = check(root, base)
            self.assertTrue(ok, out)
            self.assertIn(
                f"approved {_ISSUE} test transition: tests/unit/test_errors.py", out
            )

    def test_one_more_byte_changed_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            approve(root, base, [_PY])
            write(root, _PY, _PY_NEW + " ")
            ok, out = check(root, base)
            self.assertFalse(ok)
            self.assertIn("tests/unit/test_errors.py", out)

    def test_a_wrong_branch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            approve(root, base, [_PY], branch="bershadsky/ome-9999-another-branch")
            self.assertFalse(check(root, base)[0])

    def test_a_missing_reason_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            approve(root, base, [_PY], reason=None)
            self.assertFalse(check(root, base)[0])

    def test_a_blank_reason_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            approve(root, base, [_PY], reason="   ")
            self.assertFalse(check(root, base)[0])

    def test_an_unapproved_second_file_in_the_same_diff_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            approve(root, base, [_PY])
            write(root, _OTHER_PY, _PY_NEW)
            ok, out = check(root, base)
            self.assertFalse(ok)
            self.assertIn("tests/unit/test_other.py", out)
            self.assertNotIn("M\ttests/unit/test_errors.py", out)

    def test_an_entry_missing_its_base_blob_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            manifest = approve(root, base, [_PY])
            data = json.loads(manifest.read_text())
            del data["files"][_PY]["base_blob"]
            manifest.write_text(json.dumps(data))
            self.assertFalse(check(root, base)[0])

    def test_an_approval_named_for_another_issue_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _PY, _PY_NEW)
            manifest = approve(root, base, [_PY])
            # INVARIANT: the file name and the `issue` field must agree.
            manifest.rename(manifest.with_name("OME-1.json"))
            self.assertFalse(check(root, base)[0])


class ApprovedJsonFixtureTests(unittest.TestCase):
    def test_an_approved_json_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _JSON, _JSON_NEW)
            self.assertFalse(check(root, base)[0])
            approve(root, base, [_JSON])
            ok, out = check(root, base)
            self.assertTrue(ok, out)

    def test_one_more_byte_in_the_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _JSON, _JSON_NEW)
            approve(root, base, [_JSON])
            write(root, _JSON, _JSON_NEW + "\n")
            self.assertFalse(check(root, base)[0])

    def test_a_fixture_on_a_wrong_branch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _JSON, _JSON_NEW)
            approve(root, base, [_JSON], branch="bershadsky/ome-9999-another-branch")
            self.assertFalse(check(root, base)[0])

    def test_a_fixture_with_a_missing_reason_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _JSON, _JSON_NEW)
            approve(root, base, [_JSON], reason=None)
            self.assertFalse(check(root, base)[0])

    def test_an_unapproved_second_fixture_change_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _JSON, _JSON_NEW)
            approve(root, base, [_JSON])
            write(root, _PY, _PY_NEW)
            ok, out = check(root, base)
            self.assertFalse(ok)
            self.assertIn("tests/unit/test_errors.py", out)

    def test_json_outside_tests_is_never_approvable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, _OUTSIDE_JSON, _JSON_NEW)
            approve(root, base, [_OUTSIDE_JSON])
            # WHY: the ticket scopes JSON approvals to fixtures under tests/ — no wider.
            self.assertFalse(check(root, base)[0])


def rebase_baseline(root: pathlib.Path, rel: str, content: str) -> str:
    """Commit a different baseline for `rel` after approval; keep the approved bytes."""
    approved = (root / rel).read_bytes()
    write(root, rel, content)
    git(root, "add", rel)
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "baseline moved",
    )
    (root / rel).write_bytes(approved)
    return git(root, "rev-parse", "HEAD")


class ChangedBaselineTests(unittest.TestCase):
    # INVARIANT: the approval pins the transition, not just the result — the same
    # approved bytes over a baseline the owner never saw must fail (review of #1232:
    # dropping the base_blob comparison survived every other test).
    def _assert_moved_baseline_fails(self, rel: str, new: str, moved: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            write(root, rel, new)
            approve(root, base, [rel])
            self.assertTrue(check(root, base)[0])  # control: valid at its own base
            moved_base = rebase_baseline(root, rel, moved)
            ok, out = check(root, moved_base)
            self.assertFalse(ok)
            self.assertIn(rel.removeprefix(f"{_STACK}/"), out)

    def test_a_python_approval_over_a_changed_baseline_fails(self) -> None:
        moved = 'def test_message():\n    assert render() == "provider call failed"\n'
        self._assert_moved_baseline_fails(_PY, _PY_NEW, moved)

    def test_a_json_approval_over_a_changed_baseline_fails(self) -> None:
        moved = '{"ConnectionStatus": "Literal[\'connected\']"}\n'
        self._assert_moved_baseline_fails(_JSON, _JSON_NEW, moved)


if __name__ == "__main__":
    unittest.main()
