# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""Each judge pass gets its own pinned seed (OME-1527 R12).

FEATURE: a Benchmark that grades one Candidate reply over N judge passes (draco: 3 or 5) needs
N independent judge requests. With identical bytes the AI Gateway's exact-request cache would
answer pass 2 with pass 1's reply, so "five passes" would really be one. A row that declares
``JudgeSpec(seed_per_pass=True)`` lets its scorer name pass ``k`` as ``GenerateConfig(seed=k)``;
the judge provider sends the row's pinned params, then ``seed=k``.

INVARIANTS the suite defends: the pass number is the ONLY per-call setting a scorer may send,
and only on a row that opted in (every other row refuses ``seed`` exactly as before); a redraw
inside pass ``k`` keeps pass ``k``'s seed and still leaves the gateway cache; the opt-in is
benchmark identity, so it moves the revision.

Runs only with the `inspect` extra installed; the plain gate run skips it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("inspect_ai.model")

from inspect_ai.model import GenerateConfig, get_model  # noqa: E402
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.grading_accounting import (  # noqa: E402
    GradingEvidenceOwner,
    capture_grading_requests,
)
from screamingface_engine.grading_call_scope import grading_call_scope  # noqa: E402
from screamingface_engine.request_identity import (  # noqa: E402
    ModelRequestKey,
    model_request_key,
)
from screamingface_engine.request_scope import (  # noqa: E402
    RequestScope,
    current_scope,
    request_scope,
)
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BenchmarkSpec  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    MAX_JUDGE_PASS,
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.judge_redraw import judge_until_parsed  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from url4.wire.subrequest import (  # noqa: E402
    decode_subrequest_http,
    extract_expression_params,
)

#: The row's pinned judge params: what every pass must still send, unchanged and in order.
PINNED: tuple[tuple[str, str], ...] = (("temperature", "0"), ("max_tokens", "64"))


class _ScriptedFetch:
    """A fake node fetch: answers from a script and records each wire target plus the cache
    policy the connector would read at that moment."""

    def __init__(self, *replies: str) -> None:
        self.replies: list[str] = list(replies)
        self.targets: list[str] = []
        self.participation: list[bool | None] = []

    async def __call__(self, target: str) -> str:
        self.targets.append(target)
        # WHY read the scope here: the connector reads `current_scope().cache` at this point.
        self.participation.append(current_scope().cache.participate)
        return self.replies.pop(0)


def _params(target: str) -> tuple[tuple[str, str], ...]:
    """The wire params of one recorded target, decoded with the codec's own decoder."""

    params, _ = extract_expression_params(target.partition("?")[2])
    return tuple(params.items())


def _route_and_messages(target: str) -> tuple[str, str | None]:
    """The target without its params: the route and the encoded judge messages."""

    path, _, query = target.partition("?")
    return path, extract_expression_params(query)[1]


def _met_or_unmet(reply: str) -> bool | None:
    """A rubric item's parser: MET / UNMET, anything else is unparseable."""

    return {"MET": True, "UNMET": False}.get(reply.strip().upper())


@pytest.fixture
def run_scope() -> Iterator[RequestScope]:
    """A run's request scope that states no cache policy — the default, participating run."""

    with request_scope(RequestScope(origin="run")) as scope:
        yield scope


@scorer(metrics=[mean()])
def two_pass_rubric_judge() -> Scorer:
    """Stand-in for draco's judged scorer: one rubric item graded over 2 judge passes, the
    Case score the mean of the passes. It simulates only the pass loop a migrated draco Task
    runs; it does not prove draco's own prompt, weights or clamp."""

    async def score(state: TaskState, target: Target) -> Score:
        """Grade the reply once per pass, each pass naming its number as the judge seed."""

        judge = get_model("screamingface/judge-4", memoize=False)
        verdicts: list[bool] = []
        for judge_pass in (1, 2):
            judged = await judge_until_parsed(
                judge,
                f"Does this answer name Paris? {state.output.completion} Reply MET or UNMET.",
                _met_or_unmet,
                item=f"rubric r1 pass {judge_pass}",
                judge_pass=judge_pass,
            )
            verdicts.append(judged.verdict)
        return Score(value=sum(verdicts) / len(verdicts))

    return score


def _request() -> GradeRequest:
    """One Case the stand-in grades: a question, the Candidate's reply, its key."""

    return GradeRequest(
        case_id=3,
        input=TextPayload(text="What is the capital of France?"),
        answer=TextPayload(text="Paris."),
        row={"case": {"status": "answered"}},
        material={"target": "Paris"},
    )


