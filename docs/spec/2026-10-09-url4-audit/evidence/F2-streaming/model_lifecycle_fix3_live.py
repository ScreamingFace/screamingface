"""url4.streaming.lifecycle.run - the run's frame protocol, as an LTS.

THE BAD THING: a subscriber sees two terminal frames (two conflicting outcomes), a frame
after the terminal frame, a hole in the sequence; or a started run never gets a terminal
frame at all (the subscriber waits for ever).

Abstraction
-----------
* One run, one topic. Frames written to the stream are a tuple of (seq, kind).
  kind: S=Started, L=log/span telemetry, C=subtree cost, R=result, T:<status>=Terminated.
* The sequencer counter `n` is advanced when `seq.next()` is EVALUATED, i.e. before
  `stream.publish(...)` is awaited (lifecycle.py:117/166/177/181/182). Every outcome of a
  publish call - success, raise, cancellation - has consumed the number.
* Every awaited port call (ensure_stream, publish, flush, the executor's __anext__) is a
  suspension point. At each one the environment may: let it succeed, make it raise, deliver
  an external cancel, or (inside `async with deadline`) fire the deadline. A publish has
  two extra outcomes: written-then-raise (response lost) and written-then-cancelled.
* Exceptions are routed exactly as `run`'s try/except does (lifecycle.py:221-240):
  an exception raised INSIDE an except arm is not caught by a sibling arm; the cancel arm
  suppresses `Exception` but not a second `CancelledError`.

Variants (constant FIX):
  0  as built.
  1  `_terminate("succeeded")` moved to the `else:` clause of the try, so its own failure
     or cancellation propagates instead of selecting a second outcome arm.
  2  as built, but the terminal frame keeps ONE sequence number across retries (the arm's
     `_terminate` reuses the number the first attempt consumed); with a transport that
     de-duplicates by sequence (JetStream Nats-Msg-Id = <topic>:<seq>) the retry is
     idempotent.
  3  as built, plus a `terminal_sent` flag set when `_terminate`'s publish RETURNS; an
     except arm that finds it set re-raises instead of publishing a second terminal frame.

Run:
  fm check model_lifecycle.py --keep-going
  fm check model_lifecycle.py -D TERM_PATH_RELIABLE=1      # liveness under that assumption
"""
NAME = "url4 lifecycle.run - candidate fix FIX=3 (liveness)"

FIX = 3
MAX_TEL = 1               # telemetry frames the executor may yield before Completed
FAULTS = 2                # budget: publish/flush/ensure raises + executor raise/incomplete
CANCELS = 1               # budget: external cancels (in-process `stop`, shutdown)
HANG_POSSIBLE = 1         # the executor may never yield again
DEADLINE_SET = 1          # deadline_s is not None
DEDUP_BY_SEQ = 1          # the transport drops a frame whose seq is already stored
LOST_RESPONSE = 0         # a publish may write the frame and still raise / be cancelled
TERM_PATH_RELIABLE = 1    # 1 = publish/flush inside _terminate never fail and are never cancelled

LC = "/Users/junior/workspace/screamingface/packages/url4/src/url4/streaming/lifecycle.py"

PUB_PCS = {"pub_started": "S", "pub_tel": "L", "pub_cost": "C", "pub_result": "R"}
DEADLINE_PCS = {"pub_started", "exec", "pub_tel", "pub_cost", "pub_result", "flush_exec"}


def init():
    out = []
    for hang in ([False, True] if HANG_POSSIBLE else [False]):
        out.append({
            "pc": "ensure", "arm": None, "in_try": False, "started": False,
            "frames": (), "n": 0, "tel": 0, "faults": FAULTS, "cancels": CANCELS,
            "deadline": "armed" if DEADLINE_SET else "off", "hang": hang,
            "status": None, "term_seq": None, "out": None, "sent": False,
        })
    return out


# ---------------------------------------------------------------- helpers

def _write(s, seq, kind):
    if DEDUP_BY_SEQ and any(q == seq for q, _ in s["frames"]):
        return s  # the broker drops a duplicate sequence (Msg-Id dedup window)
    return {**s, "frames": s["frames"] + ((seq, kind),)}


def _exit(s, how):
    return {**s, "pc": "exit", "out": how, "deadline": "off"}


def _after_terminate(s):
    """_terminate returned normally: finish the arm (or the success path)."""
    if s["arm"] == "cancel":
        return _exit(s, "cancelled")          # `raise` at lifecycle.py:238
    return _exit(s, "returned")


