"""The Engine CI path scan (`engine_ci_support`) finds each way a test names a repo path.

FEATURE: Engine CI path filters (`.github/workflows/screamingface-engine-tests.yml`).
STORY: as a Gateway, SDK or scoreboard developer, a change to a file an Engine test uses runs the
Engine suite, however the test spells the path.

INVARIANT: these are the scan's own cases. The guard that applies the scan to the Engine suite is
`test_engine_ci_path_filters.py`.
"""

from __future__ import annotations

import pytest
from engine_ci_support import ENGINE_PARTS, ROOT, glob, uses

_SYNTHETIC = (*ENGINE_PARTS, "tests", "unit", "test_synthetic.py")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            'X = "apps/aigateway/src/aigateway/config.py"\n',
            {"apps/aigateway/src/aigateway/config.py"},
            id="a-repo-relative-literal",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'RELAY = R / "apps/aigateway/tests/fixtures/provider_error_relay"\n'
            'X = (RELAY / "relayed_detail.json").read_text()\n'
            'Y = (R / "apps" / "aigateway" / "src" / "aigateway" / "config.py").read_text()\n',
            {
                "apps/aigateway/tests/fixtures/provider_error_relay/relayed_detail.json",
                "apps/aigateway/src/aigateway/config.py",
            },
            id="literals-joined-to-the-repo-root",
        ),
        pytest.param(
            'SDK = Path(__file__).resolve().parents[3].parent / "packages" / "screamingface"\n'
            'skip = not SDK.exists()\nX = (SDK / "pyproject.toml").read_text()\n',
            {"packages/screamingface", "packages/screamingface/pyproject.toml"},
            id="a-bound-name-joined-later-and-an-existence-check",
        ),
        pytest.param(
            'SDK = Path(__file__).resolve().parents[4] / "packages" / "screamingface"\n'
            'def f(name):\n    return SDK / "src" / name\n',
            {"packages/screamingface/src"},
            id="a-run-time-suffix-reports-the-directory",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'X = [p.read_text() for p in R.glob("apps/*/src/aigateway/config.py")]\n'
            'Y = list((R / "apps" / "aigateway" / "src").rglob("config.py"))\n',
            {"apps/aigateway/src/aigateway/config.py"},
            id="a-glob-reads-the-files-it-matches",
        ),
        pytest.param(
            '"""Reads apps/aigateway/src/aigateway/config.py."""\n'
            'X = sorted((Path(__file__).resolve().parents[2] / "deploy" / "helm").iterdir())\n'
            'Y = "deploy/helm"\n',
            set(),
            id="engine-local-paths-and-docstrings-are-not-reads",
        ),
        pytest.param(
            "root = next(p for p in Path(__file__).resolve().parents\n"
            '            if (p / ".claude/scripts/check_layering.py").is_file())\n',
            {".claude/scripts/check_layering.py"},
            id="a-root-marker-tested-for-existence-is-a-dependency",
        ),
        pytest.param(
            'R = next(p for p in Path(__file__).resolve().parents if (p / "CLAUDE.md").is_file())\n'
            'X = (R / "apps" / "aigateway" / "src" / "aigateway" / "config.py").read_text()\n',
            {"CLAUDE.md", "apps/aigateway/src/aigateway/config.py"},
            id="a-root-found-by-its-marker",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'X = R.joinpath("apps/aigateway/src", "aigateway", "config.py").read_text()\n',
            {"apps/aigateway/src/aigateway/config.py"},
            id="literal-segments-joined-with-joinpath",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            "def f(name):\n    return (R / name).read_text(), R.joinpath(name).is_file()\n",
            {ROOT},
            id="the-repo-root-joined-with-a-run-time-name",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            "def f(path):\n    return path.relative_to(R)\n",
            set(),
            id="a-path-made-relative-to-the-root-is-not-a-read",
        ),
        pytest.param(
            "repo_root = Path(__file__).resolve().parents[4]\n"
            "ROOT = repo_root\n"
            "def f():\n"
            '    ROOT = repo_root / "packages/screamingface"\n'
            '    return (ROOT / "pyproject.toml").read_text()\n'
            'X = (ROOT / "apps/aigateway/src/aigateway/main.py").read_text()\n',
            {"packages/screamingface/pyproject.toml", "apps/aigateway/src/aigateway/main.py"},
            id="a-name-bound-in-a-function-leaves-the-module-name-alone",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'P = R / "packages/screamingface"\n'
            "if flag:\n"
            '    P = R / "apps/aigateway"\n'
            'X = (P / "pyproject.toml").read_text()\n',
            {"packages/screamingface/pyproject.toml", "apps/aigateway/pyproject.toml"},
            id="a-name-bound-twice-in-one-scope-stands-for-both-paths",
        ),
        pytest.param(
            "def f():\n"
            '    src = SDK / "src"\n'
            '    return (src / "screamingface" / "__init__.py").read_text()\n'
            'SDK = Path(__file__).resolve().parents[4] / "packages" / "screamingface"\n',
            {"packages/screamingface/src/screamingface/__init__.py"},
            id="a-function-body-sees-a-module-name-bound-below-it",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            "class T:\n"
            '    SDK = R / "packages/screamingface/pyproject.toml"\n'
            "    def test(self):\n"
            "        return self.SDK.read_text()\n",
            {"packages/screamingface/pyproject.toml"},
            id="a-path-bound-in-a-class-body-is-read",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'OPTIONAL = R / "apps/aigateway/tests/fixtures/new_contract"\n'
            "skip = not OPTIONAL.exists()\n",
            {"apps/aigateway/tests/fixtures/new_contract"},
            id="a-repo-path-that-does-not-exist-yet",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'SDK = R / "packages/screamingface"\n'
            "class T:\n"
            '    SDK = R / "apps/aigateway"\n'
            "    def test(self):\n"
            '        return (SDK / "pyproject.toml").read_text()\n',
            {"packages/screamingface/pyproject.toml", "apps/aigateway"},
            id="a-method-does-not-see-its-class-body-names",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            'SDK = R / "packages/screamingface"\n'
            "def f(SDK):\n"
            '    return (SDK / "uv.lock").read_text()\n'
            'X = (SDK / "pyproject.toml").read_text()\n',
            {"packages/screamingface/pyproject.toml"},
            id="a-parameter-is-not-the-module-name",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            "def setup():\n"
            "    global SDK\n"
            '    SDK = R / "packages/screamingface"\n'
            'X = (SDK / "pyproject.toml").read_text()\n',
            {"packages/screamingface/pyproject.toml"},
            id="a-global-statement-binds-the-module-name",
        ),
        pytest.param(
            "R = Path(__file__).resolve().parents[4]\n"
            "def outer():\n"
            '    sdk = R / "apps/aigateway"\n'
            "    def inner():\n"
            "        nonlocal sdk\n"
            '        sdk = R / "packages/screamingface"\n'
            '    return (sdk / "uv.lock").read_text()\n',
            {"apps/aigateway/uv.lock", "packages/screamingface/uv.lock"},
            id="a-nonlocal-statement-binds-the-enclosing-name",
        ),
        pytest.param(
            'X = {"content-type": "application/json", "path": "apps/aigateway/absent.json"}\n',
            set(),
            id="a-literal-that-names-no-repo-path-is-not-one",
        ),
        pytest.param(
            'SDK = Path(__file__).resolve().parents[4] / "packages/screamingface"\n'
            'X = [SDK.read_text() for SDK in [SDK / "pyproject.toml"]]\n',
            {"packages/screamingface/pyproject.toml"},
            id="a-comprehension-iterable-sees-the-enclosing-name",
        ),
        pytest.param(
            'OPTIONAL = Path("apps/aigateway/tests/fixtures/new_contract")\n'
            "skip = not OPTIONAL.exists()\n",
            {"apps/aigateway/tests/fixtures/new_contract"},
            id="a-literal-path-that-does-not-exist-yet",
        ),
        pytest.param(
            'X = Path("screamingface_engine/runner/executor.py")\n'
            'Y = (Path("/assets") / "x.json").read_text()\n'
            'Z = Path("professional")\n'
            'W = Path("/apps/aigateway/uv.lock").read_text()\n'
            'V = Path("docs/new_page.md").exists()\n',
            set(),
            id="a-literal-path-that-names-no-repo-path",
        ),
        pytest.param(
            "from engine_ci_support import REPO\n"
            'X = (REPO / "apps" / "aigateway" / "src" / "aigateway" / "main.py").read_text()\n'
            'Y = REPO / "apps/aigateway/tests/fixtures/new_contract"\n'
            "skip = not Y.exists()\n",
            {"apps/aigateway/src/aigateway/main.py", "apps/aigateway/tests/fixtures/new_contract"},
            id="a-name-imported-from-a-repo-module",
        ),
        pytest.param(
            "import engine_ci_support as support\n"
            'X = (support.REPO / "apps" / "aigateway" / "uv.lock").read_text()\n'
            'Y = Path(support.__file__).parents[4] / "packages" / "screamingface" / "uv.lock"\n'
            "Z = Y.read_text()\n",
            {"apps/aigateway/uv.lock", "packages/screamingface/uv.lock"},
            id="a-repo-module-imported-whole",
        ),
        pytest.param(
            "ROOT = Path(__file__).resolve().parents[2]\n"
            "def f():\n"
            "    from engine_ci_support import REPO as ROOT\n"
            '    return (ROOT / "apps" / "aigateway" / "uv.lock").read_text()\n'
            'X = (ROOT / "pyproject.toml").read_text()\n',
            {"apps/aigateway/uv.lock"},
            id="a-local-import-is-a-binding-of-its-own",
        ),
        pytest.param(
            "import sys\n"
            'X = (Path(sys.executable).parent / "python3").exists()\n'
            'Y = (Path.home() / ".cache").exists()\n',
            set(),
            id="a-name-from-the-standard-library-is-not-a-repo-path",
        ),
        pytest.param(
            "from engine_ci_absent_helper import REPO\n"
            'X = (REPO / "apps/aigateway/src/aigateway/main.py").read_text()\n'
            "from inspect_evals.cyberseceval_4 import threat_intelligence\n"
            'Y = (Path(threat_intelligence.__file__).parent / "data.json").read_text()\n',
            {
                "<import engine_ci_absent_helper>/apps/aigateway/src/aigateway/main.py",
                "<import inspect_evals>/data.json",
            },
            id="a-path-built-on-a-name-from-outside-the-repo-is-reported",
        ),
        pytest.param(
            "from inspect_evals.cyberseceval_4 import threat_intelligence\n"
            'DATA = Path(threat_intelligence.__file__).parent / "data"\n'
            'X = [p.read_text() for p in DATA.glob("*.json")]\n',
            {"<import inspect_evals>/data"},
            id="a-glob-under-a-module-outside-the-repo-reports-the-module",
        ),
        pytest.param(
            "import url4.observe\nX = Path(url4.observe.__file__).read_text()\n",
            {"packages/url4/src/url4/observe.py"},
            id="a-dotted-import-binds-its-top-package",
        ),
        pytest.param(
            "import url4._log_attributes as attributes\n"
            "X = Path(attributes.__file__).read_text()\n",
            {"packages/url4/src/url4/_log_attributes.py"},
            id="a-dotted-import-as-binds-the-module-itself",
        ),
        pytest.param(
            "from url4 import observe\nX = Path(observe.__file__).read_text()\n",
            {"packages/url4/src/url4/observe.py"},
            id="a-module-imported-from-its-package",
        ),
        pytest.param(
            "from .engine_ci_support import REPO\n"
            'Y = REPO / "apps/aigateway/tests/fixtures/new_contract"\n'
            "skip = not Y.exists()\n",
            {"apps/aigateway/tests/fixtures/new_contract"},
            id="a-relative-import",
        ),
        pytest.param(
            "def outer():\n"
            "    ROOT = Path(__file__).resolve().parents[2]\n"
            "    def inner():\n"
            "        nonlocal ROOT\n"
            "        from engine_ci_support import REPO as ROOT\n"
            "    inner()\n"
            '    return (ROOT / "apps" / "aigateway" / "uv.lock").read_text()\n',
            {"apps/aigateway/uv.lock"},
            id="an-import-under-nonlocal-binds-the-enclosing-name",
        ),
        pytest.param(
            "def setup():\n"
            "    global ROOT\n"
            "    from engine_ci_support import REPO as ROOT\n"
            'X = (ROOT / "apps" / "aigateway" / "uv.lock").read_text()\n',
            {"apps/aigateway/uv.lock"},
            id="an-import-under-global-binds-the-module-name",
        ),
        pytest.param(
            'X = Path("../aigateway/pyproject.toml").read_text()\n'
            'Y = open("../aigateway/uv.lock").read()\n',
            {"apps/aigateway/pyproject.toml", "apps/aigateway/uv.lock"},
            id="a-parent-relative-literal-leaves-the-engine",
        ),
        pytest.param(
            "E = Path(__file__).resolve().parents[2]\n"
            'X = (E / ".." / "aigateway" / "future.toml").exists()\n'
            'Y = [p.read_text() for p in E.glob("../aigateway/pyproject.tom?")]\n'
            'Z = (Path(__file__).resolve().parents[4] / ".." / "outside.txt").read_text()\n'
            'W = Path("../../../outside.txt").read_text()\n',
            {"apps/aigateway/future.toml", "apps/aigateway/pyproject.toml"},
            id="a-parent-segment-in-a-join-or-a-glob",
        ),
        pytest.param(
            "from inspect_evals.cyberseceval_4 import threat_intelligence\n"
            'X = (Path(threat_intelligence.__file__).parent / ".." / "up.json").read_text()\n',
            {"<import inspect_evals>/up.json"},
            id="a-parent-segment-keeps-a-module-outside-the-repo",
        ),
    ],
)
def test_the_scan_finds_each_way_a_test_names_a_path(source: str, expected: set[str]) -> None:
    assert set(uses(source, _SYNTHETIC)) == expected


