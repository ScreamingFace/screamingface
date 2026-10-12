"""Refinement check: the text lowering path and the AST lowering path agree on observables.

Claim (dag/_lowering.py:603-612): for every accepted text s,
    run(s)  ≡  run(build(s))
where ≡ compares the OBSERVABLE behaviour: the result string (or the raised error's
type + code) and the MULTISET of fetch targets issued to the IO layer. Graph shape is
explicitly not part of the claim.

Run: pytest -q tests/test_lowering_equiv.py
"""

from __future__ import annotations

import asyncio
import warnings
from collections import Counter

from gen import grammar_text
from hypothesis import HealthCheck, assume, example, given, settings

from url4 import build
from url4.core.errors import ParseError, ResolutionError, Url4Error
from url4.dag import run
from url4.io.static import StaticIOLayer

warnings.simplefilter("ignore", DeprecationWarning)


class EchoIO(StaticIOLayer):
    """Deterministic world: every fetch echoes ``<target>``; ``/llm`` is the processor route."""

    def __init__(self) -> None:
        super().__init__(
            {},
            {"/llm": lambda ctx, intent: f"LLM[{intent}|{ctx}]"},
            holdings={"": "H", "emily": "E", "emily/notes": "N"},
        )
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        try:
            return await super().fetch(target, relative=relative)
        except ResolutionError:
            return f"<{target}>"


def observe(target) -> tuple:
    io = EchoIO()
    try:
        out = asyncio.run(asyncio.wait_for(run(target, io), 10))
        res = ("ok", out)
    except Url4Error as e:
        res = ("err", type(e).__name__, str(getattr(e, "code", "")))
    except Exception as e:  # noqa: BLE001 — a non-url4 crash is itself an observable
        res = ("crash", type(e).__name__)
    return res, Counter(io.fetches)


def observe_pair(s: str):
    try:
        tree = build(s)
    except ParseError:
        return None
    return observe(s), observe(tree)


S = settings(max_examples=1500, deadline=None, suppress_health_check=list(HealthCheck))


@S
@given(grammar_text)
@example("(a=https://a.io, /claude($a)!go)!sum")
@example("(x, (/p(https://n)!'go')!merge)!top")
def test_text_and_ast_paths_agree(s):
    pair = observe_pair(s)
    assume(pair is not None)
    (r_text, f_text), (r_ast, f_ast) = pair
    assert r_text == r_ast, f"result differs for {s!r}:\n text={r_text}\n  ast={r_ast}"
    assert f_text == f_ast, f"fetch multiset differs for {s!r}:\n text={f_text}\n  ast={f_ast}"
