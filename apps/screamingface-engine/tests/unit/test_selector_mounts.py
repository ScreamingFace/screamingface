"""OME-1381 — the mount routes refuse a nonblank `X-Profile` before a direct run is queued.

# FEATURE: selector-less provider access — design `component/provider-access` v6, "Stage D
# target", rollout step 2 (Engine producer-off). Since the uniform executor (PRD 04) a mount call
# is a `shape=direct` run the App queues itself, so the mount route is the ingress that used to
# be the node tier's forwarder, and it inherits the forwarder's refusal.
# INVARIANT: a mount call that states a selector — literal `default` included — gets url4's
# envelope 400 `x_profile_unsupported` after the identity check and before every other answer
# the route can give (missing intent, bad seed, over-long target, admission), with nothing
# queued and the value never echoed. Absent, blank and whitespace-only headers queue a direct
# run that carries no profile, and nothing else about that run changes.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_mount_routes import EMAIL, TABLE, _app, _client, _ok, _Runner
from test_selector_refusal import (
    _SELECTOR_LESS,
    _SELECTORS,
    Headers,
    _assert_envelope_refusal,
)

from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.mounts import register_mounts
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import CachePolicy

pytestmark = pytest.mark.asyncio

_ENDPOINT = "/v1/chat/completions"
_CALLS = [
    pytest.param(f"{_ENDPOINT}?q=('hi')!'answer'", id="endpoint"),
    pytest.param("/v1/benchmarks/data/foo", id="data-route"),
]
_ONE_SELECTOR: Headers = [("X-Profile", "team-a")]
_TRACE = "00-" + "c" * 32 + "-" + "d" * 16 + "-01"


@pytest.fixture(autouse=True)
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Every log line at DEBUG, so "never logged" is asserted rather than assumed."""
    caplog.set_level("DEBUG")
    return caplog


async def _get(app: Any, target: str, headers: Headers) -> httpx.Response:
    async with _client(app) as client:
        return await client.get(target, headers=headers)


def _local_app() -> tuple[Any, _Runner]:
    """The mounts as `serve --local` registers them: no edge, so no identity is required."""
    stream = InMemoryEventStream()
    runner = _Runner(stream, _ok('{"ok": true}', "application/json"))
    app = create_app(Settings(jwt_secret="mount-secret"), stream=stream, job_runner=runner)  # type: ignore[arg-type]
    register_mounts(app, TABLE, require_identity=False)
    return app, runner


