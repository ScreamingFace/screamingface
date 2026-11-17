"""The Client's transports on a Run the Engine drives, end to end (E5 P2 spec D1, D9a, D13,
D14; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, `evaluate` sends my evaluation once,
follows it on one stream, reads each result from the Run, and Ctrl-C cancels what I started.

INVARIANT (D1): the Client sends `POST /runs` once and starts no Candidate itself.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from _run_engine import RUN_ID, ended, event, run_engine, settled, state
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_body

import screamingface as sf

BODY = valid_body().encode()
NAMES = ("alpha", "beta")


@pytest.fixture(autouse=True)
def _results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path / "results"))
    yield tmp_path / "results"


def _models() -> list[sf.Model]:
    return [sf.Model("provider/opus", name=name) for name in NAMES]


def _client(url: str, **options: Any) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine), **options)


def _script() -> list[list[str | int]]:
    return [
        [
            state(0, "pending"),
            state(1, "scheduled"),
            event(1, 1),
            settled(1, BODY),
            state(0, "scheduled"),
            event(0, 1),
            settled(0, BODY),
            ended(),
        ]
    ]


def test_an_evaluation_is_sent_once_followed_and_read_from_the_run() -> None:
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        report = client.evaluate(_models(), benchmark="draco", progress=False)

    (sent,) = engine.state.registered
    assert [start["name"] for start in sent["candidates"]] == list(NAMES)
    assert all(start["url4"] for start in sent["candidates"])
    assert json.loads(sent["context"])["benchmark"]["id"] == "draco"
    assert sent["detach"] is False
    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]
    assert sorted(engine.state.fetched) == [
        f"/runs/{RUN_ID}/candidates/0/result",
        f"/runs/{RUN_ID}/candidates/1/result",
    ]
    assert [candidate.name for candidate in report.candidates] == list(NAMES)
    assert report.run_id == RUN_ID
    assert engine.state.deleted == []


def test_a_saved_result_is_kept_under_the_run(_results_dir: Path) -> None:
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        client.evaluate(_models(), benchmark="draco", progress=False)

    manifests = list((_results_dir / "evaluations").glob("*.json"))
    assert [path.stem for path in manifests] == [RUN_ID]
    saved = [json.loads(path.read_text()) for path in _results_dir.glob("*/run.json")]
    assert sorted(run["outcome"]["run_result"]["index"] for run in saved) == [0, 1]
    assert all(
        (path.parent / "result.json").read_bytes() == BODY
        for path in _results_dir.glob("*/run.json")
    )


def test_a_follow_that_drops_picks_up_and_shows_each_event_once() -> None:
    script = [
        [event(0, 1, "one"), event(1, 1, "one"), 1011],
        [
            event(0, 1, "one"),
            event(0, 2, "two"),
            settled(0, BODY),
            event(1, 1, "one"),
            settled(1, BODY),
            ended(),
        ],
    ]
    seen: list[tuple[str, int]] = []

    with run_engine(script, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        client.evaluate(
            _models(),
            benchmark="draco",
            progress=False,
            on_event=lambda e: seen.append((e.run_id, e.sequence)),
        )

    assert sorted(seen) == sorted(
        [(f"url4-cloud.{0:032x}", 1), (f"url4-cloud.{0:032x}", 2), (f"url4-cloud.{1:032x}", 1)]
    )
    assert len(engine.state.followed) == 2


def test_ctrl_c_while_following_cancels_the_run_once() -> None:
    def interrupt(event: sf.Event) -> None:
        raise KeyboardInterrupt

    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(KeyboardInterrupt):
            client.evaluate(_models(), benchmark="draco", progress=False, on_event=interrupt)

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


@pytest.mark.asyncio
async def test_the_async_client_follows_the_same_run() -> None:
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine:
        async with sf.AsyncClient(
            engine_url=engine.url, http_transport=httpx.MockTransport(_catalog_engine)
        ) as client:
            report = await client.evaluate(_models(), benchmark="draco", progress=False)

    assert [candidate.name for candidate in report.candidates] == list(NAMES)
    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]
    assert len(engine.state.fetched) == 2
