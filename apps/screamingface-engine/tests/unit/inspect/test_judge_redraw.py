# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""Redrawing a judge reply that doesn't parse (OME-1527 R3).

FEATURE: a Task scorer asks the judge again when its reply has no verdict, then fails the
Case by name. INVARIANTS the suite defends: an unparseable reply never becomes "not met";
a redraw leaves BOTH caches (inspect's and the AI Gateway's exact-request cache), because a
redraw sends identical bytes and a cache would hand back the same broken text; the redraw
keeps the first ask's accounting key, so its cost lands on the same Case.

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
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.judge_redraw import (  # noqa: E402
    MAX_JUDGE_REDRAWS,
    JudgeReplyUnparseable,
    judge_until_parsed,
)

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


async def _judge_through_gateway(fetch: _ScriptedFetch) -> tuple[bool, int]:
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
    # The reply head rides the message as audit evidence for the Case's scorer_error.
    assert GARBLED[:20] in str(raised.value)


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
