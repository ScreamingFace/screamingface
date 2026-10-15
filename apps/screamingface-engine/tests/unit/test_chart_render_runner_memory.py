"""The runner pool's memory: one per-slot value, and children that reserve nothing they never use.

FEATURE (OME-1607). Two measured facts drive these renders:

- Native libraries reserve address space they never touch: pyarrow's default pool (mimalloc)
  reserves a 1 GiB arena on its first allocation, and OpenBLAS a buffer per node CPU. Under the
  child's `RLIMIT_AS` that left a judged run ~700 MiB to work with; it died of `MemoryError` at
  459 MiB resident. The pool's env turns both reservations off for every child it starts.
- The pod limit is `workerSlots × perRunCharge.memoryLimitMi + overhead`. The worker now holds
  each run to that same per-slot value in RESIDENT memory, and keeps `RLIMIT_AS` as a runaway
  backstop at a stated multiple of it — so changing the one per-slot value moves every derived
  limit together, whatever `workerSlots` or `replicas` are.

WHY render rather than read the template text: see `test_chart_render_tracing.py`.
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
_FULLNAME = f"{_RELEASE}-{_RELEASE}"
_NATS = "config.natsUrl=nats://nats.example:4222"
_MIB = 1024 * 1024

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*settings: str) -> list[dict]:
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _refusal(*settings: str) -> str:
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode != 0, "helm rendered a chart it must refuse"
    return result.stderr


def _find(docs: list[dict], kind: str, name: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind}/{name} in the rendered chart")


def _runner_env(docs: list[dict]) -> dict:
    return _find(docs, "ConfigMap", f"{_FULLNAME}-runner-env")["data"]


def _runner_container(docs: list[dict]) -> dict:
    spec = _find(docs, "Deployment", f"{_FULLNAME}-runner")["spec"]["template"]["spec"]
    return spec["containers"][0]


def _worker_env(docs: list[dict]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in _runner_container(docs)["env"]}


def test_runner_children_reserve_no_address_space_they_never_use() -> None:
    env = _runner_env(_render())
    assert env["ARROW_DEFAULT_MEMORY_POOL"] == "system"
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["OMP_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"


def test_the_per_slot_charge_is_each_run_s_resident_budget_and_sets_its_backstop() -> None:
    env = _worker_env(_render())
    assert env["URL4_CLOUD_WORKER_RESIDENT_BUDGET_BYTES"] == str(1024 * _MIB)
    assert env["URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES"] == str(2 * 1024 * _MIB)


def test_one_per_slot_value_moves_the_budget_the_backstop_and_the_pod_limit_together() -> None:
    docs = _render(
        "runnerPool.perRunCharge.memoryLimitMi=1536",
        "runnerPool.perRunCharge.addressSpaceFactor=3",
        "runnerPool.workerSlots=2",
    )
    env = _worker_env(docs)
    assert env["URL4_CLOUD_WORKER_RESIDENT_BUDGET_BYTES"] == str(1536 * _MIB)
    assert env["URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES"] == str(3 * 1536 * _MIB)
    limit = _runner_container(docs)["resources"]["limits"]["memory"]
    assert limit == f"{2 * 1536 + 256}Mi"


def test_a_backstop_at_or_below_the_resident_budget_is_refused() -> None:
    """A backstop no larger than the budget would fire first, on reserved address space —
    the exact failure this change removes."""
    message = _refusal("runnerPool.perRunCharge.addressSpaceFactor=1")
    assert "addressSpaceFactor" in message
