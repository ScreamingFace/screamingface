"""Failure-path rehearsal against the FakeGateway (OME-962, parent R7).

The cache can only replay good news — a failed provider call never stores a cache row —
so the bad-news paths are rehearsed here with a scripted stand-in: ``FakeGateway`` plays
hand-authored failure tapes through the same ``ReplayBackend`` seam the cache-seeded
gateway uses, and the REAL engine + SDK run a real one-case board against it. Each test
pins where the engine's DECLARED failure policy says that failure must land.

The declared policy chain, with the code that declares it:

- non-2xx gateway answer → ``ResolutionError`` whose code/message prefer the response's
  own ``detail`` payload; ``permanent`` is False only for 429/5xx
  (``runner/connector.py::_raise_for_status``).
- 2xx non-JSON body → ``aigateway_bad_response``, permanent
  (``runner/connector.py::_json_or_raise``).
- parsable turn with neither answer nor tool call → ``aigateway_bad_response``;
  ``finish_reason=length`` with blank text → ``model_token_cap``
  (``runner/model_response.py::raise_if_unusable``).
- a failed CANDIDATE call errors the whole Case row; the board's cases fan out with
  ``on_error="collect"`` (``benchmarks/protocol.py``), so the row becomes
  ``{"error": {"kind", "message", "code", "retryable"}}`` (url4
  ``dag/nodes.py::_error_payload``) and DRACO's
  aggregate maps it to a ``stage="candidate"`` Failure via ``public_error``
  (``benchmarks/draco/aggregate.py::_row_failure``). The wire row carries the connector's
  own code/retryable (OME-924), so the Failure code and retryability are the upstream
  ones and the gateway-authored MESSAGE names the provider failure.
- a judge that answers but is cut off (truncated verdict JSON) never errors the row:
  every verdict is bound invalid (``benchmarks/draco/verdict.py::bind``) and the case
  lands as a ``stage="grading"`` Failure, code ``no_valid_judge_verdict``
  (``benchmarks/draco/aggregate.py``), with the candidate's output preserved.

Lanes: the FakeGateway/fixture contract tests below are pure-code + loopback-thread and
run in the DEFAULT lane; the scenario tests boot the real engine subprocess and are
gated exactly like ``test_replay_plumbing.py`` (``e2e`` marker +
``SCREAMINGFACE_TEST_E2E=1`` + docker probe) plus prepared draco assets.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from harness._gating import FIXTURES_DIR, require_e2e_stack
from harness.fake_gateway import FakeGateway
from harness.stack import EngineProcess
from harness.tape import TAPE_SCHEMA, LoadedTape, TapeDocument, load_tape

FAILURES_DIR = FIXTURES_DIR / "failures"

#: Both ids are declared engine routes (models/seeds/openrouter.py); the judge id is
#: DRACO's pinned judge (benchmarks/draco/exam.py::JUDGE_MODEL).
CANDIDATE_MODEL = "openrouter/openai/gpt-5.5"
JUDGE_MODEL = "openrouter/google/gemini-3.1-pro-preview"

#: The cheapest judge-bearing board: identical to canonical DRACO but three judge
#: passes instead of five, so a one-case failure rehearsal spends the fewest calls.
BOARD = "draco-3pass"

_ASSETS_ENV = "SCREAMINGFACE_E2E_ASSETS"
_DEFAULT_ASSETS_ROOT = Path("/tmp/screamingface-benchmark-assets")

#: Every authored failure scenario and its tape file. The names are the rehearsal's
#: vocabulary — each maps one provider failure shape to one declared landing.
SCENARIO_TAPES = {
    "rate_limit_429": FAILURES_DIR / "rate_limit_429.tape.json",
    "provider_5xx": FAILURES_DIR / "provider_5xx.tape.json",
    "malformed_body": FAILURES_DIR / "malformed_body.tape.json",
    "blank_completion": FAILURES_DIR / "blank_completion.tape.json",
    "judge_cutoff": FAILURES_DIR / "judge_cutoff.tape.json",
    # OME-993 (GH #740): the two judge-side transport failures that used to be
    # misreported as "invalid Criterion envelope".
    "judge_token_cap": FAILURES_DIR / "judge_token_cap.tape.json",
    "judge_429": FAILURES_DIR / "judge_429.tape.json",
}


def _authored_tape(
    *,
    authored: bool = True,
    exchanges: list[dict[str, object]] | None = None,
) -> LoadedTape:
    """An in-memory failure tape for contract tests — one 429 candidate exchange."""
    document = {
        "schema": TAPE_SCHEMA,
        "provenance": {
            "board": BOARD,
            "revision": "authored-failure-rehearsal-2026-08",
            "expression_sha": "b" * 64,
            "engine_sha": "authored — no engine rendered this tape",
            "recorded_at": "2026-08-25T00:00:00Z",
            "run_ref": "in-memory contract-test tape",
            "authored": authored,
        },
        "exchanges": exchanges if exchanges is not None else [_exchange_429("a" * 64)],
    }
    return LoadedTape(TapeDocument.model_validate(document))


def _exchange_429(fingerprint: str, model: str = CANDIDATE_MODEL) -> dict[str, object]:
    import base64

    body = json.dumps(
        {
            "detail": {
                "code": "rate_limited",
                "message": "The upstream provider is rate limiting requests.",
            }
        }
    ).encode()
    return {
        "normalized": {"provider": "openrouter", "model": model, "fingerprint": fingerprint},
        "request": {
            "method": "POST",
            "path": "/v1/chat/completions",
            "body": {"model": model, "messages": []},
        },
        "response": {
            "status": 429,
            "media_type": "application/json",
            "body_b64": base64.b64encode(body).decode(),
        },
    }


# ---- FakeGateway contract (default lane: pure code + a loopback thread) ----
def test_a_failure_tape_must_declare_itself_authored() -> None:
    # WHY: the one lie this harness must make impossible is a synthetic fixture
    # presented as a real recording. The FakeGateway is a rehearsal instrument, so it
    # refuses any tape that claims to be recorded — real recordings replay through the
    # cache-seeded gateway, never through the stand-in.
    with pytest.raises(ValueError, match="authored"):
        FakeGateway(_authored_tape(authored=False))


def test_one_model_cannot_have_two_answers_on_one_tape() -> None:
    # WHY: the fake matches an incoming call by its MODEL (an authored tape cannot
    # pre-compute the gateway fingerprint of a body the engine will compose), so two
    # exchanges for one model would let row order decide which failure injects.
    # Ambiguity fails at construction, mirroring the tape's duplicate-identity rule.
    with pytest.raises(ValueError, match="model"):
        FakeGateway(_authored_tape(exchanges=[_exchange_429("a" * 64), _exchange_429("c" * 64)]))


def test_the_fake_serves_exactly_the_recorded_status_and_bytes() -> None:
    # WHY raw bytes: the tape contract (OME-951 invariant 4) — the stand-in must not
    # launder the authored provider payload through a decode/re-encode round trip.
    tape = _authored_tape()
    gateway = FakeGateway(tape)
    base_url = gateway.start_sync()
    try:
        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            json={"model": CANDIDATE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            timeout=10.0,
        )
    finally:
        gateway.stop_sync()

    (exchange,) = tape.exchanges()
    assert response.status_code == 429
    assert response.content == exchange.response.body
    assert response.headers["content-type"] == "application/json"
    assert gateway.refusals == ()


def test_a_request_off_the_tape_fails_loudly_with_no_default_response() -> None:
    # INVARIANT (parent R7): the FakeGateway is failure-injection ONLY — it never
    # invents an answer for a call its tape does not hold. An unmatched model gets a
    # loud named error (the stand-in's analogue of the cache-seeded 404 miss) and the
    # refusal is recorded so a test can prove the rehearsal stayed on-script.
    gateway = FakeGateway(_authored_tape())
    base_url = gateway.start_sync()
    try:
        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "openrouter/never/taped", "messages": []},
            timeout=10.0,
        )
    finally:
        gateway.stop_sync()

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "fake_gateway_unmatched_request"
    (refusal,) = gateway.refusals
    assert refusal.reason == "unmatched_model"
    assert refusal.model == "openrouter/never/taped"


def test_only_the_taped_surface_answers() -> None:
    # WHY: the stand-in serves ONLY what its tape holds — the chat-completions surface,
    # a health probe, and a catalogue that PROJECTS the tape's models (run planning
    # reads it through the engine before any model call; a projection of the tape is
    # still the tape). Any other route is refused with its own named code, so a test
    # can tell "the engine asked something off-script" from "the tape missed".
    gateway = FakeGateway(_authored_tape())
    base_url = gateway.start_sync()
    try:
        health = httpx.get(f"{base_url}/healthz", timeout=10.0)
        catalog = httpx.get(f"{base_url}/v1/models", timeout=10.0)
        admin = httpx.get(f"{base_url}/v1/admin/cache/info", timeout=10.0)
    finally:
        gateway.stop_sync()

    assert health.status_code == 200
    assert catalog.status_code == 200
    # The projection mirrors the gateway's locked /v1/models row shape (id + owned_by
    # are what the SDK's run planning requires), derived from the tape's identities.
    (row,) = catalog.json()["data"]
    assert row["id"] == CANDIDATE_MODEL
    assert row["owned_by"] == "openrouter"  # from the tape's normalized.provider
    assert row["object"] == "model"
    assert row["unsupported_parameter_behavior"] == "reject"
    assert admin.status_code == 404
    assert admin.json()["detail"]["code"] == "fake_gateway_unroutable"
    (refusal,) = gateway.refusals
    assert refusal.reason == "unroutable"


def test_a_refused_post_closes_the_connection_instead_of_garbling_the_next_request() -> None:
    # WHY: the unroutable branch refuses BEFORE reading the request body, so on a
    # kept-alive connection the unread bytes would be parsed as the next request's
    # start-line — garbling an on-script call and masking the real refusal. The fake
    # therefore closes the connection on every refusal; a follow-up request on a
    # fresh connection must still be served cleanly from the tape.
    gateway = FakeGateway(_authored_tape())
    base_url = gateway.start_sync()
    try:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            refused = client.post("/v1/not/a/route", json={"padding": "x" * 4096})
            followup = client.post(
                "/v1/chat/completions",
                json={"model": CANDIDATE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            )
    finally:
        gateway.stop_sync()

    assert refused.status_code == 404
    assert refused.headers.get("connection") == "close"
    assert followup.status_code == 429, followup.text  # served from the tape, ungarbled
    (refusal,) = gateway.refusals
    assert refusal.reason == "unroutable"


def test_the_fake_binds_loopback_only_and_stop_is_idempotent() -> None:
    # WHY loopback: zero network egress by construction — the stand-in binds
    # 127.0.0.1 and holds no HTTP client at all, so it cannot spend even in a shell
    # with real provider keys exported (the clean-environment rule's sibling).
    gateway = FakeGateway(_authored_tape())
    base_url = gateway.start_sync()
    assert base_url.startswith("http://127.0.0.1:")
    gateway.stop_sync()
    gateway.stop_sync()  # must be safe to call twice (ReplayBackend contract)


# ---- Authored failure fixtures (default lane: validation on read) ----
def test_every_rehearsed_scenario_has_an_authored_tape() -> None:
    # WHY authored=True is asserted per file: provenance is the R11 staleness surface —
    # a failure fixture must say out loud it is synthetic, or it could be mistaken for
    # a recording of a real provider incident.
    for scenario, path in SCENARIO_TAPES.items():
        assert path.is_file(), f"missing authored failure tape for scenario {scenario}: {path}"
        tape = load_tape(path)
        assert tape.provenance.authored is True, f"{scenario} must declare authored=True"
        assert tape.exchanges(), f"{scenario} tape holds no exchanges"


def test_the_provider_error_tapes_carry_the_gateway_authored_detail_envelope() -> None:
    # WHY this exact shape: the engine reads a non-2xx body's `detail.code`/`.message`
    # (runner/connector.py::_raise_for_status), and the real gateway authors provider
    # errors as {"detail": {"code", "message"}} with these exact codes
    # (aigateway routes/chat_dispatch.py::_litellm_http_exception). The tape must hold
    # what the engine can actually receive, not an invented error dialect.
    expectations = {
        "rate_limit_429": (429, "rate_limited"),
        "provider_5xx": (503, "provider_unavailable"),
    }
    for scenario, (status, code) in expectations.items():
        (exchange,) = load_tape(SCENARIO_TAPES[scenario]).exchanges()
        assert exchange.response.status == status
        assert json.loads(exchange.response.body)["detail"]["code"] == code
        assert exchange.normalized.model == CANDIDATE_MODEL


def test_the_malformed_tape_body_is_not_json_at_all() -> None:
    # The scenario rehearses a fronting proxy answering 200 with an HTML page — the
    # exact case runner/connector.py::_json_or_raise names.
    (exchange,) = load_tape(SCENARIO_TAPES["malformed_body"]).exchanges()
    assert exchange.response.status == 200
    with pytest.raises(ValueError):
        json.loads(exchange.response.body)


def test_the_blank_completion_tape_is_a_token_exhausted_empty_turn() -> None:
    # finish_reason=length + blank text is the one blank-completion shape the engine
    # classifies specially (model_token_cap, runner/model_response.py) instead of
    # blaming the gateway.
    (exchange,) = load_tape(SCENARIO_TAPES["blank_completion"]).exchanges()
    choice = json.loads(exchange.response.body)["choices"][0]
    assert choice["finish_reason"] == "length"
    assert not choice["message"]["content"].strip()


def test_the_judge_cutoff_tape_pairs_a_good_candidate_with_a_truncated_judge() -> None:
    # "Cut off mid-batch" as the engine can actually receive it: the judge ANSWERS
    # (HTTP 200) but its verdict JSON is truncated by the token budget
    # (finish_reason=length, non-empty body), so no valid verdict can be bound.
    tape = load_tape(SCENARIO_TAPES["judge_cutoff"])
    by_model = {exchange.normalized.model: exchange for exchange in tape.exchanges()}
    assert set(by_model) == {CANDIDATE_MODEL, JUDGE_MODEL}

    candidate_choice = json.loads(by_model[CANDIDATE_MODEL].response.body)["choices"][0]
    assert candidate_choice["finish_reason"] == "stop"
    assert candidate_choice["message"]["content"].strip()

    judge_choice = json.loads(by_model[JUDGE_MODEL].response.body)["choices"][0]
    assert judge_choice["finish_reason"] == "length"
    judge_text = judge_choice["message"]["content"]
    assert judge_text.strip(), "a blank judge turn would land as model_token_cap instead"
    with pytest.raises(ValueError):
        json.loads(judge_text)


def test_the_judge_token_cap_tape_pairs_a_good_candidate_with_a_blank_length_turn() -> None:
    # The GH #740 shape: the judge (a reasoning model) burns its whole budget
    # thinking — finish_reason=length with NO text — which the engine classifies as
    # model_token_cap (runner/model_response.py), a judge-side, non-retryable failure.
    tape = load_tape(SCENARIO_TAPES["judge_token_cap"])
    by_model = {exchange.normalized.model: exchange for exchange in tape.exchanges()}
    assert set(by_model) == {CANDIDATE_MODEL, JUDGE_MODEL}

    candidate_choice = json.loads(by_model[CANDIDATE_MODEL].response.body)["choices"][0]
    assert candidate_choice["finish_reason"] == "stop"
    assert candidate_choice["message"]["content"].strip()

    judge_choice = json.loads(by_model[JUDGE_MODEL].response.body)["choices"][0]
    assert judge_choice["finish_reason"] == "length"
    assert not judge_choice["message"]["content"].strip()


def test_the_judge_429_tape_rate_limits_only_the_judge() -> None:
    # Same gateway-authored detail envelope as the candidate 429 scenario, but on the
    # JUDGE model — the failure must land at stage grading, never on the candidate.
    tape = load_tape(SCENARIO_TAPES["judge_429"])
    by_model = {exchange.normalized.model: exchange for exchange in tape.exchanges()}
    assert set(by_model) == {CANDIDATE_MODEL, JUDGE_MODEL}
    assert by_model[CANDIDATE_MODEL].response.status == 200
    judge = by_model[JUDGE_MODEL].response
    assert judge.status == 429
    assert json.loads(judge.body)["detail"]["code"] == "rate_limited"


# ---- End-to-end scenarios (e2e lane: real engine + SDK vs the FakeGateway) ----
@dataclass(frozen=True, slots=True)
class _FailureStack:
    """One booted rehearsal stage: swap the cassette, run a scenario, read the report."""

    fake: FakeGateway
    engine_url: str


def _assets_root() -> Path:
    return Path(os.environ.get(_ASSETS_ENV, str(_DEFAULT_ASSETS_ROOT)))


@pytest.fixture(scope="module")
def failure_stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_FailureStack]:
    """Boot ONCE per module: FakeGateway + real engine, reused by every scenario.

    The gateway seam is stateless between runs — each ``evaluate`` is a fresh engine
    run, and the fake holds nothing per-run except its refusal record (cleared by
    ``swap``) — so swapping the cassette between tests cannot leak one scenario into
    the next, and the slow part (the engine subprocess boot) is paid exactly once.
    """
    require_e2e_stack()
    assets = _assets_root()
    if not (assets / "draco").is_dir():
        pytest.skip(
            f"the failure rehearsal drives the {BOARD} board and needs prepared draco "
            f"assets at {assets / 'draco'} "
            f"(run `screamingface prepare draco` and set {_ASSETS_ENV})"
        )
    fake = FakeGateway(load_tape(SCENARIO_TAPES["rate_limit_429"]))
    engine = EngineProcess(work_dir=tmp_path_factory.mktemp("failure-stack"), assets_dir=assets)
    base_url = fake.start_sync()
    try:
        engine_url = engine.start(base_url)
        yield _FailureStack(fake=fake, engine_url=engine_url)
    finally:
        engine.stop()
        fake.stop_sync()


def _rehearse(stack: _FailureStack, scenario: str, *, tolerate_aborted: bool = False):
    """Play one authored failure tape through a real one-case board run.

    Returns the single CaseResult of the single candidate — the surface where the
    board's declared failure policy must land.

    ``tolerate_aborted`` (OME-993): when one judge pass fails permanently, url4's
    TaskGroup CANCELS the sibling passes mid-request — the fake then reads a half
    body and records a refusal with ``model=None`` before the broken pipe. Those are
    cancellation artifacts, not improvisation; a genuinely untaped model always
    arrives with its model string, so only ``model=None`` rows are tolerated.
    """
    import screamingface as sf

    stack.fake.swap(load_tape(SCENARIO_TAPES[scenario]))
    with sf.Client(engine_url=stack.engine_url) as client:
        report = client.evaluate(
            sf.Model(CANDIDATE_MODEL), benchmark=BOARD, limit=1, progress=False
        )
    # The rehearsal must have stayed on-script: EVERY request the engine made was
    # answered from the taped surface — no untaped model call (improvisation) and no
    # off-surface route either (an engine quietly running degraded against 404'd
    # discovery routes would rehearse a stack that does not exist).
    refusals = stack.fake.refusals
    if tolerate_aborted:
        refusals = tuple(r for r in refusals if r.model is not None)
    assert not refusals, f"the engine made requests the taped surface does not hold: {refusals}"
    candidate = report.candidates.only
    (case,) = candidate.cases
    return case


@pytest.mark.e2e
def test_a_provider_429_lands_as_a_candidate_provider_failure_never_malformed(
    failure_stack: _FailureStack,
) -> None:
    # THE R7 invariant: a rate-limited provider surfaces as a candidate-stage provider
    # failure whose message carries the gateway's own rate-limit wording — never as a
    # "malformed response", which would send an operator debugging the wrong component.
    case = _rehearse(failure_stack, "rate_limit_429")

    assert str(case.status) == "failed"
    (failure,) = case.failures
    assert failure.stage == "candidate"
    assert "rate limiting" in failure.message
    assert "malformed" not in failure.message.lower()
    # OME-924: the collect row keeps the connector's code/retryable, so the Failure
    # carries the upstream rate-limit code instead of the DRACO default.
    assert failure.code == "rate_limited"
    assert failure.retryable is True


@pytest.mark.e2e
def test_a_provider_5xx_lands_as_a_candidate_provider_failure(
    failure_stack: _FailureStack,
) -> None:
    # Same landing as the 429 (both are the connector's transient class): stage
    # candidate, message = the gateway-authored provider-unavailable wording.
    case = _rehearse(failure_stack, "provider_5xx")

    assert str(case.status) == "failed"
    (failure,) = case.failures
    assert failure.stage == "candidate"
    assert "temporarily unavailable" in failure.message
    assert "malformed" not in failure.message.lower()


@pytest.mark.e2e
def test_a_malformed_gateway_body_lands_as_a_candidate_gateway_fault(
    failure_stack: _FailureStack,
) -> None:
    # A 200 whose body is not JSON at all (an intercepting proxy's HTML page) is the
    # one failure that SHOULD say "non-JSON"/gateway fault — and must not claim the
    # provider rate-limited or refused anything.
    case = _rehearse(failure_stack, "malformed_body")

    assert str(case.status) == "failed"
    (failure,) = case.failures
    assert failure.stage == "candidate"
    assert "non-JSON" in failure.message
    assert "rate limiting" not in failure.message


@pytest.mark.e2e
def test_a_blank_completion_lands_as_a_token_cap_failure_not_a_gateway_fault(
    failure_stack: _FailureStack,
) -> None:
    # INVARIANT (model_response.py): an all-reasoning `length` turn with blank text is
    # the MODEL running out of budget — labeling it a gateway fault ("malformed") sends
    # the reader debugging the wrong component, so the policy names the token cap.
    case = _rehearse(failure_stack, "blank_completion")

    assert str(case.status) == "failed"
    (failure,) = case.failures
    assert failure.stage == "candidate"
    assert "ran out of tokens" in failure.message
    assert "malformed" not in failure.message.lower()


@pytest.mark.e2e
def test_a_judge_cut_off_mid_batch_lands_as_grading_never_candidate(
    failure_stack: _FailureStack,
) -> None:
    # THE grading-half invariant: when the candidate answered and only the JUDGE was
    # cut off, the failure must land at stage="grading" with the candidate's output
    # preserved on the case — a judge fault must never masquerade as a candidate fault
    # (that would charge the evaluated model for the evaluator's failure).
    case = _rehearse(failure_stack, "judge_cutoff")

    assert str(case.status) == "failed"
    assert case.output, "the candidate's completed answer must be preserved"
    assert case.failures, "the cut-off judge must be reported, not silently ungraded"
    assert all(failure.stage == "grading" for failure in case.failures)
    assert any(failure.code == "no_valid_judge_verdict" for failure in case.failures)


@pytest.mark.e2e
def test_a_token_capped_judge_lands_as_a_named_grading_failure_never_an_envelope_error(
    failure_stack: _FailureStack,
) -> None:
    # THE OME-993 regression pin (GH #740): a judge that burned its budget thinking
    # used to surface as "invalid Criterion envelope" — the collected error row's
    # shape, not its cause. The failure must now land at stage="grading" carrying the
    # ORIGINAL model_token_cap cause, with the candidate's answer preserved.
    case = _rehearse(failure_stack, "judge_token_cap", tolerate_aborted=True)

    assert str(case.status) == "failed"
    assert case.output, "the candidate's completed answer must be preserved"
    (failure,) = case.failures
    assert failure.stage == "grading"
    assert failure.code == "model_token_cap"
    assert "ran out of tokens" in failure.message
    assert failure.retryable is False
    assert "envelope" not in failure.message.lower()


@pytest.mark.e2e
def test_a_rate_limited_judge_lands_as_a_retryable_grading_failure(
    failure_stack: _FailureStack,
) -> None:
    # The other GH #740 trigger: a judge-side 429 must propagate the gateway-authored
    # cause and stay retryable — after the bounded in-run retries (;retry=2 on every
    # verdict source) are exhausted against the still-rate-limiting fake.
    case = _rehearse(failure_stack, "judge_429", tolerate_aborted=True)

    assert str(case.status) == "failed"
    assert case.output, "the candidate's completed answer must be preserved"
    (failure,) = case.failures
    assert failure.stage == "grading"
    assert failure.code == "rate_limited"
    assert "rate limiting" in failure.message
    assert failure.retryable is True
    assert "envelope" not in failure.message.lower()
