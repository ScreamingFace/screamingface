# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""Redrawing a judge reply that doesn't parse (OME-1527 R3).

FEATURE: a Task scorer asks the judge again when its reply has no verdict, then fails the
Case by name. INVARIANTS the suite defends: an unparseable reply never becomes "not met";
a blank reply is unparseable too, and is redrawn like any other; only that error is redrawn;
a redraw leaves BOTH caches (inspect's and the AI Gateway's exact-request cache), because a
redraw sends identical bytes and a cache would hand back the same broken text; the redraw
keeps the first ask's accounting key, so its cost lands on the same Case; the redraw flag
ends with the redraw, so a later judge call is cacheable again.

Runs only with the `inspect` extra installed; the plain gate run skips it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai.model")

from inspect_ai.model import GenerateConfig, ModelOutput, get_model  # noqa: E402

from screamingface_engine.grading_accounting import (  # noqa: E402
    GradingEvidenceOwner,
    capture_grading_requests,
)
from screamingface_engine.grading_call_scope import grading_call_scope  # noqa: E402
from screamingface_engine.request_scope import (  # noqa: E402
    RequestScope,
    RequestScopeError,
    current_scope,
    request_scope,
)
from screamingface_engine.world.reply_origin import (  # noqa: E402
    ReplyOrigin,
    record_reply_origin,
)
from screamingface_engine_inspect import judge_redraw  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeFetch,
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.judge_redraw import (  # noqa: E402
    MAX_JUDGE_REDRAWS,
    JudgeReplyUnparseable,
    judge_until_parsed,
)
from url4.core.errors import ResolutionError  # noqa: E402

#: A reply with no verdict word — the shape a judge sends when it rambles or truncates.
GARBLED: str = "Let me think about whether the answer cites the source..."


def _met_or_unmet(reply: str) -> bool | None:
    """A rubric item's parser: MET / UNMET, anything else is unparseable."""

    word: str = reply.strip().upper()
    return {"MET": True, "UNMET": False}.get(word)


class _ScriptedFetch:
    """A fake node fetch: answers from a script and records, per call, the wire target and
    the cache policy the connector would read at that moment."""

    def __init__(self, *replies: str) -> None:
        self.replies: list[str] = list(replies)
        self.targets: list[str] = []
        self.participation: list[bool | None] = []

    async def __call__(self, target: str) -> str:
        self.targets.append(target)
        # WHY read the scope here: the connector reads `current_scope().cache` at exactly this
        # point (`_ModelEndpoint.__call__`), so what this sees is what the gateway is told.
        self.participation.append(current_scope().cache.participate)
        return self.replies.pop(0)


@pytest.fixture
def run_scope() -> Iterator[RequestScope]:
    """A run's request scope that states no cache policy — the default, participating run."""

    with request_scope(RequestScope(origin="run")) as scope:
        yield scope


async def _judge_through_gateway(fetch: JudgeFetch) -> tuple[bool, int]:
    """Judge one rubric item through the real gateway provider; return verdict + redraws."""

    with bound_judge_transport(JudgeTransport(fetch=fetch, benchmark_id="bench")):
        judged = await judge_until_parsed(
            get_model("screamingface/judge-4", memoize=False),
            "Does the answer cite the source? Reply MET or UNMET.",
            _met_or_unmet,
            item="case 7 rubric r2",
        )
    return judged.verdict, judged.redraws


@pytest.mark.asyncio
async def test_a_garbled_reply_is_redrawn_and_the_redraw_is_counted(
    run_scope: RequestScope,
) -> None:
    """One bad draw costs one redraw, not the Case: the second reply is the verdict."""

    fetch: _ScriptedFetch = _ScriptedFetch(GARBLED, "UNMET")
    verdict, redraws = await _judge_through_gateway(fetch)
    assert (verdict, redraws) == (False, 1)
    assert len(fetch.targets) == 2


@pytest.mark.asyncio
async def test_garbled_replies_past_the_redraw_budget_fail_the_item_by_name_never_as_not_met(
    run_scope: RequestScope,
) -> None:
    """After the budget the item raises, naming itself — a silent "not met" would be a
    silently wrong score (upstream healthbench's default)."""

    fetch: _ScriptedFetch = _ScriptedFetch(*[GARBLED] * (1 + MAX_JUDGE_REDRAWS))
    with pytest.raises(JudgeReplyUnparseable, match="case 7 rubric r2") as raised:
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 1 + MAX_JUDGE_REDRAWS
    # The reply head rides the message as audit evidence for the Case's judge_reply_invalid.
    assert GARBLED[:20] in str(raised.value)


