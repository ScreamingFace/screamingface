"""GuardNode retry + timeout, AS WRITTEN (url4 dag/nodes/guard.py).

The bad thing is: one guarded source applies its remote effect more than once
(a double charge / a double LLM bill / a double write), or the caller is told
a source "timed out" when no I/O was ever issued.

One guarded source. Each attempt runs the inner subtree on a fresh
sub-executor (guard.py:79-84). Inside an attempt the fetch first waits for a
run-wide permit (BoundedIOLayer, _context.py:145), then sends the request.
``asyncio.timeout`` (guard.py:83) wraps the WHOLE attempt: queueing included.

phase:
  idle     between attempts (the for-loop head, guard.py:69)
  queued   waiting for the run-wide semaphore permit
  pending  request sent, the remote has not applied it yet
  applied  the remote applied the effect, the response is not back yet
  ok | failed | assert_error   terminal
zombies: requests abandoned by a deadline while pending; the remote may still
         apply them later (a cancelled HTTP request is not an un-sent one).

Run:  fm check guard_retry_as_written.py --keep-going --coverage
"""

NAME = "GuardNode retry+timeout (as written)"

RETRIES = 2          # ;retry=N  -> N+1 attempts (guard.py:69)
HAS_TIMEOUT = 1      # ;t= is set
CANCEL_HONOURED = 1  # the inner IOLayer lets CancelledError propagate
DEDUP_AT_REMOTE = 0  # the remote dedups by an idempotency key (url4 sends none)

ASSUMPTIONS = {
    "HAS_TIMEOUT": "the source carries ;t= (else only the IOLayer's own timeout bounds an attempt)",
    "CANCEL_HONOURED": "the IOLayer / inner nodes do not swallow CancelledError",
}

G = "/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/nodes/guard.py"
C = "/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/_context.py"
SOURCE = {
    "start_attempt": (f"{G}:69", "for _ in range(self.retries + 1)"),
    "acquire_permit": (f"{C}:145", "async with self._sem"),
    "remote_applies": (f"{C}:146", "return await self._inner.fetch"),
    "response_ok": (f"{G}:71", "return await self._once(scope, ctx)"),
    "transient_error": (f"{G}:75", "last = exc"),
    "error_after_apply": (f"{G}:75", "last = exc"),
    "permanent_error": (f"{G}:73", "if exc.permanent"),
    "deadline_while_queued": (f"{G}:85", "except TimeoutError as exc"),
    "deadline_while_pending": (f"{G}:85", "except TimeoutError as exc"),
    "deadline_after_applied": (f"{G}:85", "except TimeoutError as exc"),
    "give_up": (f"{G}:76", "assert last is not None"),
    # zombie_applies: injected by the world (the remote processes an abandoned request)
}

# The remote's misbehaviour. The deadline_* actions are OUR timer firing (asyncio.timeout),
# so they are in FAIR; what they expose (an applied effect whose response is discarded, a
# sent request that still lands later) is carried by deadline_after_applied's successor
# states and by zombie_applies. A remote that never answers is a STUTTER: response_ok is
# deliberately NOT fair.
FAILURE_ACTIONS = ["transient_error", "error_after_apply", "permanent_error", "zombie_applies"]

TERMINALS = ("ok", "failed", "assert_error")


def init():
    return [{"phase": "idle", "attempts": 0, "effects": 0, "zombies": 0,
             "last": None, "timeout_without_io": False}]


def _apply(s):
    if DEDUP_AT_REMOTE and s["effects"] >= 1:
        return s["effects"]
    return s["effects"] + 1


def _deadline(s, extra):
    # asyncio.timeout -> TimeoutError -> ResolutionError(TIMEOUT), transient: loop again
    return {**s, "phase": "idle", "last": "timeout", **extra}


def actions(s):
    out = []
    ph = s["phase"]
    if ph == "idle":
        if s["attempts"] < RETRIES + 1:
            # timeout_without_io is per ATTEMPT (model bug fixed after run 2: it was sticky)
            out.append(("start_attempt", {**s, "phase": "queued", "attempts": s["attempts"] + 1,
                                          "timeout_without_io": False}))
        else:
            # loop exhausted: raise last (or AssertionError if the loop never ran)
            out.append(("give_up", {**s, "phase": "failed" if s["last"] else "assert_error"}))
    if ph == "queued":
        out.append(("acquire_permit", {**s, "phase": "pending"}))
    if ph == "pending":
        out.append(("remote_applies", {**s, "phase": "applied", "effects": _apply(s)}))
        out.append(("transient_error", {**s, "phase": "idle", "last": "transient"}))
        out.append(("permanent_error", {**s, "phase": "failed", "last": "permanent"}))
    if ph == "applied":
        out.append(("response_ok", {**s, "phase": "ok"}))
        # e.g. a 5xx / reset after the remote committed: looks transient, is not a non-event
        out.append(("error_after_apply", {**s, "phase": "idle", "last": "transient"}))
    if HAS_TIMEOUT and CANCEL_HONOURED:
        if ph == "queued":
            out.append(("deadline_while_queued", _deadline(s, {"timeout_without_io": True})))
        if ph == "pending":
            out.append(("deadline_while_pending", _deadline(s, {"zombies": s["zombies"] + 1})))
        if ph == "applied":
            out.append(("deadline_after_applied", _deadline(s, {})))
    if s["zombies"] > 0:
        out.append(("zombie_applies", {**s, "zombies": s["zombies"] - 1, "effects": _apply(s)}))
    return out


INVARIANTS = {
    "effect_at_most_once": lambda s: s["effects"] <= 1,
    "attempts_within_budget": lambda s: s["attempts"] <= max(RETRIES + 1, 0),
    "failure_is_a_url4_error": lambda s: s["phase"] != "assert_error",
    "timeout_implies_io_issued": lambda s: not (s["last"] == "timeout" and s["timeout_without_io"]),
    # ADDED AFTER THE FIRST RUN (review question 2: success with a lost response).
    # A source reported as failed (raised, or SourceFailure under ;optional) had no effect.
    "failed_source_had_no_effect": lambda s: not (s["phase"] == "failed" and s["effects"] > 0),
}

LEADS_TO = {
    "guarded_source_finishes": (lambda s: s["phase"] not in TERMINALS,
                                lambda s: s["phase"] in TERMINALS),
}
# The guard loop and the event-loop timer are code we run; the remote is not.
FAIR = ["start_attempt", "give_up",
        "deadline_while_queued", "deadline_while_pending", "deadline_after_applied"]


def TERMINAL(s):
    return s["phase"] in TERMINALS
