"""Executor memo + TaskGroup failure/cancellation, AS WRITTEN (url4 dag/executor.py).

The bad thing is: inside one run, a node resolves (does its I/O) twice; or a
run ends with a span that never finished, an orphaned task, or an "ok" result
built while a node failed; or a failed run never finishes.

Graph (one Executor, one TaskGroup):

        R ── A ── C          C is shared by A and B (a diamond)
        │ └─ B ──┘          F is an independent sibling that may fail
        └─── F               while C / B are mid-fetch

Per node:  st  u (no task)  q (task created, not started)  w (NodeStarted
           emitted, gathering deps)  r (resolve() in flight)  ok  err  cx
           (cancelled / aborted)
           tasks, resolves, fin (# NodeFinished), started (NodeStarted emitted)
group:     run | abort | done_ok | done_err

The memo check-then-store is ONE action (request_*), as in the code: no await
between executor.py:148 and :151. The split (non-atomic) variant is already
covered by tests/formal/executor_memo_buggy.py.

Run:  fm check executor_taskgroup.py --coverage
"""

NAME = "Executor memo + TaskGroup cancel (as written)"

DEPS = {"R": ("A", "B", "F"), "A": ("C",), "B": ("C",), "C": (), "F": ()}
NODES = tuple(DEPS)
FAILABLE = ("C", "F", "A")     # nodes whose resolve() may raise
REMOTE_ANSWERS = 1             # every in-flight resolve() eventually returns
CANCEL_HONOURED = 1            # resolve() lets CancelledError propagate

# REMOTE_ANSWERS is NOT in ASSUMPTIONS: FAIR is computed at import, so --challenge cannot
# flip it (a first --challenge run reported "holds" for it - a model bug). Check it with
# -D 'FAIR=[... without ok_*]' instead; see REPORT.md.
ASSUMPTIONS = {
    "CANCEL_HONOURED": "node code and the IOLayer do not swallow CancelledError",
}

E = "/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/executor.py"
SOURCE = {"group_done_ok": (f"{E}:117", "async with asyncio.TaskGroup() as tg"),
          "group_done_err": (f"{E}:120", "except BaseExceptionGroup as group")}
for _n in NODES:
    SOURCE[f"start_{_n}"] = (f"{E}:179", "obs.emit(NodeStarted(")
    SOURCE[f"resolve_{_n}"] = (f"{E}:193", "result = await node.resolve(")
    SOURCE[f"ok_{_n}"] = (f"{E}:208", 'obs.emit(NodeFinished(span_id, "ok"')
    SOURCE[f"cancel_{_n}"] = (f"{E}:195", 'status = "cancelled" if isinstance')
    if DEPS[_n]:
        SOURCE[f"dep_failed_{_n}"] = (f"{E}:189", 'obs.emit(NodeFinished(span_id, "cancelled"')
    if _n in FAILABLE:
        SOURCE[f"fail_{_n}"] = (f"{E}:198", "obs.emit(")
    for _d in DEPS[_n]:
        SOURCE[f"request_{_n}_{_d}"] = (f"{E}:148", "memoized = self._memo.get(id(node))")

FAILURE_ACTIONS = [f"fail_{n}" for n in FAILABLE]
FAIR = ([f"start_{n}" for n in NODES] + [f"resolve_{n}" for n in NODES]
        + [f"request_{n}_{d}" for n in NODES for d in DEPS[n]]
        + [f"dep_failed_{n}" for n in NODES if DEPS[n]] + ["group_done_ok", "group_done_err"]
        + ([f"ok_{n}" for n in NODES] if REMOTE_ANSWERS else [])
        + ([f"cancel_{n}" for n in NODES] if CANCEL_HONOURED else []))

LIVE = ("q", "w", "r")


def init():
    nodes = {n: {"st": "u", "tasks": 0, "resolves": 0, "fin": 0, "started": False,
                 "req": frozenset()} for n in NODES}
    nodes["R"] = {**nodes["R"], "st": "q", "tasks": 1}     # execute_payload -> _run(root)
    return [{"g": "run", "n": nodes}]


def _set(s, name, **kw):
    return {**s, "n": {**s["n"], name: {**s["n"][name], **kw}}}


def actions(s):
    out = []
    N = s["n"]
    if s["g"] in ("done_ok", "done_err"):
        return out
    for n in NODES:
        v = N[n]
        if v["st"] == "q" and s["g"] == "run":
            out.append((f"start_{n}", _set(s, n, st="w", started=True)))
        if v["st"] == "w":
            for d in DEPS[n]:
                if d in v["req"]:
                    continue
                t = _set(s, n, req=v["req"] | {d})
                if N[d]["tasks"] == 0:               # memo miss: create + store, atomically
                    t = _set(t, d, st="q", tasks=N[d]["tasks"] + 1)
                out.append((f"request_{n}_{d}", t))
            if len(v["req"]) == len(DEPS[n]) and all(N[d]["st"] == "ok" for d in DEPS[n]):
                out.append((f"resolve_{n}", _set(s, n, st="r", resolves=v["resolves"] + 1)))
            if any(N[d]["st"] in ("err", "cx") for d in v["req"]):
                # gather re-raises the dep's error: emit "cancelled", re-raise -> TG error
                out.append((f"dep_failed_{n}", {**_set(s, n, st="cx", fin=v["fin"] + 1),
                                                "g": "abort"}))
        if v["st"] == "r":
            out.append((f"ok_{n}", _set(s, n, st="ok", fin=v["fin"] + 1)))
            if n in FAILABLE:
                out.append((f"fail_{n}", {**_set(s, n, st="err", fin=v["fin"] + 1), "g": "abort"}))
        if s["g"] == "abort" and v["st"] in LIVE and CANCEL_HONOURED:
            # TaskGroup cancels every live task; one never started emits nothing
            fin = v["fin"] + (1 if v["st"] in ("w", "r") else 0)
            out.append((f"cancel_{n}", _set(s, n, st="cx", fin=fin)))
    if s["g"] == "run" and N["R"]["st"] == "ok":
        out.append(("group_done_ok", {**s, "g": "done_ok"}))
    if s["g"] == "abort" and not any(N[n]["st"] in LIVE for n in NODES):
        out.append(("group_done_err", {**s, "g": "done_err"}))
    return out


DONE = ("done_ok", "done_err")

INVARIANTS = {
    "one_task_per_node": lambda s: all(v["tasks"] <= 1 for v in s["n"].values()),
    "resolved_at_most_once": lambda s: all(v["resolves"] <= 1 for v in s["n"].values()),
    "finish_at_most_once": lambda s: all(v["fin"] <= 1 for v in s["n"].values()),
    "finish_implies_started": lambda s: all(v["started"] or v["fin"] == 0 for v in s["n"].values()),
    "done_means_every_span_closed": lambda s: s["g"] not in DONE or all(
        v["fin"] == (1 if v["started"] else 0) for v in s["n"].values()),
    "done_means_no_live_task": lambda s: s["g"] not in DONE or not any(
        v["st"] in LIVE for v in s["n"].values()),
    "ok_run_saw_no_error": lambda s: s["g"] != "done_ok" or not any(
        v["st"] in ("err", "cx") for v in s["n"].values()),
}

LEADS_TO = {
    "run_finishes": (lambda s: s["g"] in ("run", "abort"), lambda s: s["g"] in DONE),
}


def TERMINAL(s):
    return s["g"] in DONE