@pytest.mark.asyncio
async def test_a_blank_reply_is_redrawn_and_counted_like_a_garbled_one(
    run_scope: RequestScope,
) -> None:
    """The provider refuses a blank completion before any parser sees it. Judges do send
    blanks (DRACO's reply format names `empty` as a rejection reason), so a blank must cost
    one redraw, not the Case."""

    fetch: _ScriptedFetch = _ScriptedFetch("   ", "MET")
    assert await _judge_through_gateway(fetch) == (True, 1)
    assert fetch.participation == [None, False]


@pytest.mark.asyncio
async def test_blank_replies_past_the_redraw_budget_fail_the_item_by_name(
    run_scope: RequestScope,
) -> None:
    """A judge that only ever sends blanks spends the same budget, then fails by name."""

    fetch: _ScriptedFetch = _ScriptedFetch(*[""] * (1 + MAX_JUDGE_REDRAWS))
    with pytest.raises(JudgeReplyUnparseable, match="case 7 rubric r2"):
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 1 + MAX_JUDGE_REDRAWS


@pytest.mark.asyncio
async def test_a_failed_judge_call_is_not_redrawn(run_scope: RequestScope) -> None:
    """Only a reply with no verdict is redrawn: a call that failed (here an upstream error,
    raised as a plain RuntimeError like the blank refusal's parent) propagates on the first
    ask, so a broken gateway never costs three calls per item."""

    calls: list[str] = []

    async def failing_fetch(target: str) -> str:
        """Fail the way an upstream error does — a raise, not a reply."""

        calls.append(target)
        raise RuntimeError("upstream 502")

    with pytest.raises(RuntimeError, match="upstream 502"):
        await _judge_through_gateway(failing_fetch)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_parseable_first_reply_keeps_the_runs_cache_policy(
    run_scope: RequestScope,
) -> None:
    """Only redraws leave the cache: a good first ask stays cacheable like any judge call."""

    fetch: _ScriptedFetch = _ScriptedFetch("MET")
    assert await _judge_through_gateway(fetch) == (True, 0)
    assert fetch.participation == [None]


@pytest.mark.asyncio
async def test_a_redraw_opts_out_of_the_gateway_cache_because_it_sends_identical_bytes(
    run_scope: RequestScope,
) -> None:
    """The redraw's wire request is byte-identical to the first ask, so the gateway's
    exact-request cache would answer it with the same broken text; only the opt-out
    (`participate=False` → body `cache: {"use-cache": false}`) makes it a fresh sample.
    Same bytes also mean the same accounting key, so the redraw's cost is this Case's."""

    fetch: _ScriptedFetch = _ScriptedFetch(GARBLED, "MET")
    with capture_grading_requests() as registry, grading_call_scope(7):
        assert await _judge_through_gateway(fetch) == (True, 1)
    assert fetch.targets[0] == fetch.targets[1]
    assert fetch.participation == [None, False]
    owner: GradingEvidenceOwner = GradingEvidenceOwner(
        benchmark_id="bench", case_id=7, check_id="1", sequence=1
    )
    assert list(registry.keys_by_owner) == [owner]
    assert len(registry.keys_by_owner[owner]) == 1
    # INVARIANT: the opt-out is scoped to the one redraw — the run's policy is untouched.
    assert current_scope().cache.participate is None


@pytest.mark.asyncio
async def test_the_redraw_flag_ends_with_the_redraw_so_the_next_item_keeps_the_cache(
    run_scope: RequestScope,
) -> None:
    """A scorer judges many items in one task. If the redraw flag outlived its redraw, every
    later judge call in that scorer would skip the gateway cache — a re-run would pay again
    for answers it already has."""

    fetch: _ScriptedFetch = _ScriptedFetch(GARBLED, "MET", "UNMET")
    assert await _judge_through_gateway(fetch) == (True, 1)
    assert await _judge_through_gateway(fetch) == (False, 0)
    # The second item's first ask is an ordinary judge call again.
    assert fetch.participation == [None, False, None]


# WHY the marker: the suite's autouse fixture binds a default scope; this test needs none.
@pytest.mark.no_default_scope
@pytest.mark.asyncio
async def test_a_redraw_with_no_request_scope_refuses_rather_than_rereading_the_cache() -> None:
    """With no scope to opt out of, a redraw cannot prove it left the cache — refuse loudly."""

    replies: list[str] = [GARBLED, "MET"]

    async def unscoped_fetch(target: str) -> str:
        """Answer without reading a scope — the first ask needs none."""

        return replies.pop(0)

    with (
        bound_judge_transport(JudgeTransport(fetch=unscoped_fetch)),
        pytest.raises(RequestScopeError),
    ):
        await judge_until_parsed(
            get_model("screamingface/judge-4", memoize=False),
            "Reply MET or UNMET.",
            _met_or_unmet,
            item="case 1 rubric r1",
        )
    # The first ask went out; the redraw never did.
    assert replies == ["MET"]


