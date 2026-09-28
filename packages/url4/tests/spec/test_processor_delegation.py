"""`OME-506` — `processor=` delegation (§27.3), all three value forms.

# FEATURE: a caller selects which processor handles an intent — by id, by URI, or
# by an expression that computes one — and a fan-out reduce dispatches there.
#
# The disambiguation rule (§27.3): starts with "(" → expression; contains "://" →
# URI; otherwise → id. A "/"-leading value is a route path, which is what
# `default_route()` has always returned and what existing callers pass.
"""

from __future__ import annotations

import asyncio

import pytest

from url4.core.errors import ResolutionError
from url4.dag import run
from url4.io.static import StaticIOLayer


class _RecordingIO:
    """Registry-less adapter: records fetches, implements no optional ports."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append((target, relative))
        return "resolved"


def _routes_io() -> StaticIOLayer:
    return StaticIOLayer(
        routes={
            "/claude": lambda context, intent: f"claude:{intent}",  # noqa: ARG005
            "/gpt4": lambda context, intent: f"gpt4:{intent}",  # noqa: ARG005
        }
    )


_FANOUT = "(/claude(a)!x, /gpt4(b)!y)!combine"


# --- Form 1: processor-id -----------------------------------------------------------


def test_bare_id_resolves_to_a_registered_route() -> None:
    io = _routes_io()
    assert asyncio.run(run(_FANOUT, io, processor="gpt4")).startswith("gpt4:")


def test_unknown_id_raises_and_names_the_declared_routes() -> None:
    io = _routes_io()
    with pytest.raises(ResolutionError) as exc:
        asyncio.run(run(_FANOUT, io, processor="nope"))
    message = str(exc.value)
    assert "nope" in message
    assert "/claude" in message, "the error must list what IS available"


# --- Form 2: processor-uri ----------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    ["url4://node.example/p", "https://host.example/p", "http://host.example/p"],
)
def test_uri_processor_dispatches_absolutely(uri: str) -> None:
    io = _RecordingIO()
    asyncio.run(run(_FANOUT, io, processor=uri))
    # INVARIANT: a URI processor is NOT a localhost route — it must be fetched
    # absolute, or it would be resolved against the current node.
    absolute = [(t, rel) for t, rel in io.calls if t.startswith(uri)]
    assert absolute, f"no absolute fetch of {uri!r} in {io.calls}"
    assert all(rel is False for _t, rel in absolute)


# --- Form 3: expression-body --------------------------------------------------------


def test_expression_processor_is_evaluated_then_dispatched() -> None:
    io = _routes_io()
    # The instrumental (`OME-534` weight-0.0) source keeps the expression's
    # result the pure "/gpt4" interpolation, which is then the route.
    result = asyncio.run(run(_FANOUT, io, processor="(p:0:'/gpt4')!'$p'"))
    assert result.startswith("gpt4:")


def test_expression_result_is_not_re_evaluated() -> None:
    # INVARIANT: re-classification is single-pass. A result that itself looks
    # like an expression is not evaluated again — that would be unbounded.
    # Here the inner text resolves to the literal "('/gpt4')", which is
    # expression-shaped; it must be refused rather than evaluated a second time.
    io = _routes_io()
    with pytest.raises(ResolutionError, match="single-pass"):
        asyncio.run(run(_FANOUT, io, processor="(p='(\\'/gpt4\\')')!'$p'"))


# --- backwards compatibility --------------------------------------------------------


def test_route_path_processor_still_works() -> None:
    io = _routes_io()
    assert asyncio.run(run(_FANOUT, io, processor="/claude")).startswith("claude:")


def test_registry_less_adapter_still_accepts_a_route_path() -> None:
    # An adapter implementing no optional port must keep working with a path.
    io = _RecordingIO()
    asyncio.run(run(_FANOUT, io, processor="/reduce"))
    assert any(t.startswith("/reduce?") and rel for t, rel in io.calls)


def test_missing_processor_still_raises_the_existing_error() -> None:
    io = _RecordingIO()  # no default_route, no processor passed
    with pytest.raises(ResolutionError, match="processor"):
        asyncio.run(run(_FANOUT, io))


# --- the wire param (§27.3 over HTTP) ------------------------------------------------


def test_wire_processor_param_selects_the_processor() -> None:
    from url4.peer.server import Url4Node

    node = Url4Node(name="n")
    node.endpoint("/claude")(lambda request: f"claude:{request.intent}")
    node.endpoint("/gpt4")(lambda request: f"gpt4:{request.intent}")

    # Without a processor= the node falls back to its first endpoint...
    plain = asyncio.run(node.fetch("/v1?q=(/claude(a)!x,/gpt4(b)!y)!combine", relative=True))
    assert plain.startswith("claude:")

    # ...and the request's processor= overrides that choice.
    chosen = asyncio.run(
        node.fetch("/v1?processor=gpt4&q=(/claude(a)!x,/gpt4(b)!y)!combine", relative=True)
    )
    assert chosen.startswith("gpt4:")


def test_wire_processor_is_not_reattached_as_an_expression_param() -> None:
    # INVARIANT: `processor` is CONSUMED by the node, never appended to the
    # expression's `;` chain — it selects the run's processor, it is not a
    # protocol param of the expression. (The helper lives in
    # url4.peer._dispatch since the F2 split; the invariant did not move.)
    from url4.peer._dispatch import reassemble

    assert ";processor" not in reassemble("(a)!b", {"processor": "gpt4", "tone": "formal"})