def _route(s, exc):
    """An exception `exc` in {'exc','cancel','timeout'} surfaces at the current await."""
    if not s["in_try"]:
        return _exit(s, "cancelled" if exc == "cancel" else "raised")
    if s["arm"] is None:
        if FIX == 3 and s["sent"]:
            return _exit(s, "cancelled" if exc == "cancel" else "raised")
        status = {"timeout": "timed_out", "cancel": "stopped", "exc": "failed"}[exc]
        return {**s, "pc": "term_pub", "arm": exc, "status": status, "deadline": "off"}
    # raised inside an except arm: siblings do not catch it
    if s["arm"] == "cancel" and exc != "cancel":
        return _exit(s, "cancelled")          # suppress(Exception), then re-raise the cancel
    return _exit(s, "cancelled" if exc == "cancel" else "raised")


def _advance(s):
    pc = s["pc"]
    nxt = {"pub_started": "exec", "pub_tel": "exec", "pub_cost": "pub_result",
           "pub_result": "flush_exec"}
    if pc in nxt:
        return {**s, "pc": nxt[pc]}
    if pc == "flush_exec":
        # leave `async with deadline`; _terminate("succeeded") at lifecycle.py:226
        return {**s, "pc": "term_pub", "status": "succeeded", "deadline": "off",
                "in_try": FIX != 1}
    if pc == "term_pub":
        return {**s, "pc": "term_flush", "sent": True}
    if pc == "term_flush":
        return _after_terminate(s)
    raise AssertionError(pc)


def _alloc(s):
    """seq.next() evaluated: (state with n advanced, seq for this frame)."""
    if s["pc"] == "term_pub" and FIX == 2 and s["term_seq"] is not None:
        return s, s["term_seq"]
    n = s["n"] + 1
    t = {**s, "n": n}
    if s["pc"] == "term_pub":
        t = {**t, "term_seq": n}
    return t, n


def _kind(s):
    return "T:" + s["status"] if s["pc"] == "term_pub" else PUB_PCS[s["pc"]]


def _faultable(s):
    return not (TERM_PATH_RELIABLE and s["pc"] in ("term_pub", "term_flush"))


def actions(s):
    out = []
    pc = s["pc"]
    if pc == "exit":
        return out
    can_fault = s["faults"] > 0 and _faultable(s)
    can_cancel = s["cancels"] > 0 and _faultable(s)
    in_deadline = pc in DEADLINE_PCS and s["deadline"] == "armed"
    used_f = {**s, "faults": s["faults"] - 1}
    used_c = {**s, "cancels": s["cancels"] - 1}

    if pc == "ensure":                                   # lifecycle.py:209, before the try
        out.append(("ensure:ok", {**s, "pc": "pub_started", "in_try": True, "started": True}))
        if can_fault:
            out.append(("ensure:raises", _exit(used_f, "raised")))
        if can_cancel:
            out.append(("ensure:cancelled", _exit(used_c, "cancelled")))
        return out

    if pc == "exec":                                     # lifecycle.py:168 `async for`
        if not s["hang"]:
            if s["tel"] < MAX_TEL:
                out.append(("exec:yield_telemetry", {**s, "pc": "pub_tel", "tel": s["tel"] + 1}))
            out.append(("exec:completed", {**s, "pc": "pub_cost"}))
            if can_fault:
                out.append(("exec:raises", _route(used_f, "exc")))
                out.append(("exec:ends_without_completed", _route(used_f, "exc")))  # :179
    elif pc in PUB_PCS or pc == "term_pub":              # publish(topic, Frame(**seq.next()))
        t, q = _alloc(s)
        kind = _kind(s)
        out.append((f"{pc}:ok", _advance(_write(t, q, kind))))
        if can_fault:
            tf = {**t, "faults": t["faults"] - 1}
            out.append((f"{pc}:raises_unwritten", _route(tf, "exc")))
            if LOST_RESPONSE:
                out.append((f"{pc}:raises_after_write_lost_response", _route(_write(tf, q, kind), "exc")))
        if can_cancel:
            tc = {**t, "cancels": t["cancels"] - 1}
            out.append((f"{pc}:cancelled_unwritten", _route(tc, "cancel")))
            if LOST_RESPONSE:
                out.append((f"{pc}:cancelled_after_write", _route(_write(tc, q, kind), "cancel")))
        if in_deadline:
            td = {**t, "deadline": "fired"}
            out.append((f"{pc}:deadline_fires", _route(td, "timeout")))
        return out
    elif pc in ("flush_exec", "term_flush"):             # lifecycle.py:190 / :123
        out.append((f"{pc}:ok", _advance(s)))
        if can_fault:
            out.append((f"{pc}:raises", _route(used_f, "exc")))
        if can_cancel:
            out.append((f"{pc}:cancelled", _route(used_c, "cancel")))

    if in_deadline:
        out.append((f"{pc}:deadline_fires", _route({**s, "deadline": "fired"}, "timeout")))
    if pc == "exec" and can_cancel:
        out.append(("exec:cancelled", _route(used_c, "cancel")))
    return out


