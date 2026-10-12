"""`url4 serve` admission control + command-subprocess lifecycle.

The bad thing: an admitted request leaks its in-flight slot (permanent 503), OR a
request is released while the subprocess it spawned keeps running, so
--max-inflight no longer bounds the live work (spec serve §6: the counter "bounds
cost as well as load").

Abstraction: N requests, one command subprocess each. Per request:
  phase  idle -> admitted -> child -> done        (or idle -> rejected, the 503)
  child  none -> alive -> reaped
The serve wrapper (cli/_serve.py:_serve_http) and the command runner
(_run_command) are collapsed into one per-request automaton; the event loop is
single-threaded, so each label is one atomic step between awaits.

KILL_ON_CANCEL = 0 is the code as it is (kill only in `except TimeoutError`);
KILL_ON_CANCEL = 1 is the proposed fix (kill + wait in a `finally` that also
runs on CancelledError).

Run: fm check model_admission.py                   (buggy, current code)
     fm check model_admission.py -D KILL_ON_CANCEL=1 (fixed)
"""

NAME = "url4 serve admission + subprocess reaping"

N = 2  # concurrent requests
MAX = 1  # --max-inflight
KILL_ON_CANCEL = 0  # 0: current code; 1: kill/wait in finally
RELEASE_ON_EXCEPTION = 1  # 1: the decrement is in `finally` (_serve.py:304-305), as coded
INNER_TIMEOUT_FIRST = 0  # 1 iff the command's own wait_for can fire before the outer timeout

_SERVE = "/Users/junior/workspace/screamingface/packages/url4/src/url4/cli/_serve.py"

ASSUMPTIONS = {
    "RELEASE_ON_EXCEPTION": "1: the in-flight decrement is in a `finally` (_serve.py:304-305)",
    "INNER_TIMEOUT_FIRST": (
        "0 in url4 serve: _serve.py:252 passes config.timeout to the command and "
        "_serve.py:297 arms asyncio.timeout(config.timeout) EARLIER, so the outer "
        "deadline always fires first"
    ),
}

R = range(N)


def init():
    return [
        {
            "phase": ("idle",) * N,
            "child": ("none",) * N,
            "inflight": 0,
            "released": (0,) * N,
            "shutdown": False,
        }
    ]


def _set(t, i, v):
    return t[:i] + (v,) + t[i + 1 :]


def _finish(s, i, reap, exc=False):
    """The `finally: inflight -= 1` (_serve.py:304-305) plus what happens to the child."""
    child = s["child"][i]
    if child == "alive" and reap:
        child = "reaped"
    if exc and not RELEASE_ON_EXCEPTION:
        # the decrement is skipped: what the code would do with it outside `finally`
        return {**s, "phase": _set(s["phase"], i, "done"), "child": _set(s["child"], i, child)}
    return {
        **s,
        "phase": _set(s["phase"], i, "done"),
        "child": _set(s["child"], i, child),
        "inflight": s["inflight"] - 1,
        "released": _set(s["released"], i, s["released"][i] + 1),
    }


