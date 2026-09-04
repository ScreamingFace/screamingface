from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from url4 import expr, render, src, text

import screamingface as sf
from screamingface import _default_client
from screamingface._access import auth as auth_module
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import _compiled_operation
from screamingface._scoreboard.leaderboards import _submission

SCOREBOARD_URL = "https://scoreboard.example"
CREATED_AT = "2026-08-01T10:00:00Z"
SUBMITTED_AT = "2026-08-08T12:30:00Z"
IMPORTED_AT = "2026-08-07T09:15:00Z"
BASELINE_ID = "02fd61c7-7db8-4dce-92d7-115813e691ed"
SCORE_ID = "af95892d-7438-4ac3-9b47-5e06f62c8251"


def _linked_url4(*, prompt: str | None = None) -> str:
    candidate = compile_candidate(sf.Model("openrouter/model", prompt=prompt)).url4
    assert candidate is not None
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src(
                "/benchmarks/draco/revision-1/cases",
                name="rows",
                weight=0.0,
            ),
            intent=text("$rows"),
        )
    )


def _benchmark() -> dict[str, object]:
    return {
        "id": "draco",
        "display_name": "DRACO",
        "description": "Deep Research AI Comparison",
        "dataset_url": "https://scoreboard.example/draco.jsonl",
        "created_at": CREATED_AT,
    }


def _list_response() -> dict[str, object]:
    return {"benchmarks": [_benchmark()]}


def _get_response() -> dict[str, object]:
    return {
        "benchmark": _benchmark(),
        "entries": [
            {
                "rank": 1,
                "spec_id": "fusion/alpha",
                "score": 0.82,
                "total_questions": 100,
                "ran_with_providers": ["openrouter", "gemini-cli"],
                "submitted_at": SUBMITTED_AT,
                "submitted_by": "researcher@example.com",
                "verified_by_screamingface": True,
                "url4_expression": _linked_url4(),
            }
        ],
        "baselines": [
            {
                "id": BASELINE_ID,
                "benchmark_id": "draco",
                "model_name": "single/model",
                "score": 0.61,
                "source": "published-paper",
                "source_url": "https://example.com/paper",
                "imported_at": IMPORTED_AT,
                "metadata": {"organization": "Example Lab", "tags": ["closed"]},
            }
        ],
    }


def _score_response() -> dict[str, object]:
    return {
        "id": SCORE_ID,
        "version": 1,
        "benchmark_id": "draco",
        "spec_id": "fusion/alpha",
        "url4_expression": _linked_url4(),
        "submitted_by": "researcher@example.com",
        "submitted_at": SUBMITTED_AT,
        "score": 0.5,
        "total_questions": 2,
        "correct_questions": 1,
        "ran_with_providers": ["openrouter", "gemini-cli"],
        "ran_at_local": "2026-08-08T12:00:00Z",
        "client_name": "screamingface",
        "client_version": "0.1.0",
        "client_platform": "darwin",
        "verified_by_screamingface": False,
        "metadata": {
            "benchmark_revision": "fixture-revision",
            "candidate_kind": "fusion",
            "run_id": "run-fusion-alpha",
        },
    }


def _case(case_id: int, score: float | None) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output=f"Answer {case_id}",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=score, metrics={}, checks=()),
        failures=(),
        metadata={},
    )


def _candidate_result(
    *,
    score: float | None = 0.5,
    case_scores: tuple[float | None, ...] = (1.0, 0.0),
) -> sf.CandidateResult:
    return sf.CandidateResult(
        benchmark=sf.BenchmarkInfo(
            id="draco",
            revision="fixture-revision",
            case_count=2,
        ),
        run_id="run-fusion-alpha",
        started_at=datetime(2026, 8, 8, 11, 59, tzinfo=UTC),
        completed_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
        name="fusion/alpha",
        kind="fusion",
        url4="(@)!'fusion alpha'",
        models=("openrouter/model-a", "gemini-cli/model-b"),
        operations=(
            _compiled_operation(id="op-a", kind="model", label="a", depends_on=()),
            _compiled_operation(id="op-b", kind="model", label="b", depends_on=()),
        ),
        score=score,
        coverage=1.0,
        metrics={} if score is None else {"accuracy": score},
        cases=tuple(_case(index, value) for index, value in enumerate(case_scores, start=1)),
        members=(
            sf.MemberResult(
                operation_id="op-a",
                name="a",
                kind="model",
                models=("openrouter/model-a",),
                failures=(),
                duration_ms=1,
                usage=sf.Usage(),
            ),
            sf.MemberResult(
                operation_id="op-b",
                name="b",
                kind="model",
                models=("gemini-cli/model-b",),
                failures=(),
                duration_ms=1,
                usage=sf.Usage(),
            ),
        ),
        failures=(),
        usage=sf.Usage(),
    )


def _sync_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(handler),
    )


def _async_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(handler),
    )


class _TokenAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self.token = token
        self.logout_calls = 0
        self.close_calls = 0

    def auth_flow(self, request: httpx.Request) -> Iterator[httpx.Request]:
        request.headers["Cf-Access-Token"] = self.token
        yield request

    def logout(self) -> None:
        self.logout_calls += 1

    async def logout_async(self) -> None:
        self.logout()

    def close(self) -> None:
        self.close_calls += 1


def test_protected_score_actions_use_scoreboard_origin_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter(("engine-token", "scoreboard-token"))
    monkeypatch.setattr(
        auth_module,
        "_default_caller_auth",
        lambda _origin: _TokenAuth(next(tokens)),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Cf-Access-Token") != "scoreboard-token":
            return httpx.Response(
                302,
                headers={"location": "https://access.example/login?kid=" + "a" * 64},
            )
        assert request.extensions[_REPLAY_SAFE] is True
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json=_score_response(),
        )

    with _sync_client(handler) as client:
        fetched = client.leaderboards.get_score(SCORE_ID)
        submitted = client.leaderboards.submit(_candidate_result())

    assert fetched.id == UUID(SCORE_ID)
    assert submitted.id == UUID(SCORE_ID)


def test_client_owns_scoreboard_authentication_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auths: list[_TokenAuth] = []

    def auth(_origin: str) -> _TokenAuth:
        value = _TokenAuth(f"token-{len(auths)}")
        auths.append(value)
        return value

    monkeypatch.setattr(auth_module, "_default_caller_auth", auth)
    client = _sync_client(lambda _request: httpx.Response(200, json=_score_response()))

    client.logout()
    client.close()

    assert len(auths) == 2
    assert [value.logout_calls for value in auths] == [1, 1]
    assert [value.close_calls for value in auths] == [1, 1]


