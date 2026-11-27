"""The Engine CI path scan (`engine_ci_support`) follows a test's imports into repo modules.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).
STORY: as a developer who keeps a repo path in a helper module, a change to that path runs the
Engine suite, however the modules import each other.

INVARIANT: each case builds its modules in a repo of its own, so the real tests stay as they are.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from engine_ci_modules import Modules
from engine_ci_support import ENGINE_PARTS, scan_modules, uses

_SYNTHETIC = (*ENGINE_PARTS, "tests", "unit", "test_synthetic.py")


def _repo_with(tmp_path: Path, modules: dict[str, str]) -> Modules:
    """A repo at ``tmp_path`` whose Engine unit tests hold ``modules``, as the scan reads it."""
    for name, source in modules.items():
        file = tmp_path.joinpath(*ENGINE_PARTS, "tests", "unit", name)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source, encoding="utf-8")
    return scan_modules(tmp_path)


#: A cycle Python runs when `cycle_a` is imported first: `cycle_b` reads `BASE`, bound before.
_CYCLE = {
    "cycle_a.py": (
        "from pathlib import Path\n"
        'BASE = Path(__file__).resolve().parents[4] / "apps" / "aigateway"\n'
        "from cycle_b import FIXTURES\n"
        "OUT = FIXTURES\n"
    ),
    "cycle_b.py": 'import cycle_a\nFIXTURES = cycle_a.BASE / "tests" / "fixtures"\n',
}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            'from cycle_a import OUT\nX = (OUT / "x.json").read_text()\n',
            {"apps/aigateway/tests/fixtures/x.json"},
            id="the-scan-reads-the-re-exporting-module-first",
        ),
        pytest.param(
            "from cycle_a import OUT\nfrom cycle_b import FIXTURES\n"
            'X = (FIXTURES / "x.json").read_text()\nY = (OUT / "y.json").read_text()\n',
            {"apps/aigateway/tests/fixtures/x.json", "apps/aigateway/tests/fixtures/y.json"},
            id="the-scan-reads-the-other-module-first",
        ),
    ],
)
def test_an_import_cycle_keeps_the_path_it_re_exports(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    modules = _repo_with(tmp_path, _CYCLE)

    assert set(uses(source, _SYNTHETIC, modules)) == expected


def test_an_import_cycle_that_binds_a_name_twice_settles(tmp_path: Path) -> None:
    modules = _repo_with(
        tmp_path,
        {
            "cycle_c.py": "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[4]\n"
            'ROOT = ROOT / "apps"\n'
            "from cycle_d import D\n"
            "OUT = D\n",
            "cycle_d.py": 'import cycle_c\nD = cycle_c.ROOT / "aigateway"\n',
        },
    )
    source = 'from cycle_d import D\nX = (D / "uv.lock").read_text()\n'

    # WHY both: a name bound twice in one scope stands for every path bound to it.
    assert set(uses(source, _SYNTHETIC, modules)) == {"aigateway/uv.lock", "apps/aigateway/uv.lock"}


def test_an_import_cycle_that_builds_ever_longer_paths_fails(tmp_path: Path) -> None:
    modules = _repo_with(
        tmp_path,
        {
            "cycle_e.py": "from pathlib import Path\n"
            "E = Path(__file__).resolve().parents[4]\n"
            "from cycle_f import F\n"
            'E = F / "x"\n',
            "cycle_f.py": "from cycle_e import E\nF = E\n",
        },
    )
    source = 'from cycle_e import E\nX = (E / "y").read_text()\n'

    with pytest.raises(RecursionError, match="ever longer paths"):
        uses(source, _SYNTHETIC, modules)


def test_a_module_that_imports_its_own_name_ends_the_lookup(tmp_path: Path) -> None:
    modules = _repo_with(
        tmp_path,
        {
            "helper_root.py": "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[4]\n"
            "from helper_root import ROOT\n"
        },
    )
    source = (
        'from helper_root import ROOT\nX = (ROOT / "apps" / "aigateway" / "uv.lock").read_text()\n'
    )

    assert set(uses(source, _SYNTHETIC, modules)) == {"apps/aigateway/uv.lock"}


def test_a_test_module_named_after_a_standard_module_is_found_first(tmp_path: Path) -> None:
    # WHY: pytest puts the test's directory first on `sys.path`, so it hides the standard one.
    modules = _repo_with(
        tmp_path,
        {
            "statistics.py": "from pathlib import Path\n"
            'BASE = Path(__file__).resolve().parents[4] / "apps" / "aigateway"\n'
        },
    )
    source = 'from statistics import BASE\nX = (BASE / "uv.lock").read_text()\n'

    assert set(uses(source, _SYNTHETIC, modules)) == {"apps/aigateway/uv.lock"}
