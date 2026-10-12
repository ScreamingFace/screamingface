"""Regressions for the url4 audit (2026-10-09, report §4.C: C1, C2, C3).

The guard follows Spec C §13.3: ``;retry=N`` adds N attempts; only ``transient`` errors
retry, with exponential backoff and jitter (lengthened by ``Retry-After``, §14.3);
``;t=`` is cumulative over every attempt and wait, and a timeout ends the source.
Idempotency keys follow "reuse until answered" (owner decision D-2): a retry re-sends a
target with the same key while no reply came back for it, and with a new key after one did.
"""

from __future__ import annotations

import asyncio
import email.utils
import math
import time
from collections.abc import Callable, Mapping

import httpx
import pytest

from url4 import src
from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.dag import run
from url4.dag.nodes import GuardNode, WebFetchNode
from url4.dag.nodes import guard as guard_module
from url4.io.http import HttpIOLayer
from url4.io.idempotency import idempotency_key

pytestmark = pytest.mark.asyncio


class EffectIO:
    """The side effect lands FIRST, then the response takes ``delay`` (lost-response window)."""

    def __init__(self, delay: float = 0.0, delays: dict[str, float] | None = None) -> None:
        self.delay = delay
        self.delays = delays or {}
        self.effects: dict[str, int] = {}
        self.keys: list[str | None] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.effects[target] = self.effects.get(target, 0) + 1
        self.keys.append(idempotency_key(target))
        await asyncio.sleep(self.delays.get(target, self.delay))
        return f"<{target}>"


class FlakyIO:
    """Fails ``failures`` times with ``error`` (no reply: the key is kept), then answers."""

    def __init__(self, failures: int, error: Url4Error, delay: float = 0.0) -> None:
        self.failures = failures
        self.error = error
        self.delay = delay
        self.calls = 0
        self.keys: list[str | None] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls += 1
        self.keys.append(idempotency_key(target))
        if self.calls <= self.failures:
            raise self.error
        await asyncio.sleep(self.delay)
        return "ok"


