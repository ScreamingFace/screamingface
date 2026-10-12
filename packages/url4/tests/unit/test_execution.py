"""End-to-end execution: the single-source pipeline, scope substitution, process().

Ported from the pre-DAG interpreter suite — assertions unchanged, entry point
rewritten from ``Interpreter(resolver).evaluate(expr)`` to ``run(expr, resolver)``.
"""

from __future__ import annotations

import pytest
from conftest import RecordingIOLayer

from url4.core.context import Context
from url4.dag import run
from url4.io.static import StaticIOLayer


@pytest.mark.asyncio
async def test_single_source_fetch_and_intent() -> None:
    resolver = StaticIOLayer(fetch_map={"https://x": "ARTICLE"})
    result = await run("https://x!'summarize'", resolver)
    assert result == "summarize\n\nARTICLE"


@pytest.mark.asyncio
async def test_named_binding_substitution_in_intent() -> None:
    resolver = StaticIOLayer(fetch_map={"https://x": "ARTICLE"})
    result = await run("(article=https://x)!use $article", resolver)
    # `OME-534`: the name-only source interpolates AND packs as a labeled line.
    assert result == "use ARTICLE\n\narticle: ARTICLE"


@pytest.mark.asyncio
async def test_positional_reference() -> None:
    resolver = StaticIOLayer(fetch_map={"https://x": "X", "https://y": "Y"})
    result = await run("(https://x, https://y)!first=$1 second=$2", resolver)
    assert "first=X second=Y" in result


@pytest.mark.asyncio
async def test_dollar_escape() -> None:
    result = await run("()!it costs $$5", RecordingIOLayer())
    assert result == "it costs $5"


@pytest.mark.asyncio
async def test_unknown_variable_left_verbatim() -> None:
    result = await run("()!hello $nobody", RecordingIOLayer())
    assert result == "hello $nobody"


@pytest.mark.asyncio
async def test_quoted_text_source_strips_quotes() -> None:
    # Quotes are DELIMITERS (spec §5.1): a quoted source resolves to its
    # content, everywhere — the pre-0.2 Url4Text quote-keeping quirk is gone.
    result = await run("('formal')!'tone'", RecordingIOLayer())
    assert result == "tone\n\nformal"


@pytest.mark.asyncio
async def test_later_source_sees_earlier_binding() -> None:
    resolver = StaticIOLayer(fetch_map={"https://x": "SHARED"})
    result = await run("(a=https://x, b='$a again')!$b", resolver)
    # Quotes are delimiters; $a substitutes inside the (unquoted) content.
    # `OME-534`: both named sources pack as labeled lines after the intent.
    assert result == "SHARED again\n\na: SHARED\nb: SHARED again"


@pytest.mark.asyncio
async def test_overridable_process() -> None:
    async def shout(sources: str, intent: str | None, scope: Context) -> str:
        return (intent or "").upper()

    result = await run("()!'shout'", RecordingIOLayer(), process=shout)
    assert result == "SHOUT"


@pytest.mark.asyncio
async def test_run_accepts_prebuilt_parse_tree() -> None:
    from url4.core.parser import Parser

    tree = Parser().build("https://x!'go'")
    resolver = StaticIOLayer(fetch_map={"https://x": "DATA"})
    assert await run(tree, resolver) == "go\n\nDATA"


@pytest.mark.asyncio
async def test_run_default_io_creates_and_closes_owned_adapter(monkeypatch) -> None:
    # F4: the batteries-included default (io=None) is the first thing the
    # README quickstart shows, yet every other test injects an io/ctx — so the
    # default path (lazily create an HttpIOLayer, then close it in run()'s
    # finally) is uncovered. Patch the adapter the executor imports so we observe
    # the lifecycle without a real network round-trip: exactly one adapter is
    # created, its fetch is used to resolve the source, and it is closed.
    import url4.io.http as io_http

    created: list = []

    class FakeHttpIOLayer:
        def __init__(self) -> None:
            self.closed = False
            created.append(self)

        async def fetch(self, target: str, *, relative: bool) -> str:
            return target  # echo the URL so the source resolves

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(io_http, "HttpIOLayer", FakeHttpIOLayer)

    result = await run("https://x!'go'")  # no io → batteries-included default
    assert result == "go\n\nhttps://x"
    assert len(created) == 1
    assert created[0].closed is True


@pytest.mark.asyncio
async def test_run_default_io_closes_even_when_execution_raises(monkeypatch) -> None:
    # F4: the finally-close must run even when the run fails, so the owned
    # client never leaks on a failed expression. A fetch that raises resolves to
    # a Url4Error; the adapter must still be closed.
    import url4.io.http as io_http
    from url4.core.errors import ResolutionError

    closed = {"yes": False}

    class FailingHttpIOLayer:
        def __init__(self) -> None:
            pass

        async def fetch(self, target: str, *, relative: bool) -> str:
            raise ResolutionError("boom")

        async def aclose(self) -> None:
            closed["yes"] = True

    monkeypatch.setattr(io_http, "HttpIOLayer", FailingHttpIOLayer)
    with pytest.raises(ResolutionError, match="boom"):
        await run("https://x!'go'")
    assert closed["yes"] is True