@pytest.mark.asyncio
async def test_two_judge_passes_send_two_requests_differing_only_in_their_seed(
    run_scope: RequestScope,
) -> None:
    """The guarantee: pass 1 and pass 2 are two different requests, so the gateway cache
    cannot answer pass 2 with pass 1's reply; the row's pins ride both, unchanged, first."""

    fetch: _ScriptedFetch = _ScriptedFetch("MET", "UNMET")
    transport: JudgeTransport = JudgeTransport(fetch=fetch, params=PINNED, seed_per_pass=True)
    with bound_judge_transport(transport):
        outcome = await inspect_grade_case(two_pass_rubric_judge())(_request())
    assert (outcome.failure_code, outcome.score) == (None, 0.5)
    assert [_params(target) for target in fetch.targets] == [
        (*PINNED, ("seed", "1")),
        (*PINNED, ("seed", "2")),
    ]
    # Same route, same judge messages: the seed is the only difference between the passes.
    assert _route_and_messages(fetch.targets[0]) == _route_and_messages(fetch.targets[1])
    assert transport.params == PINNED
    # A first ask is an ordinary judge call: it keeps the run's cache policy, so a rerun of
    # the Benchmark may reuse each pass's slot (draco's hand-built behaviour).
    assert fetch.participation == [None, None]


def _connector_key(target: str) -> ModelRequestKey:
    """The accounting key the connector derives from one wire target, via the codec's decoders."""

    path, _, query = target.partition("?")
    params, q = extract_expression_params(query)
    assert q is not None
    context, intent = decode_subrequest_http(q)
    return model_request_key(path=path, params=params, context=context, intent=intent)


@pytest.mark.asyncio
async def test_each_pass_books_its_judge_cost_to_the_case_under_its_own_key(
    run_scope: RequestScope,
) -> None:
    """The cost join keys a judge call on its params: a pass registered under the row's pins
    alone would never match the seeded request the gateway bills, and its cost would drop
    off the Case."""

    fetch: _ScriptedFetch = _ScriptedFetch("MET", "MET")
    transport: JudgeTransport = JudgeTransport(
        fetch=fetch, params=PINNED, benchmark_id="bench", seed_per_pass=True
    )
    with (
        bound_judge_transport(transport),
        capture_grading_requests() as registry,
        grading_call_scope(3),
    ):
        outcome = await inspect_grade_case(two_pass_rubric_judge())(_request())
    assert outcome.score == 1.0
    owner: GradingEvidenceOwner = GradingEvidenceOwner(
        benchmark_id="bench", case_id=3, check_id="1", sequence=1
    )
    assert registry.keys_by_owner[owner] == {_connector_key(target) for target in fetch.targets}
    assert len(registry.keys_by_owner[owner]) == 2


@pytest.mark.asyncio
async def test_a_redraw_inside_a_pass_keeps_that_pass_seed_and_leaves_the_cache(
    run_scope: RequestScope,
) -> None:
    """A garbled pass-2 reply is redrawn with pass 2's seed (identical bytes), so the redraw
    must opt out of the gateway cache, or the cache would hand back the garbled text."""

    fetch: _ScriptedFetch = _ScriptedFetch("Let me think...", "MET")
    with bound_judge_transport(JudgeTransport(fetch=fetch, params=PINNED, seed_per_pass=True)):
        judged = await judge_until_parsed(
            get_model("screamingface/judge-4", memoize=False),
            "Reply MET or UNMET.",
            _met_or_unmet,
            item="rubric r1 pass 2",
            judge_pass=2,
        )
    assert (judged.verdict, judged.redraws) == (True, 1)
    assert fetch.targets[0] == fetch.targets[1]
    assert _params(fetch.targets[1]) == (*PINNED, ("seed", "2"))
    assert fetch.participation == [None, False]


@pytest.mark.asyncio
async def test_a_row_without_the_opt_in_still_refuses_a_seed() -> None:
    """INVARIANT (OME-1240): only a row that declared judge passes admits a per-call seed;
    every other row refuses it by name, exactly as before."""

    fetch: _ScriptedFetch = _ScriptedFetch("MET")
    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=fetch, params=PINNED)):
        with pytest.raises(RuntimeError, match=r"\['seed'\].*pinned params"):
            await model.generate("grade this", config=GenerateConfig(seed=1))
    assert fetch.targets == []