@pytest.mark.asyncio
async def test_async_protected_score_actions_use_scoreboard_origin_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter(("engine-token", "scoreboard-token"))
    monkeypatch.setattr(
        auth_module,
        "_default_caller_auth",
        lambda _origin: _TokenAuth(next(tokens)),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Cf-Access-Token") != "scoreboard-token":
            return httpx.Response(
                302,
                headers={"location": "https://access.example/login?kid=" + "a" * 64},
            )
        assert request.extensions[_REPLAY_SAFE] is True
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json=_score_response(),
        )

    async with _async_client(handler) as client:
        fetched = await client.leaderboards.get_score(SCORE_ID)
        submitted = await client.leaderboards.submit(_candidate_result())

    assert fetched.id == UUID(SCORE_ID)
    assert submitted.id == UUID(SCORE_ID)


@pytest.mark.asyncio
async def test_async_client_owns_scoreboard_authentication_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auths: list[_TokenAuth] = []

    def auth(_origin: str) -> _TokenAuth:
        value = _TokenAuth(f"token-{len(auths)}")
        auths.append(value)
        return value

    monkeypatch.setattr(auth_module, "_default_caller_auth", auth)
    client = _async_client(lambda _request: httpx.Response(200, json=_score_response()))

    await client.logout()
    await client.aclose()

    assert len(auths) == 2
    assert [value.logout_calls for value in auths] == [1, 1]
    assert [value.close_calls for value in auths] == [1, 1]


def test_client_lists_scoreboard_registered_leaderboards() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_list_response())

    with _sync_client(handler) as client:
        values = client.leaderboards.list()

    assert values == (
        sf.LeaderboardInfo(
            id="draco",
            display_name="DRACO",
            description="Deep Research AI Comparison",
            dataset_url="https://scoreboard.example/draco.jsonl",
            created_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
        ),
    )
    assert repr(values) == "Leaderboards(1)"
    html = cast(Any, values)._repr_html_()
    assert "sf-lb-list" in html
    assert "Filter leaderboards" in html
    assert "Deep Research AI Comparison" in html
    assert "sf.leaderboards.get(&quot;draco&quot;)" in html
    assert [request.url.path for request in seen] == ["/v1/benchmarks"]
    assert seen[0].url.host == "scoreboard.example"


def test_client_gets_one_ranked_leaderboard_with_baselines() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_get_response())

    with _sync_client(handler) as client:
        board = client.leaderboards.get("draco", top=25)

    assert board.benchmark.id == "draco"
    assert isinstance(board.entries[0].url4, sf.Url4)
    assert board.entries == (
        sf.LeaderboardEntry(
            rank=1,
            spec_id="fusion/alpha",
            score=0.82,
            total_questions=100,
            ran_with_providers=("openrouter", "gemini-cli"),
            submitted_at=datetime(2026, 8, 8, 12, 30, tzinfo=UTC),
            submitted_by="researcher@example.com",
            verified_by_screamingface=True,
            url4=sf.Url4(_linked_url4()),
        ),
    )
    assert board.baselines[0].id == UUID(BASELINE_ID)
    assert board.baselines[0].metadata == {
        "organization": "Example Lab",
        "tags": ("closed",),
    }
    assert isinstance(board.baselines[0].metadata, Mapping)
    with pytest.raises(TypeError):
        board.baselines[0].metadata["organization"] = "changed"  # type: ignore[index]
    assert seen[0].url.path == "/v1/leaderboard/draco"
    assert dict(seen[0].url.params) == {"top": "25"}


def test_client_submits_a_candidate_result_without_repeating_report_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    candidate = _candidate_result()
    with _sync_client(handler) as client:
        score = client.leaderboards.submit(candidate)

    assert score == sf.LeaderboardScore(
        id=UUID(SCORE_ID),
        version=1,
        benchmark_id="draco",
        spec_id="fusion/alpha",
        url4=sf.Url4(_linked_url4()),
        submitted_by="researcher@example.com",
        submitted_at=datetime(2026, 8, 8, 12, 30, tzinfo=UTC),
        score=0.5,
        total_questions=2,
        correct_questions=1,
        ran_with_providers=("openrouter", "gemini-cli"),
        ran_at_local=datetime(2026, 8, 8, 12, tzinfo=UTC),
        client_name="screamingface",
        client_version="0.1.0",
        client_platform="darwin",
        verified_by_screamingface=False,
        metadata={
            "benchmark_revision": "fixture-revision",
            "candidate_kind": "fusion",
            "run_id": "run-fusion-alpha",
        },
        scoreboard_url=SCOREBOARD_URL,
    )
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/v1/scores"
    assert seen[0].headers["Idempotency-Key"] == candidate.run_id
    payload = seen[0].read().decode()
    assert '"benchmark_id":"draco"' in payload
    assert '"spec_id":"fusion/alpha"' in payload
    assert '"score":0.5' in payload
    assert '"correct_questions"' not in payload
    assert '"ran_with_providers":["openrouter","gemini-cli"]' in payload


def test_client_gets_one_score_by_uuid_or_string() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_score_response())

    with _sync_client(handler) as client:
        by_uuid = client.leaderboards.get_score(UUID(SCORE_ID))
        by_text = client.leaderboards.get_score(SCORE_ID)

    assert by_uuid == by_text
    assert by_uuid.id == UUID(SCORE_ID)
    assert [request.url.path for request in seen] == [
        f"/v1/scores/{SCORE_ID}",
        f"/v1/scores/{SCORE_ID}",
    ]


