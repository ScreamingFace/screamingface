"""Cluster plumbing for the uniform executor kind suite (test-plan §5): constants, the
reachability probe, `kubectl` and `kubectl port-forward` helpers. Plain functions, not
fixtures — `conftest.py` wraps the ones that need teardown as fixtures; `test_uniform_executor.py`
imports the rest directly (never `from conftest import ...`: a root `tests/conftest.py` also
exists, and pytest's rootless import gives both files the same bare module name `conftest`).
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import time
from collections.abc import Callable, Iterator

KubectlRunner = Callable[..., "subprocess.CompletedProcess[str]"]

KIND_CONTEXT = "kind-sf-uniform"
NAMESPACE = "default"
APP_SERVICE = "sf-uniform-url4-cloud"
APP_PORT = 9108
# Must match values-kind.yaml's `nats.fullnameOverride`.
NATS_SERVICE = "sf-uniform-nats"
NATS_PORT = 4222


def run_kubectl(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """One `kubectl --context kind-sf-uniform -n default <args>` call."""
    return subprocess.run(
        ["kubectl", "--context", KIND_CONTEXT, "-n", NAMESPACE, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _context_known() -> bool:
    try:
        contexts = subprocess.run(
            ["kubectl", "config", "get-contexts", "-o", "name"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return KIND_CONTEXT in contexts.stdout.split()


def kind_reachable() -> bool:
    """Whether `kind-sf-uniform` exists as a kubectl context AND actually answers.

    A context can exist (kind writes it to kubeconfig at cluster-create time) with no cluster
    behind it any more — `kind delete cluster` does not clean up a stale kubeconfig entry left by
    an interrupted run, so both checks matter.
    """
    if not _context_known():
        return False
    try:
        probe = run_kubectl("get", "deployment", APP_SERVICE, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _endpoint_pod(service: str, *, timeout: float = 120.0) -> str:
    """The name of ONE pod actually backing `service`, resolved from its Endpoints object
    rather than from the Service's own selector.

    WHY: `kubectl port-forward svc/<name>` re-runs the Service's `spec.selector` itself and
    forwards to whichever matching pod it happens to pick — and in this chart that selector
    (`name`+`instance`, no `component`) is a SUBSET match the bundled Garage StatefulSet's pods
    also satisfy (the same rationale `deployment.yaml`'s own component-label comment warns
    about, there between the App and the runner pool, which share the same name+instance pair).
    A `port-forward` that lands on the Garage pod fails outright (it carries no `http`-named
    container port); one that lands on it silently by IP would simply not be the App. The
    Endpoints object has already done the real filtering (only pods that resolve the Service's
    target port are listed), so resolving through it and forwarding to that POD by NUMBER
    sidesteps both failure modes.
    """
    deadline = time.monotonic() + timeout
    last_stderr = ""
    while time.monotonic() < deadline:
        result = run_kubectl(
            "get",
            "endpoints",
            service,
            "-o",
            "jsonpath={.subsets[0].addresses[0].targetRef.name}",
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        last_stderr = result.stderr
        time.sleep(0.5)
    raise RuntimeError(f"service {service!r} has no ready endpoint after {timeout}s: {last_stderr}")


@contextlib.contextmanager
def port_forward(service: str, remote_port: int, *, ready_timeout: float = 120.0) -> Iterator[int]:
    """`kubectl port-forward` the pod backing a Service to a free local port; yields that port
    once it accepts TCP connections. The forward is torn down on exit regardless of how the
    block ends. See `_endpoint_pod` for why this targets the POD, not `svc/<service>`."""
    pod = _endpoint_pod(service, timeout=ready_timeout)
    local_port = _free_port()
    proc = subprocess.Popen(
        [
            "kubectl",
            "--context",
            KIND_CONTEXT,
            "-n",
            NAMESPACE,
            "port-forward",
            f"pod/{pod}",
            f"{local_port}:{remote_port}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + ready_timeout
        ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(
                    f"kubectl port-forward pod/{pod} (for service {service!r}) exited early: "
                    f"{output}"
                )
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                    ready = True
                    break
            except OSError:
                time.sleep(0.3)
        if not ready:
            raise RuntimeError(
                f"port-forward to pod/{pod}:{remote_port} (service {service!r}) did not "
                f"become ready in {ready_timeout}s"
            )
        yield local_port
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)