@pytest.mark.asyncio
async def test_an_eval_level_inspect_cache_never_serves_the_redraw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """inspect caches a call when the eval's GenerateConfig says so; a cached first ask would
    answer the identical redraw with the same garbled text. The helper's explicit
    `cache=False` wins over the eval's setting."""

    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    judge = get_model(
        "mockllm/model",
        config=GenerateConfig(cache=True),
        memoize=False,
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", GARBLED),
            ModelOutput.from_content("mockllm/model", "MET"),
        ],
    )
    judged = await judge_until_parsed(judge, "Reply MET or UNMET.", _met_or_unmet, item="i1")
    assert (judged.verdict, judged.redraws) == (True, 1)
    assert not any(tmp_path.rglob("*")), "the helper's calls must never write inspect's cache"


# --- a temporary gateway failure is asked again (review finding on PR #1387) -------------


class _FlakyFetch(_ScriptedFetch):
    """A scripted fetch whose script may also hold an HTTP status: that ask fails the way the
    connector fails a 429/5xx (``ResolutionError(permanent=False)``), instead of replying."""

    def __init__(self, *script: str | int) -> None:
        super().__init__()
        self.script: list[str | int] = list(script)

    async def __call__(self, target: str) -> str:
        self.targets.append(target)
        self.participation.append(current_scope().cache.participate)
        step: str | int = self.script.pop(0)
        if isinstance(step, int):
            # The real connector's raise for a non-2xx (`world/connector.py`
            # `_raise_for_status`): 429 and 5xx are the only non-permanent statuses.
            raise ResolutionError(
                f"aigateway request failed with status {step}",
                code=f"aigateway_http_{step}",
                permanent=not (step == 429 or 500 <= step < 600),
            )
        return step


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the backoff waits instead of sleeping them, with the jitter pinned to 0."""

    recorded: list[float] = []

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(judge_redraw, "_sleep", record)
    monkeypatch.setattr(judge_redraw, "_jitter", lambda low, high: 0.0)
    return recorded


@pytest.mark.asyncio
async def test_a_retry_after_a_gateway_5xx_still_participates_in_the_cache(
    run_scope: RequestScope, waits: list[float]
) -> None:
    """A 502 on one judge call costs one re-ask, not the Case (the hand-built `;retry=2` did
    the same; gdpval-text's golden lost 5 of 25 Cases to upstream errors). The re-ask keeps
    the cache: a 5xx stored nothing, and an opt-out would stop the good reply being stored."""

    fetch: _FlakyFetch = _FlakyFetch(502, "MET")
    assert await _judge_through_gateway(fetch) == (True, 0)
    assert fetch.participation == [None, None]
    assert waits == [0.5]


@pytest.mark.asyncio
async def test_once_a_reply_failed_to_parse_a_retry_after_a_5xx_stays_fresh(
    run_scope: RequestScope, waits: list[float]
) -> None:
    """The cache still holds the broken first reply, so the ask after a 502 must leave it too,
    or it would be handed that broken reply back and burn the last ask."""

    fetch: _FlakyFetch = _FlakyFetch(GARBLED, 503, "UNMET")
    assert await _judge_through_gateway(fetch) == (False, 1)
    assert fetch.participation == [None, False, False]


@pytest.mark.asyncio
async def test_a_gateway_that_keeps_failing_spends_the_shared_budget_then_names_the_gateway(
    run_scope: RequestScope, waits: list[float]
) -> None:
    """The budget is shared with redraws (3 asks, as `;retry=2`), so a down gateway costs at
    most 3 calls per item, and the Case fails with the gateway's error, not a fake verdict."""

    fetch: _FlakyFetch = _FlakyFetch(502, 502, 502)
    with pytest.raises(ResolutionError, match="status 502"):
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 1 + MAX_JUDGE_REDRAWS
    assert waits == [0.5, 1.0]


@pytest.mark.asyncio
async def test_a_permanent_gateway_error_is_never_asked_again(
    run_scope: RequestScope, waits: list[float]
) -> None:
    """A 400 will fail the same way every time; re-asking only spends money."""

    fetch: _FlakyFetch = _FlakyFetch(400, "MET")
    with pytest.raises(ResolutionError, match="status 400"):
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 1
    assert waits == []


# --- a recorded reply is final (spec 2026-10-16-judge-redraw-live-only) ----------------------
#
# FEATURE: a redraw happens only after a LIVE reply. A reply the gateway served from its cache,
# or a frozen copy replayed, is the recording: if it has no verdict, the item has no verdict.
# STORY: as someone replaying a recorded run (DRACO's reference seed), the replay reproduces the
# recorded score and never makes a paid judge call.


class _OriginFetch(_FlakyFetch):
    """A scripted fetch that also plays the connector's part: each reply records where it
    came from (``world/reply_origin.py``), exactly where the real connector records it."""

    def __init__(self, *script: tuple[str, ReplyOrigin] | int) -> None:
        super().__init__(*(step if isinstance(step, int) else step[0] for step in script))
        self.origins: list[ReplyOrigin | None] = [
            None if isinstance(step, int) else step[1] for step in script
        ]

    async def __call__(self, target: str) -> str:
        origin: ReplyOrigin | None = self.origins.pop(0)
        reply: str = await super().__call__(target)
        if origin is not None:
            record_reply_origin(origin)
        return reply


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["cache", "replay"])
async def test_a_recorded_reply_with_no_verdict_is_final_and_never_redrawn(
    run_scope: RequestScope, origin: ReplyOrigin
) -> None:
    """INVARIANT: one call, then the item has no verdict; nothing leaves the recording."""

    fetch: _OriginFetch = _OriginFetch((GARBLED, origin), ("MET", "live"))
    with pytest.raises(JudgeReplyUnparseable, match="case 7 rubric r2") as raised:
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 1
    assert fetch.participation == [None]
    assert raised.value.redraws == 0
    assert origin in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["cache", "replay"])
