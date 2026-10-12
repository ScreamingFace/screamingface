"""Counter abstraction of model_admission.py, for every N (requests) and MAX >= 1.

inflight  the wrapper's counter (_serve.py:273,294,305)
active    requests admitted and not finished
live      alive children owned by an active request
orphans   alive children whose request already finished (released its slot)
KILL      0 = current code (kill only on TimeoutError), 1 = kill in finally

Claim: inflight == active, 0 <= inflight <= MAX, and the number of RUNNING
subprocesses (live + orphans) never exceeds MAX - the spec serve §6 promise that
the in-flight counter "bounds cost as well as load".
"""
from z3 import And, Int, Or

NAME = "serve admission: slot accounting only, CURRENT code"
KILL = 0


def state(k):
    return {n: Int(f"{n}{k}") for n in ("inflight", "active", "live", "orphans", "max")}


def _same(s, t, *names):
    return And(*[t[n] == s[n] for n in names])


def init(s):
    return And(s["inflight"] == 0, s["active"] == 0, s["live"] == 0, s["orphans"] == 0, s["max"] >= 1)


ACTIONS = {
    "admit": lambda s, t: And(s["inflight"] < s["max"], t["inflight"] == s["inflight"] + 1,
                              t["active"] == s["active"] + 1, _same(s, t, "live", "orphans", "max")),
    "spawn": lambda s, t: And(s["active"] > s["live"], t["live"] == s["live"] + 1,
                              _same(s, t, "inflight", "active", "orphans", "max")),
    "child_exits": lambda s, t: And(s["live"] > 0, t["live"] == s["live"] - 1,
                                    t["active"] == s["active"] - 1, t["inflight"] == s["inflight"] - 1,
                                    _same(s, t, "orphans", "max")),
    "raise_before_spawn": lambda s, t: And(s["active"] > s["live"], t["active"] == s["active"] - 1,
                                           t["inflight"] == s["inflight"] - 1,
                                           _same(s, t, "live", "orphans", "max")),
    "timeout_or_cancel_with_child": lambda s, t: And(
        s["live"] > 0, t["live"] == s["live"] - 1, t["active"] == s["active"] - 1,
        t["inflight"] == s["inflight"] - 1, t["orphans"] == s["orphans"] + (1 - KILL), t["max"] == s["max"]),
    "orphan_exits": lambda s, t: And(s["orphans"] > 0, t["orphans"] == s["orphans"] - 1,
                                     _same(s, t, "inflight", "active", "live", "max")),
}


if KILL:  # with kill-in-finally an orphan cannot exist, so its exit is not an action
    del ACTIONS["orphan_exits"]


def inv(s):
    return And(s["inflight"] == s["active"], s["inflight"] >= 0, s["inflight"] <= s["max"],
               s["live"] >= 0, s["live"] <= s["active"], s["orphans"] >= 0,
               *([s["orphans"] == 0] if KILL else []))  # strengthening: with KILL=1 no orphan exists
