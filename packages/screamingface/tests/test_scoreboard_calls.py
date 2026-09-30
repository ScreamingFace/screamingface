"""One Scoreboard call as data: its builder, its re-send rule and `settle` (E14 simplify).

FEATURE: `_scoreboard/calls.py` and the call builders of `_scoreboard/leaderboards.py`. The sync
and async `Leaderboards` twins share these, so the rules are pinned here once, without a transport.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from test_submit_cache_version import TRACE_ID, _candidate, _score_response

import screamingface as sf
from screamingface._core.attempts import _Again, _Attempt, _Done
from screamingface._core.ports import _FreezeUnavailable, _FrozenCacheVersion
from screamingface._scoreboard import leaderboards
from screamingface._scoreboard.calls import _NO_RESEND, _Resend, _ScoreboardCall, settle
from screamingface._scoreboard.leaderboards import (
    UNSET,
    _leaderboard_call,
    _list_call,
    _metadata_edit_call,
    _PendingFreeze,
    _publish_call,
    _ReceiptCache,
    _replay_failure,
    _replay_grant_call,
    _score_call,
    _SubmitDraft,
)
from screamingface._scoreboard.replay_pin import _ReplayPin

URL = "https://scoreboard.example"
SCORE_UUID = UUID("0b4a5ff8-5a1e-4f1d-9f3a-6a3f0b5a9c11")
RESULT_UUID = UUID("3f0c5d0e-6f0b-4d75-a1f1-0c6f0b7d2a10")
ERROR = sf.LeaderboardError("x")


def _always(_outcome: _Attempt, _error: sf.LeaderboardError) -> bool:
    return True


def _never(_outcome: _Attempt, _error: sf.LeaderboardError) -> bool:
    return False


def _transport_failed(outcome: _Attempt, _error: sf.LeaderboardError) -> bool:
    return isinstance(outcome, httpx.TransportError)


def _call(**changes: Any) -> _ScoreboardCall[tuple[object, str]]:
    fields: dict[str, Any] = {
        "method": "GET",
        "path": "/v1/x",
        "replay_safe": True,
        "decode": lambda payload, url: (payload, url),
    }
    return _ScoreboardCall(**{**fields, **changes})


def _raised(call: _ScoreboardCall[Any], outcome: _Attempt, attempt: int = 0) -> sf.LeaderboardError:
    with pytest.raises(sf.LeaderboardError) as caught:
        settle(call, URL, attempt, outcome)
    return caught.value


# --- _Resend.next_step -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("resend", "attempt", "expected"),
    [
        (_Resend(), 0, None),
        (_Resend(limit=1, when=_never), 0, None),
        (_Resend(limit=1, when=_always), 0, _Again(None)),
        (_Resend(limit=1, when=_always), 1, None),
        (_Resend(limit=2, when=_always), 1, _Again(None)),
        (_Resend(limit=2, when=_always), 2, None),
        (_Resend(limit=2, when=_always, backoff=lambda n: n * 10.0), 0, _Again(10.0)),
        (_Resend(limit=2, when=_always, backoff=lambda n: n * 10.0), 1, _Again(20.0)),
        (_Resend(limit=2, when=_always, backoff=lambda n: n * 10.0), 2, None),
        (_Resend(limit=2, when=_never, backoff=lambda n: n * 10.0), 0, None),
    ],
)
def test_resend_next_step_truth_table(
    resend: _Resend, attempt: int, expected: _Again | None
) -> None:
    assert resend.next_step(attempt, httpx.Response(500), ERROR) == expected


def test_the_default_resend_never_resends() -> None:
    assert _NO_RESEND == _Resend(0)
    assert _NO_RESEND.next_step(0, httpx.ConnectError("x"), ERROR) is None


def test_a_resend_when_gets_the_outcome_and_the_error() -> None:
    seen: list[tuple[_Attempt, sf.LeaderboardError]] = []

    def when(outcome: _Attempt, error: sf.LeaderboardError) -> bool:
        seen.append((outcome, error))
        return False

    outcome = httpx.Response(503)
    _Resend(limit=1, when=when).next_step(0, outcome, ERROR)

    assert seen == [(outcome, ERROR)]


# --- settle ------------------------------------------------------------------------------------


def test_settle_a_2xx_is_done_with_the_decoded_body() -> None:
    step = settle(_call(), URL, 0, httpx.Response(200, json={"a": 1}))

    assert step == _Done(({"a": 1}, URL))


def test_settle_a_2xx_that_is_not_json_is_an_invalid_response_and_is_not_sent_again() -> None:
    call = _call(resend=_Resend(limit=1, when=_transport_failed))

    error = _raised(call, httpx.Response(200, content=b"not json"))

    assert error.code == "invalid_leaderboard"


def test_settle_runs_the_decoder_outside_the_resend_decision() -> None:
    def decode(_payload: object, _url: str) -> object:
        raise sf.LeaderboardError("bad body", code="invalid_leaderboard")

    call = _call(decode=decode, resend=_Resend(limit=2, when=_always))

    assert _raised(call, httpx.Response(200, json={})).code == "invalid_leaderboard"


def test_settle_a_404_with_missing_gives_the_typed_not_found() -> None:
    call = _call(missing=("unknown_score", "Score 'x' was not found"))

    error = _raised(call, httpx.Response(404))

    assert (error.code, error.status, error.permanent) == ("unknown_score", 404, True)
    assert "Score 'x' was not found" in str(error)


def test_settle_a_404_without_missing_is_a_contract_error() -> None:
    error = _raised(_call(), httpx.Response(404))

    assert (error.code, error.status) == ("scoreboard_contract_error", 404)
    assert "Could not load the Scoreboard: HTTP 404" in str(error)


def test_settle_a_coded_call_takes_the_body_code_first_then_the_status_map() -> None:
    call = _call(codes={403: "forbidden_by_map"}, operation="do a thing on")
    coded = httpx.Response(403, json={"detail": {"code": "from_body"}})
    plain = httpx.Response(403, json={"detail": "nope"})
    unlisted = httpx.Response(418)

    assert _raised(call, coded).code == "from_body"
    assert _raised(call, plain).code == "forbidden_by_map"
    assert _raised(call, unlisted).code == "scoreboard_contract_error"


def test_settle_an_uncoded_call_ignores_a_body_code() -> None:
    coded = httpx.Response(403, json={"detail": {"code": "from_body"}})

    assert _raised(_call(), coded).code == "scoreboard_contract_error"


def test_settle_a_4xx_is_permanent_and_a_5xx_or_429_is_not() -> None:
    call = _call(codes={400: "bad", 429: "slow", 500: "broke"})

    assert _raised(call, httpx.Response(400)).permanent is True
    assert _raised(call, httpx.Response(429)).permanent is False
    assert _raised(call, httpx.Response(500)).permanent is False


def test_settle_an_uncoded_409_with_the_flag_is_transient_and_gives_the_retry_hint() -> None:
    call = _call(codes={409: "conflict"}, retry_uncoded_409=True)

    error = _raised(call, httpx.Response(409, json={"detail": "race"}))

    assert (error.code, error.permanent, error.hint) == ("conflict", False, "Retry the submission.")


def test_settle_an_uncoded_409_without_the_flag_is_permanent_with_no_hint() -> None:
    call = _call(codes={409: "conflict"})

    error = _raised(call, httpx.Response(409, json={"detail": "race"}))

    assert (error.permanent, error.hint) == (True, None)


def test_settle_a_coded_409_with_the_flag_is_a_fixed_fact() -> None:
    call = _call(codes={409: "conflict"}, retry_uncoded_409=True)

    error = _raised(call, httpx.Response(409, json={"detail": {"code": "system_name_taken"}}))

    assert (error.code, error.permanent, error.hint) == ("system_name_taken", True, None)


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), httpx.DecodingError("bad gzip")],
)
def test_settle_an_httpx_error_is_unreachable_with_the_error_as_its_cause(
    failure: httpx.HTTPError,
) -> None:
    error = _raised(_call(), failure)

    assert (error.code, error.permanent, error.status) == ("scoreboard_unreachable", False, None)
    assert error.__cause__ is failure


def test_settle_a_resend_wins_over_the_error_while_it_has_attempts_left() -> None:
    call = _call(resend=_Resend(limit=1, when=_always))
    failure = httpx.ConnectError("down")

    assert settle(call, URL, 0, failure) == _Again(None)
    assert _raised(call, failure, attempt=1).code == "scoreboard_unreachable"


def test_settle_a_response_the_resend_refuses_raises_its_error() -> None:
    call = _call(resend=_Resend(limit=1, when=_never))

    assert _raised(call, httpx.Response(503)).status == 503


def test_settle_on_failure_maps_an_unreachable_board_and_a_5xx_with_the_cause() -> None:
    call = _call(on_failure=_replay_failure)

    for outcome in (httpx.ConnectError("down"), httpx.Response(503)):
        with pytest.raises(sf.ReplayUnavailable) as caught:
            settle(call, URL, 0, outcome)
        assert isinstance(caught.value.__cause__, sf.LeaderboardError)
        assert caught.value.scoreboard_url == URL


def test_settle_on_failure_leaves_a_verdict_alone() -> None:
    call = _call(on_failure=_replay_failure, codes={404: "replay_pin_not_found"})

    error = _raised(call, httpx.Response(404))

    assert type(error) is sf.LeaderboardError
    assert error.code == "replay_pin_not_found"


def test_settle_on_failure_that_gives_none_keeps_the_error() -> None:
    call = _call(on_failure=lambda _url, _error: None)

    assert _raised(call, httpx.Response(503)).status == 503


def test_settle_on_failure_raises_what_the_handler_gives_with_the_error_as_cause() -> None:
    mapped = RuntimeError("mapped")
    call = _call(on_failure=lambda _url, _error: mapped)

    with pytest.raises(RuntimeError) as caught:
        settle(call, URL, 0, httpx.Response(400))

    assert caught.value is mapped
    assert isinstance(caught.value.__cause__, sf.LeaderboardError)


def test_one_patch_point_decides_down_for_the_replay_handler_and_the_submit_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resend = _draft().call(_frozen()).resend
    verdict = sf.LeaderboardError("x", status=404)
    assert _replay_failure(URL, verdict) is None
    assert resend.when(httpx.Response(404), verdict) is False

    monkeypatch.setattr(leaderboards, "_scoreboard_down", lambda _error: True)

    assert isinstance(_replay_failure(URL, verdict), sf.ReplayUnavailable)
    assert resend.when(httpx.Response(404), verdict) is True


def test_settle_a_resend_runs_before_on_failure() -> None:
    call = _call(on_failure=_replay_failure, resend=_Resend(limit=1, when=_always))

    assert settle(call, URL, 0, httpx.ConnectError("down")) == _Again(None)


# --- _ScoreboardCall.send ----------------------------------------------------------------------


def _recording() -> tuple[list[tuple[tuple[object, ...], dict[str, object]]], Callable[..., str]]:
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def request(*args: object, **kwargs: object) -> str:
        seen.append((args, kwargs))
        return "sent"

    return seen, request


def test_send_passes_the_whole_call_shape_and_a_timeout_only_when_set() -> None:
    seen, request = _recording()

    assert _call(params={"top": 3}, json={"a": 1}, headers={"H": "v"}).send(request) == "sent"
    assert _call(timeout=15.0).send(request) == "sent"

    assert seen[0] == (
        ("GET", "/v1/x"),
        {"params": {"top": 3}, "json": {"a": 1}, "headers": {"H": "v"}, "replay_safe": True},
    )
    assert seen[1][1] == {
        "params": None,
        "json": None,
        "headers": None,
        "replay_safe": True,
        "timeout": 15.0,
    }


def test_a_call_cannot_be_built_without_saying_whether_it_is_replay_safe() -> None:
    with pytest.raises(TypeError):
        _ScoreboardCall("GET", "/v1/x", decode=lambda payload, url: payload)  # type: ignore[call-arg]


# --- builders ----------------------------------------------------------------------------------


def test_list_call() -> None:
    call = _list_call()

    assert (call.method, call.path, call.replay_safe) == ("GET", "/v1/benchmarks", True)
    assert (call.timeout, call.json, call.headers, call.params, call.missing) == (None,) * 5
    assert (call.operation, dict(call.codes), call.resend, call.on_failure) == (
        "load",
        {},
        _NO_RESEND,
        None,
    )


def test_leaderboard_call_quotes_the_id_and_names_the_missing_board() -> None:
    call = _leaderboard_call("/draco v2", 7)

    assert (call.method, call.path, call.replay_safe) == ("GET", "/v1/leaderboard/draco%20v2", True)
    assert call.params == {"top": 7}
    assert call.missing == ("unknown_leaderboard", "Leaderboard 'draco v2' is not registered")
    assert (call.timeout, dict(call.codes), call.resend) == (None, {}, _NO_RESEND)


def test_leaderboard_call_checks_the_id_before_top() -> None:
    with pytest.raises(TypeError, match="benchmark_id must be a string"):
        _leaderboard_call(7, 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="top must be positive"):
        _leaderboard_call("draco", 0)


def test_score_call() -> None:
    call = _score_call(str(SCORE_UUID))

    assert (call.method, call.path, call.replay_safe) == ("GET", f"/v1/scores/{SCORE_UUID}", True)
    assert call.missing == ("unknown_score", f"Score {str(SCORE_UUID)!r} was not found")
    assert (call.timeout, dict(call.codes), call.resend, call.json) == (None, {}, _NO_RESEND, None)
    with pytest.raises(ValueError, match="score_id must be a valid UUID"):
        _score_call("nope")


def test_metadata_edit_call() -> None:
    call = _metadata_edit_call(SCORE_UUID, 3, ["a@b.co"], None)

    assert (call.method, call.path, call.replay_safe) == (
        "PATCH",
        f"/v1/scores/{SCORE_UUID}",
        True,
    )
    assert call.json == {"authors": ["a@b.co"], "paper_url": None}
    assert call.headers == {"If-Match": '"3"'}
    assert call.timeout == 15.0
    assert call.operation == "edit the submission metadata on"
    assert call.codes[412] == "metadata_revision_conflict"
    assert call.missing == ("unknown_score", f"Score {str(SCORE_UUID)!r} was not found")
    assert call.on_failure is None


def test_metadata_edit_call_resends_once_at_once_and_only_after_a_transport_error() -> None:
    resend = _metadata_edit_call(SCORE_UUID, 1, UNSET, None).resend

    assert (resend.limit, resend.backoff) == (1, None)
    assert resend.when(httpx.ConnectError("x"), ERROR) is True
    assert resend.when(httpx.ReadTimeout("x"), ERROR) is True
    assert resend.when(httpx.DecodingError("x"), ERROR) is False
    assert resend.when(httpx.Response(503), ERROR) is False


def test_metadata_edit_call_checks_score_then_revision_then_body() -> None:
    with pytest.raises(ValueError, match="score_id must be a valid UUID"):
        _metadata_edit_call("nope", 0, UNSET, UNSET)
    with pytest.raises(ValueError, match="expected_revision must be positive"):
        _metadata_edit_call(SCORE_UUID, 0, UNSET, UNSET)
    with pytest.raises(ValueError, match="update_submission needs authors or paper_url"):
        _metadata_edit_call(SCORE_UUID, 1, UNSET, UNSET)


def test_replay_grant_call() -> None:
    pin = _ReplayPin("kevins-best", "name")

    call = _replay_grant_call(pin, "draco")

    assert (call.method, call.path, call.replay_safe) == ("POST", "/v1/replay-grants", True)
    assert call.json == {"pin": "kevins-best", "benchmark_id": "draco"}
    assert call.timeout == 10.0
    assert call.operation == "request a replay grant from"
    assert dict(call.codes) == {
        404: "replay_pin_not_found",
        410: "cache_version_withdrawn",
        422: "invalid_replay_pin",
    }
    assert call.resend == _NO_RESEND
    assert call.on_failure is _replay_failure
    assert (call.headers, call.missing) == (None, None)


def test_replay_grant_call_decodes_the_binding_with_the_pin() -> None:
    call = _replay_grant_call(_ReplayPin("score:x", "score"), "draco")
    body = {
        "grant": " opaque ",
        "result_id": str(RESULT_UUID),
        "score_id": str(SCORE_UUID),
        "cache_version_id": str(SCORE_UUID),
        "expires_at": "2026-10-01T00:00:00Z",
    }

    binding = call.decode(body, URL)

    assert (binding.grant, binding.result_id, binding.pinned_baseline_result_id) == (
        "opaque",
        RESULT_UUID,
        None,
    )


def test_publish_call() -> None:
    call = _publish_call(str(RESULT_UUID))

    assert (call.method, call.path, call.replay_safe) == (
        "POST",
        f"/v1/results/{RESULT_UUID}/publish",
        True,
    )
    assert call.operation == "publish the cache version on"
    assert dict(call.codes) == {
        403: "not_result_owner",
        409: "not_publishable",
        503: "publish_unavailable",
    }
    assert call.missing == ("unknown_result", f"Result {str(RESULT_UUID)!r} was not found")
    assert (call.timeout, call.json, call.resend, call.on_failure) == (None, None, _NO_RESEND, None)
    publication = call.decode({"state": "requested"}, URL)
    assert (publication.result_id, publication.state) == (RESULT_UUID, "requested")
    with pytest.raises(ValueError, match="result_id must be a valid UUID"):
        _publish_call("nope")


# --- the submit draft --------------------------------------------------------------------------


def _frozen() -> _FrozenCacheVersion:
    return _FrozenCacheVersion(
        receipt="jws",
        cache_version_id=SCORE_UUID,
        entry_count=1,
        call_count=1,
        missing_count=0,
        coverage_status="complete",
        archive_sha256="a" * 64,
    )


def _draft() -> _SubmitDraft:
    return _SubmitDraft.of(_candidate(), authors=None, paper_url=None, revision_of=None)


def test_submit_draft_checks_the_input_before_anything_else() -> None:
    with pytest.raises(TypeError, match="candidate_result must be an sf.CandidateResult"):
        _SubmitDraft.of("nope", authors=None, paper_url=None, revision_of=None)  # type: ignore[arg-type]


def test_submit_call_with_a_receipt() -> None:
    draft = _draft()

    call = draft.call(_frozen())

    assert (call.method, call.path, call.replay_safe) == ("POST", "/v1/scores", True)
    assert call.headers == {"Idempotency-Key": draft.candidate_result.run_id}
    assert call.timeout == 30.0
    assert call.operation == "submit a score to"
    assert call.retry_uncoded_409 is True
    assert call.codes[409] == "score_submission_conflict"
    assert (call.missing, call.on_failure) == (None, None)
    assert call.json is not None
    assert call.json["cache_version_receipt"] == "jws"
    assert call.json["trace_id"] == TRACE_ID


def test_submit_call_copies_the_payload_so_the_draft_stays_receipt_free() -> None:
    draft = _draft()

    draft.call(_frozen())

    assert "cache_version_receipt" not in draft.payload
    assert "trace_id" not in draft.payload


def test_submit_call_without_a_receipt_carries_the_warning_on_the_decoded_score() -> None:
    call = _draft().call(_FreezeUnavailable("no_trace"))

    assert call.json is not None
    assert "cache_version_receipt" not in call.json
    score = call.decode(_score_response(), URL)
    assert score.cache_version_warning == "cache_version_unavailable: no_trace"
    assert score.scoreboard_url == URL


def test_submit_call_with_a_receipt_has_no_warning() -> None:
    score = _draft().call(_frozen()).decode(_score_response(), URL)

    assert score.cache_version_warning is None


def test_submit_resend_is_two_with_backoff_after_an_unreachable_board_or_a_5xx() -> None:
    resend = _draft().call(_frozen()).resend

    assert resend.limit == 2
    down = sf.LeaderboardError("x", code="scoreboard_unreachable")
    assert resend.when(httpx.ConnectError("x"), down) is True
    assert resend.when(httpx.Response(503), sf.LeaderboardError("x", status=503)) is True
    assert resend.when(httpx.Response(400), sf.LeaderboardError("x", status=400)) is False
    assert resend.backoff is not None
    assert 0.5 <= resend.backoff(1) <= 0.625
    assert 1.0 <= resend.backoff(2) <= 1.25


def test_submit_resend_looks_its_rule_and_backoff_up_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resend = _draft().call(_frozen()).resend
    monkeypatch.setattr(leaderboards, "_scoreboard_down", lambda _error: True)
    monkeypatch.setattr(leaderboards, "_submit_backoff", lambda n: n * 100.0)

    assert resend.when(httpx.Response(400), sf.LeaderboardError("x", status=400)) is True
    assert resend.backoff is not None
    assert resend.backoff(2) == 200.0


# --- the receipt cache -------------------------------------------------------------------------


class _Freezer:
    def freeze(self, trace_id: str) -> _FrozenCacheVersion:
        return _frozen()


def test_receipt_cache_without_a_trace_or_a_freezer_is_unavailable_with_a_token() -> None:
    cache = _ReceiptCache()

    assert cache.pending(_candidate(trace_id=None), _Freezer()) == _FreezeUnavailable("no_trace")
    assert cache.pending(_candidate(), None) == _FreezeUnavailable("freeze_unconfigured")
    assert cache.pending(_candidate(trace_id=None), None) == _FreezeUnavailable("no_trace")


def test_receipt_cache_asks_for_a_freeze_until_a_receipt_is_kept() -> None:
    cache = _ReceiptCache()
    freezer = _Freezer()
    candidate = _candidate()

    pending = cache.pending(candidate, freezer)
    assert isinstance(pending, _PendingFreeze)
    assert (pending.key, pending.trace_id, pending.freezer) == (
        (candidate.run_id, TRACE_ID),
        TRACE_ID,
        freezer,
    )
    assert cache.keep(pending.key, _frozen()) == _frozen()
    assert cache.pending(candidate, freezer) == _frozen()


def test_receipt_cache_never_keeps_an_unavailable_outcome() -> None:
    cache = _ReceiptCache()
    candidate = _candidate()
    pending = cache.pending(candidate, _Freezer())
    assert isinstance(pending, _PendingFreeze)

    assert cache.keep(pending.key, _FreezeUnavailable("timeout")) == _FreezeUnavailable("timeout")

    assert isinstance(cache.pending(candidate, _Freezer()), _PendingFreeze)


def test_receipt_cache_is_bounded_and_drops_the_oldest_first() -> None:
    cache = _ReceiptCache()
    candidates = [_candidate(run_id=f"run-{n}") for n in range(33)]
    for candidate in candidates:
        pending = cache.pending(candidate, _Freezer())
        assert isinstance(pending, _PendingFreeze)
        cache.keep(pending.key, _frozen())

    assert isinstance(cache.pending(candidates[0], _Freezer()), _PendingFreeze)
    assert cache.pending(candidates[1], _Freezer()) == _frozen()
    assert cache.pending(candidates[32], _Freezer()) == _frozen()


def test_the_clients_keep_their_cache_under_the_receipts_name() -> None:
    board = leaderboards.Leaderboards(lambda *args, **kwargs: httpx.Response(200), URL)

    assert isinstance(board._receipts, _ReceiptCache)
    assert not isinstance(board._receipts, OrderedDict)
