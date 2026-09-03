"""Spec §7's two caller classes, end to end through the deployed posture.

The whole of spec §10's identity list lives here, because each item is a statement about a real
request rather than about a function: a forged header is not honoured, an anonymous caller needs
a token, a mesh-verified one needs none, an unevaluable gate is `503` and not `403`, and none of
the refusals store anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import report_intake
from report_intake.config import Settings
from report_intake.core.problem import PROBLEM_MEDIA_TYPE, ProblemException
from report_intake.identity.gate import admit
from report_intake.identity.mesh_identity import MESH_IDENTITY_HEADER
from report_intake.identity.rate_limit import CLIENT_IP_HEADER
from report_intake.identity.turnstile import TURNSTILE_RESPONSE_HEADER, TurnstileUnavailable
from report_intake.main import create_app
from report_intake.reports.pipeline import Accepted, Submission

from ..conftest import MESH_NETWORK, StubTurnstile
from .test_report_schema import a_report

_TOKEN = "a-token-from-the-widget"
_MESH_IDENTITY = {MESH_IDENTITY_HEADER: "reporter@example.org"}
_BOT_TOKEN = {TURNSTILE_RESPONSE_HEADER: _TOKEN}


class _RecordingPipeline:
    """Captures what reached the pipeline — which for most of these is *whether* anything did,
    since every refusal here has to store nothing."""

    def __init__(self) -> None:
        self.submissions: list[Submission] = []

    async def submit(self, submission: Submission) -> Accepted:
        self.submissions.append(submission)
        return Accepted(ref="r_stub", classification="envelope", delivery_state="queued")


@pytest.fixture
def pipeline(mesh_client: TestClient) -> _RecordingPipeline:
    recording = _RecordingPipeline()
    mesh_client.app.state.report_pipeline = recording  # type: ignore[attr-defined]
    return recording


def _post(client: TestClient, headers: dict[str, str] | None = None) -> Any:
    return client.post(
        "/v1/reports",
        json=a_report(),
        headers={"content-type": "application/json", **(headers or {})},
    )


def test_a_mesh_verified_caller_is_accepted_with_no_bot_token_at_all(
    mesh_client: TestClient, pipeline: _RecordingPipeline, turnstile: StubTurnstile
) -> None:
    """Spec §7: identity already answers the question the gate asks, so the gate is skipped —
    asserted by the verifier never being consulted, not only by the status."""
    response = _post(mesh_client, _MESH_IDENTITY)

    assert response.status_code == 202
    assert turnstile.tokens == []


def test_the_mesh_injected_address_is_bound_to_the_report(
    mesh_client: TestClient, pipeline: _RecordingPipeline
) -> None:
    _post(mesh_client, _MESH_IDENTITY)

    assert [s.caller_email for s in pipeline.submissions] == ["reporter@example.org"]


def test_a_forged_identity_header_from_outside_the_mesh_never_reaches_the_report(
    database_url: str, turnstile: StubTurnstile
) -> None:
    """Spec §10's first identity assertion, at the level that matters: not merely disbelieved but
    not carried into the row either. The stranger falls back to the anonymous class and clears the
    bot gate, so this is `202` — with `caller_email` still `None`."""
    app = create_app(
        Settings.model_validate(
            {
                "database_url": database_url,
                "auth_mode": "mesh_or_turnstile",
                "allowed_networks": MESH_NETWORK,
                "turnstile_secret": "a-test-secret",
            }
        )
    )
    app.state.turnstile_verifier = turnstile
    recording = _RecordingPipeline()
    app.state.report_pipeline = recording

    # A peer outside `MESH_NETWORK`: nothing vouches for this caller's claim.
    with TestClient(app, base_url="http://r.example.test", client=("203.0.113.9", 50000)) as c:
        response = _post(c, {**_MESH_IDENTITY, **_BOT_TOKEN})

    assert response.status_code == 202
    assert [s.caller_email for s in recording.submissions] == [None]


def test_an_anonymous_report_with_no_bot_token_is_403_and_stores_nothing(
    mesh_client: TestClient, pipeline: _RecordingPipeline
) -> None:
    response = _post(mesh_client)

    assert response.status_code == 403
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert pipeline.submissions == []


def test_an_anonymous_report_with_a_valid_bot_token_is_accepted(
    mesh_client: TestClient, pipeline: _RecordingPipeline, turnstile: StubTurnstile
) -> None:
    response = _post(mesh_client, _BOT_TOKEN)

    assert response.status_code == 202
    assert turnstile.tokens == [_TOKEN]
    assert [s.caller_email for s in pipeline.submissions] == [None]


def test_an_anonymous_report_with_a_rejected_bot_token_is_403_and_stores_nothing(
    mesh_client: TestClient, pipeline: _RecordingPipeline, turnstile: StubTurnstile
) -> None:
    turnstile.answer = False

    response = _post(mesh_client, _BOT_TOKEN)

    assert response.status_code == 403
    assert pipeline.submissions == []


def test_an_unreachable_siteverify_is_503_and_not_403(
    mesh_client: TestClient, pipeline: _RecordingPipeline, turnstile: StubTurnstile
) -> None:
    """Spec §10 names this one by name: the client must be told to retry unchanged rather than to
    fetch a new token, because the token was never the problem."""
    turnstile.answer = TurnstileUnavailable("siteverify could not be reached")

    response = _post(mesh_client, _BOT_TOKEN)

    assert response.status_code == 503
    assert pipeline.submissions == []


def test_the_bot_gate_answers_before_the_body_is_parsed(mesh_client: TestClient) -> None:
    """A refusal that says *nothing was stored* is cheapest to keep true when nothing capable of
    storing has been reached — and a caller who cannot clear the gate should not get this service
    to parse anything for them either. Malformed JSON would be a `400` if it were read first."""
    response = mesh_client.post(
        "/v1/reports", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 403


def test_a_flood_of_anonymous_reports_is_throttled_with_a_backoff_hint(
    mesh_client: TestClient, pipeline: _RecordingPipeline
) -> None:
    statuses = [_post(mesh_client, _BOT_TOKEN).status_code for _ in range(8)]

    assert statuses[0] == 202
    assert 429 in statuses
    assert int(_post(mesh_client, _BOT_TOKEN).headers["retry-after"]) > 0


def test_rotating_the_client_ip_header_does_not_buy_a_fresh_budget(
    mesh_client: TestClient, pipeline: _RecordingPipeline
) -> None:
    """Spec §10. The default keys on the peer, and the peer is the mesh proxy on every request —
    so a header the caller chooses must change nothing."""
    statuses = [
        _post(mesh_client, {**_BOT_TOKEN, CLIENT_IP_HEADER: f"203.0.113.{n}"}).status_code
        for n in range(8)
    ]

    assert 429 in statuses


def test_the_rate_limit_answers_before_the_bot_gate(
    mesh_client: TestClient, pipeline: _RecordingPipeline, turnstile: StubTurnstile
) -> None:
    """Verifying a token is an outbound request this service makes on an anonymous caller's say
    so. If a flood reached the verifier, the gate meant to absorb abuse would amplify it."""
    for _ in range(20):
        _post(mesh_client, _BOT_TOKEN)

    assert len(turnstile.tokens) < 20


def test_a_mesh_verified_caller_is_not_rate_limited(
    mesh_client: TestClient, pipeline: _RecordingPipeline
) -> None:
    """The budget is the anonymous one (spec §7). A verified caller filing a burst — a test run
    that failed twenty ways at once — must not be turned away."""
    statuses = [_post(mesh_client, _MESH_IDENTITY).status_code for _ in range(20)]

    assert set(statuses) == {202}


def test_the_local_posture_gates_nothing_and_binds_no_identity(client: TestClient) -> None:
    """`disabled` has no mesh to have injected an address, so a header claiming one came from the
    caller themselves and is ignored — the loopback guard is the whole boundary there."""
    recording = _RecordingPipeline()
    client.app.state.report_pipeline = recording  # type: ignore[attr-defined]

    response = _post(client, _MESH_IDENTITY)

    assert response.status_code == 202
    assert [s.caller_email for s in recording.submissions] == [None]


@pytest.mark.asyncio
async def test_a_request_this_process_cannot_attribute_is_throttled(
    mesh_client: TestClient,
) -> None:
    """`None` from `rate_limit_key` is a refusal, not an exemption: an unattributable
    unauthenticated write must not be admitted under a bucket every other unattributable request
    would share. Unreachable under uvicorn, which always supplies a peer — so it is driven through
    a hand-built scope rather than through a client that would invent one."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/reports",
        "headers": [],
        "client": None,
        "app": mesh_client.app,
    }

    with pytest.raises(ProblemException) as raised:
        await admit(Request(scope))

    assert raised.value.problem.status == 429


def test_nothing_in_the_identity_package_reads_an_id_out_of_a_report() -> None:
    """`OME-966`, structurally: an id in a report is a claim, not a credential.

    The call order already makes it impossible — `admit` runs before `bind`, so no parsed report
    exists yet — but the order is one edit away from changing and the reason it must not is not
    visible from `routes/reports.py`. A scan is what makes the constraint outlive the ordering.
    """
    package = Path(report_intake.__file__).resolve().parent / "identity"
    naming_an_id = {
        path.name
        for path in package.rglob("*.py")
        if any(claim in path.read_text(encoding="utf-8") for claim in ("trace_id", "run_id"))
    }

    assert (package / "gate.py").is_file(), "the scan must be pointed at real source"
    assert naming_an_id == set()
