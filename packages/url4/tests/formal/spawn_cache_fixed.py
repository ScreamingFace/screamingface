# formal model — spawn compile cache: atomic get → compile → store (the code as written)
#
# Proves: two rows of a MapNode both spawn the SAME unique body text, but
# because ``compile_expression`` is synchronous (no ``await`` between the
# ``compiled.get`` and the store), the get → compile → store is one atomic
# action, so each unique text compiles exactly once and the second row always
# hits the cache. Invariant ``one_compile_per_unique_text`` holds across all
# reachable states.
#
# Check:  python3 ~/Documents/skills/concepts/formal-modeling/bin/fm.py check spawn_cache_fixed.py
#         (expect clean, 4 states)
#
# The code this mirrors: packages/url4/src/url4/dag/executor.py, the
# ``spawn_hook`` closure in ``_wire_spawn`` (the INVARIANT comment above the
# ``compile_expression`` call).

"""spawn_hook compile cache — the REAL atomic get → compile → store.

Two rows (A, B) of a map (or two consumers of one lazy fragment) both spawn
the same unique text T. The code's INVARIANT (executor.py, ``spawn_hook``):
the compile cache's check-and-store is a critical section because
``compile_expression`` never awaits, so T compiles EXACTLY ONCE. This is the
same class of invariant as the ``Executor._run`` memo (see
``executor_memo_fixed.py``) — proven here because the spawn cache claims it
by comment only, and the class deserves a machine check where it is cheap
(second review, F5).

Run:  fm check spawn_cache_fixed.py     # expect clean
      fm check spawn_cache_buggy.py     # expect a violation (compiles == 2)
"""

NAME = "spawn_hook compile cache - atomic get/compile/store (as written)"


def init():
    return {"cache": False, "spawned": frozenset(), "compiles": 0}


def actions(s):
    out = []
    for r in ("A", "B"):
        if r in s["spawned"]:
            continue
        if s["cache"]:
            # entry already present: hit the cache, compile NOTHING
            out.append((f"row_{r}_hits_cache", {**s, "spawned": s["spawned"] | {r}}))
        else:
            # atomic: read missing AND compile AND store in one action
            out.append(
                (
                    f"row_{r}_compiles_stores",
                    {
                        **s,
                        "cache": True,
                        "spawned": s["spawned"] | {r},
                        "compiles": s["compiles"] + 1,
                    },
                )
            )
    return out


INVARIANTS = {
    "one_compile_per_unique_text": lambda s: s["compiles"] <= 1,
}


def TERMINAL(s):
    return len(s["spawned"]) == 2