def test_submit_rejects_results_the_accuracy_scoreboard_cannot_represent() -> None:
    client = _sync_client(lambda _: pytest.fail("invalid result reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="unscored"):
        client.leaderboards.submit(_candidate_result(score=None))


def test_submit_surfaces_the_live_closed_write_contract() -> None:
    client = _sync_client(
        lambda _: httpx.Response(403, json={"detail": "score submission is not open yet"})
    )

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.submit(_candidate_result())

    assert exc_info.value.code == "score_submission_forbidden"
    assert exc_info.value.status == 403
    assert exc_info.value.details == "score submission is not open yet"


def test_submit_surfaces_a_scoreboard_conflict_as_retryable() -> None:
    client = _sync_client(
        lambda _: httpx.Response(
            409,
            json={"detail": "another request changed this submission; retry"},
        )
    )

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.submit(_candidate_result())

    assert exc_info.value.code == "score_submission_conflict"
    assert exc_info.value.status == 409
    assert exc_info.value.retryable is True
    assert exc_info.value.hint == "Retry the submission."


def test_leaderboard_rich_display_uses_the_brand_board_with_only_real_fields() -> None:
    with _sync_client(lambda _: httpx.Response(200, json=_get_response())) as client:
        board = client.leaderboards.get("draco")

    html = cast(Any, board)._repr_html_()

    assert "ScreamingFace candidate leaderboard" in html
    assert "sf-lb-board" in html
    assert "sf-lb__score-fill--gradient" in html
    assert "sf-lb__row--winner" in html
    assert "fusion/alpha" in html
    assert "single/model" in html
    assert "0.82" in html
    assert "0.61" in html
    # OME-832: the "verified only" control was removed. verified_by_screamingface became
    # uniform in OME-820, so the checkbox filtered nothing. Inverted rather than
    # deleted so it still catches the control being re-added before OME-821.
    assert "verified only" not in html
    assert "data-python=" in html
    assert "candidate = sf.Model(" in html
    assert "&#x27;openrouter/model&#x27;" in html
    assert "copies editable Python" in html
    assert "questions" in html
    assert "cost" not in html.lower()
    assert "mine only" not in html.lower()


def test_leaderboard_rich_display_escapes_scoreboard_text_and_recipe_attributes() -> None:
    payload = _get_response()
    benchmark = cast(dict[str, object], payload["benchmark"])
    benchmark["display_name"] = "DRACO <script>"
    entry = cast(list[dict[str, object]], payload["entries"])[0]
    entry["spec_id"] = 'fusion/"alpha" <script>'
    entry["url4_expression"] = _linked_url4(prompt='" onclick="alert(1)')

    with _sync_client(lambda _: httpx.Response(200, json=payload)) as client:
        html = cast(Any, client.leaderboards.get("draco"))._repr_html_()

    assert "DRACO &lt;script&gt;" in html
    assert "fusion/&quot;" in html
    assert "<script>" not in html
    assert "prompt=&#x27;&quot; onclick=&quot;alert(1)&#x27;" in html


def test_leaderboard_widgets_use_the_brand_system_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _list_response() if request.url.path == "/v1/benchmarks" else _get_response()
        return httpx.Response(200, json=payload)

    with _sync_client(handler) as client:
        list_html = cast(Any, client.leaderboards.list())._repr_html_()
        board_html = cast(Any, client.leaderboards.get("draco"))._repr_html_()

    for html in (list_html, board_html):
        assert "--sf-lb-bg:#fcfdff" in html
        assert 'font-family:"IBM Plex Sans"' in html
        assert 'font-family:"IBM Plex Mono"' in html
        assert "border-radius:0" in html
        assert "max-width:920px" in html
        assert ".jp-mod-theme-dark .sf-lb" in html
        assert '.jp-mod-theme-light .sf-lb,[data-jp-theme-light="true"] .sf-lb' in html
        assert ".vscode-dark .sf-lb" in html
        assert ".vscode-light .sf-lb" in html


@pytest.mark.asyncio
async def test_async_client_exposes_the_same_leaderboard_interface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks":
            return httpx.Response(200, json=_list_response())
        return httpx.Response(200, json=_get_response())

    async with _async_client(handler) as client:
        listed = await client.leaderboards.list()
        board = await client.leaderboards.get("draco", top=10)

    assert listed[0].id == "draco"
    assert board.entries[0].rank == 1


@pytest.mark.asyncio
async def test_async_client_submits_and_gets_scores() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201 if request.method == "POST" else 200, json=_score_response())

    async with _async_client(handler) as client:
        submitted = await client.leaderboards.submit(_candidate_result())
        fetched = await client.leaderboards.get_score(submitted.id)

    assert submitted == fetched


def test_module_leaderboards_delegate_to_the_lazy_default_client(monkeypatch: Any) -> None:
    omitted = object()

    class Leaderboards:
        def list(self) -> tuple[str, ...]:
            return ("draco",)

        def get(self, benchmark_id: str, *, top: int = 50) -> str:
            return f"{benchmark_id}:{top}"

        def submit(
            self,
            candidate_result: object,
            *,
            authors: object = omitted,
        ) -> tuple[str, object, object]:
            return ("submitted", candidate_result, authors)

        def get_score(self, score_id: object) -> tuple[str, object]:
            return ("score", score_id)

    class FakeClient:
        leaderboards = Leaderboards()

    monkeypatch.setattr(_default_client, "_client", FakeClient())

    assert sf.leaderboards.list() == ("draco",)
    assert sf.leaderboards.get("draco", top=20) == "draco:20"
    candidate = _candidate_result()
    assert sf.leaderboards.submit(candidate) == ("submitted", candidate, None)
    assert sf.leaderboards.submit(candidate, authors=("alice@example.com",)) == (
        "submitted",
        candidate,
        ("alice@example.com",),
    )
    assert sf.leaderboards.get_score(SCORE_ID) == ("score", SCORE_ID)

    monkeypatch.setattr(_default_client, "_client", None)


def test_default_client_reads_the_scoreboard_environment_once(monkeypatch: Any) -> None:
    monkeypatch.setattr(_default_client, "_client", None)
    monkeypatch.setenv("SCREAMINGFACE_SCOREBOARD_URL", "https://first.example")

    first = _default_client.default_client()
    monkeypatch.setenv("SCREAMINGFACE_SCOREBOARD_URL", "https://second.example")
    second = _default_client.default_client()

    assert first is second
    assert first.scoreboard_url == "https://first.example"
    first.close()
    monkeypatch.setattr(_default_client, "_client", None)


@pytest.mark.parametrize(
    ("response", "operation", "code", "permanent"),
    [
        (
            httpx.Response(404, json={"detail": "Benchmark not found"}),
            "get",
            "unknown_leaderboard",
            True,
        ),
        (httpx.Response(503), "list", "scoreboard_contract_error", False),
        (httpx.Response(200, text="{"), "list", "invalid_leaderboard", True),
        (httpx.Response(200, json={"benchmarks": "wrong"}), "list", "invalid_leaderboard", True),
    ],
)
def test_leaderboard_failures_are_typed(
    response: httpx.Response,
    operation: str,
    code: str,
    permanent: bool,
) -> None:
    client = _sync_client(lambda _: response)

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        if operation == "get":
            client.leaderboards.get("missing")
        else:
            client.leaderboards.list()

    assert exc_info.value.code == code
    assert exc_info.value.permanent is permanent


def test_unreachable_scoreboard_is_a_typed_retryable_failure() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = _sync_client(unreachable)

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.list()

    assert exc_info.value.code == "scoreboard_unreachable"
    assert exc_info.value.scoreboard_url == SCOREBOARD_URL
    assert exc_info.value.retryable is True


@pytest.mark.parametrize(("benchmark_id", "top"), [("", 50), ("draco", 0), ("draco", True)])
def test_get_rejects_invalid_query_values(benchmark_id: str, top: object) -> None:
    client = _sync_client(lambda _: pytest.fail("invalid query reached the scoreboard"))

    with client, pytest.raises((TypeError, ValueError)):
        client.leaderboards.get(benchmark_id, top=top)  # type: ignore[arg-type]


def _invalid_list_payloads() -> tuple[object, ...]:
    duplicate_list = _list_response()
    duplicate_list["benchmarks"] = [_benchmark(), _benchmark()]

    invalid_info = _list_response()
    cast(list[dict[str, object]], invalid_info["benchmarks"])[0]["created_at"] = "not-a-date"

    return [], duplicate_list, invalid_info


def _invalid_board_payloads() -> tuple[object, ...]:
    invalid_entries = _get_response()
    invalid_entries["entries"] = "not-an-array"

    invalid_entry_rank = _get_response()
    cast(list[dict[str, object]], invalid_entry_rank["entries"])[0]["rank"] = True

    nonconsecutive_entry_rank = _get_response()
    cast(list[dict[str, object]], nonconsecutive_entry_rank["entries"])[0]["rank"] = 2

    invalid_entry_accuracy = _get_response()
    cast(list[dict[str, object]], invalid_entry_accuracy["entries"])[0]["score"] = True

    invalid_entry_verification = _get_response()
    cast(list[dict[str, object]], invalid_entry_verification["entries"])[0][
        "verified_by_screamingface"
    ] = "yes"

    invalid_baseline_metadata = _get_response()
    cast(list[dict[str, object]], invalid_baseline_metadata["baselines"])[0]["metadata"] = []

    invalid_baseline_id = _get_response()
    cast(list[dict[str, object]], invalid_baseline_id["baselines"])[0]["id"] = "not-a-uuid"

    return (
        invalid_entries,
        invalid_entry_rank,
        nonconsecutive_entry_rank,
        invalid_entry_accuracy,
        invalid_entry_verification,
        invalid_baseline_metadata,
        invalid_baseline_id,
    )


def _invalid_score_payloads() -> tuple[object, ...]:
    invalid_score_metadata = _score_response()
    invalid_score_metadata["metadata"] = []

    invalid_score_id = _score_response()
    invalid_score_id["id"] = "not-a-uuid"

    invalid_score_timestamp = _score_response()
    invalid_score_timestamp["submitted_at"] = "2026-08-08T12:30:00"

    invalid_score_text = _score_response()
    invalid_score_text["benchmark_id"] = " "

    return invalid_score_metadata, invalid_score_id, invalid_score_timestamp, invalid_score_text


def test_scoreboard_rejects_malformed_wire_values_at_the_http_seam() -> None:
    cases = (
        *(("list", payload) for payload in _invalid_list_payloads()),
        *(("get", payload) for payload in _invalid_board_payloads()),
        *(("score", payload) for payload in _invalid_score_payloads()),
    )

    for operation, payload in cases:
        client = _sync_client(lambda _, value=payload: httpx.Response(200, json=value))
        with client, pytest.raises(sf.LeaderboardError) as exc_info:
            if operation == "list":
                client.leaderboards.list()
            elif operation == "get":
                client.leaderboards.get("draco")
            else:
                client.leaderboards.get_score(SCORE_ID)

        assert exc_info.value.code == "invalid_leaderboard"
        assert exc_info.value.permanent is True


def test_scoreboard_submission_validates_the_score_contract() -> None:
    # INVARIANT (OME-866): the ONLY client-side gates are "is a CandidateResult",
    # "has a score" and "score is finite". The pre-OME-866 version of this test also
    # demanded 0..1, binary Case grades and score==correct/total — all deleted WITH
    # the binary contract, never to return as client-side recomputation.
    client = _sync_client(lambda _: pytest.fail("invalid result reached the Scoreboard"))

    def _failed_case(case_id: int) -> sf.CaseResult:
        return sf.CaseResult(
            case_id=case_id,
            input=f"Question {case_id}",
            output=None,
            finish_reason=None,
            grade=None,
            failures=(
                sf.Failure(
                    stage="grading",
                    code="fixture_ungraded",
                    message="the fixture Case could not be graded",
                    case_id=case_id,
                ),
            ),
            metadata={},
        )

    def _unscored_result() -> sf.CandidateResult:
        # A genuinely unscored CandidateResult: no numeric Case grade anywhere, so
        # score=None survives report construction and reaches the submission adapter.
        template = _candidate_result()
        return sf.CandidateResult(
            benchmark=template.benchmark,
            run_id=template.run_id,
            started_at=template.started_at,
            completed_at=template.completed_at,
            name=template.name,
            kind=template.kind,
            url4=str(template.url4),
            models=template.models,
            operations=template.operations,
            score=None,
            coverage=0.0,
            metrics={},
            cases=(_failed_case(1), _failed_case(2)),
            members=template.members,
            failures=(),
            usage=template.usage,
        )

    invalid: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: object(), "sf.CandidateResult"),
        (lambda: _unscored_result(), "unscored"),
        (lambda: _candidate_result(score=float("inf")), "finite"),
    )

    with client:
        for build, message in invalid:
            with pytest.raises((TypeError, ValueError), match=message):
                client.leaderboards.submit(cast(Any, build()))


