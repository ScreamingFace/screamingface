"""MapNode semaphore nested inside a MapNode row, under the run-wide BoundedIOLayer.

The bad thing is: a nested map deadlocks because a holder of one semaphore waits
for a permit that only a waiter can release (hold-and-wait cycle), or the
run-wide cap is exceeded.

Outer map: rows r1, r2 share ONE outer semaphore (MAP permits; iteration.py:104,164).
Each outer row spawns an inner map with its OWN semaphore (a fresh one per
resolve() call) over leaves (r, 1), (r, 2). Each leaf fetches through the
run-wide semaphore (RUN permits; _context.py:145). Every leaf may be cancelled
while waiting (a GuardNode ;t= around the leaf).

REENTRANT_IO=1 is a hypothetical IOLayer whose fetch re-enters the SAME
BoundedIOLayer while holding its permit (no url4 adapter does this today).

Run:  fm check semaphore_nesting.py
      fm check semaphore_nesting.py -D REENTRANT_IO=1 -D RUN=1
"""

NAME = "MapNode semaphores nested under the run-wide semaphore"

MAP = 1
RUN = 1
REENTRANT_IO = 0
ASSUMPTIONS = {"REENTRANT_IO": "no IOLayer.fetch re-enters the run's BoundedIOLayer"}

ROWS = (1, 2)
LEAVES = tuple((r, i) for r in ROWS for i in (1, 2))

I = "/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/nodes/iteration.py"
C = "/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/_context.py"
SOURCE = {}
for _r in ROWS:
    SOURCE[f"outer_acquire_{_r}"] = (f"{I}:164", "async with sem")
    SOURCE[f"outer_release_{_r}"] = (f"{I}:165", "return await ctx.spawn(expr, scope)")
for _r, _i in LEAVES:
    SOURCE[f"inner_acquire_{_r}{_i}"] = (f"{I}:164", "async with sem")
    SOURCE[f"run_acquire_{_r}{_i}"] = (f"{C}:145", "async with self._sem")
    SOURCE[f"fetch_returns_{_r}{_i}"] = (f"{C}:146", "return await self._inner.fetch")
    SOURCE[f"cancel_waiting_{_r}{_i}"] = (f"{C}:145", "async with self._sem")
FAILURE_ACTIONS = [f"cancel_waiting_{r}{i}" for r, i in LEAVES]


def init():
    return [{"outer": {r: "wait" for r in ROWS}, "leaf": {f"{r}{i}": "idle" for r, i in LEAVES}}]


def _held_run(s):
    return sum({"run": 1, "waitrun2": 1, "run2": 2}.get(v, 0) for v in s["leaf"].values())


def _held_inner(s, r):
    return sum(1 for i in (1, 2) if s["leaf"][f"{r}{i}"] in ("inner", "run", "run2", "waitrun2"))


def actions(s):
    out = []
    held_outer = sum(1 for v in s["outer"].values() if v == "in")
    for r in ROWS:
        if s["outer"][r] == "wait" and held_outer < MAP:
            out.append((f"outer_acquire_{r}", {**s, "outer": {**s["outer"], r: "in"}}))
        if s["outer"][r] == "in" and all(s["leaf"][f"{r}{i}"] in ("done", "failed") for i in (1, 2)):
            out.append((f"outer_release_{r}", {**s, "outer": {**s["outer"], r: "done"}}))
    for r, i in LEAVES:
        k = f"{r}{i}"
        v = s["leaf"][k]

        def put(nv, k=k):
            return {**s, "leaf": {**s["leaf"], k: nv}}
        if s["outer"][r] != "in":
            continue
        if v == "idle" and _held_inner(s, r) < MAP:
            out.append((f"inner_acquire_{k}", put("inner")))
        if v == "inner" and _held_run(s) < RUN:
            out.append((f"run_acquire_{k}", put("run")))
        if v == "run":
            if REENTRANT_IO:
                out.append((f"fetch_reenters_{k}", put("waitrun2")))
            else:
                out.append((f"fetch_returns_{k}", put("done")))
        if v == "waitrun2" and _held_run(s) < RUN:
            out.append((f"run_acquire_again_{k}", put("run2")))
        if v == "run2":
            out.append((f"fetch_returns_{k}", put("done")))
        if v in ("inner", "waitrun2"):
            out.append((f"cancel_waiting_{k}", put("failed")))
    return out


INVARIANTS = {
    "run_cap_respected": lambda s: _held_run(s) <= RUN,
    "map_cap_respected": lambda s: sum(1 for v in s["outer"].values() if v == "in") <= MAP
    and all(_held_inner(s, r) <= MAP for r in ROWS),
}


def TERMINAL(s):
    return all(v == "done" for v in s["outer"].values())


# A guarantee needs fairness of the code's own steps; cancellation is NOT fair.
LEADS_TO = {"map_finishes": (lambda s: True, TERMINAL)}
FAIR = ([f"outer_acquire_{r}" for r in ROWS] + [f"outer_release_{r}" for r in ROWS]
        + [f"inner_acquire_{r}{i}" for r, i in LEAVES] + [f"run_acquire_{r}{i}" for r, i in LEAVES]
        + [f"run_acquire_again_{r}{i}" for r, i in LEAVES]
        + [f"fetch_returns_{r}{i}" for r, i in LEAVES] + [f"fetch_reenters_{r}{i}" for r, i in LEAVES])
