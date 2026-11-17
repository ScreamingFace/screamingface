"""The Kubernetes adapter of `PodCostWriter` (OME-1931): one merge PATCH on this pod's own
annotation, with the in-cluster ServiceAccount token.

The request is the whole contract with the platform's guard (spec D1, D8): `PATCH
/api/v1/namespaces/<ns>/pods/<pod>`, `Content-Type: application/merge-patch+json`, a body with
ONLY the `pod-deletion-cost` annotation. No GET, LIST or WATCH: the Role has one verb.

INVARIANT: the token is never logged and never put in a message this module builds.

LAYERING: worker mode; imports `config.Settings` only. No Kubernetes client library: `httpx` is
already a runtime dependency.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from screamingface_engine.config import Settings

logger = logging.getLogger(__name__)

# The annotation the ReplicaSet controller reads on scale-down: the LOWER cost goes first; no
# annotation = 0. WHY here and not in `deletion_cost.py`: the publisher only handles counts; this
# adapter is the one place that names the annotation.
DELETION_COST_ANNOTATION = "controller.kubernetes.io/pod-deletion-cost"
SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
# Spec D3: 5 s for the whole request.
WRITE_TIMEOUT_S = 5.0
_MERGE_PATCH = "application/merge-patch+json"


class KubePodCostWriter:
    """PATCHes this pod's pod-deletion-cost; raises on any failure."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        token_path: Path,
        namespace: str,
        pod_name: str,
        timeout_s: float = WRITE_TIMEOUT_S,
    ) -> None:
        self._client = client
        self._token_path = token_path
        self._path = f"/api/v1/namespaces/{namespace}/pods/{pod_name}"
        self._timeout_s = timeout_s

    async def write(self, cost: int) -> None:
        # WHY read the token on EACH write: the kubelet replaces the bound token before it
        # expires; a cached token stops working after about 1 h. The file is a few KB on tmpfs, so
        # a sync read is accepted.
        token = self._token_path.read_text(encoding="utf-8").strip()
        body = json.dumps({"metadata": {"annotations": {DELETION_COST_ANNOTATION: str(cost)}}})
        # Spec D3: 5 s for the WHOLE request; the httpx timeout only limits each phase.
        async with asyncio.timeout(self._timeout_s):
            response = await self._client.patch(
                self._path,
                content=body.encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": _MERGE_PATCH},
            )
            response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


def _default_client(base_url: str, ca_path: Path) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        verify=ssl.create_default_context(cafile=str(ca_path)),
        timeout=WRITE_TIMEOUT_S,
    )


def _api_base_url(host: str, port: str) -> str:
    # An IPv6 host (it contains `:`) goes in brackets.
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}:{port}"


def _skip(missing: str) -> None:
    logger.warning(
        "pod-deletion-cost is enabled, but %s is missing; the worker runs without it", missing
    )


def build_pod_cost_writer(  # noqa: PLR0911 - one exit per prerequisite, then the build error
    settings: Settings,
    environ: Mapping[str, str],
    *,
    service_account_dir: Path = SERVICE_ACCOUNT_DIR,
    client_factory: Callable[[str, Path], httpx.AsyncClient] = _default_client,
) -> KubePodCostWriter | None:
    """None with NO log when the feature is off; None with ONE warning naming the first missing
    item when it is on (spec D4, fail open: a crash loop of the runner pool would stop all runs).
    """
    if not settings.worker_deletion_cost_enabled:
        return None
    pod_name = settings.worker_pod_name
    namespace = settings.worker_pod_namespace
    host = environ.get("KUBERNETES_SERVICE_HOST", "")
    token_path = service_account_dir / "token"
    ca_path = service_account_dir / "ca.crt"
    if not pod_name:
        _skip("URL4_CLOUD_WORKER_POD_NAME")
        return None
    if not namespace:
        _skip("URL4_CLOUD_WORKER_POD_NAMESPACE")
        return None
    if not host:
        _skip("KUBERNETES_SERVICE_HOST")
        return None
    if not token_path.is_file():
        _skip(f"the ServiceAccount token file {token_path}")
        return None
    if not ca_path.is_file():
        _skip(f"the ServiceAccount CA file {ca_path}")
        return None
    port = environ.get("KUBERNETES_SERVICE_PORT", "443")
    try:
        client = client_factory(_api_base_url(host, port), ca_path)
    except Exception as exc:  # spec D4, fail open: a bad CA file must not crash-loop the pool
        logger.warning(
            "pod-deletion-cost is enabled, but the API client cannot be built (%r); the worker "
            "runs without it",
            exc,
        )
        return None
    return KubePodCostWriter(
        client=client, token_path=token_path, namespace=namespace, pod_name=pod_name
    )


__all__ = [
    "DELETION_COST_ANNOTATION",
    "SERVICE_ACCOUNT_DIR",
    "WRITE_TIMEOUT_S",
    "KubePodCostWriter",
    "build_pod_cost_writer",
]