@pytest.mark.parametrize(
    "config",
    [
        GenerateConfig(seed=1, temperature=0.7),
        GenerateConfig(seed=1, reasoning_effort="high"),
        GenerateConfig(top_p=0.5),
    ],
    ids=["temperature-beside-a-pass", "reasoning-effort-beside-a-pass", "top-p-alone"],
)
@pytest.mark.asyncio
async def test_an_opted_in_row_still_refuses_every_other_per_call_setting(
    config: GenerateConfig,
) -> None:
    """The opt-in admits the pass number and nothing else: any other grade-affecting setting
    is refused by name, even when it arrives beside a valid pass."""

    fetch: _ScriptedFetch = _ScriptedFetch("MET")
    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=fetch, params=PINNED, seed_per_pass=True)):
        with pytest.raises(RuntimeError, match="pinned params"):
            await model.generate("grade this", config=config)
    assert fetch.targets == []


@pytest.mark.parametrize("judge_pass", [-1, MAX_JUDGE_PASS + 1, 2**31 - 1])
@pytest.mark.asyncio
async def test_a_seed_that_is_not_a_pass_number_is_refused(judge_pass: int) -> None:
    """A real seed (a hash, a timestamp) must not pass as a pass number: the scorer names a
    pass, the row's pinned mapping turns it into the seed."""

    fetch: _ScriptedFetch = _ScriptedFetch("MET")
    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=fetch, params=PINNED, seed_per_pass=True)):
        with pytest.raises(RuntimeError, match="judge pass"):
            await model.generate("grade this", config=GenerateConfig(seed=judge_pass))
    assert fetch.targets == []


def test_a_row_cannot_pin_a_seed_and_declare_judge_passes() -> None:
    """Two seeds on one call would be ambiguous: the declaration refuses at import time."""

    with pytest.raises(ValueError, match="seed"):
        JudgeSpec(model="judge-4", params=(("seed", "7"),), seed_per_pass=True)


def _judged_spec(judge: JudgeSpec) -> BenchmarkSpec:
    """One minimal judged row (reuses the gsm8k cases row), differing only in its judge."""

    values: dict[str, Any] = {
        "key": "gsm8k",
        "title": "Judged Test Benchmark",
        "description": "test",
        "focus": "test",
        "dataset_url": "https://example.test/ds",
        "difficulty": "easy",
        "scorer": "inspect_ai.scorer:model_graded_qa",
        "scorer_kwargs": {"model": "screamingface/judge-4"},
        "judge": judge,
        "with_check_surface": False,
    }
    return BenchmarkSpec(**values)


def _revision(spec: BenchmarkSpec, monkeypatch: pytest.MonkeyPatch) -> str:
    """Assemble one row through the real catalogue path, on fresh caches; its revision."""

    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    return str(benchmarks.imported_benchmark(spec.key).benchmark.revision)


def test_declaring_judge_passes_is_benchmark_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opting in changes how the judge is asked, so the revision moves; leaving the field at
    its default contributes nothing, so no published judged revision moves."""

    plain: str = _revision(_judged_spec(JudgeSpec(model="judge-4", params=PINNED)), monkeypatch)
    explicit_default: str = _revision(
        _judged_spec(JudgeSpec(model="judge-4", params=PINNED, seed_per_pass=False)), monkeypatch
    )
    opted_in: str = _revision(
        _judged_spec(JudgeSpec(model="judge-4", params=PINNED, seed_per_pass=True)), monkeypatch
    )
    assert plain == explicit_default
    assert opted_in != plain


@pytest.mark.asyncio
async def test_an_opted_in_row_refuses_a_judge_call_that_names_no_pass(
    run_scope: RequestScope,
) -> None:
    """A scorer on an opted-in row that forgets its pass number must fail by name: N unseeded
    passes are N identical requests, so the cache would serve one reply as a fake N-0 vote."""

    fetch: _ScriptedFetch = _ScriptedFetch("MET")
    with bound_judge_transport(JudgeTransport(fetch=fetch, params=PINNED, seed_per_pass=True)):
        with pytest.raises(RuntimeError, match=r"no pass number.*seed_per_pass"):
            # WHY through the redraw helper: judge_pass=None is the forgetful scorer's call.
            await judge_until_parsed(
                get_model("screamingface/judge-4", memoize=False),
                "Reply MET or UNMET.",
                _met_or_unmet,
                item="rubric r1",
            )
    assert fetch.targets == []
