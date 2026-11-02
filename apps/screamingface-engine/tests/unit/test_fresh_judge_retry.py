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

import ast
from dataclasses import replace
from pathlib import Path

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


# --- no route raises a retryable judge_reply_invalid (spec 2026-10-16-judge-redraw-live-only) ---

_SOURCE_ROOT: Path = Path(__file__).parents[2] / "src"
_FAILURE_CLASSES: Path = _SOURCE_ROOT / "screamingface_engine" / "benchmarks" / "failure_classes.py"


def _retryable_judge_reply_invalid_sites(tree: ast.Module) -> list[int]:
    """Lines that call ``judge_failure(...)``, or build an error with code
    ``judge_reply_invalid`` and no ``permanent=True``."""

    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name: str | None = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        keywords: dict[str | None, ast.expr] = {kw.arg: kw.value for kw in node.keywords}
        code: ast.expr | None = keywords.get("code")
        names_the_code: bool = (
            isinstance(code, ast.Name) and code.id == "JUDGE_REPLY_INVALID_CODE"
        ) or (isinstance(code, ast.Constant) and code.value == JUDGE_REPLY_INVALID_CODE)
        permanent: ast.expr | None = keywords.get("permanent")
        is_permanent: bool = isinstance(permanent, ast.Constant) and permanent.value is True
        if name == "judge_failure" or (names_the_code and not is_permanent):
            lines.append(node.lineno)
    return lines


async def test_no_production_route_raises_a_retryable_judge_reply_invalid() -> None:
    """INVARIANT (AIDEV-NOTE in ``world/fresh_judge_retry.py``): a recorded Judge reply is final,
    and today no route can hand the guard a RETRYABLE ``judge_reply_invalid`` (the combine
    Judge's becomes permanent in ``world/combine.py``). A new raise site fails here until it
    reads the reply's origin and raises a recorded reply as permanent, then is exempted here."""

    offenders: list[str] = [
        f"{path.relative_to(_SOURCE_ROOT)}:{line}"
        for path in sorted(_SOURCE_ROOT.rglob("*.py"))
        if path != _FAILURE_CLASSES
        for line in _retryable_judge_reply_invalid_sites(ast.parse(path.read_text()))
    ]
    assert offenders == []
