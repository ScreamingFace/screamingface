"""Reproductions for the F1-executor lane. Read-only use of url4; run in the scratch venv.

Each case prints one line: CASE name -> observed outcome.
"""

from __future__ import annotations

import asyncio
import time
import traceback

from url4.core.errors import ResolutionError, Url4Error
from url4.dag import Executor, compile_expression, run
from url4.dag.node import ExecutionContext


class EffectIO:
    """fetch applies an effect FIRST, then waits `delay` before returning (lost-response window)."""

    def __init__(self, delay: float = 0.0, delays: dict[str, float] | None = None) -> None:
        self.delay = delay
        self.delays = delays or {}
        self.effects: dict[str, int] = {}
        self.started: list[tuple[str, float]] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.started.append((target, time.monotonic()))
        self.effects[target] = self.effects.get(target, 0) + 1  # the side effect lands here
        await asyncio.sleep(self.delays.get(target, self.delay))
        return f"<{target}>"


def case(name):
    def deco(fn):
        async def wrapped():
            try:
                print(f"CASE {name} -> {await fn()}")
            except BaseException as exc:  # noqa: BLE001 - we want to see every outcome
                print(f"CASE {name} -> RAISED {type(exc).__name__}: {exc}")
        wrapped.__name__ = fn.__name__
        return wrapped
    return deco


@case("G1 timeout-but-succeeded duplicates the effect (;t=0.05;retry=2)")
async def g1():
    io = EffectIO(delay=0.1)
    try:
        await run("https://x.test/charge;t=0.05;retry=2", io=io)
    except Url4Error as exc:
        return f"raised {type(exc).__name__}({exc.code}); effects applied={io.effects}"
    return f"ok; effects={io.effects}"


@case("G2 ;retry=-1 (negative retry) on a required source")
async def g2():
    io = EffectIO()
    return await run("https://x.test/a;retry=-1", io=io)


@case("G2b ;retry=-1;optional")
async def g2b():
    io = EffectIO()
    out = await run("(https://x.test/a;retry=-1;optional, https://x.test/b)!join", io=io)
    return f"result={out!r} effects={io.effects}"


@case("G3 ;t=0 (zero timeout)")
async def g3():
    io = EffectIO()
    try:
        await run("https://x.test/a;t=0", io=io)
    except Url4Error as exc:
        return f"raised {type(exc).__name__}({exc.code}) effects={io.effects}"
    return f"ok effects={io.effects}"


@case("G4 ;t= counts time queued on the run-wide semaphore (concurrency=1)")
async def g4():
    # /slow holds the only run-wide permit for 0.3s. The guarded /fast fetch takes 0.01s
    # but has ;t=0.1: it can only time out while WAITING for the permit, never in its own I/O.
    io = EffectIO(delays={"https://x.test/slow": 0.3, "https://x.test/fast": 0.01})
    try:
        out = await run("(https://x.test/slow, https://x.test/fast;t=0.1)!join", io=io, concurrency=1)
    except Url4Error as exc:
        return f"raised {type(exc).__name__}({exc.code}): {exc}; fast effects={io.effects.get('https://x.test/fast', 0)}"
    return f"ok {out!r}"


@case("G4b same, with ;retry=3 - every attempt burns waiting, no I/O issued")
async def g4b():
    io = EffectIO(delays={"https://x.test/slow": 0.5, "https://x.test/fast": 0.01})
    try:
        await run("(https://x.test/slow, https://x.test/fast;t=0.1;retry=3)!join", io=io, concurrency=1)
    except Url4Error as exc:
        return f"raised {type(exc).__name__}({exc.code}); fast fetches issued={io.effects.get('https://x.test/fast', 0)}"
    return "ok"


@case("E1 Executor reused after a failed run")
async def e1():
    class FailIO:
        async def fetch(self, target, *, relative):
            if "bad" in target:
                raise ResolutionError("boom")
            await asyncio.sleep(0.05)
            return "v"

    ctx = ExecutionContext(FailIO())
    graph = compile_expression("(https://x.test/bad, https://x.test/good)!join")
    ex = Executor(ctx)
    first = "?"
    try:
        await ex.execute(graph.sink)
    except Url4Error as exc:
        first = f"{type(exc).__name__}"
    try:
        second = await ex.execute(graph.sink)
        return f"first={first} second=ok {second!r}"
    except BaseException as exc:
        return f"first={first} second=RAISED {type(exc).__name__}"


@case("E2 hand-built graph: node shared inside a GuardNode inner AND as an outer dep")
async def e2():
    from url4.dag.nodes import GuardNode, JoinNode, WebFetchNode  # type: ignore[attr-defined]

    io = EffectIO()
    shared = WebFetchNode("https://x.test/shared")
    guard = GuardNode(shared, retries=0, optional=True)
    root = JoinNode(deps={"0": shared, "1": guard})
    out = await run(root, io=io)
    return f"result={out!r} shared fetched {io.effects.get('https://x.test/shared')}x (debug resolve-once guard silent)"


async def main():
    for fn in (g1, g2, g2b, g3, g4, g4b, e1, e2):
        await fn()


if __name__ == "__main__":
    asyncio.run(main())


class Rec:
    def __init__(self):
        self.events = []

    def on_event(self, e):
        self.events.append(e)


def _pairs(rec):
    from url4.observe import NodeFinished, NodeStarted
    started = [e.span_id for e in rec.events if isinstance(e, NodeStarted)]
    finished = [e.span_id for e in rec.events if isinstance(e, NodeFinished)]
    seqs = [e.engine_seq for e in rec.events if hasattr(e, "engine_seq")]
    return (sorted(started) == sorted(finished) and len(set(finished)) == len(finished),
            seqs == list(range(1, len(seqs) + 1)), len(started))


@case("E3 compiled: binding referenced inside a guarded+retried source resolves once")
async def e3():
    io = EffectIO(delay=0.1, delays={"https://x.test/a": 0.0})
    rec = Rec()
    try:
        await run("(x=https://x.test/a, https://x.test/b?q=$x;t=0.05;retry=2)!join", io=io, observer=rec)
    except Url4Error as exc:
        pass
    return f"effects={io.effects}; (startedOneFinish, seqGapFree, nStarted)={_pairs(rec)}"


@case("E4 obs pairing when a dep fails while a sibling is mid-fetch")
async def e4():
    class IO:
        async def fetch(self, target, *, relative):
            if "bad" in target:
                await asyncio.sleep(0.01)
                raise ResolutionError("boom")
            await asyncio.sleep(0.2)
            return "v"
    rec = Rec()
    try:
        await run("(https://x.test/bad, https://x.test/slow, https://x.test/slow)!join", io=IO(), observer=rec)
    except Url4Error as exc:
        first = type(exc).__name__
    from url4.observe import NodeFinished
    st = [(e.status) for e in rec.events if isinstance(e, NodeFinished)]
    return f"raised={first}; finishes={st}; (paired, gapfree, n)={_pairs(rec)}"


if __name__ == "__main__":
    async def _more():
        await e3()
        await e4()
    asyncio.run(_more())
