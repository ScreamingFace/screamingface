#!/usr/bin/env python3
"""Report whether this machine can run the traceability e2e lanes (OME-1106).

    python3 e2e/failor/check_setup.py

Two lanes are checked independently:

- **local** — the correlation ladder (`packages/screamingface/tests/e2e/
  test_correlation_chain.py`). Needs only Docker and a prepared board; it is the lane that
  can actually be made green on a laptop, so it alone decides the exit code.
- **k8s** — the live notebook (`e2e/failor/notebooks/`). Needs cluster credentials nobody
  here controls, so it is reported but never fails the run; a permanently red validator is
  an ignored one.

INVARIANT: read-only and offline. This script never SSHes, authenticates, or contacts a
cluster. Bastion reachability is reported UNKNOWN rather than probed — opening a session to a
jump host is a credentialed action that belongs to the operator, not to a status command.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT = REPO_ROOT / "packages" / "screamingface"

# From `firecall-connect` on the bastion. Recorded so nobody has to SSH in to learn them.
BASTION = "firecall@172.190.209.255"
AKS_CLUSTER = "aks-dev-eastus"
AKS_GROUP = "rg-aks-platform-dev-eastus"
NAMESPACES = ("sf-aigw", "sf-fusion", "sf-scoreboard")

# The modules the `[runtime]` extra provides that the local stack actually boots.
RUNTIME_MODULES = (
    "uvicorn",
    "fastapi",
    "tortoise",
    "litellm",
    "aiosqlite",
    "pydantic_settings",
)

OK, MISSING, UNKNOWN = "OK", "MISSING", "UNKNOWN"


def _client_python() -> tuple[str, str]:
    """The interpreter to probe, and a label saying which one it is.

    WHY not `sys.executable`: this script is run as `python3 e2e/failor/check_setup.py` from
    the repo root, so `sys.executable` is whatever python is on PATH — usually NOT the client
    venv. Probing that would report the `[runtime]` extra missing while it is installed in the
    only environment that runs the lane, which is worse than not checking at all.
    """
    venv = CLIENT / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv), "packages/screamingface/.venv"
    return sys.executable, f"fallback: {sys.executable}"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    state: str
    detail: str
    remedy: str = ""


def _docker() -> Check:
    if shutil.which("docker") is None:
        return Check(
            "docker", MISSING, "not on PATH", "install Docker Desktop / colima"
        )
    probe = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if probe.returncode != 0:
        return Check(
            "docker", MISSING, "daemon unreachable", "start Docker, then re-run"
        )
    return Check("docker", OK, "daemon reachable")


def _runtime_extra() -> Check:
    # WHY find_spec and not import: importing litellm installs logging handlers at import
    # time (OME-1050) and is slow. Presence is the question; execution is not needed.
    python, label = _client_python()
    probe = subprocess.run(
        [
            python,
            "-c",
            "import importlib.util,sys;"
            f"mods={list(RUNTIME_MODULES)!r};"
            "print(','.join(m for m in mods if importlib.util.find_spec(m) is None))",
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return Check(
            "[runtime] extra",
            UNKNOWN,
            f"probe failed in {label}",
            "cd packages/screamingface && uv sync --extra runtime",
        )
    absent = [m for m in probe.stdout.strip().split(",") if m]
    if absent:
        return Check(
            "[runtime] extra",
            MISSING,
            f"absent in {label}: {', '.join(absent)}",
            "cd packages/screamingface && uv sync --extra runtime",
        )
    return Check("[runtime] extra", OK, f"all local-stack modules present in {label}")


def _assets() -> Check:
    override = os.environ.get("SCREAMINGFACE_E2E_ASSETS")
    roots = [Path(override)] if override else []
    roots += [
        Path.home() / ".screamingface" / "benchmark-assets",
        CLIENT / "tests" / "e2e" / "fixtures" / "assets",
    ]
    for root in roots:
        if (root / "draco").is_dir():
            return Check("draco assets", OK, f"found at {root}")
    return Check(
        "draco assets",
        MISSING,
        "no prepared draco board found",
        "screamingface prepare draco   # then export SCREAMINGFACE_E2E_ASSETS="
        f"{Path.home() / '.screamingface' / 'benchmark-assets'}",
    )


def _e2e_env() -> Check:
    if os.environ.get("SCREAMINGFACE_TEST_E2E") == "1":
        return Check("SCREAMINGFACE_TEST_E2E", OK, "set to 1")
    return Check(
        "SCREAMINGFACE_TEST_E2E",
        MISSING,
        "unset — the lane is opt-in and will SKIP",
        "export SCREAMINGFACE_TEST_E2E=1",
    )


def _client_has_trace_id() -> Check:
    """Does the installed client carry OME-967 (`trace_id` on the error hierarchy)?"""
    python, label = _client_python()
    probe = subprocess.run(
        [
            python,
            "-c",
            "import inspect,screamingface as sf;"
            "print('trace_id' in inspect.signature(sf.ScreamingFaceError).parameters)",
        ],
        capture_output=True,
        text=True,
        cwd=CLIENT,
    )
    if probe.returncode != 0:
        return Check(
            "client has OME-967",
            UNKNOWN,
            f"screamingface not importable in {label}",
            "cd packages/screamingface && uv sync --extra runtime",
        )
    if probe.stdout.strip() != "True":
        return Check(
            "client has OME-967",
            MISSING,
            "installed client predates OME-967",
            "cd packages/screamingface && uv build && pip install -U dist/*.whl",
        )
    return Check("client has OME-967", OK, "ScreamingFaceError accepts trace_id")


def _kubectl_context() -> Check:
    if shutil.which("kubectl") is None:
        return Check(
            "kubectl context", MISSING, "kubectl not on PATH", "brew install kubectl"
        )
    probe = subprocess.run(
        ["kubectl", "config", "view", "-o", "json"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        return Check(
            "kubectl context",
            MISSING,
            "kubeconfig unreadable",
            "restore ~/.kube/config",
        )
    config = json.loads(probe.stdout or "{}")
    contexts = config.get("contexts") or []
    current = config.get("current-context") or "<none>"
    if not contexts:
        clusters = [c.get("name") for c in (config.get("clusters") or [])]
        return Check(
            "kubectl context",
            MISSING,
            f"NO contexts defined (current-context names {current!r}; "
            f"{len(clusters)} cluster(s) present but nothing binds them)",
            f"ssh {BASTION} and run firecall-connect, then copy the kubeconfig back",
        )
    return Check(
        "kubectl context", OK, f"{len(contexts)} context(s); current={current}"
    )


def _bastion() -> Check:
    # Deliberately NOT probed — see the module docstring.
    return Check(
        "firecall bastion",
        UNKNOWN,
        f"{BASTION} -> AKS {AKS_CLUSTER} ({AKS_GROUP}); ns: {', '.join(NAMESPACES)}",
        f"ssh {BASTION} 'firecall-connect'   # run it yourself; not probed from here",
    )


def _render(title: str, checks: list[Check]) -> None:
    width = max(len(c.name) for c in checks)
    print(f"\n{title}")
    print("-" * (width + 42))
    for c in checks:
        print(f"  {c.state:<7}  {c.name:<{width}}  {c.detail}")
        if c.remedy and c.state != OK:
            print(f"  {'':<7}  {'':<{width}}  -> {c.remedy}")


def main() -> int:
    local = [_docker(), _runtime_extra(), _assets(), _e2e_env(), _client_has_trace_id()]
    k8s = [_kubectl_context(), _bastion()]

    _render("LOCAL LANE — the correlation ladder (decides the exit code)", local)
    _render("K8S LANE — the live notebook (reported only, never fails this run)", k8s)

    blocked = [c for c in local if c.state == MISSING]
    print()
    if blocked:
        print(
            f"LOCAL LANE NOT READY — {len(blocked)} prerequisite(s) missing (see -> lines)."
        )
        # WHY this warning is worth its own line: without assets every rung SKIPS and pytest
        # exits 0. An all-skipped run is indistinguishable from a passing one by exit code,
        # which is the most likely way to believe the chain was validated when nothing ran.
        print(
            "NOTE: a skipped rung proves NOTHING. `pytest` exits 0 on an all-skipped run."
        )
        return 1

    print("LOCAL LANE READY. Run:")
    print("  cd packages/screamingface && SCREAMINGFACE_TEST_E2E=1 \\")
    print("    uv run pytest tests/e2e/test_correlation_chain.py -m e2e -q")
    print(
        "Expected today: 5 xfailed, 0 failed. A rung turning green means its change landed"
    )
    print("and its xfail marker must be deleted in that same PR.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
