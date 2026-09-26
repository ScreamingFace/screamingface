"""`runnerPool.warmChildren` (uniform executor PRD 03): the chart value that reaches the worker
as `URL4_CLOUD_WORKER_WARM_CHILDREN`, and the schema/render-time guards around it.

WHY render and not read the template text: the charts.yml gate exists because `helm lint`
reports success for a chart that cannot render. The assertions here are against the RENDERED
manifest — the same precedent as `test_chart_render_runner_pool.py`.

The env var is rendered INLINE in the runner Deployment's own `env:` list (like
`URL4_CLOUD_WORKER_DRAIN_GRACE_S` and `URL4_CLOUD_WORKER_METRICS_PORT` beside it), not through
the checksummed `runner-env` ConfigMap — so there is no separate checksum annotation to change
when `warmChildren` changes. A pod TEMPLATE change already rolls the Deployment on its own
(Kubernetes' own rollout trigger), so the assertion here is that the rendered env differs, not
that a checksum annotation changed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "deploy" / "helm"
_RELEASE = "url4-cloud"


def _render_with_overrides(**overrides: str) -> list[dict]:
    """Render the chart with `--set` overrides. `--set`, not `--set-string`: the schema types
    `warmChildren`/`workerSlots` as numbers, and helm refuses a quoted string for them."""
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    for key, value in overrides.items():
        args += ["--set", f"{key}={value}"]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _find(docs: list[dict], kind: str, name: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind} named {name!r} in the rendered chart")


def _runner_env(docs: list[dict]) -> dict[str, str]:
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    container = pool["spec"]["template"]["spec"]["containers"][0]
    return {entry["name"]: entry["value"] for entry in container["env"]}


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_unset_warm_children_renders_no_env_var() -> None:
    """The chart default (`values.yaml`) leaves `warmChildren` null, so the key must be ABSENT
    from the rendered env — not rendered empty, which would override the worker's own default
    (one warm child per slot) with 0 warm children."""
    env = _runner_env(_render_with_overrides())
    assert "URL4_CLOUD_WORKER_WARM_CHILDREN" not in env


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_warm_children_zero_renders_as_the_string_zero() -> None:
    """0 is a legal, meaningful value (spawn on claim, no idle children) and must render as
    "0" — not be dropped as falsy the way an empty string is elsewhere in this chart."""
    env = _runner_env(_render_with_overrides(**{"runnerPool.warmChildren": "0"}))
    assert env["URL4_CLOUD_WORKER_WARM_CHILDREN"] == "0"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_warm_children_set_reaches_the_worker_env() -> None:
    env = _runner_env(_render_with_overrides(**{"runnerPool.warmChildren": "2"}))
    assert env["URL4_CLOUD_WORKER_WARM_CHILDREN"] == "2"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_schema_rejects_a_negative_warm_children() -> None:
    with pytest.raises(subprocess.CalledProcessError) as exc:
        _render_with_overrides(**{"runnerPool.warmChildren": "-1"})
    assert "warmChildren" in exc.value.stderr


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_warm_children_above_worker_slots_fails_the_render() -> None:
    """The worker caps `warmChildren` at `workerSlots` itself (`worker/loop.py`), so this can
    never deploy a pool that over-warms — but a value an operator set expecting it to take
    effect would otherwise be silently truncated. The render refuses instead, naming both
    values, the same shape as the drain-timing guard (`test_chart_render_runner_pool.py`'s
    `test_a_termination_grace_that_cannot_cover_the_drain_fails_the_render`)."""
    with pytest.raises(subprocess.CalledProcessError) as exc:
        _render_with_overrides(**{"runnerPool.workerSlots": "4", "runnerPool.warmChildren": "8"})
    assert "runnerPool.warmChildren (8)" in exc.value.stderr
    assert "runnerPool.workerSlots (4)" in exc.value.stderr


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_warm_children_equal_to_worker_slots_is_the_boundary_and_renders() -> None:
    """The guard is `>`, not `>=` — warming every slot is legal, not "above" the slot count."""
    env = _runner_env(
        _render_with_overrides(**{"runnerPool.workerSlots": "4", "runnerPool.warmChildren": "4"})
    )
    assert env["URL4_CLOUD_WORKER_WARM_CHILDREN"] == "4"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_a_warm_children_change_changes_the_rendered_pod_env() -> None:
    """`URL4_CLOUD_WORKER_WARM_CHILDREN` is rendered INLINE in the runner Deployment's own
    `env:` list (like `URL4_CLOUD_WORKER_DRAIN_GRACE_S` beside it), not through the checksummed
    `runner-env` ConfigMap — so there is no `checksum/runner-env` annotation to change here. A
    pod TEMPLATE change already rolls the Deployment on its own; this asserts the template's
    rendered env actually differs between two `warmChildren` values, which is what makes that
    rollout carry the new setting."""
    env_a = _runner_env(_render_with_overrides(**{"runnerPool.warmChildren": "1"}))
    env_b = _runner_env(_render_with_overrides(**{"runnerPool.warmChildren": "2"}))
    assert env_a != env_b
    assert env_a["URL4_CLOUD_WORKER_WARM_CHILDREN"] == "1"
    assert env_b["URL4_CLOUD_WORKER_WARM_CHILDREN"] == "2"
