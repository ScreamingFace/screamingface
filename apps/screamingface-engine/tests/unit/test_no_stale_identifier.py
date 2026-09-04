"""No source or test module still spells the old package name, and the deliberate survivors do
(OME-876).

FEATURE: the rename is complete inside the app, and the handful of `url4-cloud` strings that were
kept are kept ON PURPOSE rather than missed.

STORY: as the next agent touching this app I can tell a leftover from a decision, because the
decisions are asserted here and everything else is forbidden.

WHY the two halves are asserted differently:

- The Python identifier `screamingface_engine` has NO legitimate survivor. Absence is
  the whole contract, so it is asserted as absence.
- The hyphenated `url4-cloud` has several deliberate survivors (a NATS wire prefix,
  Kubernetes pod
  labels, the chart's `nameOverride` pin, the legacy console scripts). Asserting its absence would
  need a brittle line-level allowlist that goes stale on every edit. Instead the survivors are
  asserted POSITIVELY: if someone "finishes the rename" by removing one, this fails and points at
  `OME-877`, which is where that work belongs.

AIDEV-NOTE: this module is excluded from its own scan — it necessarily contains the string it
forbids. Nothing else may be added to that exclusion.
"""

from __future__ import annotations

from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
_SRC = _APP_ROOT / "src"
_TESTS = _APP_ROOT / "tests"

_OLD_IDENTIFIER = "url4" + "_cloud"  # split so this literal is not itself a match
_SELF = Path(__file__).resolve()

_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "data"}
_TEXT_SUFFIXES = {".py", ".toml", ".yaml", ".yml", ".tpl", ".json", ".md", ".txt"}


def _scanned_files() -> list[Path]:
    found: list[Path] = []
    for root in (_SRC, _TESTS):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.resolve() == _SELF:
                continue
            found.append(path)
    return found


def test_the_scan_actually_reaches_the_source_tree() -> None:
    """Guard against a permanently green gate.

    INVARIANT: a scan that matches nothing passes vacuously. If the layout moves and this stops
    finding files, that must fail loudly rather than certify an unscanned tree.
    """
    scanned = _scanned_files()
    assert len(scanned) > 100, f"expected to scan the whole app, found only {len(scanned)} files"
    assert any(path.suffix == ".py" for path in scanned)


def test_no_module_still_spells_the_old_package_name() -> None:
    """The Python identifier is fully renamed across `src/` and `tests/`."""
    offenders = [
        str(path.relative_to(_APP_ROOT))
        for path in _scanned_files()
        if _OLD_IDENTIFIER in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, f"the old package identifier survives in: {sorted(offenders)}"


def test_no_path_still_carries_the_old_package_name() -> None:
    """The package directory itself is renamed, not just its contents."""
    offenders = [
        str(path.relative_to(_APP_ROOT))
        for path in _scanned_files()
        if _OLD_IDENTIFIER in str(path)
    ]
    assert not offenders, f"the old package name survives in these paths: {sorted(offenders)}"


def test_the_nats_wire_prefix_is_deliberately_unchanged() -> None:
    """The NATS subject and stream prefix is a live wire contract.

    INVARIANT: renaming it orphans every existing `url4-cloud_*` stream on the broker —
    `owns_stream` would stop recognising them, so the reclamation sweep never frees them and each
    keeps holding its full `max_bytes` reservation. `OME-877` carries the migration.
    """
    subjects = (_SRC / "screamingface_engine" / "subjects.py").read_text(encoding="utf-8")
    assert 'PREFIX = "url4-cloud"' in subjects


def test_the_runner_pod_labels_are_deliberately_unchanged() -> None:
    """The runner pool's labels are an allowlist entry in another app.

    INVARIANT: `apps/aigateway`'s NetworkPolicy admits `url4-runner` by name. Changing this
    label without changing that chart in the same window denies the pool at the CNI, which
    surfaces as a connect timeout with nothing in the gateway's logs. The labels moved from
    the retired Job adapter (`adapters/k8s.py` RUNNER_LABELS) to the runner pool Deployment
    at the cutover (OME-1092); the contract is unchanged.
    """
    chart = (_APP_ROOT / "deploy" / "helm" / "templates" / "deployment-runner.yaml").read_text(
        encoding="utf-8"
    )
    assert "app.kubernetes.io/name: url4-runner" in chart
    assert "app.kubernetes.io/part-of: url4-cloud" in chart


def test_the_job_env_prefix_is_deliberately_unchanged() -> None:
    """The Job env contract keeps its prefix.

    INVARIANT: these names are read by the Runner and written by the App, which are different
    processes that roll at different moments. They are also ConfigMap keys in the chart and an
    assertion in `verify_chart_wiring.py` — a four-sided contract. `OME-877` carries it.
    """
    job_env = (_SRC / "screamingface_engine" / "job_env.py").read_text(encoding="utf-8")
    assert 'TOPIC = "URL4_CLOUD_TOPIC"' in job_env
    assert 'EXPRESSION = "URL4_CLOUD_EXPRESSION"' in job_env
