"""Diamond across the GuardNode isolation boundary (executor.py:288-296, guard.py:26-33).

The bad thing is: a node shared by the outer graph and a guarded subtree does
its I/O more than once per run, and the debug resolve-once guard
(executor.py:86-87, 154-165) does not notice.

Outer executor:   R -> C, R -> G          (G = GuardNode, retries -> ATTEMPTS)
Guarded subtree:  I, run on a FRESH Executor per attempt (own memo, own counts)
  HANDBUILT=0  compiler shape (_lowering.py:376-381): C is G's dep edge; I reads
               it from the scope frame -> I has no edge to C
  HANDBUILT=1  a hand-built graph puts the SAME C object inside G.inner: I -> C

Run:  fm check executor_guard_boundary.py                 # compiler shape
      fm check executor_guard_boundary.py -D HANDBUILT=1  # hand-built shape
"""

NAME = "Diamond across the GuardNode boundary"

HANDBUILT = 0
ATTEMPTS = 2   # ;retry=1

E = "/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/executor.py"
G = "/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/nodes/guard.py"
SOURCE = {
    "outer_resolves_C": (f"{E}:150", "task = self._tg.create_task(self._eval(node, parent_span_id))"),
    "guard_starts_attempt": (f"{E}:296", "return await Executor(invoking_ctx.child(scope)).execute_payload"),
    "inner_resolves_C": (f"{E}:150", "task = self._tg.create_task(self._eval(node, parent_span_id))"),
    "inner_resolves_I": (f"{E}:193", "result = await node.resolve("),
    "attempt_times_out": (f"{G}:85", "except TimeoutError as exc"),
    "attempt_ok": (f"{G}:71", "return await self._once(scope, ctx)"),
    "guard_ready": (f"{E}:182", "values = await asyncio.gather(*(self._run(dep, span_id)"),
    "guard_gives_up": (f"{G}:77", "raise last"),
}
FAILURE_ACTIONS = ["attempt_times_out"]


def init():
    return [{"outer_C": 0, "inner_C": 0, "inner_C_max": 0, "attempt": 0,
             "g": "wait_deps", "inner": "none", "total_C": 0}]


def actions(s):
    out = []
    if s["outer_C"] == 0:
        out.append(("outer_resolves_C", {**s, "outer_C": 1, "total_C": s["total_C"] + 1}))
    # compiler shape: G waits for its dep C (outer memo hit) before resolve()
    ready = s["outer_C"] == 1 if not HANDBUILT else True
    if s["g"] == "wait_deps" and ready:
        out.append(("guard_ready", {**s, "g": "idle"}))
    if s["g"] == "idle" and s["attempt"] < ATTEMPTS:
        # fresh Executor: memo and debug counts start empty
        out.append(("guard_starts_attempt", {**s, "g": "running", "attempt": s["attempt"] + 1,
                                             "inner_C": 0, "inner": "start"}))
    if s["g"] == "running":
        if HANDBUILT and s["inner"] == "start" and s["inner_C"] == 0:
            c = s["inner_C"] + 1
            out.append(("inner_resolves_C", {**s, "inner_C": c, "inner_C_max": max(c, s["inner_C_max"]),
                                              "total_C": s["total_C"] + 1, "inner": "c_done"}))
        if s["inner"] == ("c_done" if HANDBUILT else "start"):
            out.append(("inner_resolves_I", {**s, "inner": "i_inflight"}))
        if s["inner"] == "i_inflight":
            out.append(("attempt_ok", {**s, "g": "done", "inner": "none"}))
            out.append(("attempt_times_out", {**s, "g": "idle", "inner": "none"}))
    if s["g"] == "idle" and s["attempt"] >= ATTEMPTS:
        out.append(("guard_gives_up", {**s, "g": "done"}))
    return out


INVARIANTS = {
    "shared_C_resolved_at_most_once_per_run": lambda s: s["total_C"] <= 1,
    # the debug guard asserts per Executor: count != 1 for some node of ONE executor
    "debug_guard_sees_every_duplicate": lambda s: s["total_C"] <= 1 or
        max(s["outer_C"], s["inner_C_max"]) > 1,
}


def TERMINAL(s):
    return s["g"] == "done" and s["outer_C"] == 1
