# formal model — executor memo: atomic check-then-act (the code as written)
#
# Proves: two parents of a diamond both reach the shared child, but because the
# ``_memo`` check-and-store is one atomic action (no ``await`` between), the
# child resolves at most once. Invariant ``child_resolved_at_most_once`` holds
# across all 4 reachable states.
#
# Check:  python3 ~/Documents/skills/concepts/formal-modeling/bin/fm.py check executor_memo_fixed.py
#         (expect clean, 4 states)
#
# The code this mirrors: packages/url4/src/url4/dag/executor.py, Executor._run.

"""Executor._run memo — the REAL atomic check-then-act (no await between).

Two parents (A, B) of a diamond both reach the shared child C. The code's
INVARIANT (packages/url4/src/url4/dag/executor.py:154-174): the check-then-act
on ``_memo`` is a critical section because ``create_task`` does not yield, so
the shared child resolves EXACTLY ONCE.

Run:  fm check executor_memo_fixed.py     # expect clean
      fm check executor_memo_buggy.py     # expect a 5-step counterexample
"""

NAME = "Executor._run memo - atomic check-then-act (as written)"


def init():
    return {"memo": False, "reached": frozenset(), "evals": 0}


def actions(s):
    out = []
    for p in ("A", "B"):
        if p in s["reached"]:
            continue
        if s["memo"]:
            # entry already present: observe it, create NO task
            out.append((f"reach_{p}_hits_memo", {**s, "reached": s["reached"] | {p}}))
        else:
            # atomic: read missing AND store the task in one action
            out.append(
                (
                    f"reach_{p}_creates",
                    {**s, "memo": True, "reached": s["reached"] | {p}, "evals": s["evals"] + 1},
                )
            )
    return out


INVARIANTS = {
    "child_resolved_at_most_once": lambda s: s["evals"] <= 1,
}


def TERMINAL(s):
    return len(s["reached"]) == 2
