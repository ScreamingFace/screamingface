#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Permanent temp-repo matrix for run_gates.py's append-only check (OME-369).

Replaces the round-1 manual scratch-repo verification with a runnable suite, per
PR #383 review feedback. Each test builds a throwaway git repo, commits a "base"
state, mutates it, then calls the check functions directly against that repo.

Usage: uv run .claude/scripts/tests/test_run_gates.py
"""
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

_SCRIPT_PATH = pathlib.Path(__file__).resolve().parent.parent / "run_gates.py"
_spec = importlib.util.spec_from_file_location("run_gates", _SCRIPT_PATH)
run_gates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_gates)


def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc


def _init_repo(root: pathlib.Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    # INVARIANT: repo-local only — never touches the real user's global git config.
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")


def _commit_all(root: pathlib.Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class AppendOnlyCheckTests(unittest.TestCase):
    def _check(self, root: pathlib.Path, base: str, globs: list[str] | None = None) -> bool:
        import io
        import contextlib

        with contextlib.redirect_stdout(io.StringIO()):
            return run_gates.append_only_check(root, base, globs or ["test_*.py"])

    def test_pure_addition_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 1\n\n\ndef test_two():\n    assert 2 == 2\n",
            )
            self.assertTrue(self._check(root, base))

    def test_real_rewrite_inside_existing_test_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 2\n")
            self.assertFalse(self._check(root, base))

    def test_new_import_insertion_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "import os\n\n\ndef test_one():\n    assert 1 == 1\n",
            )
            self.assertTrue(self._check(root, base))

    def test_existing_import_line_changed_no_test_touched_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "import os\n\n\ndef test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "import os, sys\n\n\ndef test_one():\n    assert 1 == 1\n",
            )
            self.assertTrue(self._check(root, base))

    def test_whole_test_file_delete_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            (root / "test_a.py").unlink()
            self.assertFalse(self._check(root, base))

    def test_nested_stack_root_detects_rewrite(self):
        """Regression test for the review-flagged bug: a stack root below the repo
        root (e.g. apps/scoreboard) must still detect a rewrite inside an existing
        test body — `git show` needs the `./` cwd-relative prefix to find the file."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            _init_repo(repo_root)
            stack_root = repo_root / "apps" / "scoreboard"
            _write(stack_root / "tests" / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(repo_root, "base")
            _write(stack_root / "tests" / "test_a.py", "def test_one():\n    assert 1 == 2\n")
            self.assertFalse(self._check(stack_root, base, ["tests/*.py"]))

    def test_decorator_edit_detected(self):
        """Regression test: editing a decorator above an existing test (e.g. its
        parametrize list) must count as touching that test's body, even though
        ast.FunctionDef.lineno points at `def`, not the decorator line."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                'import pytest\n\n\n@pytest.mark.parametrize("x", [1])\ndef test_param(x):\n    assert x == 1\n',
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                'import pytest\n\n\n@pytest.mark.parametrize("x", [2])\ndef test_param(x):\n    assert x == 1\n',
            )
            self.assertFalse(self._check(root, base))

    def test_dash_prefixed_content_detected(self):
        """Regression test: a removed line whose content starts at column 0 with
        `--` (diff form `----`) must not false-match the file-header skip."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", 'def test_sep():\n    doc = """\n---\nsection\n"""\n    assert doc\n')
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                'def test_sep():\n    doc = """\nCHANGED\nsection\n"""\n    assert doc\n',
            )
            self.assertFalse(self._check(root, base))

    def test_insertion_neuters_existing_test_fails(self):
        """Regression test (review concern): a pure insertion — zero removed lines
        — can still neuter a prior test's real check (e.g. forcing a variable's
        value right before the assertion). `removed`-only detection is blind to
        this; `inserted_after` must catch it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                "def compute():\n    return 41\n\n\ndef test_foo():\n    result = compute()\n"
                "    assert result == 42\n",
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def compute():\n    return 41\n\n\ndef test_foo():\n    result = compute()\n"
                "    result = 42  # neuters the assertion, nothing removed\n"
                "    assert result == 42\n",
            )
            self.assertFalse(self._check(root, base))

    def test_fixture_edit_detected(self):
        """Regression test (review concern): a `@pytest.fixture` (not `test_*`-named)
        that an existing test depends on must be protected too — editing it changes
        what the dependent test actually exercises."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                'import pytest\n\n\n@pytest.fixture\ndef db():\n    return {"ready": True}\n\n\n'
                'def test_uses_fixture(db):\n    assert db["ready"]\n',
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                'import pytest\n\n\n@pytest.fixture\ndef db():\n    return {"ready": False}\n\n\n'
                'def test_uses_fixture(db):\n    assert db["ready"]\n',
            )
            self.assertFalse(self._check(root, base))

    def test_append_new_function_immediately_after_existing_passes(self):
        """Boundary case: a whole new test typed directly after an existing one,
        ZERO blank lines between them, must stay unflagged — its insertion anchors
        at exactly the old function's last line (`n == hi`), which must be excluded
        or this reopens OME-369's original false positive."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 1\ndef test_two():\n    assert 2 == 2\n",
            )
            self.assertTrue(self._check(root, base))

    def test_insert_new_function_immediately_before_existing_passes(self):
        """Symmetric boundary case: a whole new test typed directly before an
        existing one, zero blank lines, must also stay unflagged."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_two():\n    assert 2 == 2\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 1\ndef test_two():\n    assert 2 == 2\n",
            )
            self.assertTrue(self._check(root, base))

    def test_module_level_test_data_edit_detected(self):
        """Regression test (review concern): shared module-level test data (e.g.
        `_BASE_KW = {...}`, the real pattern in
        apps/aigateway/tests/unit/test_request_cache_keys.py) is invisible to a
        function-only pass — a `-` line there must still be caught."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                '_BASE_KW = {\n    "x": 1,\n}\n\n\ndef test_uses_base_kw():\n    assert _BASE_KW["x"] == 1\n',
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                '_BASE_KW = {\n    "x": 999,\n}\n\n\ndef test_uses_base_kw():\n    assert _BASE_KW["x"] == 1\n',
            )
            self.assertFalse(self._check(root, base))

    def test_existing_import_line_changed_still_passes_with_data_protection(self):
        """Regression guard: protecting module-level data must not reverse round 1's
        explicit decision that editing an existing import line is legitimate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                'import os\n\n_BASE_KW = {\n    "x": 1,\n}\n\n\ndef test_one():\n    assert _BASE_KW["x"] == 1\n',
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                'import os, sys\n\n_BASE_KW = {\n    "x": 1,\n}\n\n\ndef test_one():\n    assert _BASE_KW["x"] == 1\n',
            )
            self.assertTrue(self._check(root, base))

    def test_new_module_level_constant_addition_passes(self):
        """Pure addition of a brand new module-level constant must stay legitimate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                '_NEW_CONST = 5\n\n\ndef test_one():\n    assert 1 == 1\n',
            )
            self.assertTrue(self._check(root, base))

    def test_append_new_constant_immediately_after_existing_passes(self):
        """Boundary case at module-data scope, mirroring the function-scope one:
        a new constant typed directly after an existing one, zero blank lines,
        must stay unflagged."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "_A = 1\ndef test_one():\n    assert _A == 1\n")
            base = _commit_all(root, "base")
            _write(root / "test_a.py", "_A = 1\n_B = 2\ndef test_one():\n    assert _A == 1\n")
            self.assertTrue(self._check(root, base))

    def test_module_docstring_edit_passes(self):
        """Regression test (code-review finding): a bare module docstring is an
        ast.Expr, not Assign/AnnAssign — editing it must stay legitimate, with
        zero test logic touched."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", '"""Old docstring."""\n\n\ndef test_one():\n    assert 1 == 1\n')
            base = _commit_all(root, "base")
            _write(root / "test_a.py", '"""New docstring."""\n\n\ndef test_one():\n    assert 1 == 1\n')
            self.assertTrue(self._check(root, base))

    def test_if_main_block_edit_passes(self):
        """Regression test (code-review finding): the near-universal
        `if __name__ == "__main__":` runner block is an ast.If, not
        Assign/AnnAssign — editing it (e.g. switching runners) must stay
        legitimate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                'def test_one():\n    assert 1 == 1\n\n\nif __name__ == "__main__":\n    pass\n',
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                'def test_one():\n    assert 1 == 1\n\n\nif __name__ == "__main__":\n'
                "    import unittest\n\n    unittest.main()\n",
            )
            self.assertTrue(self._check(root, base))

    def test_import_nested_in_conditional_edit_passes(self):
        """Regression test (code-review finding): an import nested inside a
        module-level version-guard (if/else) must stay legitimate to edit — the
        whole `if` block is an ast.If, not Assign/AnnAssign, so it isn't swept
        into a protected range that would incorrectly cover the nested import."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                "import sys\n\nif sys.version_info >= (3, 10):\n    from typing import ParamSpec\n"
                "else:\n    from typing_extensions import ParamSpec\n\n\n"
                "def test_one():\n    assert ParamSpec\n",
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "import sys\n\nif sys.version_info >= (3, 10):\n    from typing import ParamSpec\n"
                "else:\n    from typing_extensions import ParamSpec as ParamSpec\n\n\n"
                "def test_one():\n    assert ParamSpec\n",
            )
            self.assertTrue(self._check(root, base))

    def test_replace_blank_separator_line_passes(self):
        """Regression test (code-review finding): replacing the blank separator
        line between two functions with a comment must stay legitimate — the
        replacement's insertion anchor must not be mis-computed as landing on
        the START of the second function's protected range."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 1\n\ndef test_two():\n    assert 2 == 2\n",
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 1\n# note\ndef test_two():\n    assert 2 == 2\n",
            )
            self.assertTrue(self._check(root, base))

    def test_module_level_augassign_edit_detected(self):
        """Regression test (code-review finding): a module-level accumulator
        statement (e.g. `_CASES += [...]`) is an ast.AugAssign, not covered by
        Assign/AnnAssign alone — editing it must still be caught."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                "_CASES = [1, 2, 3]\n_CASES += [4, 5]\n\n\ndef test_uses_cases():\n    assert len(_CASES) == 5\n",
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "_CASES = [1, 2, 3]\n_CASES += [4, 5, 999]\n\n\ndef test_uses_cases():\n    assert len(_CASES) == 5\n",
            )
            self.assertFalse(self._check(root, base))

    def test_append_after_file_without_trailing_newline_passes(self):
        """Regression test (code-review finding): appending new content after a
        protected range's last line, when that file didn't end in a newline at
        base, must stay legitimate — git represents the unchanged last line as
        a remove+add pair purely because its EOF status changed, not its text."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            with open(root / "test_a.py", "w", newline="\n") as f:
                f.write("def test_one():\n    assert 1 == 1")  # no trailing newline
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 1\n\n\ndef test_two():\n    assert 2 == 2\n",
            )
            self.assertTrue(self._check(root, base))

    def test_losing_trailing_newline_with_no_other_change_passes(self):
        """Regression test (code-review finding, mirror image of the previous
        test): a protected range's last line LOSING its trailing newline, with
        zero other change, must also stay legitimate — the SequenceMatcher
        rewrite handles this by construction (splitlines() ignores trailing-
        newline presence on either side), unlike the old text-parsing approach
        which only recognized the "gained a newline" direction."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            with open(root / "test_a.py", "w", newline="\n") as f:
                f.write("def test_one():\n    assert 1 == 1")  # lost trailing newline
            self.assertTrue(self._check(root, base))

    def test_real_edit_adjacent_to_eof_artifact_still_detected(self):
        """Coverage guard: a real rewrite of one protected assertion, sharing a
        hunk with an unrelated EOF-newline-only change to an adjacent protected
        line, must still be caught. SequenceMatcher's LCS-based opcodes handle
        multi-line hunks correctly by construction (each line is matched by
        content, not by naive "first added line after last removed line"
        position-pairing) — this guards that property, not any specific old
        bug (a clean discriminating repro for the old pairing bug turns out to
        require the shadowing technique, which is a separate, already-deferred
        limitation, not something this fix does or should close)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            with open(root / "test_a.py", "w", newline="\n") as f:
                f.write(
                    "def test_one():\n    assert 1 == 1\ndef test_two():\n    assert 2 == 2"
                )  # no trailing newline
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 999\ndef test_two():\n    assert 2 == 2\n",
            )
            self.assertFalse(self._check(root, base))

    def test_binary_content_flags_without_crashing(self):
        """Regression test (code-review finding): a test file rewritten with
        undecodable binary content must produce a verdict (flagged, since the
        protected lines differ), not crash the gate with UnicodeDecodeError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            (root / "test_a.py").write_bytes(b"def test_one():\n\x00\xff\xfe binary junk")
            self.assertFalse(self._check(root, base))

    def test_verbatim_test_swap_is_flagged(self):
        """Behavior pin (deliberate, conservative): swapping two tests' order
        verbatim — zero text changes, pure relocation — IS flagged. Reordering
        previously-committed tests is a structural change to prior tests, and
        rule 5 says a prior-test change is a Confidence-Gate decision (STOP and
        ask), so the conservative outcome is intended, not a false positive to
        fix. This test pins that choice so a future change flipping it is a
        conscious decision, not an accident."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                "def test_one():\n    assert 1 == 1\n\n\ndef test_two():\n    assert 2 == 2\n",
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_two():\n    assert 2 == 2\n\n\ndef test_one():\n    assert 1 == 1\n",
            )
            self.assertFalse(self._check(root, base))

    def test_rewrite_after_exotic_linebreak_chars_detected(self):
        """Regression test (code-review finding, false-NEGATIVE direction): a
        string containing \\f or \\u2028 earlier in the file must not desync
        diff line numbering from ast's. str.splitlines() splits on those
        characters (+2 lines here) while Python's tokenizer does not, so the
        old str-based comparison shifted every later position out of its
        protected range — a rewrite of a later test went silently undetected.
        bytes.splitlines() splits only on \\r/\\n, matching the tokenizer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                'def test_one():\n    s = "a\fb c"\n    assert s\n\n\n'
                "def test_two():\n    assert 2 == 2\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(root / "test_a.py", base_src.replace("assert 2 == 2", "assert 2 == 999"))
            self.assertFalse(self._check(root, base))

    def test_bom_file_rewrite_detected(self):
        """Regression test (code-review finding, false-negative direction): a
        UTF-8 BOM at base must not strip protection. CPython's tokenizer skips
        a BOM when reading source BYTES, but ast.parse of a STR starting with
        U+FEFF raises SyntaxError — without stripping it, a BOM'd (valid,
        runnable) test file fell into the permissive branch and lost ALL
        protection."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            (root / "test_a.py").write_bytes(
                b"\xef\xbb\xbfdef test_one():\n    assert 1 == 1\n"
            )
            base = _commit_all(root, "base")
            (root / "test_a.py").write_bytes(
                b"\xef\xbb\xbfdef test_one():\n    assert 1 == 2\n"
            )
            self.assertFalse(self._check(root, base))

    def test_typechange_to_symlink_flagged(self):
        """Regression test (code-review finding, false-negative direction):
        replacing a committed test file with a symlink is git status T
        (typechange), not M/D — it must be flagged like a delete, not silently
        skipped as 'not in MDR'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert 1 == 1\n")
            _write(root / "junk.txt", "not a test\n")
            base = _commit_all(root, "base")
            (root / "test_a.py").unlink()
            (root / "test_a.py").symlink_to("junk.txt")
            self.assertFalse(self._check(root, base))

    def test_non_ascii_filename_rewrite_detected(self):
        """Regression test (code-review finding, false-negative direction): with
        git's default core.quotepath, a non-ASCII filename is emitted as an
        octal-escaped quoted C-string that matches no glob — rewrites (and
        deletions) of such files were silently skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_ä.py", "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(root / "test_ä.py", "def test_one():\n    assert 1 == 2\n")
            self.assertFalse(self._check(root, base))

    def test_git_quoted_filename_rewrite_detected(self):
        """NUL-delimited git output must preserve path characters that trigger
        C-style quoting or collide with line/tab-delimited status parsing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            path = root / 'test_\t\n\\"case.py'
            _write(path, "def test_one():\n    assert 1 == 1\n")
            base = _commit_all(root, "base")
            _write(path, "def test_one():\n    assert 1 == 2\n")
            self.assertFalse(self._check(root, base))

    def test_indented_append_extending_final_test_body_detected(self):
        """Regression test (code-review finding, false-negative direction): an
        INDENTED line appended directly after the file's final test extends
        that test's body — e.g. appending `break` inside its loop flips a
        failing test green with zero old lines touched. An insertion anchored
        at a range's end whose first non-blank line is indented deeper than the
        range's own definition column is a violation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                "CASES = [1, 2, 3]\n\n\ndef test_all_cases():\n"
                "    for c in CASES:\n        assert c < 3\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(root / "test_a.py", base_src + "        break\n")
            self.assertFalse(self._check(root, base))

    def test_new_method_after_existing_method_in_class_passes(self):
        """Boundary guard for the indented-append rule: a new test METHOD typed
        directly after an existing method inside a class shares the anchor
        `n == hi` and IS indented — but at the same column as the existing
        method's `def`, not deeper, so it must stay legitimate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                "class TestThings:\n    def test_one(self):\n        assert 1 == 1\n",
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "class TestThings:\n    def test_one(self):\n        assert 1 == 1\n\n"
                "    def test_two(self):\n        assert 2 == 2\n",
            )
            self.assertTrue(self._check(root, base))

    def test_existing_typescript_assertion_rewrite_fails_closed(self):
        """A configured non-Python test file must not lose all protection merely
        because Python's AST cannot parse it. Until a language-aware range parser
        exists, modifications to an existing unsupported test artifact fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "src" / "nested" / "auth.test.ts",
                'test("auth", () => {\n  expect(authorize()).toBe(false);\n});\n',
            )
            base = _commit_all(root, "base")
            _write(
                root / "src" / "nested" / "auth.test.ts",
                'test("auth", () => {\n  expect(true).toBe(true);\n});\n',
            )
            self.assertFalse(self._check(root, base, ["src/**/*.test.ts"]))

    def test_replacing_separator_with_indented_code_fails(self):
        """The added side of a SequenceMatcher replace matters: replacing the
        old blank immediately after a loop test with `break` extends that test."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                "CASES = [1, 2, 3]\n\n\ndef test_all_cases():\n"
                "    for case in CASES:\n        assert case < 3\n\n\n"
                "def test_other():\n    assert True\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                base_src.replace(
                    "        assert case < 3\n\n",
                    "        assert case < 3\n        break\n",
                    1,
                ),
            )
            self.assertFalse(self._check(root, base))

    def test_comment_before_indented_append_does_not_hide_code(self):
        """Comments do not emit Python indentation tokens. A column-zero comment
        before an indented `break` must not make the body extension look dedented."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                "CASES = [1, 2, 3]\n\n\ndef test_all_cases():\n"
                "    for case in CASES:\n        assert case < 3\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                base_src + "# explanation\n        break\n",
            )
            self.assertFalse(self._check(root, base))

    def test_existing_test_class_decorator_edit_fails(self):
        """Existing test-class metadata is prior test behavior too. This is not
        OME-475's deferred case of stacking a new outer function decorator."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                "import pytest\n\n"
                '@pytest.mark.skipif(False, reason="enabled")\n'
                "class TestThings:\n"
                "    def test_one(self):\n        assert False\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                base_src.replace("skipif(False", "skipif(True"),
            )
            self.assertFalse(self._check(root, base))

    def test_module_level_assert_edit_fails(self):
        """A direct module assertion executes during collection and is test logic,
        not documentation or an exempt runner block."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "test_a.py",
                "def behavior():\n    return False\n\nassert behavior()\n",
            )
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def behavior():\n    return False\n\nassert True\n",
            )
            self.assertFalse(self._check(root, base))

    def test_direct_child_typescript_test_matches_recursive_glob(self):
        """`**/` includes zero directories in stack-card intent; direct children
        must not escape merely because fnmatch treats the slash literally."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(
                root / "src" / "auth.test.ts",
                'test("auth", () => expect(authorize()).toBe(false));\n',
            )
            base = _commit_all(root, "base")
            _write(
                root / "src" / "auth.test.ts",
                'test("auth", () => expect(true).toBe(true));\n',
            )
            self.assertFalse(self._check(root, base, ["src/**/*.test.ts"]))

    def test_first_method_added_to_existing_class_passes(self):
        """Protect class metadata without treating its header endpoint like a
        function body endpoint: the first new method is a legitimate addition."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "class TestThings:\n    pass\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "class TestThings:\n    def test_one(self):\n        assert True\n    pass\n",
            )
            self.assertTrue(self._check(root, base))

    def test_invalid_current_source_fails_closed_on_deep_added_code(self):
        """If tokenization fails, a leading comment must not hide deeper added
        code at a protected endpoint. Invalid current source should fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                "CASES = [1, 2, 3]\n\n\ndef test_all_cases():\n"
                "    for case in CASES:\n        assert case < 3\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                base_src + "# explanation\n        break\n(\n",
            )
            self.assertFalse(self._check(root, base))

    def test_each_recursive_glob_segment_can_match_zero_directories(self):
        """Multiple `**/` segments vary independently; removing only a prefix
        chain leaves valid direct-child combinations unmatched."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            path = root / "x" / "foo" / "bar.test.ts"
            _write(path, 'test("x", () => expect(false).toBe(true));\n')
            base = _commit_all(root, "base")
            _write(path, 'test("x", () => expect(true).toBe(true));\n')
            self.assertFalse(
                self._check(root, base, ["**/foo/**/bar.test.ts"])
            )

    def test_invalid_source_form_feed_indentation_fails_closed(self):
        """Python accepts form feed in leading indentation. The invalid-source
        fallback must not treat a deeply indented line as column zero."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                "CASES = [1, 2, 3]\n\n\ndef test_all_cases():\n"
                "    for case in CASES:\n        assert case < 3\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                base_src + "# explanation\n\f        break\n(\n",
            )
            self.assertFalse(self._check(root, base))

    def test_form_feed_prefixed_sibling_function_passes(self):
        """At the start of indentation, form feed resets Python's indentation
        column; it must not make a module-level sibling look nested."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _write(root / "test_a.py", "def test_one():\n    assert True\n")
            base = _commit_all(root, "base")
            _write(
                root / "test_a.py",
                "def test_one():\n    assert True\n\fdef test_two():\n    assert True\n",
            )
            self.assertTrue(self._check(root, base))

    def test_current_tab_error_fails_closed(self):
        """Tokenization alone does not validate indentation. A current file that
        ast.parse rejects with TabError must not pass append-only checking."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = (
                "class TestThings:\n    def test_all(self):\n"
                "        for case in [1, 2, 3]:\n            assert case < 3\n"
            )
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(root / "test_a.py", base_src + "\t\tbreak\n")
            self.assertFalse(self._check(root, base))

    def test_current_compile_time_syntax_error_fails_closed(self):
        """AST construction accepts some contextually invalid statements, so
        current Python source must pass full compilation before it can pass."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            base_src = "def test_one():\n    assert True\n"
            _write(root / "test_a.py", base_src)
            base = _commit_all(root, "base")
            _write(root / "test_a.py", base_src + "break\n")
            self.assertFalse(self._check(root, base))

    def test_globstar_inside_component_is_not_recursive(self):
        """Only a standalone `**` path component has zero-directory semantics;
        textual `**/` inside a larger component must retain fnmatch behavior."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            path = root / "src" / "testauth.test.ts"
            _write(path, 'test("x", () => expect(false).toBe(true));\n')
            base = _commit_all(root, "base")
            _write(path, 'test("x", () => expect(true).toBe(true));\n')
            self.assertTrue(
                self._check(root, base, ["src/test**/auth.test.ts"])
            )

    def test_non_globstar_wildcard_does_not_cross_directories(self):
        """Wildcards within a component must not consume path separators."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            path = root / "src" / "test" / "deep" / "auth.test.ts"
            _write(path, 'test("x", () => expect(false).toBe(true));\n')
            base = _commit_all(root, "base")
            _write(path, 'test("x", () => expect(true).toBe(true));\n')
            self.assertTrue(
                self._check(root, base, ["src/test**/auth.test.ts"])
            )


