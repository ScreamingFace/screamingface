"""OME-1381 — Engine ingress refuses a nonblank `X-Profile` (Stage D step 2 of OME-1138).

# FEATURE: selector-less provider access — design `component/provider-access` v6, "Stage D
# target", rollout step 2 (Engine producer-off). The gateway still honours a selector; the Engine
# stops accepting new ones, so nothing new that it schedules, fetches or mutates names a label.
# INVARIANT: every Engine ingress that used to read, forward or pass on `X-Profile` refuses a
# nonblank value — literal `default` included — with a non-retryable 400 `x_profile_unsupported`
# BEFORE any schedule, queue publication, catalog or gateway I/O, or connection mutation, and
# never echoes the value. Absent, blank and whitespace-only headers are selector-less and behave
# exactly as absent.
# AIDEV-NOTE: the wire code is asserted as a literal, not through the constant, on purpose: this
# module pins the public contract, so a rename of the constant must fail here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport
from test_forwarder import _ok, _StubNode
from test_model_parameters_proxy import _CONTRACT, _MODEL, _json_content, _ParameterSource
from test_rest_models import EMAIL_A, FakeCatalog, auth, build_app, client_for
from test_scope_producers import _local_client, _Recorder

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.catalog.port import Credential, ModelParameterResponse
from screamingface_engine.config import Settings
from screamingface_engine.rest.forwarder import NodeForwarder
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import CachePolicy

pytestmark = pytest.mark.asyncio

_CODE = "x_profile_unsupported"
# HS256 key of at least 32 bytes (RFC 7518 §3.2): shorter keys make PyJWT warn on every sign.
_SECRET = "selector-refusal-hs256-test-secret-0123456789"
_WINDOW_S = 60
_LIFETIME_S = 58_800
_T0 = datetime(2026, 9, 25, 9, 0, 0, tzinfo=UTC)
_TRACE = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
_IDENTITY = {"X-User-Email": "caller@example.com"}

Headers = list[tuple[str, str]]

# Every shape that states a selector. `blank-then-named` is the silent-ignore trap: a reader that
# looked only at the FIRST value would see "absent" and drop the second one without a word.
_SELECTORS = [
    pytest.param([("X-Profile", "team-a")], id="named"),
    pytest.param([("X-Profile", "default")], id="literal-default"),
    pytest.param([("X-Profile", "  team-a  ")], id="padded"),
    pytest.param([("X-Profile", ""), ("X-Profile", "team-a")], id="blank-then-named"),
]

_SELECTOR_LESS = [
    pytest.param([], id="absent"),
    pytest.param([("X-Profile", "")], id="blank"),
    pytest.param([("X-Profile", "   ")], id="whitespace"),
]


@pytest.fixture(autouse=True)
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Every log line at DEBUG, so "never logged" is asserted rather than assumed."""
    caplog.set_level(logging.DEBUG)
    return caplog