@pytest.mark.asyncio
async def test_async_scoreboard_network_failures_are_typed() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with _async_client(unreachable) as client:
        with pytest.raises(sf.LeaderboardError) as exc_info:
            await client.leaderboards.list()

    assert exc_info.value.code == "scoreboard_unreachable"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("score_id", [cast(Any, object()), "not-a-uuid"])
def test_get_score_rejects_invalid_identifiers(score_id: object) -> None:
    client = _sync_client(lambda _: pytest.fail("invalid id reached the Scoreboard"))

    with client, pytest.raises((TypeError, ValueError)):
        client.leaderboards.get_score(cast(Any, score_id))


def test_public_leaderboard_values_defend_their_invariants() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = (
            _score_response() if request.url.path.startswith("/v1/scores/") else _get_response()
        )
        return httpx.Response(200, json=payload)

    with _sync_client(handler) as client:
        board = client.leaderboards.get("draco")
        score = client.leaderboards.get_score(SCORE_ID)

    info = board.benchmark
    entry = board.entries[0]
    baseline = board.baselines[0]
    naive = datetime(2026, 8, 8, 12, 30)
    invalid: tuple[tuple[Callable[[], object], type[Exception], str], ...] = (
        (lambda: replace(info, id=cast(Any, 1)), TypeError, "must be a string"),
        (lambda: replace(info, display_name=" "), ValueError, "must be non-empty"),
        (lambda: replace(info, created_at=naive), ValueError, "timezone-aware"),
        (lambda: replace(entry, rank=0), ValueError, "positive integer"),
        (lambda: replace(entry, score=float("nan")), ValueError, "must be a finite number"),
        (
            lambda: replace(entry, ran_with_providers=cast(Any, "openrouter")),
            TypeError,
            "must be a sequence",
        ),
        (
            lambda: replace(entry, ran_with_providers=("openrouter", "openrouter")),
            ValueError,
            "must not contain duplicates",
        ),
        (
            lambda: replace(entry, verified_by_screamingface=cast(Any, 1)),
            TypeError,
            "must be a boolean",
        ),
        (lambda: replace(score, id=cast(Any, SCORE_ID)), TypeError, "must be a UUID"),
        (
            lambda: replace(score, correct_questions=score.total_questions + 1),
            ValueError,
            "cannot exceed",
        ),
        (
            lambda: replace(score, correct_questions=-1),
            ValueError,
            "non-negative integer",
        ),
        (lambda: replace(score, ran_at_local=naive), ValueError, "timezone-aware"),
        (
            lambda: replace(score, verified_by_screamingface=cast(Any, "yes")),
            TypeError,
            "must be a boolean",
        ),
        (lambda: replace(baseline, id=cast(Any, BASELINE_ID)), TypeError, "must be a UUID"),
        (lambda: replace(baseline, source_url="file:///tmp/result"), ValueError, r"HTTP\(S\)"),
        (
            lambda: replace(board, benchmark=cast(Any, "draco")),
            TypeError,
            "must be LeaderboardInfo",
        ),
        (
            lambda: replace(board, entries=cast(Any, "entries")),
            TypeError,
            "must be a sequence",
        ),
        (
            lambda: replace(board, entries=cast(Any, (info,))),
            TypeError,
            "invalid value",
        ),
        (
            lambda: replace(board, entries=(entry, entry)),
            ValueError,
            "ranks must be consecutive",
        ),
        (
            lambda: replace(
                board,
                baselines=(replace(baseline, benchmark_id="other"),),
            ),
            ValueError,
            "benchmark_id must match",
        ),
    )

    for factory, error, message in invalid:
        with pytest.raises(error, match=message):
            factory()