# ---------------------------------------------------------------- properties

def _terms(s):
    return [k for _, k in s["frames"] if k.startswith("T:")]


def _seqs(s):
    return [q for q, _ in s["frames"]]


INVARIANTS = {
    "at_most_one_terminal": lambda s: len(_terms(s)) <= 1,
    "terminal_is_last": lambda s: all(not k.startswith("T:") for _, k in s["frames"][:-1]),
    # seq_gap_free REMOVED: triaged "wrong property" - no producer-side design meets it
    # under pre-write publish failures (see REPORT.md F3). Its fingerprint differs on purpose.
    "seq_gap_free_when_succeeded": lambda s: ("T:succeeded" not in _terms(s))
        or _seqs(s) == list(range(1, len(s["frames"]) + 1)),
    "succeeded_only_after_result": lambda s: ("T:succeeded" not in _terms(s))
        or any(k == "R" for _, k in s["frames"]),
}

LEADS_TO = {
    "started_run_gets_a_terminal_frame": (lambda s: s["started"],
                                          lambda s: len(_terms(s)) >= 1),
}

_OK = ["ensure:ok", "exec:yield_telemetry", "exec:completed",
       *[f"{p}:ok" for p in [*PUB_PCS, "flush_exec", "term_pub", "term_flush"]],
       *[f"{p}:deadline_fires" for p in DEADLINE_PCS]]
# The timer and every successful step are guaranteed to run when they stay enabled.
# No failure action is fair.
FAIR = _OK

FAILURE_ACTIONS = [
    "ensure:raises", "ensure:cancelled", "exec:raises", "exec:ends_without_completed",
    "exec:cancelled",
    *[f"{p}:{o}" for p in [*PUB_PCS, "term_pub"]
      for o in ("raises_unwritten", "raises_after_write_lost_response",
                "cancelled_unwritten", "cancelled_after_write")],
    *[f"{p}:{o}" for p in ("flush_exec", "term_flush") for o in ("raises", "cancelled")],
]

TERMINAL = lambda s: s["pc"] == "exit"

ASSUMPTIONS = {
    "LOST_RESPONSE": ("no publish both writes the frame and then raises or is cancelled "
                      "(true of JetStreamPublisher sequenced path and InMemoryEventStream)", 1),
    "TERM_PATH_RELIABLE": "publish/flush inside _terminate do not fail and the task is not "
                          "cancelled while it terminates (ack futures resolve; one stop only)",
    "DEADLINE_SET": "run() is given a deadline_s (both engine runners pass one)",
    "DEDUP_BY_SEQ": "the transport drops a second frame carrying an already-stored seq "
                    "(JetStream Nats-Msg-Id dedup window; NOT true of InMemoryEventStream)",
}

_SNIP = {
    "ensure": (209, "await stream.ensure_stream(topic)"),
    "pub_started": (166, "StartedEvent(**seq.next(root_tp)"),
    "exec": (168, "async for step in executor.execute"),
    "pub_tel": (177, "_wrap_telemetry(seq.next(tp, ts), payload)"),
    "pub_cost": (181, "CostUsageEvent(**seq.next(root_tp)"),
    "pub_result": (182, "ResultEvent(**seq.next(root_tp)"),
    "flush_exec": (190, "await stream.flush()"),
    "term_pub": (117, "TerminatedEvent(**seq.next(root_tp)"),
    "term_flush": (123, "await stream.flush()"),
}
_EXTRA = {"exec:ends_without_completed": (179, "_IncompleteExecution(")}


def _source():
    src = {}
    for lbl in [*_OK, *FAILURE_ACTIONS, *[f"{p}:deadline_fires" for p in ("term_pub",)]]:
        pc = lbl.split(":")[0]
        if lbl in _EXTRA:
            line, snip = _EXTRA[lbl]
        else:
            line, snip = _SNIP[pc]
        src[lbl] = (f"{LC}:{line}", snip)
    src.pop("term_pub:deadline_fires", None)
    return src


SOURCE = _source()
