"""`sf.evaluate` is a pass-through to `Client.evaluate`, not a narrower door.

INVARIANT under test (OME-1227): every option the Client's `evaluate` accepts reaches it
through the module-level convenience call too. `sf.evaluate(...)` is what every
`examples/*.ipynb` uses, so an option the wrapper forgets is an option the notebook
audience cannot reach at all — answer seeds (OME-1038) shipped that way and stayed
unreachable until a `TypeError` surfaced it.

Both branches matter and are tested separately: the Recipes branch, and the complete-URL4
branch, which takes neither `benchmark` nor `limit` and so is the one a forwarding change
is most likely to miss.
"""

from __future__ import annotations

from typing import Any

import pytest

import screamingface as sf
from screamingface import _default_client


class _RecordingClient:
    """Stand in for the lazy default Client, capturing one `evaluate` call's kwargs."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def evaluate(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append((args, kwargs))
        return "report"


@pytest.fixture
def recording_client(monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    """Replace the process-wide Client lookup for the duration of one test."""

    client = _RecordingClient()
    monkeypatch.setattr(_default_client, "default_client", lambda: client)
    return client


def test_answer_seed_reaches_the_client_on_the_recipes_branch(
    recording_client: _RecordingClient,
) -> None:
    # WHY this is the headline case: it is the notebook idiom verbatim.
    sf.evaluate(sf.Model(model="openrouter/qwen/qwen3.7-flash"), benchmark="b", answer_seed=42)

    _, kwargs = recording_client.calls[0]
    assert kwargs["answer_seed"] == 42


def test_answer_seed_reaches_the_client_on_the_complete_url4_branch(
    recording_client: _RecordingClient,
) -> None:
    # WHY separately: this branch takes neither benchmark nor limit, so it is forwarded by
    # its own call site — the one a partial fix leaves behind.
    sf.evaluate("url4://an/expression", answer_seed=42)

    _, kwargs = recording_client.calls[0]
    assert kwargs["answer_seed"] == 42


def test_an_unseeded_call_still_declares_no_seed(recording_client: _RecordingClient) -> None:
    # INVARIANT: omitting the keyword must keep forwarding None, because `apply_answer_seed`
    # treats None as a no-op returning the params mapping ITSELF — that is what keeps an
    # unseeded run's egress byte-identical and every request-keyed replay fixture valid.
    sf.evaluate(sf.Model(model="openrouter/qwen/qwen3.7-flash"), benchmark="b")

    _, kwargs = recording_client.calls[0]
    assert kwargs.get("answer_seed") is None


def test_url4_branch_still_refuses_benchmark_and_limit(
    recording_client: _RecordingClient,
) -> None:
    # A complete URL4 already names its benchmark and case set; accepting either here would
    # silently ignore the caller's intent.
    #
    # WHY the ignores: the overloads already type these as `None` for a str candidate, so a
    # typed caller cannot reach this. The runtime guard still has to exist and stay tested —
    # notebooks are untyped, and this is the call they make.
    with pytest.raises(TypeError):
        sf.evaluate("url4://an/expression", benchmark="b")  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        sf.evaluate("url4://an/expression", limit=1)  # type: ignore[call-overload]
