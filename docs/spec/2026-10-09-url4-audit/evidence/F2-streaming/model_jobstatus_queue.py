"""JobStatus as observed through a JobRunner adapter, against the port's state machine.

THE BAD THING: `status(topic)` reports an outcome the run did not have (a failed run read
as `succeeded`), or a terminal status that later changes, so a caller acting on it (the
reaper, `exists()`, a REST status read, the unclaimed-run warner) acts on a false verdict.

The port (url4/streaming/interfaces/jobs.py:16-25):
    scheduled -> running -> {succeeded | failed | stopped | timed_out},  not_found = unknown.
The relation below is that sentence written as a SET, plus the edges the port text and the
adapters' docstrings call intended (capability expiry, a cancel before start, history
eviction, an adapter that reports `running` from acceptance).

ADAPTER = "queue"  ->  screamingface_engine/adapters/inprocess.py (_map_status, schedule,
                            stop): status derived from the asyncio TASK.
ADAPTER = "queue"      ->  screamingface_engine/adapters/queue_runner.py (status): status
                            derived from the run's stream TAIL + replica-local capability.

The environment (the run itself) ends through lifecycle.run, whose terminal FRAME carries
the outcome; `lifecycle.run` catches failed/timed_out and RETURNS (task not failed), and
re-raises only CancelledError (task cancelled).

Run:  fm check model_jobstatus.py -D ADAPTER='"inprocess"'   /   -D ADAPTER='"queue"'
"""
NAME = "JobStatus observed through a JobRunner"

ADAPTER = "queue"
WORKER_DROPS_EXPIRED = 1   # queue: the worker never starts a run whose capability expired

TERMINAL_STATUSES = ("succeeded", "failed", "stopped", "timed_out")
ENG = "/Users/junior/workspace/screamingface/apps/screamingface-engine/src/screamingface_engine/adapters"
JOBS = "/Users/junior/workspace/screamingface/packages/url4/src/url4/streaming/interfaces/jobs.py"

SPEC = {
    ("not_found", "scheduled"), ("not_found", "running"),     # accepted (running: in-process)
    ("scheduled", "running"),
    ("scheduled", "stopped"),                                  # cancel before start (tombstone)
    ("scheduled", "not_found"),                                # capability expired while queued
    *(("running", t) for t in TERMINAL_STATUSES),
    *((t, "not_found") for t in TERMINAL_STATUSES),            # history eviction / forgotten
}


def init():
    return [{"run": "none", "outcome": None, "task": None, "tail": None, "cap": False,
             "status": "not_found"}]


def _observe(s):
    if ADAPTER == "inprocess":
        task = s["task"]                         # inprocess.py:61-72
        if task is None:
            return "not_found"
        if task == "pending":
            return "running"
        if task == "cancelled":
            return "stopped"
        return "failed" if task == "raised" else "succeeded"
    tail = s["tail"]                             # queue_runner.py:451-483
    if tail in TERMINAL_STATUSES:
        return tail
    if tail is not None:
        return "running"
    return "scheduled" if s["cap"] else "not_found"


def _st(s):
    return {**s, "status": _observe(s)}


def actions(s):
    out = []
    run = s["run"]
    if ADAPTER == "inprocess":
        # schedule: refused only while the previous task is still pending (inprocess.py:248-250)
        if s["task"] != "pending":
            out.append(("schedule", _st({**s, "run": "running", "outcome": None,
                                         "task": "pending"})))
        if run == "running":
            for o in ("succeeded", "failed", "timed_out"):     # lifecycle returns normally
                out.append((f"run_ends_{o}", _st({**s, "run": "done", "outcome": o,
                                                  "task": "returned"})))
            out.append(("stop_cancels_task", _st({**s, "run": "done", "outcome": "stopped",
                                                  "task": "cancelled"})))
            # an arm's own _terminate raised: run() raises with no terminal frame
            out.append(("run_raises_without_frame", _st({**s, "run": "done", "outcome": None,
                                                         "task": "raised"})))
        if s["task"] in ("returned", "cancelled", "raised"):
            out.append(("history_evicts", _st({**s, "run": "none", "outcome": None,
                                               "task": None})))
        if s["task"] is None:
            out.append(("stop_unknown_noop", _st(s)))
        return out

    # queue adapter
    if run == "none":
        out.append(("schedule", _st({**s, "run": "queued", "cap": True})))
    if run == "queued":
        if s["cap"] or not WORKER_DROPS_EXPIRED:
            out.append(("worker_claims_and_starts", _st({**s, "run": "running", "tail": "started"})))
        out.append(("stop_tombstones_queued", _st({**s, "run": "done", "outcome": "stopped",
                                                   "tail": "stopped"})))
    if s["cap"]:
        out.append(("capability_expires", _st({**s, "cap": False})))
    if run == "running":
        for o in TERMINAL_STATUSES:
            out.append((f"run_ends_{o}", _st({**s, "run": "done", "outcome": o, "tail": o})))
    if run == "done" and s["tail"] in TERMINAL_STATUSES:
        # delete_stream keeps the terminal frame (keep=1); a late stop is a no-op on a terminal tail
        out.append(("reclaim_keeps_terminal", _st(s)))
        out.append(("stop_on_terminal_noop", _st(s)))
    if run == "none":
        out.append(("stop_unknown_noop", _st(s)))
    return out


