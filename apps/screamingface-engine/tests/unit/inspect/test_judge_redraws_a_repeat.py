# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A scorer's own re-ask, in the same words, is a new draw on a row that declares it.

FEATURE: OME-1478 PR 1 of 2 (review finding on #1631). HLE's ``regex_judge`` asks its judge
up to three times (``max_grader_attempts=3``) when a reply has no ``GRADE: C/I``, and each
re-ask sends the very same bytes. The AI Gateway's exact-request cache (on by default) keeps
any successful reply, an unparseable one included, so without help the second and third asks
get the first reply back and HLE's three attempts shrink to one. A row that sets
``JudgeSpec(redraw_repeats=True)`` makes a re-ask after a LIVE reply skip the cache, as
inspect's own ``eval()`` would draw again. A reply that came from the cache or a frozen copy
stays final, so a replay grades as it was recorded (spec 2026-10-16-judge-redraw-live-only).

INVARIANT the suite defends: a row that does not opt in sends exactly what it sent before,
and no redraw ever follows a recorded reply.

Stand-ins: ``_CachingGateway`` stands in for the node's model route AND the gateway's cache.
It answers a fresh request live (first a reply with no grade, then ``GRADE: C``), serves a
repeat from its store unless the scope opts out of the cache, and reports each reply's origin
the way the connector does. HLE's scorer is HLE's own.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.request_scope import (  # noqa: E402
    RequestScope,
    current_scope,
    request_scope,
)
from screamingface_engine.world.reply_origin import ReplyOrigin, record_reply_origin  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
    judge_filling_model_role,
)
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402

#: HLE's default.yaml judge stanza, as the row pins it.
_PINS: tuple[tuple[str, str], ...] = (("temperature", "0"), ("max_tokens", "32768"))

#: The live judge's replies in order: the first has no grade line, the second grades.
_LIVE_REPLIES: tuple[str, ...] = ("I think the response is probably fine.", "GRADE: C")


class _CachingGateway:
    """A stand-in route plus exact-request cache: live replies in order, repeats from the store
    unless the scope opts out, each reply's origin recorded as the connector records it."""

    def __init__(self, first_origin: ReplyOrigin = "live") -> None:
        self.live: list[str] = list(_LIVE_REPLIES)
        self.store: dict[str, str] = {}
        self.first_origin: ReplyOrigin = first_origin
        self.cache_skipped: list[bool] = []

    async def __call__(self, target: str) -> str:
        skip: bool = current_scope().cache.participate is False
        self.cache_skipped.append(skip)
        if target in self.store and not skip:
            record_reply_origin("cache")
            return self.store[target]
        reply: str = self.live.pop(0)
        record_reply_origin("live" if self.store or skip else self.first_origin)
        self.store[target] = reply
        return reply


async def _grade(gateway: _CachingGateway, redraw_repeats: bool) -> Any:
    """Grade one HLE Case with HLE's real regex_judge (3 attempts) through the gateway judge."""

    from inspect_evals.hle.scorers import regex_judge

    request = GradeRequest(
        case_id=3,
        input=TextPayload(text="What is the capital of France?"),
        answer=TextPayload(text="Explanation: it is Paris.\nAnswer: Paris\nConfidence: 80%"),
        row={"case": {"status": "answered"}},
        material={"target": "Paris"},
    )
    transport = JudgeTransport(fetch=gateway, params=_PINS, redraw_repeats=redraw_repeats)
    with (
        request_scope(RequestScope(origin="run")),
        judge_filling_model_role("grader", "judge-4"),
        bound_judge_transport(transport),
    ):
        scorer = regex_judge(
            template="regex_judge_template",
            instructions="regex_judge_instructions",
            grader_role="grader",
            max_grader_attempts=3,
        )
        return await inspect_grade_case(scorer, named_scores=("score", "confidence"))(request)


@pytest.mark.asyncio
async def test_a_re_ask_after_a_live_unparseable_reply_is_a_new_draw() -> None:
    """The payoff: attempt 2 skips the cache, the live judge grades, the Case scores 1.0."""

    gateway = _CachingGateway()

    outcome: Any = await _grade(gateway, redraw_repeats=True)

    assert outcome.failure_code is None
    assert outcome.score == 1.0
    assert gateway.cache_skipped == [False, True]


@pytest.mark.asyncio
async def test_without_the_declaration_a_re_ask_gets_the_stored_reply_as_before() -> None:
    """The bug the declaration fixes, and proof a row that does not opt in is unchanged: all
    three attempts read the first, unparseable reply, so the Case fails."""

    gateway = _CachingGateway()

    outcome: Any = await _grade(gateway, redraw_repeats=False)

    assert outcome.failure_code is not None
    assert gateway.cache_skipped == [False, False, False]


@pytest.mark.asyncio
async def test_a_recorded_first_reply_is_never_redrawn() -> None:
    """WHY: a reply from the cache or a frozen copy is final, so a replay grades as recorded;
    redrawing it would make a live call the recording never had."""

    gateway = _CachingGateway(first_origin="cache")

    outcome: Any = await _grade(gateway, redraw_repeats=True)

    assert outcome.failure_code is not None
    assert gateway.cache_skipped == [False, False, False]