@pytest.mark.parametrize("sent", _SELECTORS)
@pytest.mark.parametrize("target", _CALLS)
async def test_a_mount_call_refuses_a_selector_before_queueing(
    target: str, sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    app, runner = _app(_ok('{"ok": true}', "application/json"))

    response = await _get(app, target, [*EMAIL.items(), *sent])

    _assert_envelope_refusal(response, sent, logs)
    # Refused before a topic exists: no run to name, none queued, none to stop.
    assert "x-url4-run" not in response.headers
    assert runner.scheduled == []
    assert runner.stopped == []


async def test_a_mount_call_checks_identity_before_the_selector() -> None:
    """Authentication first (design Stage D target, "Scope"), as the forwarder did."""
    app, runner = _app(_ok("x"))

    response = await _get(app, f"{_ENDPOINT}?q=(a)!b", _ONE_SELECTOR)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "identity_access_denied"
    assert runner.scheduled == []


# --- precedence: the refusal comes before every other answer a mount call can give -------------
# Each case's selector-less control is `test_mount_routes`' own test for that answer.

_OTHER_REFUSALS = [
    pytest.param(_ENDPOINT, [], {}, id="missing-intent"),
    pytest.param(f"{_ENDPOINT}?q=(a)!b", [("X-Answer-Seed", "not-a-seed")], {}, id="bad-seed"),
    pytest.param(f"{_ENDPOINT}?q=({'x' * 9000})!b", [], {}, id="target-over-8kib"),
    pytest.param(f"{_ENDPOINT}?q=(a)!b", [], {"full": True}, id="at-capacity"),
]


@pytest.mark.parametrize(("target", "extra", "flags"), _OTHER_REFUSALS)
async def test_the_refusal_wins_over_every_other_mount_refusal(
    target: str, extra: Headers, flags: dict[str, Any], logs: pytest.LogCaptureFixture
) -> None:
    app, runner = _app(_ok("x"), **flags)

    response = await _get(app, target, [*EMAIL.items(), *extra, *_ONE_SELECTOR])

    _assert_envelope_refusal(response, _ONE_SELECTOR, logs)
    assert runner.scheduled == []


# --- selector-less calls ------------------------------------------------------------------------


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
@pytest.mark.parametrize("target", _CALLS)
async def test_a_selector_less_mount_call_queues_a_direct_run(target: str, sent: Headers) -> None:
    app, runner = _app(_ok('{"ok": true}', "application/json"))

    response = await _get(app, target, [*EMAIL.items(), *sent])

    assert response.status_code == 200, response.text
    (run,) = runner.scheduled
    assert run["shape"] == "direct"
    assert "profile" not in run


async def test_a_blank_selector_changes_nothing_else_a_direct_run_carries() -> None:
    """Identity, trace, cache policy and answer seed reach the runner exactly as they do without
    the header — producer-off removes one value from a direct run and touches no other."""
    common: Headers = [
        *EMAIL.items(),
        ("traceparent", _TRACE),
        ("Cache-Control", "no-store"),
        ("X-Answer-Seed", "7"),
    ]
    without_app, without = _app(_ok("x"))
    blank_app, blank = _app(_ok("x"))

    await _get(without_app, f"{_ENDPOINT}?q=(a)!b", common)
    await _get(blank_app, f"{_ENDPOINT}?q=(a)!b", [*common, ("X-Profile", " ")])

    # Each call names its own run, so the topic is the one field expected to differ.
    (plain,), (blanked,) = without.scheduled, blank.scheduled
    assert {**blanked, "topic": None} == {**plain, "topic": None}
    assert "profile" not in blanked
    assert blanked["traceparent"] == _TRACE
    assert blanked["cache"] == CachePolicy(participate=False)
    assert blanked["answer_seed"] == 7


# --- local mode: the same routes, registered without an identity requirement --------------------


@pytest.mark.parametrize("sent", _SELECTORS)
async def test_local_mode_mounts_refuse_a_selector_even_without_an_identity(
    sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    """Local mode needs no identity, so nothing answers before the refusal — it still comes: local
    mode must not accept a selector production refuses."""
    app, runner = _local_app()

    response = await _get(app, f"{_ENDPOINT}?q=(a)!b", sent)

    _assert_envelope_refusal(response, sent, logs)
    assert runner.scheduled == []


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
async def test_local_mode_mounts_serve_a_selector_less_call(sent: Headers) -> None:
    app, runner = _local_app()

    response = await _get(app, f"{_ENDPOINT}?q=(a)!b", sent)

    assert response.status_code == 200, response.text
    (run,) = runner.scheduled
    assert "profile" not in run


# --- the published contract ---------------------------------------------------------------------


async def test_every_mount_operation_documents_the_refusal() -> None:
    """A mount answers in url4's envelope, not an RFC 9457 problem, so its 400 names the code in
    the description; the header itself is declared deprecated, as on the REST operations."""
    app, _ = _app(_ok("x"))
    async with _client(app) as client:
        schema = (await client.get("/openapi.json")).json()

    for mount in TABLE.mounts:
        operation = schema["paths"][mount.path]["get"]
        (header,) = [p for p in operation["parameters"] if p["name"] == "X-Profile"]
        assert header["in"] == "header"
        assert header["deprecated"] is True
        assert header.get("required", False) is False
        assert "refused with 400" in header["description"]
        assert "x_profile_unsupported" in operation["responses"]["400"]["description"]
