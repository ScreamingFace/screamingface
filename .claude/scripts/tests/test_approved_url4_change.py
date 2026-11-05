#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""url4 fixtures under tests/ get the same fail-closed, byte-exact approvals as JSON (OME-1653).

FEATURE: blob-pinned owner approvals in the append-only gate.
STORY: as an owner who approved one exact change of compiled url4 fixtures (a new judge
template, a new field-pick operator), I want the gate to pass those bytes and nothing
else, so nobody runs `--skip-append-only` for a stack.

Usage: uv run .claude/scripts/tests/test_approved_url4_change.py
"""

import importlib.util
import pathlib
import sys
import tempfile
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
_spec = importlib.util.spec_from_file_location(
    "test_approved_py_json_change", _HERE / "test_approved_py_json_change.py"
)
assert _spec is not None and _spec.loader is not None
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)

_URL4 = f"{shared._STACK}/tests/unit/data/judge_candidate.url4"
_OUTSIDE_URL4 = f"{shared._STACK}/data/judge_candidate.url4"
_URL4_OLD = "url4://candidate?judge=judge-template%401+returns%3Dscores\n"
_URL4_NEW = "url4://candidate?judge=judge-template%402+returns%3Dscores\n"


def setup(root: pathlib.Path) -> str:
    """The shared baseline plus one url4 fixture under tests/ and one outside it."""
    for rel in (_URL4, _OUTSIDE_URL4):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_URL4_OLD)
    return shared.setup(root)


class ApprovedUrl4FixtureTests(unittest.TestCase):
    def test_an_approved_url4_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            shared.write(root, _URL4, _URL4_NEW)
            self.assertFalse(shared.check(root, base)[0])
            shared.approve(root, base, [_URL4])
            ok, out = shared.check(root, base)
            self.assertTrue(ok, out)

    def test_one_more_byte_in_the_url4_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            shared.write(root, _URL4, _URL4_NEW)
            shared.approve(root, base, [_URL4])
            shared.write(root, _URL4, _URL4_NEW + "\n")
            self.assertFalse(shared.check(root, base)[0])

    def test_a_url4_on_a_wrong_branch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            shared.write(root, _URL4, _URL4_NEW)
            shared.approve(
                root, base, [_URL4], branch="bershadsky/ome-9999-another-branch"
            )
            self.assertFalse(shared.check(root, base)[0])

    def test_a_url4_with_a_missing_reason_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            shared.write(root, _URL4, _URL4_NEW)
            shared.approve(root, base, [_URL4], reason=None)
            self.assertFalse(shared.check(root, base)[0])

    def test_url4_outside_tests_is_never_approvable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            shared.write(root, _OUTSIDE_URL4, _URL4_NEW)
            shared.approve(root, base, [_OUTSIDE_URL4])
            # WHY: like JSON, a url4 approval is scoped to fixtures under tests/.
            self.assertFalse(shared.check(root, base)[0])

    def test_a_url4_approval_over_a_changed_baseline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = setup(root)
            shared.write(root, _URL4, _URL4_NEW)
            shared.approve(root, base, [_URL4])
            self.assertTrue(shared.check(root, base)[0])
            moved = shared.rebase_baseline(
                root, _URL4, "url4://candidate?judge=other\n"
            )
            self.assertFalse(shared.check(root, moved)[0])


if __name__ == "__main__":
    unittest.main()
