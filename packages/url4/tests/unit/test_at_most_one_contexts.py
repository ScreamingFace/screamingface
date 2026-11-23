"""A C19 form in a relative call's context: refused by the caller as lowering would read it.

FEATURE: Router Recipe extension, contract C19. A relative call's context is the caller's to
read (``test_at_most_one_receivers`` pins the contexts that are not). The entry check reads it
as lowering does: whether it holds a holdings ref is a question about its structure, which the
mark must not change, and each segment is a deferred group or a grammar source alike in both.

STORY: as a Fusion author, a mark I wrote wrong beside an email, a URL with a user or a
group that fails on another rule fails at once, before the run fetches or calls anything.
"""

from __future__ import annotations

import pytest

from url4 import StaticIOLayer, build
from url4.core.at_most_one import AtMostOneFormError
from url4.core.context import Context
from url4.core.errors import ErrorCode
from url4.core.nodes import Node
from url4.dag import compile_expression, run
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes

KEY = "expand.at_most_one"
BAD = f"*m:https://two;required;{KEY}=false"
IMG = "https://example.com/pic.png"


class _LoggedIO(StaticIOLayer):
    """Records every fetch, text and bytes alike; a request to ``/ep`` answers ``FORWARDED``."""

    def __init__(self) -> None:
        super().__init__(
            fetch_map={"/a": "A", "https://user@host/a": '["one"]'},
            media_types={IMG: "image/png"},
        )
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        if target.startswith("/ep?"):
            return "FORWARDED"
        return await super().fetch(target, relative=relative)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.fetches.append(request.target)
        return await super().fetch_bytes(request)


class _Calls:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    async def __call__(self, sources: str, intent: str | None, scope: Context) -> str:
        self.calls.append(intent)
        return "done"


async def _refused(target: str | Node) -> None:
    """Run ``target`` and assert a C19 refusal with no fetch and no call."""
    io, process = _LoggedIO(), _Calls()
    with pytest.raises(AtMostOneFormError) as caught:
        await run(target, io, process=process)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert (io.fetches, process.calls) == ([], [])


# --- an "@" that is not a holdings ref ------------------------------------------------------

_AT_SIGNS = {
    "quoted-email": f"*m:'user@example.com';{KEY}=true",
    "url-with-a-user": f"*m:https://user@host/a;{KEY}=true",
    "valued-mark-beside-an-email": f"*m:'user@example.com';required;{KEY}=false",
    "sibling-in-a-nested-group": f"(a:'x@y', *m:/a;{KEY}=true)!'q'",
}


@pytest.mark.parametrize("context", list(_AT_SIGNS.values()), ids=list(_AT_SIGNS))
@pytest.mark.asyncio
async def test_an_at_sign_in_data_never_makes_a_c19_context_receiver_owned(context: str) -> None:
    # INVARIANT: an "@" in quoted text or a URL is data, not a holdings ref, mark or no mark.
    # Before, the C19 error made the segment unreadable, an unreadable segment with an "@"
    # counted as a holdings ref, and the broken mark shipped to the route verbatim.
    text = f"(/a, /ep({context})!'out')!'r'"
    for target in (text, build(text)):
        await _refused(target)
        with pytest.raises(AtMostOneFormError):
            compile_expression(target)


_HOLDINGS = {
    "own-segment": f"{BAD}, @alice",
    "nested-group": f"(@, {BAD})!'q'",
}


@pytest.mark.parametrize("context", list(_HOLDINGS.values()), ids=list(_HOLDINGS))
@pytest.mark.asyncio
async def test_a_real_holdings_ref_still_ships_the_context_verbatim(context: str) -> None:
    # WHY the control: a context that holds a holdings ref is the receiving route's to parse
    # (spec §5.6.3.1/.2), so a broken mark in it still ships as written.
    io, process = _LoggedIO(), _Calls()
    assert await run(f"/ep({context})!'i'", io, process=process) == "FORWARDED"
    (request,) = io.fetches
    assert f"{KEY}=false" in request
    assert process.calls == []


@pytest.mark.asyncio
async def test_a_well_formed_mark_beside_a_url_user_resolves_on_the_caller() -> None:
    io, process = _LoggedIO(), _Calls()
    text = f"/ep(*m:https://user@host/a;required;{KEY}=true)!'i'"
    assert await run(text, io, process=process) == "FORWARDED"
    assert io.fetches == ["https://user@host/a", "/ep?q=(m:%20one)!%27i%27"]


# --- a group the text path defers --------------------------------------------------------------

_DEFERRED = {
    "mark-after-the-group": f"(img:{IMG};accept=image/png, /ep((a;1=2)!'i', {BAD})!'out')!'r'",
    "mark-in-a-later-group": f"(/a, /ep((bad;1=2)!'i', ({BAD})!'y')!'out')!'r'",
}


@pytest.mark.parametrize("text", list(_DEFERRED.values()), ids=list(_DEFERRED))
@pytest.mark.asyncio
async def test_a_deferred_group_that_fails_on_another_rule_never_hides_a_c19_error(
    text: str,
) -> None:
    # INVARIANT: lowering reads a group the text path may defer as a source without parsing
    # its sources, so the entry check does too; it read such a group with the eager grammar,
    # took the context for prose and let the run fetch the image, or compile the call and fail
    # at run time on the other error.
    for target in (text, build(text)):
        await _refused(target)
        with pytest.raises(AtMostOneFormError):
            compile_expression(target)


def test_a_deferred_group_that_fails_on_another_rule_alone_still_compiles() -> None:
    # The base behavior: the group's error is met when it runs.
    compile_expression("/ep((bad;1=2)!'i', b:/b)!'out'")


# --- tenth review: a context too deep for the holdings-ref reading ----------------------------

_DEPTH = 300  # WHY: past the eager parser's reach (about 140 nested groups), not the compiler's


def _deep(bottom: str) -> str:
    for _ in range(_DEPTH):
        bottom = f"(/b(y)!'w', {bottom})!'h'"
    return bottom


_DEEP_MARKED = f"/p({_deep(f'*m:https://one;required;{KEY}=true')})!'i'"
_DEEP_UNMARKED = f"/p({_deep('b:https://one')})!'i'"


@pytest.mark.asyncio
async def test_a_context_too_deep_to_read_is_refused_when_it_names_the_mark() -> None:
    # INVARIANT (FAIL CLOSED): a context too deep for the eager parser cannot be read, so one
    # that names the mark is refused, a well-formed mark included. Before, the holdings-ref
    # reading met the depth first and the run escaped as a RecursionError, an HTTP 500.
    await _refused(f"(/a, {_DEEP_MARKED})!'r'")
    with pytest.raises(AtMostOneFormError, match="nested too deeply"):
        compile_expression(_DEEP_MARKED)


def test_a_context_too_deep_to_read_without_the_mark_is_not_c19_s_to_refuse() -> None:
    # WHY: a context that names the mark nowhere has no C19 form to check; it keeps its base
    # outcome, a RecursionError in lowering today.
    try:
        compile_expression(_DEEP_UNMARKED)
    except AtMostOneFormError:
        pytest.fail("a context with no mark was refused as C19")
    except RecursionError:
        pass  # the base outcome
