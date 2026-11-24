#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""An approved CJS test transition must not waive any other append-only check."""

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

_BRANCH = "OME-1974-colab-analytics-status"
_TEST = "packages/screamingface/tests/browser/other-bridge.test.cjs"
_OLD = "test('old contract', () => { assert.ok(true); });\n"
_NEW = "test('new contract', () => { assert.ok(false); });\n"


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def setup(root: pathlib.Path) -> tuple[pathlib.Path, str]:
    git(root, "init", "-q")
    git(root, "checkout", "-qb", _BRANCH)
    path = root / _TEST
    path.parent.mkdir(parents=True)
    path.write_text(_OLD)
    (path.parent / "other.test.cjs").write_text(_OLD)
    git(root, "add", "packages/screamingface/tests/browser")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "base",
    )
    base = git(root, "rev-parse", "HEAD")
    path.write_text(_NEW)
    return path, base


def approve(root: pathlib.Path, base: str, *, branch: str = _BRANCH) -> None:
    manifest = root / ".claude/test-change-approvals/OME-1974.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "issue": "OME-1974",
                "branch": branch,
                "reason": "Owner approved a corrected module pointer in the bridge test",
                "files": {
                    _TEST: {
                        "base_blob": git(root, "rev-parse", f"{base}:{_TEST}"),
                        "approved_blob": git(root, "hash-object", _TEST),
                    }
                },
            }
        )
    )


def check(root: pathlib.Path, base: str) -> bool:
    with contextlib.redirect_stdout(io.StringIO()):
        return run_gates.append_only_check(
            root / "packages/screamingface", base, ["tests/**/*.cjs"]
        )


class ApprovedCjsChangeTests(unittest.TestCase):
    def test_exact_owner_approved_change_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            _, base = setup(root)
            self.assertFalse(check(root, base))
            approve(root, base)
            self.assertTrue(check(root, base))

    def test_an_extra_edit_is_not_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            path, base = setup(root)
            approve(root, base)
            path.write_text(_NEW + "test('another', () => { assert.ok(true); });\n")
            self.assertFalse(check(root, base))

    def test_other_existing_cjs_test_remains_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            _, base = setup(root)
            approve(root, base)
            other = root / "packages/screamingface/tests/browser/other.test.cjs"
            other.write_text(_NEW)
            self.assertFalse(check(root, base))

    def test_wrong_branch_cannot_use_an_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            _, base = setup(root)
            approve(root, base, branch="OME-9999-another-branch")
            self.assertFalse(check(root, base))

    def test_wrong_base_blob_cannot_use_an_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            _, base = setup(root)
            approve(root, base)
            manifest = root / ".claude/test-change-approvals/OME-1974.json"
            data = json.loads(manifest.read_text())
            data["files"][_TEST]["base_blob"] = "0" * 40
            manifest.write_text(json.dumps(data))
            self.assertFalse(check(root, base))

    def test_cjs_outside_tests_is_never_approvable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            git(root, "init", "-q")
            git(root, "checkout", "-qb", _BRANCH)
            served = root / "packages/screamingface/bridge.cjs"
            served.parent.mkdir(parents=True)
            served.write_text(_OLD)
            git(root, "add", "packages/screamingface/bridge.cjs")
            git(
                root,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-qm",
                "base",
            )
            base = git(root, "rev-parse", "HEAD")
            served.write_text(_NEW)
            manifest = root / ".claude/test-change-approvals/OME-1974.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "issue": "OME-1974",
                        "branch": _BRANCH,
                        "reason": "should never match: not under tests/",
                        "files": {
                            "packages/screamingface/bridge.cjs": {
                                "base_blob": git(
                                    root,
                                    "rev-parse",
                                    f"{base}:packages/screamingface/bridge.cjs",
                                ),
                                "approved_blob": git(root, "hash-object", str(served)),
                            }
                        },
                    }
                )
            )
            with contextlib.redirect_stdout(io.StringIO()):
                passed = run_gates.append_only_check(
                    root / "packages/screamingface", base, ["bridge.cjs"]
                )
            self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
