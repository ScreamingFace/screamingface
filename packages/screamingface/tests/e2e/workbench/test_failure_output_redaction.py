"""Review finding 1: a secret in a failing notebook must not reach ANY pytest sink.

A pytester lane runs the real verdict (``workbench.verdict.judge_notebook``) on a real notebook
that prints secrets and raises an error quoting them, under the real lane conftest hook. The
terminal output, the JUnit XML and the evidence bundle are then searched for every secret.

WHY ``-l`` and ``--tb=long``: show-locals would print ``run.error`` raw from any traceback
frame; the verdict must not leave a traceback carrying it.
"""

from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

from workbench.redaction import MASK

pytest_plugins = ["pytester"]

_ARGS = ("-p", "no:cacheprovider", "--import-mode=importlib", "-l", "--tb=long", "-rA")
_HOOK = "from workbench.conftest import pytest_runtest_makereport  # noqa: F401\n"

# Fake, assembled at runtime (secret scanners); each is a different redaction shape.
OPAQUE = "op4que-V4lue-zz9"
GHP = "ghp_" + "a1B2" * 9
AIZA = "AIza" + "Sy" + "Q7x_" * 9
QUERY_KEY = "qk3y-0paque-77"
QUERY_TOKEN = "qt0k-0paque-88"
SECRETS = (OPAQUE, GHP, AIZA, QUERY_KEY, QUERY_TOKEN)
LEAK = (
    f"OPENROUTER_API_KEY={OPAQUE} {GHP} {AIZA} "
    f"https://h.test/v1?api_key={QUERY_KEY}&token={QUERY_TOKEN}"
)


def _notebook(path: Path) -> Path:
    params = nbformat.v4.new_code_cell("LEAK = ''\nENGINE_URL = ''\nSCOREBOARD_URL = ''")
    params.metadata["tags"] = ["parameters"]
    boom = nbformat.v4.new_code_cell("print(LEAK)\nraise RuntimeError('upstream said ' + LEAK)")
    nb = nbformat.v4.new_notebook(cells=[params, boom])
    nb.metadata["workbench"] = {"targets": ["replay"], "required_result": ["trace_ids"]}
    nbformat.write(nb, path)
    return path


def _lane_test(notebook: Path, out: Path) -> str:
    return f"""
from pathlib import Path

from workbench.targets import LiveTarget
from workbench.verdict import judge_notebook

LEAK = {LEAK!r}


def test_notebook(record_property):
    target = LiveTarget(
        name="replay",
        engine_url="http://127.0.0.1:9",
        scoreboard_url="http://127.0.0.1:9",
        sources=(),
        required_hops=(),
        params={{"LEAK": LEAK}},
    )
    judge_notebook(Path({str(notebook)!r}), target, Path({str(out)!r}), record_property)


def test_plain_failure_in_the_lane(record_property):
    record_property("echo", LEAK)
    print(LEAK)
    raise RuntimeError("raw " + LEAK)
"""


def _assert_clean(text: str, where: str) -> None:
    # WHY a count, not the values: this assertion's own failure must not print them.
    leaked = sum(s in text for s in SECRETS)
    if leaked:
        pytest.fail(f"{leaked} secret(s) leaked into {where}", pytrace=False)


def test_a_secret_bearing_notebook_failure_leaks_into_no_pytest_sink(
    pytester: pytest.Pytester,
) -> None:
    notebook = _notebook(pytester.path / "leaky.ipynb")
    out = pytester.path / "evidence"
    junit = pytester.path / "junit.xml"
    pytester.makepyfile(
        **{
            "lane/conftest.py": _HOOK,
            "lane/test_notebooks.py": _lane_test(notebook, out),
        }
    )

    result = pytester.runpytest(*_ARGS, f"--junitxml={junit}")

    result.assert_outcomes(failed=2)
    stdout = result.stdout.str() + result.stderr.str()
    xml = junit.read_text()
    _assert_clean(stdout, "terminal output")
    _assert_clean(xml, "JUnit XML")
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        _assert_clean(path.read_text(), f"bundle file {path.name}")
    # The failure itself is still reported — masked, not dropped.
    assert "notebook failed: RuntimeError: upstream said OPENROUTER_API_KEY=" + MASK in xml
    assert MASK in stdout