class FetchAll:
    """A hand-built subtree: fetch every target in order, then join the bodies."""

    deps: dict = {}

    def __init__(self, *targets: str) -> None:
        self.targets = targets

    async def resolve(self, inputs: Mapping[str, object], ctx) -> str:
        return "+".join([await ctx.io.fetch(t, relative=False) for t in self.targets])


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the backoff sleeps instead of waiting them out."""
    recorded: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(guard_module, "_sleep", fake_sleep)
    return recorded


# --- C1: a timed-out attempt is not retried --------------------------------------------


async def test_timeout_is_cumulative_and_does_not_retry_the_effect() -> None:
    io = EffectIO(delay=0.1)
    with pytest.raises(ResolutionError) as exc_info:
        await run("https://x.test/charge;t=0.05;retry=2", io=io)
    assert exc_info.value.code == ErrorCode.TIMEOUT
    assert io.effects == {"https://x.test/charge": 1}


async def test_backoff_wait_is_counted_against_t(monkeypatch: pytest.MonkeyPatch) -> None:
    # REAL TIME (~0.25 s): the real sleep is restored. One 0.1 s backoff fits in `;t=0.25`,
    # the slow second attempt does not; the run ends at the deadline, not at 0.1 + 0.3 s.
    monkeypatch.setattr(guard_module, "_sleep", asyncio.sleep)
    monkeypatch.setattr(guard_module, "_jitter", lambda low, high: 0.0)
    monkeypatch.setattr(guard_module, "_BACKOFF_BASE_S", 0.1)
    io = FlakyIO(failures=1, error=ResolutionError("blip"), delay=0.3)
    started = time.monotonic()
    with pytest.raises(ResolutionError) as exc_info:
        await run("https://x.test/a;t=0.25;retry=1", io=io)
    assert exc_info.value.code == ErrorCode.TIMEOUT
    assert io.calls == 2
    assert time.monotonic() - started < 0.38


async def test_a_wait_longer_than_the_time_left_raises_the_last_error(
    delays: list[float],
) -> None:
    # The 0.5-1.0 s backoff cannot fit in `;t=0.2`: the real failure surfaces at once.
    io = FlakyIO(failures=5, error=ResolutionError("blip"))
    with pytest.raises(ResolutionError, match="blip"):
        await run("https://x.test/a;t=0.2;retry=3", io=io)
    assert io.calls == 1
    assert delays == []


# --- C1 / D-2: "reuse until answered" idempotency keys ----------------------------------


async def test_lost_response_retry_reuses_the_key(delays: list[float]) -> None:
    io = FlakyIO(failures=2, error=ResolutionError("blip"))
    assert await run("https://x.test/charge;retry=2", io=io) == "ok"
    assert io.calls == 3
    assert io.keys[0] is not None
    assert len(set(io.keys)) == 1


async def test_http_network_error_retry_reuses_the_key(delays: list[float]) -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Idempotency-Key"))
        if len(seen) == 1:
            raise httpx.ConnectError("reset", request=request)
        return httpx.Response(200, text="done")

    async with _http(handler) as client:
        result = await run("https://x.test/charge;retry=1", io=HttpIOLayer(client=client))
    assert result == "done"
    assert seen[0] is not None and seen[0] == seen[1]


async def test_http_answered_retry_gets_a_fresh_key(delays: list[float]) -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Idempotency-Key"))
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(200, text="done")

    async with _http(handler) as client:
        result = await run("https://x.test/charge;retry=1", io=HttpIOLayer(client=client))
    assert result == "done"
    assert None not in seen and seen[0] != seen[1]


async def test_retry_after_an_answered_fetch_in_the_subtree(delays: list[float]) -> None:
    # /a answered, then /b lost its response: the retry re-sends /b with its key and /a
    # (already answered) with a new one.
    keys: dict[str, list[str | None]] = {"/a": [], "/b": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        keys[path].append(request.headers.get("Idempotency-Key"))
        if path == "/b" and len(keys["/b"]) == 1:
            raise httpx.ReadError("lost", request=request)
        return httpx.Response(200, text=path)

    subtree = FetchAll("https://x.test/a", "https://x.test/b")
    async with _http(handler) as client:
        assert await run(GuardNode(subtree, retries=1), HttpIOLayer(client=client)) == "/a+/b"
    assert keys["/a"][0] != keys["/a"][1]
    assert keys["/b"][0] == keys["/b"][1]


async def test_distinct_targets_get_distinct_keys_over_http(delays: list[float]) -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = request.headers.get("Idempotency-Key")
        return httpx.Response(200, text="ok")

    subtree = FetchAll("https://a.test/x", "https://b.test/x")
    async with _http(handler) as client:
        await run(GuardNode(subtree, retries=1), HttpIOLayer(client=client))
    assert None not in seen.values()
    assert seen["a.test"] != seen["b.test"]


async def test_nested_guards_share_the_outer_keys(delays: list[float]) -> None:
    io = FlakyIO(failures=3, error=ResolutionError("blip"))
    inner = GuardNode(WebFetchNode("https://x.test/a"), retries=1)
    assert await run(GuardNode(inner, retries=1), io) == "ok"
    assert io.calls == 4
    assert io.keys[0] is not None and len(set(io.keys)) == 1


async def test_each_guarded_resolve_gets_its_own_key(delays: list[float]) -> None:
    io = EffectIO()
    await run("(https://x.test/a;retry=1, https://x.test/b;retry=1)!'join'", io=io)
    first, second = io.keys
    assert first is not None and second is not None
    assert first != second
    io_again = EffectIO()
    await run("https://x.test/a;retry=1", io=io_again)
    assert io_again.keys[0] != first


async def test_sibling_of_a_retrying_guard_gets_no_key(delays: list[float]) -> None:
    io = EffectIO()
    await run("(https://x.test/a;retry=1, https://x.test/b)!'join'", io=io)
    keys = dict(zip(io.effects, io.keys, strict=True))
    assert keys["https://x.test/a"] is not None
    assert keys["https://x.test/b"] is None


async def test_no_key_outside_a_retrying_guard() -> None:
    io = EffectIO()
    await run("(https://x.test/a, https://x.test/b;t=5)!'join'", io=io)
    assert io.keys == [None, None]


async def test_http_adapter_sends_no_key_without_a_guard() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Idempotency-Key"))
        return httpx.Response(200, text="done")

    async with _http(handler) as client:
        await run("https://x.test/read", io=HttpIOLayer(client=client))
    assert seen == [None]


# --- Spec C §13.2.1 / §13.3 / §14.3: which errors retry, and how long to wait -----------


async def test_permanent_error_is_not_retried(delays: list[float]) -> None:
    io = FlakyIO(failures=5, error=ResolutionError("gone", permanent=True))
    with pytest.raises(ResolutionError, match="gone"):
        await run("https://x.test/a;retry=3", io=io)
    assert io.calls == 1
    assert delays == []


async def test_non_url4_errors_are_not_retried(delays: list[float]) -> None:
    class Broken:
        calls = 0

        async def fetch(self, target: str, *, relative: bool) -> str:
            self.calls += 1
            raise RuntimeError("adapter bug")

    io = Broken()
    with pytest.raises(RuntimeError, match="adapter bug"):
        await run("https://x.test/a;retry=3", io=io)
    assert io.calls == 1


@pytest.mark.parametrize(("status", "calls"), [(404, 1), (400, 1), (503, 2), (429, 2), (500, 2)])
async def test_http_status_class_decides_the_retry(
    delays: list[float], status: int, calls: int
) -> None:
    # Spec C §13.2.1: 4xx is permanent except 408/409/421/423/425/429; 5xx is transient
    # except 501/505/508.
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(status)

    async with _http(handler) as client:
        with pytest.raises(ResolutionError):
            await run("https://x.test/a;retry=1", io=HttpIOLayer(client=client))
    assert len(seen) == calls


async def test_backoff_follows_the_spec_schedule(
    delays: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guard_module, "_jitter", lambda low, high: high)
    io = FlakyIO(failures=7, error=ResolutionError("blip"))
    assert await run("https://x.test/a;retry=7", io=io) == "ok"
    # min(500ms * 2^(k-1) + jitter(<=500ms), 30s) for attempt k = 1..7
    assert delays == [1.0, 1.5, 2.5, 4.5, 8.5, 16.5, 30.0]


async def test_retry_after_makes_a_4xx_transient(delays: list[float]) -> None:
    # Spec C §13.2.1: `Retry-After` on any response overrides the class to transient.
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(403, headers={"Retry-After": "1"})
        return httpx.Response(200, text="done")

    async with _http(handler) as client:
        assert await run("https://x.test/a;retry=1", io=HttpIOLayer(client=client)) == "done"
    assert len(seen) == 2


@pytest.mark.parametrize("header", ["seconds", "http-date"])
async def test_retry_after_is_the_minimum_wait(delays: list[float], header: str) -> None:
    # Spec C §14.3: the backoff (here <= 1 s) is raised to the source's Retry-After.
    value = "20" if header == "seconds" else email.utils.formatdate(time.time() + 20, usegmt=True)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(503, headers={"Retry-After": value})
        return httpx.Response(200, text="done")

    async with _http(handler) as client:
        assert await run("https://x.test/a;retry=1", io=HttpIOLayer(client=client)) == "done"
    assert len(delays) == 1
    assert 18.0 <= delays[0] <= 20.0


async def test_retry_after_beyond_t_raises_the_answer_at_once(delays: list[float]) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(503, headers={"Retry-After": "60"})

    async with _http(handler) as client:
        with pytest.raises(ResolutionError) as exc_info:
            await run("https://x.test/a;t=5;retry=3", io=HttpIOLayer(client=client))
    assert exc_info.value.code != ErrorCode.TIMEOUT
    assert exc_info.value.retry_after == 60.0
    assert len(seen) == 1
    assert delays == []


# --- C2: a deadline spent waiting for the run-wide I/O permit ---------------------------


async def test_admission_timeout_has_its_own_code() -> None:
    io = EffectIO(delays={"https://x.test/slow": 0.3})
    expression = "(https://x.test/slow, https://x.test/fast;t=0.05;retry=3)!'join'"
    with pytest.raises(ResolutionError) as exc_info:
        await run(expression, io=io, concurrency=1)
    # Spec C §13.5.2: an implementation code carries the `x.` prefix.
    assert exc_info.value.code == ErrorCode.ADMISSION_TIMEOUT == "x.admission_timeout"
    assert "https://x.test/fast" not in io.effects


async def test_timeout_after_io_issued_is_a_plain_timeout() -> None:
    io = EffectIO(delay=0.3)
    with pytest.raises(ResolutionError) as exc_info:
        await run("https://x.test/a;t=0.05", io=io, concurrency=1)
    assert exc_info.value.code == ErrorCode.TIMEOUT


async def test_inner_timeout_error_is_not_the_guard_deadline() -> None:
    class RaisesTimeout:
        deps: dict = {}

        async def resolve(self, inputs, ctx) -> str:
            raise TimeoutError("the node's own timeout")

    with pytest.raises(TimeoutError, match="the node's own timeout"):
        await run(GuardNode(RaisesTimeout(), timeout=5.0), EffectIO())


# --- C3: one validator for ;t= and ;retry= ----------------------------------------------


@pytest.mark.parametrize(
    "annotation",
    ["retry=-1", "retry=-5;optional", "retry=11", "retry=1.5", "t=0", "t=-1", "t=nan", "t=inf"],
)
async def test_bad_guard_values_are_parse_errors(annotation: str) -> None:
    io = EffectIO()
    with pytest.raises(ParseError):
        await run(f"(https://x.test/a;{annotation}, https://x.test/b)!'join'", io=io)
    assert io.effects == {}


async def test_parse_error_names_the_expected_type() -> None:
    with pytest.raises(ParseError, match="must be an integer"):
        await run("https://x.test/a;retry=1.5", io=EffectIO())
    with pytest.raises(ParseError, match="must be a number"):
        await run("https://x.test/a;t=soon", io=EffectIO())


@pytest.mark.parametrize(
    "kwargs",
    [{"retry": -1}, {"retry": 11}, {"t": 0}, {"t": -1.0}, {"t": math.nan}, {"t": math.inf}],
)
async def test_bad_guard_values_are_rejected_by_the_builder(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        src("https://x.test/a", **kwargs)


async def test_retry_cap_is_accepted() -> None:
    io = EffectIO()
    assert await run("https://x.test/a;retry=10", io=io) == "<https://x.test/a>"


async def test_guard_node_rejects_negative_retries() -> None:
    with pytest.raises(ValueError):
        GuardNode(WebFetchNode("https://x.test/a"), retries=-1)


async def test_unparseable_retry_after_still_retries_with_the_backoff(
    delays: list[float],
) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(403, headers={"Retry-After": "soon"})
        return httpx.Response(200, text="done")

    async with _http(handler) as client:
        assert await run("https://x.test/a;retry=1", io=HttpIOLayer(client=client)) == "done"
    assert len(delays) == 1
    assert 0.5 <= delays[0] <= 1.0
