"""Pins the Kubernetes adapter of the pod-deletion-cost writer (spec D1, D4; OME-1931).

What is pinned:
- D1: one merge PATCH on this pod's own annotation, with the ServiceAccount token read on
  each write.
- D4: the feature fails open. When a prerequisite is missing, the builder returns None and logs
  exactly one warning. When the feature is off, the builder is silent.
- The token never reaches a log record or an error message.

No test calls a real Kubernetes API: the HTTP client uses httpx.MockTransport and the CA-dependent
default client factory is replaced by an injected factory.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from screamingface_engine.config import Settings
from screamingface_engine.worker.kube_pod import (
    DELETION_COST_ANNOTATION,
    KubePodCostWriter,
    build_pod_cost_writer,
)

_TOKEN = "tok-SECRET-123"
_LOGGER = "screamingface_engine.worker.kube_pod"


def _sa_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sa"
    d.mkdir(exist_ok=True)
    (d / "token").write_text(_TOKEN + "\n")
    (d / "ca.crt").write_text("not-a-real-ca\n")
    return d


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={})


def _writer(tmp_path: Path, recorder: _Recorder) -> KubePodCostWriter:
    client = httpx.AsyncClient(
        base_url="https://kube.test:443", transport=httpx.MockTransport(recorder.handle)
    )
    return KubePodCostWriter(
        client=client,
        token_path=_sa_dir(tmp_path) / "token",
        namespace="sf-fusion",
        pod_name="url4-cloud-runner-abc",
    )


class _Factory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.recorder = _Recorder()

    def __call__(self, base_url: str, ca_path: Path) -> httpx.AsyncClient:
        self.calls.append((base_url, ca_path))
        return httpx.AsyncClient(
            base_url=base_url, transport=httpx.MockTransport(self.recorder.handle)
        )


def _on(**overrides: object) -> Settings:
    return Settings(
        **{
            "worker_deletion_cost_enabled": True,
            "worker_pod_name": "url4-cloud-runner-abc",
            "worker_pod_namespace": "sf-fusion",
            **overrides,
        }
    )


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING]


@pytest.mark.asyncio
async def test_write_sends_one_merge_patch_on_its_own_pod(tmp_path: Path) -> None:
    recorder = _Recorder()
    writer = _writer(tmp_path, recorder)

    await writer.write(3)

    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/api/v1/namespaces/sf-fusion/pods/url4-cloud-runner-abc"
    assert request.headers["content-type"] == "application/merge-patch+json"
    assert request.headers["authorization"] == f"Bearer {_TOKEN}"
    assert request.content == (
        b'{"metadata": {"annotations": {"controller.kubernetes.io/pod-deletion-cost": "3"}}}'
    )
    assert DELETION_COST_ANNOTATION == "controller.kubernetes.io/pod-deletion-cost"
    await writer.aclose()


@pytest.mark.asyncio
async def test_the_token_file_is_read_again_for_each_write(tmp_path: Path) -> None:
    recorder = _Recorder()
    writer = _writer(tmp_path, recorder)

    await writer.write(1)
    (tmp_path / "sa" / "token").write_text("tok-2\n")
    await writer.write(2)

    assert [r.headers["authorization"] for r in recorder.requests] == [
        f"Bearer {_TOKEN}",
        "Bearer tok-2",
    ]
    await writer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 500])
async def test_a_non_2xx_status_raises(tmp_path: Path, status: int) -> None:
    recorder = _Recorder()
    recorder.status = status
    writer = _writer(tmp_path, recorder)

    with pytest.raises(httpx.HTTPStatusError):
        await writer.write(1)
    await writer.aclose()


@pytest.mark.asyncio
async def test_aclose_closes_the_client(tmp_path: Path) -> None:
    recorder = _Recorder()
    writer = _writer(tmp_path, recorder)
    client = writer._client

    await writer.aclose()

    assert client.is_closed


@pytest.mark.asyncio
async def test_the_token_is_in_no_log_record_or_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    recorder = _Recorder()
    recorder.status = 403
    writer = _writer(tmp_path, recorder)

    with pytest.raises(httpx.HTTPStatusError) as info:
        await writer.write(1)
    assert _TOKEN not in str(info.value)
    assert _TOKEN not in repr(info.value)
    await writer.aclose()

    sa_dir = _sa_dir(tmp_path)
    (sa_dir / "ca.crt").unlink()
    build_pod_cost_writer(
        _on(),
        {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
        service_account_dir=sa_dir,
        client_factory=_Factory(),
    )

    assert all(_TOKEN not in r.getMessage() for r in caplog.records)


def test_the_builder_returns_none_silently_when_off(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    factory = _Factory()

    writer = build_pod_cost_writer(
        Settings(worker_deletion_cost_enabled=False),
        {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
        service_account_dir=_sa_dir(tmp_path),
        client_factory=factory,
    )

    assert writer is None
    assert _warnings(caplog) == []
    assert factory.calls == []


_MISSING_CASES = [
    (
        "pod name",
        {"worker_pod_name": None},
        {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
        None,
        "URL4_CLOUD_WORKER_POD_NAME",
    ),
    (
        "namespace",
        {"worker_pod_namespace": None},
        {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
        None,
        "URL4_CLOUD_WORKER_POD_NAMESPACE",
    ),
    ("api host", {}, {}, None, "KUBERNETES_SERVICE_HOST"),
    ("token", {}, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, "token", "token"),
    ("ca", {}, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, "ca.crt", "ca.crt"),
]


@pytest.mark.parametrize(
    ("description", "overrides", "environ", "delete", "expected"),
    _MISSING_CASES,
    ids=[case[0] for case in _MISSING_CASES],
)
def test_a_missing_prerequisite_gives_none_and_one_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    description: str,
    overrides: dict[str, object],
    environ: dict[str, str],
    delete: str | None,
    expected: str,
) -> None:
    sa_dir = _sa_dir(tmp_path)
    if delete is not None:
        (sa_dir / delete).unlink()
    factory = _Factory()

    writer = build_pod_cost_writer(
        _on(**overrides), environ, service_account_dir=sa_dir, client_factory=factory
    )

    assert writer is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert expected in warnings[0].getMessage()
    assert factory.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environ", "expected_base"),
    [
        (
            {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "KUBERNETES_SERVICE_PORT": "6443"},
            "https://10.0.0.1:6443",
        ),
        ({"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, "https://10.0.0.1:443"),
        ({"KUBERNETES_SERVICE_HOST": "fd00::1"}, "https://[fd00::1]:443"),
    ],
    ids=["explicit-port", "default-port", "ipv6-host"],
)
async def test_the_builder_uses_the_in_cluster_address(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    environ: dict[str, str],
    expected_base: str,
) -> None:
    sa_dir = _sa_dir(tmp_path)
    factory = _Factory()

    writer = build_pod_cost_writer(
        _on(), environ, service_account_dir=sa_dir, client_factory=factory
    )

    assert isinstance(writer, KubePodCostWriter)
    assert factory.calls == [(expected_base, sa_dir / "ca.crt")]
    assert _warnings(caplog) == []
    await writer.write(0)
    assert len(factory.recorder.requests) == 1
    # WHY httpx.URL on both sides: httpx drops a default :443, so the raw string would differ.
    assert factory.recorder.requests[0].url == httpx.URL(
        expected_base + "/api/v1/namespaces/sf-fusion/pods/url4-cloud-runner-abc"
    )
    await writer.aclose()


def test_an_empty_pod_name_counts_as_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    factory = _Factory()

    writer = build_pod_cost_writer(
        _on(worker_pod_name=""),
        {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
        service_account_dir=_sa_dir(tmp_path),
        client_factory=factory,
    )

    assert writer is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "URL4_CLOUD_WORKER_POD_NAME" in warnings[0].getMessage()
