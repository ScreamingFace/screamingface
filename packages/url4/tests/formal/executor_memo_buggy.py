# formal model — executor memo: an await inserted between check and store (the regression)
#
# Proves: if the ``_memo`` check and the store become SEPARATE actions (i.e. an
# ``await`` / yield point is inserted between them), both diamond parents can
# miss the memo before either stores, so the shared child gets two eval tasks.
# Invariant ``child_resolved_at_most_once`` is violated with a 5-step
# counterexample (``evals=2``). This is the silent regression the INVARIANT
# comment in Executor._run exists to forbid — and the reason the debug-mode
# resolve-once guard was added.
#
# Check:  python3 ~/Documents/skills/concepts/formal-modeling/bin/fm.py check executor_memo_buggy.py
#         (expect a violation + 5-step counterexample)
#
# The code this mirrors: packages/url4/src/url4/dag/executor.py, Executor._run.

"""Executor._run memo — WRONG: an await inserted between check and store.

Same shape as the fixed model, but the check and the store are SEPARATE
actions (a yield point). Both parents can miss the memo before either stores,
so the shared child gets two eval tasks. This is the exact regression the
INVARIANT comment at executor.py:154-174 exists to forbid.
"""

NAME = "Executor._run memo - check and store split by an await (bug)"


def init():
    return {"memo": False, "checked": frozenset(), "reached": frozenset(), "saw": {}, "evals": 0}


def actions(s):
    out = []
    for p in ("A", "B"):
        # step 1: check the memo (a yield point in the buggy version)
        if p not in s["checked"]:
            out.append(
                (
                    f"check_{p}",
                    {**s, "checked": s["checked"] | {p}, "saw": {**s["saw"], p: s["memo"]}},
                )
            )
        # step 2: store a freshly created task if the CHECK saw nothing
        if p in s["checked"] and p not in s["reached"]:
            created = not s["saw"].get(p, False)
            out.append(
                (
                    f"store_{p}",
                    {
                        **s,
                        "memo": True,
                        "reached": s["reached"] | {p},
                        "evals": s["evals"] + (1 if created else 0),
                    },
                )
            )
    return out


INVARIANTS = {
    "child_resolved_at_most_once": lambda s: s["evals"] <= 1,
}


def TERMINAL(s):
    return len(s["reached"]) == 2