def test_empty_and_unforkable_leaderboards_have_complete_widget_states() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks":
            return httpx.Response(200, json={"benchmarks": []})
        payload = _get_response()
        payload["entries"] = []
        payload["baselines"] = []
        return httpx.Response(200, json=payload)

    with _sync_client(handler) as client:
        catalog = client.leaderboards.list()
        empty_board = client.leaderboards.get("draco")

    assert catalog == ()
    assert catalog == catalog
    assert catalog != []
    assert tuple(catalog) == ()
    assert "No Leaderboards are registered" in cast(Any, catalog)._repr_html_()
    assert "No scores have been published" in cast(Any, empty_board)._repr_html_()
    assert repr(empty_board) == "Leaderboard('draco', entries=0, baselines=0)"

    invalid_entry = sf.LeaderboardEntry(
        rank=1,
        spec_id="external/candidate",
        score=0.5,
        total_questions=2,
        ran_with_providers=("external",),
        submitted_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
        submitted_by=None,
        verified_by_screamingface=False,
        url4=sf.Url4("(@)!'not a ScreamingFace candidate'"),
    )
    board = sf.Leaderboard(
        benchmark=sf.LeaderboardInfo(
            id="draco",
            display_name="DRACO",
            description=None,
            dataset_url=None,
            created_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
        ),
        entries=(invalid_entry,),
        baselines=(),
    )
    html = cast(Any, board)._repr_html_()

    assert "sf-lb__score-fill--accent" in html
    assert "<span class='sf-lb__action' role='cell'>—</span>" in html

    forkable_entry = replace(invalid_entry, url4=sf.Url4(_linked_url4()))
    forkable_board = replace(board, entries=(forkable_entry,))
    forkable_html = cast(Any, forkable_board)._repr_html_()

    assert "<span class='sf-lb__chip'>verified</span>" not in forkable_html
    assert ">fork</button>" in forkable_html


# --- OME-832: the notebook view must not present an inert flag as trust ---


def _chip_board(*, verified: bool, forkable: bool) -> sf.Leaderboard:
    """One candidate plus one baseline, so both chip paths are exercised."""
    entry = sf.LeaderboardEntry(
        rank=1,
        spec_id="fusion/alpha",
        score=0.9,
        total_questions=10,
        ran_with_providers=("openrouter",),
        submitted_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
        submitted_by="tester@screamingface.ai",
        verified_by_screamingface=verified,
        url4=sf.Url4(_linked_url4() if forkable else "(@)!'not a ScreamingFace candidate'"),
    )
    baseline = sf.LeaderboardBaseline(
        id=uuid4(),
        benchmark_id="draco",
        model_name="single/model",
        score=0.6,
        source="LMArena",
        source_url="https://example.invalid/board",
        imported_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
        metadata=None,
    )
    return sf.Leaderboard(
        benchmark=sf.LeaderboardInfo(
            id="draco",
            display_name="DRACO",
            description=None,
            dataset_url=None,
            created_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
        ),
        entries=(entry,),
        baselines=(baseline,),
    )


@pytest.mark.parametrize("verified", [True, False])
@pytest.mark.parametrize("forkable", [True, False])
def test_leaderboard_view_shows_no_verification_ui(verified: bool, forkable: bool) -> None:
    """OME-820 left verified_by_screamingface without trustworthy semantics.

    Not uniform — rows predating that change keep false, since D5 forbids a backfill —
    but meaningless either way, because nothing re-runs submissions and nothing attests
    where a run executed. So the chip certifies nothing, and the "verified only"
    checkbox would split rows by whether they predate the default change while
    presenting itself as a verification filter: worse than filtering nothing.
    (Dmitry's review note on #601.)
    """
    html = cast(Any, _chip_board(verified=verified, forkable=forkable))._repr_html_()

    assert "verified only" not in html
    # The MARKUP, not the class name: LEADERBOARD_STYLE is inlined into the same string
    # and still carries the .sf-lb__checkbox rules, kept unused for OME-821 (D5). Dead
    # CSS renders no control.
    assert "<label class='sf-lb__checkbox'>" not in html
    assert "<input type='checkbox'" not in html
    assert "data-verified" not in html
    assert "<span class='sf-lb__chip'>verified</span>" not in html


@pytest.mark.parametrize("verified", [True, False])
def test_a_candidate_is_never_labelled_baseline(verified: bool) -> None:
    """INVARIANT: only an imported single-Model row may wear the baseline chip.

    `_row_chip` used to fall through to the baseline branch on `python_source is None`.
    Simply deleting the verified branch would therefore label a candidate with no
    forkable url4 as "baseline" — presenting a community submission as an imported
    reference, which is a worse error than the one being fixed. The predicate must key
    on `kind`, not on forkability.
    """
    html = cast(Any, _chip_board(verified=verified, forkable=False))._repr_html_()

    # The candidate row carries its spec_id; the baseline row carries the model name.
    candidate_row = html.split("fusion/alpha")[1].split("</div>")[0]

    assert "baseline" not in candidate_row
    assert "<span class='sf-lb__chip'>baseline</span>" in html  # the real baseline still has it


# --- OME-866: benchmark-native scores ------------------------------------------------


