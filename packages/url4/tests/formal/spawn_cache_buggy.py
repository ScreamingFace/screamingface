# formal model — spawn compile cache: an await inserted between get and store (the regression)
#
# Proves: if the cache get and the store become SEPARATE actions (i.e. an
# ``await`` / yield point is inserted between them — a log call, a metric,
# anything), both rows can miss the cache before either stores, so the same
# unique text compiles TWICE. Invariant ``one_compile_per_unique_text`` is
# violated (``compiles == 2``). A duplicate compile is wasted work only (same
# text → an equivalent graph), never a correctness bug — but this is the exact
# regression the INVARIANT comment in ``spawn_hook`` exists to forbid, twin of
# the ``Executor._run`` memo bug model.
#
# Check:  python3 ~/Documents/skills/concepts/formal-modeling/bin/fm.py check spawn_cache_buggy.py
#         (expect a violation + counterexample)
#
# The code this mirrors: packages/url4/src/url4/dag/executor.py, the
# ``spawn_hook`` closure in ``_wire_spawn``.

"""spawn_hook compile cache — WRONG: an await inserted between get and store.

Same shape as the fixed model, but the get and the compile+store are SEPARATE
actions (a yield point). Both rows can miss the cache before either stores,
so the unique text compiles twice. This is what the second review's F5 exists
to machine-check: the memo model proved this class of invariant for
``Executor._run``; the spawn cache claimed it by comment only.
"""

NAME = "spawn_hook compile cache - get and store split by an await (bug)"


def init():
    return {
        "cache": False,
        "checked": frozenset(),
        "saw": {},
        "spawned": frozenset(),
        "compiles": 0,
    }


def actions(s):
    out = []
    for r in ("A", "B"):
        # step 1: get the cache entry (a yield point in the buggy version)
        if r not in s["checked"]:
            out.append(
                (
                    f"get_{r}",
                    {**s, "checked": s["checked"] | {r}, "saw": {**s["saw"], r: s["cache"]}},
                )
            )
        # step 2: compile and store if the GET saw nothing
        if r in s["checked"] and r not in s["spawned"]:
            compiled = not s["saw"].get(r, False)
            out.append(
                (
                    f"compile_store_{r}",
                    {
                        **s,
                        "cache": True,
                        "spawned": s["spawned"] | {r},
                        "compiles": s["compiles"] + (1 if compiled else 0),
                    },
                )
            )
    return out


INVARIANTS = {
    "one_compile_per_unique_text": lambda s: s["compiles"] <= 1,
}


def TERMINAL(s):
    return len(s["spawned"]) == 2