def _assert_never_echoed(
    response: httpx.Response, sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    """The stated value appears nowhere the caller or an operator reads it back: not in the body,
    not in any response header (names or values), not in a log line."""
    header_text = "\n".join(f"{name}: {value}" for name, value in response.headers.multi_items())
    for _name, value in sent:
        if value.strip():
            assert value.strip() not in response.text
            assert value.strip().lower() not in header_text.lower()
            assert value.strip() not in logs.text


def _assert_problem_refusal(
    response: httpx.Response, sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    """The REST surfaces' RFC 9457 rendering of the refusal."""
    assert response.status_code == 400, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    # Non-retryable: nothing invites the same request again.
    assert "retry-after" not in response.headers
    body = response.json()
    assert body["status"] == 400
    assert body["code"] == _CODE
    assert body["detail"]
    _assert_never_echoed(response, sent, logs)


def _assert_envelope_refusal(
    response: httpx.Response, sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    """The sync mounts' url4 envelope rendering of the same refusal."""
    assert response.status_code == 400, response.text
    assert "retry-after" not in response.headers
    error = response.json()["error"]
    assert error["code"] == _CODE
    assert error["message"]
    _assert_never_echoed(response, sent, logs)


# --- execution: `GET /?q=` --------------------------------------------------------------------


def _token(topic: str) -> str:
    codec = JwtCodec(secret=_SECRET, iat_window_s=_WINDOW_S, capability_lifetime_s=_LIFETIME_S)
    return codec.sign(topic, _T0)


def _run_app(runner: RecordingJobRunner, *, subscribed: bool = True) -> FastAPI:
    return create_app(
        Settings(jwt_secret=_SECRET, iat_window_s=_WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: _T0,
        interest=FixedGate(subscribed),
    )


async def _start(app: FastAPI, topic: str | None, headers: Headers) -> httpx.Response:
    capability = [] if topic is None else [("URL4-Capability", _token(topic))]
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers=[*capability, ("Prefer", "respond-async"), *headers],
        )


@pytest.mark.parametrize("sent", _SELECTORS)
async def test_execution_refuses_a_selector_before_scheduling(
    sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    runner = RecordingJobRunner()

    response = await _start(_run_app(runner), "sel-exec", sent)

    _assert_problem_refusal(response, sent, logs)
    assert runner.scheduled == []


async def test_execution_refuses_before_the_subscriber_gate_is_consulted(
    logs: pytest.LogCaptureFixture,
) -> None:
    """The gate may read shared state; a refused request must not cost that read, and a caller
    fixing its request should learn about the header first, not about a WebSocket."""
    sent = [("X-Profile", "team-a")]

    response = await _start(_run_app(RecordingJobRunner(), subscribed=False), "sel-gate", sent)

    _assert_problem_refusal(response, sent, logs)


async def test_execution_authenticates_before_it_refuses() -> None:
    """The refusal runs after authentication (design Stage D target, "Scope")."""
    response = await _start(_run_app(RecordingJobRunner()), None, [("X-Profile", "team-a")])

    assert response.status_code == 401


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
async def test_a_selector_less_run_is_scheduled_without_a_profile(sent: Headers) -> None:
    runner = RecordingJobRunner()

    response = await _start(_run_app(runner), "sel-less", sent)

    assert response.status_code == 202, response.text
    (run,) = runner.scheduled
    assert run.profile is None


class _KwargsRunner(RecordingJobRunner):
    """Records every keyword the REST edge hands the runner, so a comparison is whole."""

    def __init__(self) -> None:
        super().__init__()
        self.kwargs: list[dict[str, Any]] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        self.kwargs.append(kwargs)
        return await super().schedule(topic, url4, deadline_s, **kwargs)


async def test_a_blank_selector_changes_nothing_else_the_run_carries() -> None:
    """Identity, trace, cache policy, answer seed and client version reach the runner exactly as
    they do without the header — the producer-off change removes one value and touches no other.
    """
    common = [
        *_IDENTITY.items(),
        ("traceparent", _TRACE),
        ("Cache-Control", "no-store"),
        ("X-Answer-Seed", "7"),
        ("User-Agent", "screamingface/1.2.3"),
    ]
    without, blank = _KwargsRunner(), _KwargsRunner()

    await _start(_run_app(without), "sel-same-a", common)
    await _start(_run_app(blank), "sel-same-b", [*common, ("X-Profile", " ")])

    assert blank.kwargs == without.kwargs
    (call,) = blank.kwargs
    assert call.get("profile") is None
    assert call["identity"] == _IDENTITY
    assert call["traceparent"] == _TRACE
    assert call["cache"] == CachePolicy(participate=False)
    assert call["answer_seed"] == 7
    assert call["client_version"] == "1.2.3"


async def test_the_run_scheduling_log_names_no_profile(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.routes"):
        response = await _start(_run_app(RecordingJobRunner()), "sel-log", [])

    assert response.status_code == 202
    (line,) = [r.getMessage() for r in caplog.records if "run scheduled" in r.getMessage()]
    assert "profile" not in line


# --- catalog: `GET /v1/models` and `GET /v1/model-parameters` -----------------------------------


@pytest.mark.parametrize("sent", _SELECTORS)
async def test_the_model_listing_refuses_a_selector_before_fetching(
    sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    catalog = FakeCatalog()

    async with client_for(build_app(catalog)) as client:
        response = await client.get("/v1/models", headers=[*auth(EMAIL_A).items(), *sent])

    _assert_problem_refusal(response, sent, logs)
    assert catalog.seen == []


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
async def test_the_model_listing_keys_a_blank_selector_as_absent(sent: Headers) -> None:
    """Same credential, same cache key: a selector-less caller keeps its cached catalog."""
    catalog = FakeCatalog()

    async with client_for(build_app(catalog)) as client:
        response = await client.get("/v1/models", headers=[*auth(EMAIL_A).items(), *sent])

    assert response.status_code == 200
    (credential,) = catalog.seen
    assert credential.profile is None
    assert credential.key == Credential.derive(None, auth(EMAIL_A)).key


def _parameters_app(source: _ParameterSource) -> FastAPI:
    return create_app(
        Settings(jwt_secret=_SECRET), stream=InMemoryEventStream(), model_parameters=source
    )


def _contract_source() -> _ParameterSource:
    return _ParameterSource(ModelParameterResponse(status=200, content=_json_content(_CONTRACT)))


@pytest.mark.parametrize("sent", _SELECTORS)
async def test_model_parameters_refuse_a_selector_before_fetching(
    sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    source = _contract_source()

    async with client_for(_parameters_app(source)) as client:
        response = await client.get(
            "/v1/model-parameters", params={"model": _MODEL}, headers=[*_IDENTITY.items(), *sent]
        )

    _assert_problem_refusal(response, sent, logs)
    # The route's privacy headers ride on every answer it gives, this refusal included.
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Vary"] == "X-Profile, X-User-Email"
    assert source.seen == []


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
async def test_model_parameters_treat_a_blank_selector_as_absent(sent: Headers) -> None:
    source = _contract_source()

    async with client_for(_parameters_app(source)) as client:
        response = await client.get(
            "/v1/model-parameters", params={"model": _MODEL}, headers=[*_IDENTITY.items(), *sent]
        )

    assert response.status_code == 200
    ((credential, _model),) = source.seen
    assert credential.profile is None
    assert credential.identity == _IDENTITY


# --- the sync mounts: the deployed forwarder and local mode ------------------------------------


def _forwarder_client(stub: _StubNode) -> httpx.AsyncClient:
    forwarder = NodeForwarder(
        node_base_url="http://node.test",
        timeout_s=5.0,
        client=httpx.AsyncClient(transport=stub.transport()),
    )
    return httpx.AsyncClient(transport=ASGITransport(app=forwarder), base_url="http://app.test")


@pytest.mark.parametrize("sent", _SELECTORS)
async def test_the_sync_forwarder_refuses_a_selector_without_forwarding(
    sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    stub = _StubNode(_ok())

    async with _forwarder_client(stub) as client:
        response = await client.get(
            f"/{_MODEL}", params={"q": "('')!'x'"}, headers=[*_IDENTITY.items(), *sent]
        )

    _assert_envelope_refusal(response, sent, logs)
    assert stub.calls == []


async def test_the_sync_forwarder_checks_identity_before_the_selector() -> None:
    stub = _StubNode(_ok())

    async with _forwarder_client(stub) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-Profile": "team-a"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "identity_access_denied"
    assert stub.calls == []


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
async def test_the_sync_forwarder_forwards_a_selector_less_request(sent: Headers) -> None:
    stub = _StubNode(_ok(body=b"PARIS"))

    async with _forwarder_client(stub) as client:
        response = await client.get(f"/{_MODEL}", headers=[*_IDENTITY.items(), *sent])

    assert response.status_code == 200
    assert len(stub.calls) == 1


@pytest.mark.parametrize("sent", _SELECTORS)
async def test_the_local_sync_mount_refuses_a_selector_before_binding(
    sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    recorder = _Recorder()

    async with _local_client(recorder) as client:
        response = await client.get("/m", headers=[*_IDENTITY.items(), *sent])

    _assert_envelope_refusal(response, sent, logs)
    assert recorder.scope is None


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
async def test_the_local_sync_mount_binds_a_selector_less_scope(sent: Headers) -> None:
    recorder = _Recorder()

    async with _local_client(recorder) as client:
        response = await client.get("/m", headers=[*_IDENTITY.items(), *sent])

    assert response.status_code == 200, response.text
    assert recorder.scope is not None
    # `origin` proves the MOUNT bound this scope: the harness's default scope is selector-less too.
    assert recorder.scope.origin == "sync"
    assert recorder.scope.profile is None