def _native_score_response(score: float) -> dict[str, object]:
    """The post-OME-866 wire shape: `score`, no universal correctness counts."""
    payload = _score_response()
    payload.pop("accuracy", None)
    payload["score"] = score
    payload["correct_questions"] = None
    return payload


def test_submit_sends_the_engine_score_unchanged_for_fractional_case_grades() -> None:
    """INVARIANT (OME-866): the Engine Benchmark is the sole scoring authority — the
    Client submits `CandidateResult.score` verbatim and never derives a replacement
    from Case grades. DRACO's weighted rubric grades are fractional, which the old
    binary contract rejected."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_native_score_response(0.399))

    candidate = _candidate_result(score=0.399, case_scores=(0.62, 0.18))
    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(candidate)

    assert submitted.score == 0.399
    body = seen[0].read().decode()
    assert '"score":0.399' in body
    assert '"total_questions":2' in body
    assert "accuracy" not in body
    assert "correct_questions" not in body


def test_submit_accepts_a_negative_healthbench_score() -> None:
    """HealthBench worst-30 reports an unclipped mean that is negative for every
    serious baseline; the Client must pass it through untouched."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_native_score_response(-1.143))

    candidate = _candidate_result(score=-1.143, case_scores=(-1.4, -0.886))
    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(candidate)

    assert submitted.score == -1.143
    assert '"score":-1.143' in seen[0].read().decode()


