#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""An approved TS test transition must not waive any other append-only check."""

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

_BRANCH = "OME-1322-aigateway-ui-stop-authoring-profile-defaults"
_TEST = "apps/aigateway-ui/src/app/actions.test.ts"
_OLD = 'it("old contract", () => { expect(true).toBe(true); });\n'
_NEW = 'it("new contract", () => { expect(false).toBe(false); });\n'


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
    (path.parent / "other.test.ts").write_text(_OLD)
    git(root, "add", "apps/aigateway-ui/src/app")
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
    manifest = root / ".claude/test-change-approvals/OME-1322.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "issue": "OME-1322",
                "branch": branch,
                "reason": "Owner approved the retired saved-default contract tests",
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
            root / "apps/aigateway-ui", base, ["src/**/*.test.ts"]
        )


class ApprovedTsChangeTests(unittest.TestCase):
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
            path.write_text(_NEW + 'it("another", () => { expect(1).toBe(1); });\n')
            self.assertFalse(check(root, base))

    def test_other_existing_ts_test_remains_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            _, base = setup(root)
            approve(root, base)
            other = root / "apps/aigateway-ui/src/app/other.test.ts"
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
            manifest = root / ".claude/test-change-approvals/OME-1322.json"
            data = json.loads(manifest.read_text())
            data["files"][_TEST]["base_blob"] = "0" * 40
            manifest.write_text(json.dumps(data))
            self.assertFalse(check(root, base))


if __name__ == "__main__":
    unittest.main()