INVARIANTS = {
    # what a caller reads is the run's real outcome once the run has one
    "status_is_the_outcome": lambda s: s["outcome"] is None or s["status"] == s["outcome"],
    "status_is_a_jobstatus": lambda s: s["status"] in
        ("scheduled", "running", "not_found", *TERMINAL_STATUSES),
}

STEP_INVARIANTS = {
    "only_port_transitions": lambda s, t: s["status"] == t["status"]
        or (s["status"], t["status"]) in SPEC,
    "terminal_is_absorbing": lambda s, t: s["status"] not in TERMINAL_STATUSES
        or t["status"] in (s["status"], "not_found"),
}

FAILURE_ACTIONS = ["run_raises_without_frame", "capability_expires", "stop_cancels_task",
                   "stop_tombstones_queued"]
ALLOW_DEADLOCK = True

ASSUMPTIONS = {"WORKER_DROPS_EXPIRED": "the worker never starts a run whose capability "
                                       "expired while it sat queued (config.py:163-165)"}

SOURCE = {
    "schedule": (f"{ENG}/inprocess.py:249", "if existing is not None and not existing.done()")
    if ADAPTER == "inprocess" else (f"{ENG}/queue_runner.py:263", "async def schedule("),
    "run_ends_succeeded": (f"{ENG}/inprocess.py:64", 'return "failed" if task.exception()')
    if ADAPTER == "inprocess" else (f"{ENG}/queue_runner.py:478", "return frame.data.status"),
    "run_ends_failed": (f"{ENG}/inprocess.py:64", 'return "failed" if task.exception()')
    if ADAPTER == "inprocess" else (f"{ENG}/queue_runner.py:478", "return frame.data.status"),
    "run_ends_timed_out": (f"{ENG}/inprocess.py:64", 'return "failed" if task.exception()')
    if ADAPTER == "inprocess" else (f"{ENG}/queue_runner.py:478", "return frame.data.status"),
    "stop_unknown_noop": (f"{ENG}/inprocess.py:298", "if task is not None and not task.done()")
    if ADAPTER == "inprocess" else (f"{ENG}/queue_runner.py:420", "Never scheduled by this App"),
}
if ADAPTER == "inprocess":
    SOURCE.update({
        "stop_cancels_task": (f"{ENG}/inprocess.py:299", "task.cancel()"),
        "run_raises_without_frame": (f"{ENG}/inprocess.py:64", "task.exception()"),
        "history_evicts": (f"{ENG}/inprocess.py:83", "frees its `job_name` slot"),
    })
else:
    SOURCE.update({
        "run_ends_stopped": (f"{ENG}/queue_runner.py:478", "return frame.data.status"),
        "worker_claims_and_starts": (f"{ENG}/queue_runner.py:482", 'return "running"'),
        "stop_tombstones_queued": (f"{ENG}/queue_runner.py:426", "await self._publish_tombstone(topic)"),
        "capability_expires": (f"{ENG}/queue_runner.py:483", "_capability_valid(topic)"),
        "reclaim_keeps_terminal": (f"{ENG}/jetstream.py:548", "keep=1"),
        "stop_on_terminal_noop": (f"{ENG}/queue_runner.py:395", "if isinstance(frame, TerminatedEvent)"),
    })