async def test_a_recorded_blank_reply_is_final_too(
    run_scope: RequestScope, origin: ReplyOrigin
) -> None:
    """A blank is refused by the provider before any parser; a recorded blank is still the
    recording, so it ends the item the same way."""

    fetch: _OriginFetch = _OriginFetch(("  ", origin), ("MET", "live"))
    with pytest.raises(JudgeReplyUnparseable, match="case 7 rubric r2"):
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 1


@pytest.mark.asyncio
async def test_a_live_reply_with_no_verdict_is_still_redrawn(run_scope: RequestScope) -> None:
    fetch: _OriginFetch = _OriginFetch((GARBLED, "live"), ("UNMET", "live"))
    assert await _judge_through_gateway(fetch) == (False, 1)
    assert fetch.participation == [None, False]


@pytest.mark.asyncio
async def test_a_recorded_reply_with_a_verdict_is_used_as_is(run_scope: RequestScope) -> None:
    fetch: _OriginFetch = _OriginFetch(("MET", "cache"))
    assert await _judge_through_gateway(fetch) == (True, 0)
    assert len(fetch.targets) == 1


@pytest.mark.asyncio
async def test_a_retry_after_a_5xx_still_happens_and_its_recorded_reply_is_final(
    run_scope: RequestScope, waits: list[float]
) -> None:
    """R3: a failure stores nothing, so the retry after a 502 is unchanged; the reply it gets
    from the cache is then the recording, and is not redrawn."""

    fetch: _OriginFetch = _OriginFetch(502, (GARBLED, "cache"), ("MET", "live"))
    with pytest.raises(JudgeReplyUnparseable):
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 2
    assert waits == [0.5]


@pytest.mark.asyncio
async def test_a_redraw_that_meets_a_recorded_reply_stops_there(run_scope: RequestScope) -> None:
    """A live garbled reply earns a redraw; should that redraw be answered from a recording
    (a frozen-copy replay), the recording is final."""

    fetch: _OriginFetch = _OriginFetch((GARBLED, "live"), (GARBLED, "replay"), ("MET", "live"))
    with pytest.raises(JudgeReplyUnparseable) as raised:
        await _judge_through_gateway(fetch)
    assert len(fetch.targets) == 2
    assert raised.value.redraws == 1


@pytest.mark.asyncio
async def test_spending_the_redraw_budget_reports_how_many_redraws_it_took(
    run_scope: RequestScope,
) -> None:
    """The failure carries its redraw count, so a scorer books what was spent, not a guess."""

    live_garbled: tuple[str, ReplyOrigin] = (GARBLED, "live")
    fetch: _OriginFetch = _OriginFetch(*[live_garbled] * (1 + MAX_JUDGE_REDRAWS))
    with pytest.raises(JudgeReplyUnparseable) as raised:
        await _judge_through_gateway(fetch)
    assert raised.value.redraws == MAX_JUDGE_REDRAWS
