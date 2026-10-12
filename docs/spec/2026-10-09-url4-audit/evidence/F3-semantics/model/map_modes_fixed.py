"""MapNode on_error modes x the run-wide collected-error tally.

The bad thing: `ctx.collected_errors` (a per-run count, _context.py:226-231) says
K row errors were captured, but the map's output carries a different number of
error objects - or a map that RAISED (fail mode) leaves a non-zero tally behind.

Abstraction: N=2 outer rows. A row may run a NESTED collect-mode map that records
one error into the shared tally (iteration.py:187 inside the row's sub-executor)
before the row itself finishes ok or fails. Outer mode is fixed per run.
"""
NAME = "FIX candidate: row-scoped tally, committed to the run only when the map returns"
N = 2
MODES = ("collect", "skip", "fail")


def init():
    return [
        {"mode": m, "rows": ("pending",) * N, "nested": (0,) * N, "tally": 0,
         "phase": "running", "out_errors": -1, "out_len": -1, "pending": 0}
        for m in MODES
    ]


def _set(t, i, v):
    return t[:i] + (v,) + t[i + 1:]


def actions(s):
    out = []
    if s["phase"] != "running":
        return out
    rows = s["rows"]
    failed_any = "failed" in rows
    for i, st in enumerate(rows):
        if st == "pending" and s["nested"][i] == 0:
            # nested collect map inside row i captures one inner row error
            out.append((f"inner_record_{i}", {**s, "nested": _set(s["nested"], i, 1)}))
        if st == "pending":
            out.append((f"row_ok_{i}", {**s, "rows": _set(rows, i, "ok"),
                                       "pending": s["pending"] + s["nested"][i]}))
            out.append((f"row_fail_{i}", {**s, "rows": _set(rows, i, "failed")}))
    if s["mode"] == "fail" and failed_any and "pending" in rows:
        # TaskGroup cancels every still-running sibling (iteration.py:139-145)
        out.append(("cancel", {**s, "rows": tuple("cancelled" if r == "pending" else r for r in rows)}))
    if "pending" not in rows:
        if s["mode"] == "fail":
            if failed_any:
                out.append(("finish_raise", {**s, "phase": "raised"}))
            else:
                emb = sum(s["nested"])
                out.append(("finish", {**s, "phase": "done", "tally": s["tally"] + s["pending"],
                                       "out_errors": emb, "out_len": N}))
        elif s["mode"] == "collect":
            fails = rows.count("failed")
            emb = sum(n for r, n in zip(rows, s["nested"]) if r == "ok") + fails
            out.append(("finish", {**s, "phase": "done", "tally": s["tally"] + s["pending"] + fails,
                                   "out_errors": emb, "out_len": N}))
        else:  # skip
            emb = sum(n for r, n in zip(rows, s["nested"]) if r == "ok")
            out.append(("finish", {**s, "phase": "done", "tally": s["tally"] + s["pending"],
                                   "out_errors": emb, "out_len": rows.count("ok")}))
    return out


FAILURE_ACTIONS = ["row_fail_0", "row_fail_1", "inner_record_0", "inner_record_1", "cancel"]

INVARIANTS = {
    # coupling invariant: the tally counts exactly the error objects the caller can see
    "tally_matches_output": lambda s: s["phase"] != "done" or s["tally"] == s["out_errors"],
    # an aborted (fail-mode) map leaves no captured-error residue
    "raise_leaves_no_tally": lambda s: s["phase"] != "raised" or s["tally"] == 0,
    # collect never loses a row; skip keeps exactly the ok rows
    "collect_keeps_all_rows": lambda s: not (s["phase"] == "done" and s["mode"] == "collect")
        or s["out_len"] == N,
    "skip_keeps_ok_rows": lambda s: not (s["phase"] == "done" and s["mode"] == "skip")
        or s["out_len"] == s["rows"].count("ok"),
}
STEP_INVARIANTS = {"tally_monotone": lambda s, t: t["tally"] >= s["tally"]}
TERMINAL = lambda s: s["phase"] in ("done", "raised")
EVENTUALLY = {"settles": lambda s: s["phase"] in ("done", "raised")}

SOURCE_UNUSED = {
    "inner_record_0": ("/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/nodes/iteration.py:187", "ctx.record_collected_error()"),
    "cancel": ("/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/nodes/iteration.py:139", "async with asyncio.TaskGroup() as tg:"),
    "finish": ("/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/nodes/iteration.py:113", "return self._skip(raw)"),
    "finish_raise": ("/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/nodes/iteration.py:145", "reraise_first(group)"),
}