def test_submit_rejects_a_non_finite_score_before_http() -> None:
    """INVARIANT (OME-866 don't-regress): NaN and infinities never reach the wire —
    previously rejected only as a side effect of the deleted 0..1 range check."""
    client = _sync_client(lambda _: pytest.fail("a non-finite score reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="finite"):
        client.leaderboards.submit(_candidate_result(score=float("nan")))


def test_leaderboard_values_accept_negative_scores() -> None:
    """Public Leaderboard values carry any finite benchmark-native score."""
    entry_payload = {
        "rank": 1,
        "spec_id": "fusion/alpha",
        "score": -1.143,
        "total_questions": 30,
        "ran_with_providers": ["openrouter"],
        "submitted_at": SUBMITTED_AT,
        "submitted_by": None,
        "verified_by_screamingface": True,
        "url4_expression": _linked_url4(),
    }
    board = {
        "benchmark": _benchmark(),
        "entries": [entry_payload],
        "baselines": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=board)

    with _sync_client(handler) as client:
        value = client.leaderboards.get("draco")

    assert value.entries[0].score == -1.143


def test_leaderboard_widget_renders_negative_scores_without_percentages() -> None:
    """INVARIANT (OME-866): the notebook widget renders benchmark-native scores as plain
    numbers with min..max-normalized bars. On an all-negative HealthBench board the old
    `score * 100` / `score / max` math produced "-114.3" and negative CSS widths — the
    floor row must render an EMPTY track, the best row a full one, and nothing negative.
    """
    entries = tuple(
        sf.LeaderboardEntry(
            rank=rank,
            spec_id=name,
            score=score,
            total_questions=30,
            ran_with_providers=("openrouter",),
            submitted_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
            submitted_by=None,
            verified_by_screamingface=False,
            url4=sf.Url4("(@)!'not a ScreamingFace candidate'"),
        )
        for rank, (name, score) in enumerate(
            (("fusion/best", -0.4), ("fusion/worst", -1.143)), start=1
        )
    )
    board = sf.Leaderboard(
        benchmark=sf.LeaderboardInfo(
            id="healthbench_worst30",
            display_name="HealthBench worst-30",
            description=None,
            dataset_url=None,
            created_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
        ),
        entries=entries,
        baselines=(),
    )

    html = cast(Any, board)._repr_html_()

    assert "-0.4" in html
    assert "-1.143" in html
    assert "width:-" not in html, "a negative CSS width is invalid and collapses the track"
    assert "width:100.0%" in html, "the best (least negative) row fills the track"
    assert "width:0.0%" in html, "the floor row renders empty, never negative"
    assert "-40.0" not in html and "-114.3" not in html, "no ×100 percentage rendering"


def test_leaderboard_score_repr_is_a_summary_not_a_url4_dump() -> None:
    """WHY: submit() returns a LeaderboardScore straight into a notebook cell, and the
    dataclass auto-repr printed the ENTIRE compiled url4 expression — a multi-thousand
    character wall. The repr is a summary; the expression stays reachable via .url4."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_native_score_response(-1.1429))

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(
            _candidate_result(score=-1.1429, case_scores=(-1.4, -0.886))
        )

    text = repr(submitted)
    assert len(text) < 250, f"repr must stay one glanceable line, got {len(text)} chars"
    assert "draco" in text
    assert "fusion/alpha" in text
    assert "-1.1429" in text
    assert "candidate:0.0" not in text, "the compiled url4 expression must not leak into repr"


def test_submitted_score_renders_as_an_sfds_card() -> None:
    """The value submit() drops into a notebook cell renders as a brand card like the
    Report panel — not as a repr dump. Plain benchmark-native number (never ×100), the
    enormous url4 expression folded behind a disclosure."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_native_score_response(-1.1429))

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(
            _candidate_result(score=-1.1429, case_scores=(-1.4, -0.886))
        )

    html = cast(Any, submitted)._repr_html_()

    assert "sf-report" in html, "reuses the vendored report-card system"
    assert "Score published" in html
    assert "draco" in html
    assert "fusion/alpha" in html
    assert "-1.1429" in html
    assert "-114.3" not in html, "never a ×100 percentage rendering"
    assert "<details" in html and "URL4" in html, "the expression stays folded"
    assert "candidate:0.0" not in html.split("<details")[0], "url4 only inside the disclosure"
    # The card deep-links to this score's spec page on the SAME Scoreboard it came
    # from — localhost in a local stack, the deployed board in production.
    assert f"href='{SCOREBOARD_URL}/spec.html?benchmark=draco&amp;spec=fusion%2Falpha'" in html, (
        "links to the portal spec page on the originating Scoreboard"
    )


# --- OME-1029: the run cost reaches the submission payload -----------------------------------
# Scoreboard accepts `run_cost_usd`, the Engine produces a run total and the SDK holds it on
# CandidateResult.usage.cost_usd — the payload just omitted it, so the column was null on every
# row of every board. OME-822 (cost required) and OME-923's Pareto marks both wait on this.


def _result_costing(cost: str | None) -> sf.CandidateResult:
    # Rebuilt rather than `replace`d: CandidateResult takes `metrics=` but stores `_metric_items`,
    # so dataclasses.replace feeds back a keyword __init__ does not accept. Constructing from the
    # fixture's own attributes leaves the shared fixture untouched.
    base = _candidate_result()
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id=base.run_id,
        started_at=base.started_at,
        completed_at=base.completed_at,
        name=base.name,
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=base.operations,
        score=base.score,
        coverage=base.coverage,
        metrics=dict(base.metrics),
        cases=base.cases,
        members=base.members,
        failures=base.failures,
        usage=sf.Usage(cost_usd=None if cost is None else Decimal(cost)),
    )


def test_a_priced_run_submits_its_cost_as_a_decimal_string() -> None:
    # INVARIANT: a STRING on the wire, never a float and never a raw Decimal. The payload is handed
    # to `json=`, which raises TypeError on a Decimal; a float would silently lose precision on a
    # DECIMAL(12, 6) money column. Both failures are invisible to a test that only checks presence.
    payload = _submission(_result_costing("1.234567"))

    assert payload["run_cost_usd"] == "1.234567"
    assert isinstance(payload["run_cost_usd"], str)


def test_an_unpriced_run_submits_null_and_never_zero() -> None:
    # INVARIANT: absent means "no cost was reported". Coercing it to 0 would put an unpriced run at
    # the cheapest end of the Pareto frontier OME-923 is about to build — a claim about money
    # nobody measured.
    payload = _submission(_result_costing(None))

    assert payload["run_cost_usd"] is None


def test_a_run_that_genuinely_cost_nothing_submits_zero() -> None:
    # A fully cache-served run legitimately costs zero, and that is a different fact from "not
    # reported". OME-770 D10 and OME-923's exclusion rule both depend on the distinction.
    payload = _submission(_result_costing("0"))

    assert payload["run_cost_usd"] == "0"
    assert payload["run_cost_usd"] is not None


def test_zero_and_absent_are_distinguishable_in_the_payload() -> None:
    priced_zero = _submission(_result_costing("0"))["run_cost_usd"]
    unpriced = _submission(_result_costing(None))["run_cost_usd"]

    assert priced_zero != unpriced


def test_the_submission_payload_gains_only_the_cost_key() -> None:
    # A characterisation guard: this is the submission path every user depends on, so an accidental
    # change to a neighbouring field should fail loudly rather than ship.
    payload = _submission(_result_costing("0.5"))

    assert set(payload) == {
        "version",
        "benchmark_id",
        "spec_id",
        "url4_expression",
        "score",
        "total_questions",
        "ran_with_providers",
        "ran_at_local",
        "run_cost_usd",
        "client",
        "metadata",
    }


def test_the_cost_survives_json_serialisation() -> None:
    # INVARIANT: the payload is handed to `json=`, so it must survive json.dumps. A raw Decimal
    # raises TypeError there — a failure no assertion on the dict alone would catch.
    import json

    encoded = json.loads(json.dumps(_submission(_result_costing("1.234567"))))

    assert encoded["run_cost_usd"] == "1.234567"
    assert json.loads(json.dumps(_submission(_result_costing(None))))["run_cost_usd"] is None


def test_the_cost_reaches_the_wire_on_a_real_submit() -> None:
    # End to end through the client, not just the payload builder: the value has to survive
    # httpx's own JSON encoding, which is where a raw Decimal would raise.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    with _sync_client(handler) as client:
        client.leaderboards.submit(_result_costing("2.5"))

    assert json.loads(seen[-1].content)["run_cost_usd"] == "2.5"


@pytest.mark.asyncio
async def test_the_async_submit_sends_the_cost_too() -> None:
    # Sync and async share _submission(), and this keeps that true: a divergence would be silent
    # and only one set of users would carry costs.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    async with _async_client(handler) as client:
        await client.leaderboards.submit(_result_costing("2.5"))

    assert json.loads(seen[-1].content)["run_cost_usd"] == "2.5"


@pytest.mark.parametrize(
    "cost",
    ["0", "0.000001", "1.234567", "999999.999999"],
)
def test_the_wire_string_parses_back_to_the_same_decimal(cost: str) -> None:
    # The SDK and Scoreboard are separate deployables with no shared type — Scoreboard's
    # `run_cost_usd` is `Decimal | None` and Pydantic parses the string we send. Importing that
    # schema here is not possible (its dependencies are not in this venv, correctly), so the
    # contract is pinned as the property that field relies on: what we emit must parse back to
    # exactly the Decimal we started with, across the column's DECIMAL(12, 6) range.
    emitted = _submission(_result_costing(cost))["run_cost_usd"]

    assert isinstance(emitted, str)
    assert Decimal(emitted) == Decimal(cost)


def test_no_cost_is_absent_rather_than_an_empty_string() -> None:
    # An empty string would parse as neither a Decimal nor null and would 422 the submission.
    assert _submission(_result_costing(None))["run_cost_usd"] is None


# --- OME-1053: explicit authorship is distinct from the authenticated submitter ----------------


def test_submission_omits_unspecified_authors_and_preserves_an_explicit_list() -> None:
    candidate = _candidate_result()

    assert "authors" not in _submission(candidate)
    assert _submission(
        candidate,
        authors=("alice@example.com", "bob@example.org", "alice@example.com"),
    )["authors"] == ["alice@example.com", "bob@example.org", "alice@example.com"]


def test_submission_accepts_the_author_count_and_length_boundaries() -> None:
    boundary_address = "a" * 243 + "@example.com"
    authors = (boundary_address,) * 10

    assert len(boundary_address) == 255
    assert _submission(_candidate_result(), authors=authors)["authors"] == list(authors)


@pytest.mark.parametrize(
    ("authors", "error"),
    [
        ("alice@example.com", TypeError),
        (("alice@example.com", 7), TypeError),
        ((), ValueError),
        (("alice@example.com",) * 11, ValueError),
        (("not-an-email",), ValueError),
        (("alice@localhost",), ValueError),
        ((" alice@example.com",), ValueError),
        (("a" * 244 + "@example.com",), ValueError),
    ],
)
def test_submission_rejects_invalid_author_arguments_before_http(
    authors: object,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        _submission(_candidate_result(), authors=cast(Any, authors))


def test_sync_submit_sends_exact_authors_and_decodes_public_authors() -> None:
    seen: list[httpx.Request] = []
    response = _score_response()
    response["authors"] = ["alice", "bob"]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=response)

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(
            _candidate_result(),
            authors=["alice@example.com", "bob@example.org"],
        )

    assert json.loads(seen[-1].content)["authors"] == [
        "alice@example.com",
        "bob@example.org",
    ]
    assert submitted.authors == ("alice", "bob")
    assert isinstance(submitted.authors, tuple)


def test_submit_decodes_corrected_authors_from_a_deduplicated_response() -> None:
    response = _score_response()
    response["authors"] = ["alice", "bob"]

    def handler(request: httpx.Request) -> httpx.Response:
        # INVARIANT: Scoreboard answers a deduplicated correction with 200, not the 201 used for a
        # newly created row. Both successful POST outcomes carry the same score response contract.
        assert request.method == "POST"
        return httpx.Response(200, json=response)

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(
            _candidate_result(),
            authors=["alice@example.com", "bob@example.org"],
        )

    assert submitted.authors == ("alice", "bob")
    assert isinstance(submitted.authors, tuple)


@pytest.mark.asyncio
async def test_async_submit_uses_the_same_authors_contract() -> None:
    seen: list[httpx.Request] = []
    response = _score_response()
    response["authors"] = ["alice"]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=response)

    async with _async_client(handler) as client:
        submitted = await client.leaderboards.submit(
            _candidate_result(), authors=["alice@example.com"]
        )

    assert json.loads(seen[-1].content)["authors"] == ["alice@example.com"]
    assert submitted.authors == ("alice",)