def test_the_arguments_of_path_are_not_reads_of_their_own() -> None:
    source = (
        'SDK = Path(__file__).resolve().parents[4] / "packages" / "screamingface"\n'
        "skip = not Path(SDK).exists()\n"
        'OPTIONAL = Path("apps/aigateway/uv.lock")\n'
        "ready = OPTIONAL.is_file()\n"
    )

    found = uses(source, _SYNTHETIC)

    assert {path: use.exists_only for path, use in found.items()} == {
        "packages/screamingface": True,
        "apps/aigateway/uv.lock": True,
    }


def test_the_scan_tells_an_existence_check_from_a_read() -> None:
    source = (
        'SDK = Path(__file__).resolve().parents[4] / "packages" / "screamingface"\n'
        "skip = not SDK.exists()\n"
        'X = (SDK / "pyproject.toml").read_text()\n'
        'Y = (SDK / "pyproject.toml").exists()\n'
        'Z = (SDK / "uv.lock").is_file()\n'
        'def f(name):\n    return (SDK / "src" / name).is_file()\n'
    )

    found = uses(source, _SYNTHETIC)

    assert {path: use.exists_only for path, use in found.items()} == {
        "packages/screamingface": True,
        "packages/screamingface/pyproject.toml": False,
        "packages/screamingface/uv.lock": True,
        "packages/screamingface/src": False,
    }


@pytest.mark.parametrize(
    ("pattern", "path", "matched"),
    [
        # WHY these: the examples of GitHub's filter pattern cheat sheet.
        ("docs/**/*.md", "docs/README.md", True),
        ("docs/**/*.md", "docs/a/markdown/file.md", True),
        ("**/README.md", "README.md", True),
        ("**/README.md", "js/README.md", True),
        ("**/*src/**", "my-src/code/js/app.js", True),
        ("**.js", "src/js/app.js", True),
        ("*.js", "src/app.js", False),
        ("docs/*", "docs/mona/octocat.txt", False),
        ("docs/**", "docs/mona/octocat.txt", True),
        ("*.jsx?", "page.js", True),
        ("*.jsx?", "page.jsx", True),
        ("*.jsx?", "page.jsxx", False),
        ("[CB]at", "Cat", True),
        ("[CB]at", "Hat", False),
        ("a+.md", "aaa.md", True),
        ("apps/*/deploy/**/*.sh", "apps/example/deploy/run.sh", True),
    ],
)
def test_a_filter_pattern_matches_as_github_documents_it(
    pattern: str, path: str, matched: bool
) -> None:
    assert bool(glob(pattern).fullmatch(path)) is matched