class JavaScriptApprovalTests(unittest.TestCase):
    _check = AppendOnlyCheckTests._check

    def test_javascript_requires_exact_branch_and_blob_approval(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _init_repo(root)
            _git(root, "checkout", "-b", "OME-1309-external-history")
            path = "apps/scoreboard/tests/portal/contract.test.js"
            _write(root / path, 'assert.equal(label, "Original result");\n')
            base = _commit_all(root, "base")
            _write(root / path, 'assert.equal(label, "Source");\n')
            self.assertFalse(self._check(root, base, ["apps/scoreboard/tests/**"]))
            approval = {
                "issue": "OME-1309", "branch": "OME-1309-external-history",
                "reason": "Owner-approved label change",
                "files": {path: {
                    "base_blob": _git(root, "rev-parse", f"{base}:{path}").stdout.strip(),
                    "approved_blob": _git(root, "hash-object", path).stdout.strip(),
                }},
            }
            manifest = root / ".claude/test-change-approvals/OME-1309.json"
            _write(manifest, json.dumps(approval))
            self.assertTrue(self._check(root, base, ["apps/scoreboard/tests/**"]))
            _write(root / path, 'assert.equal(label, "Anything");\n')
            self.assertFalse(self._check(root, base, ["apps/scoreboard/tests/**"]))
            _write(root / path, 'assert.equal(label, "Source");\n')
            _git(root, "checkout", "-b", "another-branch")
            self.assertFalse(self._check(root, base, ["apps/scoreboard/tests/**"]))


if __name__ == "__main__":
    unittest.main()
