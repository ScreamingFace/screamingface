"""A Judge retry after an unparseable reply gets a fresh reply, not the cached garbled one.

FEATURE (OME-1533): a hand-built Benchmark nested each Judge call inside a verdict route whose
``;retry=`` asked the Judge again after ``judge_reply_invalid``. That retry sends the same bytes,
and the AI Gateway's global request cache has already stored the garbled reply (it stores any
successful reply), so before this fix every retry got the same garbled reply back and the Case
failed. The send-side rule lives in ``world/fresh_judge_retry.py``; these tests pin it.

OME-1527 moved every judged hand-built Benchmark to a local inspect Task: gdpval-text, draco,
then healthbench, whose verdict route was the last one wired this way. Their scorers redraw
through ``judge_redraw`` (its own cache opt-out is pinned by ``test_judge_redraw.py``), so the
end-to-end rubric-verdict tests went with the healthbench folder; the rule itself stays pinned
here.

STORY: as someone running a judged Benchmark with the hosted cache on, a garbled judge reply
costs one extra judge call, not the whole Case.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from screamingface_engine.benchmarks.failure_classes import JUDGE_REPLY_INVALID_CODE
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.world.fresh_judge_retry import scope_for_this_send
from url4.core.errors import ResolutionError
from url4.dag import GuardNode, GuardRetry, current_guard_retry, run
from url4.io.static import StaticIOLayer
from url4.streaming.protocol import CachePolicy

pytestmark = pytest.mark.asyncio

# --- the helper on its own: what an opted-out send keeps ----------------------------------


class _ScopePerSend:
    """A guarded stand-in leaf that records the scope each send would run under.

    It simulates the connector reading the retry and the scope at call time (the same two
    lines); the failure codes it raises are the ones a verdict route (``judge_reply_invalid``)
    or the connector (``upstream_error``) would raise. It does not exercise a real route.
    """

    deps: dict = {}

    def __init__(self, scope: RequestScope, *failure_codes: str) -> None:
        self._scope = scope
        self._failure_codes: list[str] = list(failure_codes)
        self.scopes: list[RequestScope] = []

    async def resolve(self, inputs: object, ctx: object) -> str:
        """Record this send's scope, then fail with the next scripted code or answer."""
        retry: GuardRetry | None = current_guard_retry()
        self.scopes.append(
            scope_for_this_send(self._scope, None if retry is None else retry.failure_code)
        )
        if self._failure_codes:
            raise ResolutionError("send failed", code=self._failure_codes.pop(0))
        return "answer"


_CALLER_SCOPE = RequestScope(
    identity_headers={"X-Example-Identity": "caller"},
    answer_seed=7,
    cache=CachePolicy(participate=True, max_age=60),
    origin="sync",
    deadline=123.0,
)


async def test_an_opted_out_retry_changes_only_the_cache_policy() -> None:
    # WHY: the retry must still bill and log as the same caller with the same seed; only the
    # cache control may differ, or the fix would leak into identity or attribution.
    leaf = _ScopePerSend(_CALLER_SCOPE, JUDGE_REPLY_INVALID_CODE)

    assert await run(GuardNode(leaf, retries=1), StaticIOLayer()) == "answer"

    first, retry = leaf.scopes
    assert first is _CALLER_SCOPE
    assert retry.cache == CachePolicy(participate=False)
    assert replace(retry, cache=_CALLER_SCOPE.cache) == _CALLER_SCOPE


async def test_a_retry_after_any_other_failure_keeps_the_callers_scope() -> None:
    # WHY: only an unusable-but-successful Judge reply is stored and echoed by the cache; a
    # retry after an upstream failure must keep storing its good reply.
    leaf = _ScopePerSend(_CALLER_SCOPE, "upstream_error", "timeout")

    assert await run(GuardNode(leaf, retries=2), StaticIOLayer()) == "answer"

    assert all(scope is _CALLER_SCOPE for scope in leaf.scopes)


async def test_an_unguarded_call_keeps_the_callers_scope() -> None:
    assert scope_for_this_send(_CALLER_SCOPE, None) is _CALLER_SCOPE