def test_lazy_submit_forwards_authors_to_the_default_client(monkeypatch: Any) -> None:
    seen: list[object] = []

    class Leaderboards:
        def submit(
            self,
            candidate_result: object,
            *,
            authors: Sequence[str] | None = None,
        ) -> tuple[object, Sequence[str] | None]:
            seen.extend((candidate_result, authors))
            return candidate_result, authors

    class FakeClient:
        leaderboards = Leaderboards()

    fake = FakeClient()
    monkeypatch.setattr(_default_client, "_client", fake)
    candidate = _candidate_result()

    assert sf.leaderboards.submit(candidate, authors=["alice@example.com"]) == (
        candidate,
        ["alice@example.com"],
    )
    assert seen == [candidate, ["alice@example.com"]]


def test_leaderboard_entries_decode_public_authors_as_an_immutable_tuple() -> None:
    response = _get_response()
    entries = cast(list[dict[str, object]], response["entries"])
    entries[0]["authors"] = ["alice", "bob"]

    with _sync_client(lambda _request: httpx.Response(200, json=response)) as client:
        board = client.leaderboards.get("draco")

    assert board.entries[0].authors == ("alice", "bob")
    assert isinstance(board.entries[0].authors, tuple)


def test_score_response_does_not_apply_the_write_cap_to_public_authors() -> None:
    response = _score_response()
    response["authors"] = [f"author-{index}" for index in range(11)]

    with _sync_client(lambda _request: httpx.Response(200, json=response)) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.authors == tuple(f"author-{index}" for index in range(11))


def test_score_response_preserves_nonblank_public_author_text_exactly() -> None:
    response = _score_response()
    response["authors"] = [" alice "]

    with _sync_client(lambda _request: httpx.Response(200, json=response)) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.authors == (" alice ",)


def test_score_receipt_distinguishes_submitter_from_authors_and_escapes_them() -> None:
    response = _score_response()
    response["authors"] = ["alice<admin>", "bob"]

    with _sync_client(lambda _request: httpx.Response(200, json=response)) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    html = cast(Any, score)._repr_html_()

    assert ">submitter<" in html
    assert ">authors<" in html
    assert ">author<" not in html
    assert "researcher@example.com" in html
    assert "alice&lt;admin&gt;, bob" in html
    assert "alice<admin>" not in html


@pytest.mark.parametrize("authors", [[], "alice", [""]])
def test_score_response_rejects_malformed_public_authors(authors: object) -> None:
    response = _score_response()
    response["authors"] = authors

    with (
        _sync_client(lambda _request: httpx.Response(200, json=response)) as client,
        pytest.raises(sf.LeaderboardError, match="Invalid Scoreboard Leaderboard response"),
    ):
        client.leaderboards.get_score(SCORE_ID)


# --- OME-909: the successful submit receipt says when the score will not rank ----------------


def _revision_mismatch_response(
    *, submitted: str | None = "submitted-revision", registered: str = "registered-revision"
) -> dict[str, object]:
    payload = _score_response()
    payload["benchmark_revision"] = submitted
    payload["ranking_notice"] = {
        "code": "benchmark_revision_mismatch",
        "submitted_benchmark_revision": submitted,
        "registered_benchmark_revision": registered,
    }
    return payload


def test_submit_decodes_a_revision_mismatch_as_a_public_typed_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_revision_mismatch_response())

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(_candidate_result())

    assert submitted.ranking_notice == sf.LeaderboardRankingNotice(
        code="benchmark_revision_mismatch",
        submitted_benchmark_revision="submitted-revision",
        registered_benchmark_revision="registered-revision",
    )


def test_submit_from_an_older_scoreboard_has_no_ranking_notice() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_score_response())

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(_candidate_result())

    assert submitted.ranking_notice is None


@pytest.mark.parametrize(
    "notice",
    [
        None,
        {},
        {
            "code": "some_future_reason",
            "submitted_benchmark_revision": "old",
            "registered_benchmark_revision": "new",
        },
        {
            "code": "benchmark_revision_mismatch",
            "submitted_benchmark_revision": "old",
            "registered_benchmark_revision": None,
        },
    ],
)
def test_submit_rejects_a_malformed_ranking_notice(notice: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _score_response()
        payload["ranking_notice"] = notice
        return httpx.Response(201, json=payload)

    with _sync_client(handler) as client:
        with pytest.raises(sf.LeaderboardError, match="ranking notice"):
            client.leaderboards.submit(_candidate_result())


def test_revision_mismatch_card_keeps_the_receipt_and_adds_an_alert() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_revision_mismatch_response())

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(_candidate_result())

    html = cast(Any, submitted)._repr_html_()

    assert "Score published" in html
    assert "Not ranked · benchmark revision mismatch." in html
    assert "This run used revision submitted-revision" in html
    assert "the board ranks revision registered-revision" in html
    assert "class='sf-report__warn'" in html
    assert "role='alert'" in html


def test_revision_mismatch_card_escapes_server_revision_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json=_revision_mismatch_response(
                submitted="old<script>alert(1)</script>",
                registered="new' onclick='alert(2)",
            ),
        )

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(_candidate_result())

    html = cast(Any, submitted)._repr_html_()

    assert "<script>" not in html
    assert "old&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "new&#x27; onclick=&#x27;alert(2)" in html


def test_matching_revision_card_has_no_not_ranked_warning() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_score_response())

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(_candidate_result())

    html = cast(Any, submitted)._repr_html_()

    assert "Score published" in html
    assert "Not ranked" not in html
    assert "role='alert'" not in html


def test_revision_mismatch_card_identity_uses_the_persisted_revision() -> None:
    # The typed response field is the store-resolved authority. Metadata is untyped client input
    # and can retain a stale, conflicting legacy revision; the warning and identity strip must not
    # tell two different stories on the same receipt.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_revision_mismatch_response())

    with _sync_client(handler) as client:
        submitted = client.leaderboards.submit(_candidate_result())

    html = cast(Any, submitted)._repr_html_()

    assert "draco · rev submitted-revision" in html
    assert "draco · rev fixture-revision" not in html
