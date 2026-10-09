"""The RDS code pointer over HTTP (row 24) and the E4a three-model vote spine (row 29).

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a group of named sources calls a remote scorer by a `url4://` code
# pointer, and the E4a three-model vote runs as one deterministic reducer call, so the scorer
# and the combine get their inputs as exact JSON and no model sees them.
#
# INVARIANT: the document carries every source's resolved text byte for byte, in source order,
# over an HTTP hop as well as in-process.
"""

from __future__ import annotations

import httpx
import pytest

from url4.core.context import Context
from url4.io.http import HttpIOLayer
from url4.peer.server import Request, Url4Node

# WHY: a newline is not authorable in url4 quoted text (raw control characters and `\n` are
# refused, see tests/spec/test_charclass_conformance.py), so it comes from a caller data route.
_ALPHABET_INTENT = "url4://scorer.test/score/v1?reducer=vote&extract=last_number@1"
_ALPHABET_EXPR = (
    r"""(lines:/lines, quote_text:'it\'s "fine"', escapes:'back\\slash', """
    r"""percent:'100% & (done) #1 + 2', unicode:'é 日 🎉', symbols:'!$*,;:@/?=')!"""
    + _ALPHABET_INTENT
)
_ALPHABET_INPUTS = {
    "lines": "first line\nsecond line",
    "quote_text": 'it\'s "fine"',
    "escapes": "back\\slash",
    "percent": "100% & (done) #1 + 2",
    "unicode": "é 日 🎉",
    "symbols": "!$*,;:@/?=",
}


@pytest.mark.asyncio
async def test_http_rds_inputs_are_byte_exact_and_ordered_over_an_asgi_hop() -> None:
    # WHY: PRD row 24 (H2 over HTTP) — the hard alphabet crosses a real HTTP hop byte-exact.
    # WHY: PRD row 24 (H4 over HTTP) — `@` in the code pointer's query survives the hop.
    seen: list[Request] = []
    scorer = Url4Node("scorer")

    @scorer.endpoint("/score/v1")
    async def score(request: Request) -> str:
        seen.append(request)
        return "OK"

    transport = httpx.ASGITransport(app=scorer.asgi())
    client = httpx.AsyncClient(transport=transport, base_url="https://scorer.test")
    caller = Url4Node("caller", outbound=HttpIOLayer(client=client))
    caller.data("/lines", "first line\nsecond line")

    result = await caller.evaluate(_ALPHABET_EXPR)

    assert result.text == "OK"
    (request,) = seen
    assert request.mode == "rds"
    assert request.intent == ""
    assert request.params == {"reducer": "vote", "extract": "last_number@1"}
    assert list(request.inputs or {}) == list(_ALPHABET_INPUTS)
    assert request.inputs == _ALPHABET_INPUTS


_M1 = 'Reasoning: "2 + 2" is 4, or 100%.\nANSWER: 4'
_M2 = "Half sure: it's 4, not 5.\nANSWER: 4"
_M3 = 'Guess "five" & #3 (roughly)\nANSWER: 5'
_E4A_EXPR = (
    r"""(member_1:/m1($input)!'P', member_2:/m2($input)!'P', member_3:/m3($input)!'P', """
    r"""extract_pattern:0.0:'ANSWER: \\d+')!/ensemble/combine/v1?reducer=vote"""
    r"""&extract=last_number@1&normalize=numeric@1&tie=first&min_votes=2"""
)
_E4A_PARAMS = {
    "reducer": "vote",
    "extract": "last_number@1",
    "normalize": "numeric@1",
    "tie": "first",
    "min_votes": "2",
}


@pytest.mark.asyncio
async def test_e4a_vote_runs_three_members_then_one_combine_call_with_exact_inputs() -> None:
    # WHY: PRD row 29 (E2E, the E4a 3-model vote) — the combine is called once with the three
    # member texts byte-exact and the weight-0.0 pattern, and no processor or process hook runs.
    combine_calls: list[Request] = []
    processor_calls: list[str] = []
    hook_calls: list[str] = []

    async def process(sources: str, intent: str | None, scope: Context) -> str:
        hook_calls.append(sources)
        return sources

    node = Url4Node("ensemble", default_processor="/claude", process_fn=process)

    @node.endpoint("/m1")
    async def member_1(request: Request) -> str:
        return _M1

    @node.endpoint("/m2")
    async def member_2(request: Request) -> str:
        return _M2

    @node.endpoint("/m3")
    async def member_3(request: Request) -> str:
        return _M3

    @node.endpoint("/ensemble/combine/v1")
    async def combine(request: Request) -> str:
        combine_calls.append(request)
        return "4"

    @node.endpoint("/claude")
    async def claude(request: Request) -> str:
        processor_calls.append(request.path)
        return "CLAUDE"

    result = await node.evaluate(_E4A_EXPR, env={"input": "What is 2 + 2?"})

    assert result.text == "4"
    (request,) = combine_calls
    assert request.mode == "rds"
    assert list(request.inputs or {}) == ["member_1", "member_2", "member_3", "extract_pattern"]
    # WHY: the expected texts are literals, not the endpoint constants, so a changed byte on
    # either side fails the row.
    assert request.inputs == {
        "member_1": 'Reasoning: "2 + 2" is 4, or 100%.\nANSWER: 4',
        "member_2": "Half sure: it's 4, not 5.\nANSWER: 4",
        "member_3": 'Guess "five" & #3 (roughly)\nANSWER: 5',
        "extract_pattern": "ANSWER: \\d+",
    }
    assert request.params == _E4A_PARAMS
    assert processor_calls == []
    assert hook_calls == []
