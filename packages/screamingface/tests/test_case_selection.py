"""`evaluate(..., cases=[...])`: a run on a fixed list of Case ids (OME-1739, PR 2 of 2).

STORY: as a researcher with a frozen development set and a held-out set, I run a Benchmark on
exactly those Case ids, and the Report says which Cases it scored.

The fake Engine below plays the Engine's selection route from PR 1 (#1636): it answers
`POST /v1/benchmarks/draco/selection` with a resource that echoes `selected_case_ids`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest
from test_client_run import _engine, _ForbiddenTransport
from test_replay_partial import CASE_COUNT, _benchmark_url4
from test_reproduce import _AsyncReplayer, _Replayer

import screamingface as sf
from screamingface.errors import ExecutionError, PlanningError

SELECTED: list[int] = [3, 17, 42]
INSTALLED: int = 50
MODEL = sf.Model("provider/opus", prompt="Answer.")


class _SelectionEngine:
    """The Engine's catalog: GET for `limit=`, POST `/selection` for a Case-id list.

    `echo` decides what the selection resource says it selected: the posted ids (an Engine with
    PR 1), other ids (a broken Engine), or nothing at all (an Engine older than PR 1).
    """

    def __init__(self, *, echo: str = "posted", status: int = 200) -> None:
        self.echo = echo
        self.status = status
        self.requests: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith("/v1/benchmarks/draco"):
            return _engine(request)
        body: Any = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if request.method == "GET":
            raw: str | None = request.url.params.get("limit")
            count: int = INSTALLED if raw is None else int(raw)
            return httpx.Response(200, json=self._resource(count))
        return self._selection(body["cases"])

    def _selection(self, cases: list[int]) -> httpx.Response:
        """The selection route: the 422 or 404 it is told to give, else the resource."""

        if self.status == 404:
            # WHY this body: an Engine older than #1636 has no `/selection` route, so FastAPI's
            # router answers its own plain 404, not the Engine's "Unknown benchmark" problem.
            return httpx.Response(404, json={"detail": "Not Found"})
        if self.status != 200:
            return httpx.Response(
                self.status,
                json={"title": "Invalid benchmark selection", "detail": "'draco': 999 > 50"},
            )
        resource: dict[str, object] = self._resource(len(cases))
        if self.echo == "posted":
            resource["selected_case_ids"] = sorted(cases)
        elif self.echo == "other":
            resource["selected_case_ids"] = [1, 2, 3]
        return httpx.Response(200, json=resource)

    @staticmethod
    def _resource(count: int) -> dict[str, object]:
        return {
            "schema": "screamingface.benchmark.v1",
            "id": "draco",
            "title": "DRACO",
            "description": "Fixture DRACO Benchmark.",
            "revision": "fixture-revision",
            "case_count": INSTALLED,
            "selected_case_count": count,
            "url4": _benchmark_url4(count),
        }


def _client(catalog: _SelectionEngine, run: object) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog),
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(_no_scoreboard),
        run_transport=run,  # type: ignore[arg-type]
    )


def _no_scoreboard(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"the Scoreboard must not be called: {request.method} {request.url}")


def _graded(*case_ids: int) -> _Replayer:
    return _Replayer(cases=tuple((case_id, None) for case_id in case_ids))


def test_a_selected_run_posts_the_ids_and_the_report_names_the_cases_it_scored() -> None:
    catalog = _SelectionEngine()
    run = _graded(3, 17, 42)

    with _client(catalog, run) as client:
        report = client.evaluate(MODEL, benchmark="draco", cases=[42, 3, 17], progress=False)

    # WHY sorted on the wire: one set of Cases is one recipe, whatever order it was typed in.
    assert catalog.requests == [("POST", "/v1/benchmarks/draco/selection", {"cases": SELECTED})]
    assert report.case_count == 3
    assert report.selected_cases == (3, 17, 42)
    assert report.candidates.only.selected_cases == (3, 17, 42)
    # INVARIANT: the fingerprint is the sha256 of the sorted ids, so anyone can recompute it.
    assert report.selection_fingerprint == ("sha256:" + hashlib.sha256(b"3,17,42").hexdigest())


def test_a_limit_run_is_still_a_get_and_names_no_selection() -> None:
    catalog = _SelectionEngine()

    with _client(catalog, _graded(1, 2)) as client:
        report = client.evaluate(MODEL, benchmark="draco", limit=2, progress=False)

    assert catalog.requests == [("GET", "/v1/benchmarks/draco", None)]
    assert report.selected_cases is None
    assert report.selection_fingerprint is None
    assert report.candidates.only.selected_cases is None


def test_a_list_of_cases_one_to_n_is_the_same_run_as_limit_n() -> None:
    """The Engine writes 1..N as the plain count, so the run is `limit=N` and names no selection."""

    with _client(_SelectionEngine(), _graded(1, 2, 3)) as client:
        report = client.evaluate(MODEL, benchmark="draco", cases=[1, 2, 3], progress=False)

    assert report.case_count == 3
    assert report.selected_cases is None


@pytest.mark.parametrize(
    ("cases", "error", "message"),
    [
        ([0, 17], ValueError, "at least 1"),
        ([-1], ValueError, "at least 1"),
        ([17, 17], ValueError, "17 twice"),
        ([], ValueError, "at least one Case id"),
        ([True, 2], TypeError, "whole numbers"),
        ([3.0], TypeError, "whole numbers"),
        (["3"], TypeError, "whole numbers"),
        ("3,17", TypeError, "a list of Case ids"),
        (3, TypeError, "a list of Case ids"),
        (list(range(1, 1002)), ValueError, "at most 1,000 Case ids"),
    ],
    ids=[
        "zero",
        "negative",
        "duplicate",
        "empty",
        "bool",
        "float",
        "text-id",
        "text",
        "bare-int",
        "over-the-cap",
    ],
)
def test_a_bad_case_list_fails_at_the_door_before_anything_is_sent(
    cases: Any, error: type[Exception], message: str
) -> None:
    catalog = _SelectionEngine()
    run = _ForbiddenTransport()

    with _client(catalog, run) as client, pytest.raises(error, match=message):
        client.evaluate(MODEL, benchmark="draco", cases=cases, progress=False)

    assert catalog.requests == []
    assert run.called is False


def test_cases_and_limit_together_fail_at_the_door() -> None:
    catalog = _SelectionEngine()

    with _client(catalog, _ForbiddenTransport()) as client:
        with pytest.raises(TypeError, match="cases= or limit=, not both"):
            client.evaluate(MODEL, benchmark="draco", cases=[3], limit=5, progress=False)

    assert catalog.requests == []


def test_an_engine_without_the_selection_route_is_refused_before_any_run() -> None:
    """F2: an Engine older than PR 1 answers 404, so nothing runs (it would bill every Case)."""

    catalog = _SelectionEngine(status=404)
    run = _ForbiddenTransport()

    with _client(catalog, run) as client, pytest.raises(PlanningError) as raised:
        client.evaluate(MODEL, benchmark="draco", cases=SELECTED, progress=False)

    # WHY the Engine, not the Benchmark: "not installed" sent the researcher to check the
    # Benchmark id when the fix is a newer Engine (review on #1653).
    assert raised.value.code == "engine_cannot_select_cases"
    assert "SF Engine cannot run a fixed list of Case ids" in str(raised.value)
    assert "not installed" not in str(raised.value)
    assert run.called is False


def test_an_unknown_benchmark_on_a_selecting_engine_still_reads_unknown() -> None:
    """The Engine's own 404 problem ("Unknown benchmark") keeps today's code and wording."""

    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/benchmarks/draco"):
            return httpx.Response(
                404,
                json={"title": "Unknown benchmark", "detail": "no Benchmark is installed"},
            )
        return _engine(request)

    with (
        sf.Client(
            engine_url="https://engine.example",
            http_transport=httpx.MockTransport(engine),
            scoreboard_url="https://scoreboard.example",
            scoreboard_transport=httpx.MockTransport(_no_scoreboard),
            run_transport=_ForbiddenTransport(),  # type: ignore[arg-type]
        ) as client,
        pytest.raises(PlanningError) as raised,
    ):
        client.evaluate(MODEL, benchmark="draco", cases=SELECTED, progress=False)

    assert raised.value.code == "unknown_benchmark"


@pytest.mark.parametrize("echo", ["missing", "other"])
def test_a_resource_that_does_not_echo_the_selection_is_refused_before_any_run(
    echo: str,
) -> None:
    """F2: the SDK never runs a recipe for a Case set other than the one it asked for."""

    run = _ForbiddenTransport()

    with _client(_SelectionEngine(echo=echo), run) as client:
        with pytest.raises(PlanningError, match="did not select the requested Cases") as raised:
            client.evaluate(MODEL, benchmark="draco", cases=SELECTED, progress=False)

    assert raised.value.code == "invalid_benchmark_resource"
    assert run.called is False


def test_an_out_of_range_id_is_the_engines_422_before_any_run() -> None:
    """F3: only the Engine knows the installed count; its 422 detail reaches the researcher."""

    run = _ForbiddenTransport()

    with _client(_SelectionEngine(status=422), run) as client:
        with pytest.raises(PlanningError, match="999 > 50") as raised:
            client.evaluate(MODEL, benchmark="draco", cases=[3, 17, 999], progress=False)

    assert raised.value.code == "invalid_benchmark_selection"
    assert run.called is False


def test_a_graded_roll_call_other_than_the_selection_is_refused() -> None:
    """F6: no score is reported for a Case set nobody asked for.

    WHY a per-Candidate failure (review on #1653): the check runs while each result body is
    decoded, so the mismatch is `candidates_failed` naming the Candidate with
    `engine_contract_error`, and it is an ExecutionError because the money is already spent.
    """

    with _client(_SelectionEngine(), _graded(3, 17, 18)) as client:
        with pytest.raises(ExecutionError) as raised:
            client.evaluate(MODEL, benchmark="draco", cases=SELECTED, progress=False)

    assert raised.value.code == "candidates_failed"
    assert raised.value.details == {"failed": {"opus": "engine_contract_error"}}
    # INVARIANT: the Partial Report holds no Candidate that graded other Cases.
    assert raised.value.partial_report is None
    cause: BaseException | None = raised.value.__cause__
    assert isinstance(cause, ExecutionError)
    assert "graded Cases [3, 17, 18]" in str(cause) and "[3, 17, 42]" in str(cause)


class _LostSecond(_Replayer):
    """The replay fake whose run for the Candidate named `two` is lost mid-flight."""

    def run(self, candidate: Any, on_event: object) -> Any:
        if candidate.name == "two":
            raise ExecutionError("lost", code="websocket_disconnected")
        return super().run(candidate, on_event)


def test_a_wrong_roll_call_is_not_reported_through_a_partial_report() -> None:
    """F6 beside a failed sibling (review on #1653): the roll call is checked per Candidate.

    WHY: `candidates_failed` carries a Partial Report of the Candidates that succeeded. If the
    check ran on the finished Report only, a Candidate graded on Cases 3, 17, 18 would reach the
    caller inside that Partial Report, scored, with no `engine_contract_error` anywhere.
    """

    one = sf.Model("provider/opus", prompt="Answer.", name="one")
    two = sf.Model("provider/opus", prompt="Answer.", name="two")

    with _client(_SelectionEngine(), _LostSecond(cases=((3, None), (17, None), (18, None)))) as c:
        with pytest.raises(ExecutionError) as raised:
            c.evaluate([one, two], benchmark="draco", cases=SELECTED, progress=False)

    assert raised.value.code == "candidates_failed"
    assert raised.value.details == {
        "failed": {"one": "engine_contract_error", "two": "websocket_disconnected"}
    }
    assert raised.value.partial_report is None


def test_a_selected_run_cannot_be_submitted_to_the_leaderboard() -> None:
    """F4: the Scoreboard ranks full runs only; the refusal comes before any request."""

    with _client(_SelectionEngine(), _graded(3, 17, 42)) as client:
        report = client.evaluate(MODEL, benchmark="draco", cases=SELECTED, progress=False)
        with pytest.raises(ValueError, match="selected Cases can't be submitted"):
            client.leaderboards.submit(report.candidates.only, authors=["a@example.com"])


def test_a_complete_url4_and_a_replay_refuse_cases() -> None:
    with _client(_SelectionEngine(), _ForbiddenTransport()) as client:
        with pytest.raises(TypeError, match="cases must not be passed"):
            client.evaluate("https://engine.example/x", cases=[3])  # type: ignore[call-overload]
        with pytest.raises(TypeError, match="cases= is not supported when replaying"):
            client.evaluate(pinned_cache="copy", cases=[3])  # type: ignore[call-overload]


@pytest.mark.asyncio
async def test_the_async_client_runs_the_same_selection() -> None:
    catalog = _SelectionEngine()
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog),
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(_no_scoreboard),
        run_transport=_AsyncReplayer(cases=((3, None), (17, None), (42, None))),  # type: ignore[arg-type]
    ) as client:
        report = await client.evaluate(MODEL, benchmark="draco", cases=SELECTED, progress=False)

    assert catalog.requests == [("POST", "/v1/benchmarks/draco/selection", {"cases": SELECTED})]
    assert report.selected_cases == (3, 17, 42)


@pytest.mark.asyncio
async def test_the_async_client_refuses_a_graded_roll_call_other_than_the_selection() -> None:
    """F6, async twin (review on #1653): the per-Candidate check is shared by both doors."""

    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_SelectionEngine()),
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(_no_scoreboard),
        run_transport=_AsyncReplayer(cases=((3, None), (17, None), (18, None))),  # type: ignore[arg-type]
    ) as client:
        with pytest.raises(ExecutionError) as raised:
            await client.evaluate(MODEL, benchmark="draco", cases=SELECTED, progress=False)

    assert raised.value.code == "candidates_failed"
    assert raised.value.details == {"failed": {"opus": "engine_contract_error"}}
    assert raised.value.partial_report is None


def test_the_default_client_passes_cases_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class _Recorder:
        def evaluate(self, *args: object, **kwargs: object) -> str:
            seen.update(kwargs)
            return "report"

    import screamingface._default_client as default_client

    monkeypatch.setattr(default_client, "default_client", lambda: _Recorder())
    assert sf.evaluate(MODEL, benchmark="draco", cases=SELECTED) == "report"
    assert seen["cases"] == SELECTED


assert CASE_COUNT < INSTALLED  # the borrowed url4 helper only names a count