def actions(s):
    out = []
    for i in range(N):
        ph, ch = s["phase"][i], s["child"][i]
        if ph == "idle" and not s["shutdown"]:
            if s["inflight"] >= MAX:
                out.append((f"reject503_{i}", {**s, "phase": _set(s["phase"], i, "rejected")}))
            else:
                out.append(
                    (
                        f"admit_{i}",
                        {
                            **s,
                            "phase": _set(s["phase"], i, "admitted"),
                            "inflight": s["inflight"] + 1,
                        },
                    )
                )
        if ph == "admitted":
            out.append(
                (
                    f"spawn_{i}",
                    {
                        **s,
                        "phase": _set(s["phase"], i, "child"),
                        "child": _set(s["child"], i, "alive"),
                    },
                )
            )
            # create_subprocess_exec OSError, a dispatch error, or a client disconnect
            # while sending: some exception other than TimeoutError leaves base().
            out.append((f"handler_raises_{i}", _finish(s, i, reap=True, exc=True)))
        if ph == "child" and ch == "alive":
            # communicate() returns: the child has exited (any exit code) and is reaped.
            out.append((f"child_exits_{i}", _finish(s, i, reap=True)))
            if INNER_TIMEOUT_FIRST:
                out.append((f"inner_timeout_kill_{i}", _finish(s, i, reap=True)))
        if ph in ("admitted", "child"):
            # the wrapper deadline fires: CancelledError is thrown into the awaiting
            # handler; _run_command catches only TimeoutError.
            out.append((f"outer_timeout_{i}", _finish(s, i, reap=bool(KILL_ON_CANCEL), exc=True)))
            # the task is cancelled from outside (server force-shutdown, disconnect
            # handling in some ASGI servers): same exception path, no 504.
            out.append((f"task_cancelled_{i}", _finish(s, i, reap=bool(KILL_ON_CANCEL), exc=True)))
        if ph == "done" and ch == "alive":
            # an orphan MAY finish by itself (`sleep N`); one blocked on a full stdout
            # pipe (`yes`) never does — so this is not FAIR.
            out.append((f"orphan_exits_{i}", {**s, "child": _set(s["child"], i, "reaped")}))
    if not s["shutdown"]:
        out.append(("lifespan_shutdown", {**s, "shutdown": True}))  # node.aclose: no child effect
    return out


def _live(s):
    return sum(1 for c in s["child"] if c == "alive")


def _active(s):
    return sum(1 for p in s["phase"] if p in ("admitted", "child"))


INVARIANTS = {
    "inflight_nonneg": lambda s: s["inflight"] >= 0,
    "inflight_le_max": lambda s: s["inflight"] <= MAX,
    "inflight_equals_active": lambda s: s["inflight"] == _active(s),
    "released_at_most_once": lambda s: all(r <= 1 for r in s["released"]),
    "done_means_released": lambda s: all(
        (p == "done") == (r == 1) for p, r in zip(s["phase"], s["released"], strict=True)
    ),
    "live_children_le_inflight": lambda s: _live(s) <= s["inflight"],
}

STEP_INVARIANTS = {
    "no_child_outlives_its_request": lambda s, t: all(
        not (t["phase"][i] == "done" and t["child"][i] == "alive") for i in range(N)
    ),
}

EVENTUALLY = {
    "slot_can_free": lambda s: s["inflight"] == 0,
}


def TERMINAL(s):
    return all(p in ("done", "rejected", "idle") for p in s["phase"]) and _live(s) == 0


ALLOW_DEADLOCK = False

FAILURE_ACTIONS = (
    [f"handler_raises_{i}" for i in R]
    + [f"outer_timeout_{i}" for i in R]
    + [f"task_cancelled_{i}" for i in R]
    + [f"inner_timeout_kill_{i}" for i in R]
    + ["lifespan_shutdown"]
)

SOURCE = {}
for _i in R:
    SOURCE[f"reject503_{_i}"] = (f"{_SERVE}:287", 'if state["inflight"] >= config.max_inflight:')
    SOURCE[f"admit_{_i}"] = (f"{_SERVE}:294", 'state["inflight"] += 1')
    SOURCE[f"spawn_{_i}"] = (f"{_SERVE}:144", "proc = await asyncio.create_subprocess_exec(")
    SOURCE[f"handler_raises_{_i}"] = (f"{_SERVE}:305", 'state["inflight"] -= 1')
    SOURCE[f"child_exits_{_i}"] = (
        f"{_SERVE}:153",
        "out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode()), timeout)",
    )
    SOURCE[f"inner_timeout_kill_{_i}"] = (f"{_SERVE}:155", "proc.kill()")
    SOURCE[f"outer_timeout_{_i}"] = (f"{_SERVE}:297", "async with asyncio.timeout(config.timeout):")
    SOURCE[f"task_cancelled_{_i}"] = (f"{_SERVE}:154", "except TimeoutError:")
SOURCE["lifespan_shutdown"] = (f"{_SERVE}:277", "await _lifespan(receive, send, on_shutdown=node.aclose)")

COST = {"fix": "try/finally in _run_command: if proc.returncode is None: kill(); await wait()"}
