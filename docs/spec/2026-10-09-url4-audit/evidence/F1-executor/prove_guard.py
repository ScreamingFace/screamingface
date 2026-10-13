"""GuardNode, candidate fix (idempotency key), proved for EVERY retry budget R >= 0
and every number of abandoned (zombie) requests.

Same transition relation as guard_retry_fixed.py, with R symbolic (a frozen
Int, unconstrained except R >= 0). Two claims:

  inv      effect applied at most once; attempts within budget; no AssertionError path
  variant  5*(R+1-attempts) + rank(phase) + zombies  strictly decreases on every step
           -> the guard loop (guard.py:69) has no infinite behaviour, for any R.

phase encoding: 0 terminal(ok/failed), 1 idle, 2 applied, 3 pending, 4 queued, 9 assert_error
Run:  fm prove prove_guard.py --bmc 6
"""
from z3 import And, If, Int, Or

NAME = "GuardNode with idempotency key - unbounded"

TERM, IDLE, APPLIED, PENDING, QUEUED, ASSERT = 0, 1, 2, 3, 4, 9


def state(k):
    return {"ph": Int(f"ph{k}"), "att": Int(f"att{k}"), "eff": Int(f"eff{k}"),
            "zom": Int(f"zom{k}"), "seen": Int(f"seen{k}"), "R": Int(f"R{k}")}


def init(s):
    return And(s["ph"] == IDLE, s["att"] == 0, s["eff"] == 0, s["zom"] == 0,
               s["seen"] == 0, s["R"] >= 0)


def _keep(s, t, *names):
    return And(*[t[n] == s[n] for n in names])


def _apply(s, t):
    # deduping remote: applies only the first time it sees the key
    return t["eff"] == If(s["eff"] >= 1, s["eff"], s["eff"] + 1)


ACTIONS = {
    "start_attempt": lambda s, t: And(s["ph"] == IDLE, s["att"] < s["R"] + 1,
                                      t["ph"] == QUEUED, t["att"] == s["att"] + 1,
                                      _keep(s, t, "eff", "zom", "seen", "R")),
    "give_up": lambda s, t: And(s["ph"] == IDLE, s["att"] >= s["R"] + 1,
                                t["ph"] == If(s["att"] >= 1, TERM, ASSERT),
                                _keep(s, t, "att", "eff", "zom", "seen", "R")),
    "acquire_permit": lambda s, t: And(s["ph"] == QUEUED, t["ph"] == PENDING,
                                       _keep(s, t, "att", "eff", "zom", "R"), t["seen"] == 1),
    "remote_applies": lambda s, t: And(s["ph"] == PENDING, t["ph"] == APPLIED, _apply(s, t),
                                       _keep(s, t, "att", "zom", "seen", "R")),
    "transient_error": lambda s, t: And(s["ph"] == PENDING, t["ph"] == IDLE,
                                        _keep(s, t, "att", "eff", "zom", "seen", "R")),
    "permanent_error": lambda s, t: And(s["ph"] == PENDING, s["eff"] == 0, s["zom"] == 0,
                                        t["ph"] == TERM,
                                        _keep(s, t, "att", "eff", "zom", "seen", "R")),
    "response_ok": lambda s, t: And(s["ph"] == APPLIED, t["ph"] == TERM,
                                    _keep(s, t, "att", "eff", "zom", "seen", "R")),
    "error_after_apply": lambda s, t: And(s["ph"] == APPLIED, t["ph"] == IDLE,
                                          _keep(s, t, "att", "eff", "zom", "seen", "R")),
    "deadline_while_queued": lambda s, t: And(s["ph"] == QUEUED, t["ph"] == IDLE,
                                              _keep(s, t, "att", "eff", "zom", "seen", "R")),
    "deadline_while_pending": lambda s, t: And(s["ph"] == PENDING, t["ph"] == IDLE,
                                               t["zom"] == s["zom"] + 1,
                                               _keep(s, t, "att", "eff", "seen", "R")),
    "deadline_after_applied": lambda s, t: And(s["ph"] == APPLIED, t["ph"] == IDLE,
                                               _keep(s, t, "att", "eff", "zom", "seen", "R")),
    "zombie_applies": lambda s, t: And(s["zom"] >= 1, t["zom"] == s["zom"] - 1, _apply(s, t),
                                       _keep(s, t, "ph", "att", "seen", "R")),
}


def inv(s):
    return And(
        s["R"] >= 0, s["att"] >= 0, s["zom"] >= 0,
        s["eff"] >= 0, s["eff"] <= 1,                     # effect_at_most_once
        s["att"] <= s["R"] + 1,                           # attempts_within_budget
        s["ph"] != ASSERT,                                # failure_is_a_url4_error
        Or(s["ph"] == TERM, s["ph"] == IDLE, s["ph"] == APPLIED,
           s["ph"] == PENDING, s["ph"] == QUEUED),
        # strengthening: a non-idle, non-terminal phase means an attempt is running
        If(Or(s["ph"] == QUEUED, s["ph"] == PENDING, s["ph"] == APPLIED), s["att"] >= 1, True),
        If(s["ph"] == APPLIED, s["eff"] == 1, True),
    )


def variant(s):
    rank = If(s["ph"] == QUEUED, 4, If(s["ph"] == PENDING, 3,
              If(s["ph"] == APPLIED, 2, If(s["ph"] == IDLE, 1, 0))))
    return 5 * (s["R"] + 1 - s["att"]) + rank + s["zom"]
