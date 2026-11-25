"""A C19 form in a context the receiver parses is forwarded as is, and refused there.

FEATURE: Router Recipe extension, contract C19. Three contexts are the receiver's to parse,
never the caller's: a remote call's (C6, OME-535), a relative reducer's (it ships to its route
with the rows as the intent) and one that holds a holdings ref (spec §5.6.3.1/.2, OME-1945).
The caller forwards each byte for byte; a receiving node of this version refuses a malformed
mark at its own entry. A relative call's own context is the caller's: it refuses there
(``test_at_most_one_texts`` pins every such text).

STORY: as a Fusion author, a mark I wrote wrong in a request another node parses fails on that
node, before it fetches anything; the calling node never reads into it.
"""

from __future__ import annotations

import pytest

from url4 import StaticIOLayer, Url4Node
from url4.core.at_most_one import AtMostOneFormError
from url4.core.context import Context
from url4.dag import run
from url4.wire.subrequest import decode_subrequest, extract_expression_params

BAD = "*m:https://two;required;expand.at_most_one=false"


class _LoggedIO(StaticIOLayer):
    """Records every fetch; a relative or ``url4://`` request answers ``FORWARDED``."""

    def __init__(self) -> None:
        super().__init__(fetch_map={"https://a": "A", "https://list": '["1","2"]'})
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        if relative or target.startswith("url4://"):
            return "FORWARDED"
        return await super().fetch(target, relative=relative)


async def _done(sources: str, intent: str | None, scope: Context) -> str:
    return "done"


_FORWARDED = {
    "remote-call": (
        f"(url4://n2.example/v1({BAD})!'Describe')!'Summarize'",
        "url4://n2.example/v1",
        (BAD, "Describe"),
    ),
    "relative-reducer": (
        f"(https://list*(a:https://a)!'per')!/r({BAD})!'reduce'",
        "/r",
        (BAD, '["done", "done"]'),
    ),
    "holdings-context": (f"/p(@, {BAD})!'i'", "/p", (f"@, {BAD}", "i")),
}
_CASES = pytest.mark.parametrize(
    ("text", "path", "sent"), list(_FORWARDED.values()), ids=list(_FORWARDED)
)


async def _forwarded(text: str, path: str) -> tuple[str, list[str]]:
    """Run ``text`` on the caller; return the one request sent to ``path`` and every fetch."""
    io = _LoggedIO()
    await run(text, io, process=_done)
    (target,) = [fetch for fetch in io.fetches if fetch.startswith(f"{path}?")]
    return target, io.fetches


@_CASES
@pytest.mark.asyncio
async def test_a_receiver_owned_context_is_forwarded_byte_for_byte(
    text: str, path: str, sent: tuple[str, str]
) -> None:
    # INVARIANT: the caller neither refuses nor resolves the marked source in such a context:
    # it fetches nothing the mark names and sends the context unchanged. For the reducer, the
    # rows travel as the intent.
    target, fetches = await _forwarded(text, path)
    assert "https://two" not in fetches
    _params, query = extract_expression_params(target.partition("?")[2])
    assert query is not None
    assert decode_subrequest(query) == sent


@_CASES
@pytest.mark.asyncio
async def test_a_receiving_node_refuses_the_forwarded_c19_form_at_its_entry(
    text: str, path: str, sent: tuple[str, str]
) -> None:
    # WHY: forwarding stays safe because the receiver checks C19 at its own entry. Each request
    # is evaluated as a node's eval path evaluates it; nothing is fetched before the refusal.
    target, _ = await _forwarded(text, path)
    receiver_io = _LoggedIO()
    receiver = Url4Node("n2", outbound=receiver_io)
    with pytest.raises(AtMostOneFormError):
        await receiver.fetch(f"/v1?{target.partition('?')[2]}", relative=True)
    assert receiver_io.fetches == []


@pytest.mark.asyncio
async def test_a_relative_call_s_own_context_is_refused_by_the_caller() -> None:
    # WHY the contrast: the same mark in a relative call's own context is the caller's to read.
    io = _LoggedIO()
    with pytest.raises(AtMostOneFormError):
        await run(f"/p({BAD})!'i'", io, process=_done)
    assert io.fetches == []
