"""The REQUIRE_ALL guard (e2e workbench spec §3.4): a skipped workbench notebook fails the run.

The guard is the real ``workbench.conftest`` hook, mounted in a pytester lane directory. A
sibling directory without it stands for every other e2e test in the same pytest run.
"""

from __future__ import annotations

import pytest

from workbench.conftest import REQUIRE_ALL_ENV

pytest_plugins = ["pytester"]

# importlib: both lanes hold a test_notebooks.py, as the real tree may.
_ARGS = ("-p", "no:cacheprovider", "--import-mode=importlib")
_HOOK = "from workbench.conftest import pytest_runtest_makereport  # noqa: F401\n"
_SKIP = "import pytest\n\ndef test_notebook():\n    pytest.skip('no target')\n"


@pytest.fixture
def lanes(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makepyfile(
        **{
            # The workbench lane: the real hook, scoped to this directory like the real conftest.
            "lane/conftest.py": _HOOK,
            "lane/test_notebooks.py": _SKIP,
            # Same directory, not a notebook test: the guard must leave it alone.
            "lane/test_build_notebooks.py": (
                "import pytest\n\ndef test_notebook_builder():\n    pytest.skip('unrelated')\n"
            ),
            # Another e2e lane in the same run, even with a lookalike name: untouched.
            "other/test_notebooks.py": _SKIP,
        }
    )
    return pytester


def test_require_all_turns_a_skipped_notebook_into_a_failure(
    lanes: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REQUIRE_ALL_ENV, "1")
    result = lanes.runpytest(*_ARGS, "-rfs")
    result.assert_outcomes(failed=1, skipped=2)
    result.stdout.fnmatch_lines(
        [
            f"{REQUIRE_ALL_ENV}=1 and the workbench skipped * no target",
            "FAILED lane/test_notebooks.py::test_notebook*",
        ]
    )


def test_without_require_all_a_skipped_notebook_stays_skipped(
    lanes: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REQUIRE_ALL_ENV, raising=False)
    lanes.runpytest(*_ARGS).assert_outcomes(skipped=3)
