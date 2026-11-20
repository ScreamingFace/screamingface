"""A `run_transport` of the old shape is refused when the Client is made (#1982 review).

FEATURE: a detached Run (OME-1837). `run_transport` takes the follow-a-Run port (`register_run`,
`follow_run`, `cancel_run`, `close`). A custom transport written for the port before it ran one
Candidate at a time (`run`, `cancel_active`, `close`).
STORY: as a researcher with such a transport, `Client(run_transport=...)` tells me at once which
shape it needs, instead of an AttributeError after the evaluation has already called the Engine.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from _run_transport import AsyncScriptedRun, ScriptedRun

import screamingface as sf


class _OneCandidateAtATime:
    """The port's shape before E5 P2."""

    def run(self, candidate: Any, on_event: Any) -> Any:
        raise AssertionError("never run")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _NoCancel(ScriptedRun):
    cancel_run = None  # type: ignore[assignment]


_SHAPE = "register_run, follow_run, cancel_run and close"


@pytest.mark.parametrize(
    ("transport", "missing"),
    [
        (_OneCandidateAtATime(), "register_run, follow_run, cancel_run"),
        (_NoCancel(), "cancel_run"),
    ],
)
def test_a_transport_without_the_follow_port_is_refused_by_name(
    transport: object, missing: str
) -> None:
    with pytest.raises(TypeError) as caught:
        sf.Client(run_transport=cast(Any, transport))

    assert _SHAPE in str(caught.value)
    assert f"has no {missing}" in str(caught.value)


def test_an_async_transport_without_the_follow_port_is_refused_by_name() -> None:
    with pytest.raises(TypeError) as caught:
        sf.AsyncClient(run_transport=cast(Any, _OneCandidateAtATime()))

    assert _SHAPE in str(caught.value)
    assert "has no register_run, follow_run, cancel_run" in str(caught.value)


def test_a_transport_with_the_follow_port_is_taken() -> None:
    transport = ScriptedRun()

    with sf.Client(run_transport=transport) as client:
        assert client._transport is transport  # noqa: SLF001


@pytest.mark.asyncio
async def test_an_async_transport_with_the_follow_port_is_taken() -> None:
    transport = AsyncScriptedRun()

    async with sf.AsyncClient(run_transport=transport) as client:
        assert client._transport is transport  # noqa: SLF001
