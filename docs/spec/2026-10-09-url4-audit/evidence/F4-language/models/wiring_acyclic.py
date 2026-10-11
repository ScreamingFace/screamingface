"""Explicit-state model of dag/_wiring.py:_build_slots (two-phase slot wiring).

The bad thing: the compiler wires a dependency cycle (or a dangling edge to a
node that does not exist yet) between the sources of one group, so the
executor deadlocks / raises CycleError on a compiler-emitted graph.

Abstraction: N=3 source slots; each slot has a name in {None,'a','b'} (duplicates
allowed — later binding shadows) and a reference set ⊆ {'a','b'}. Building a
slot = calling slot.make(edges); the node gets the next construction rank.
Edges point from the slot being built to nodes found in by_name.

Run:  fm check wiring_acyclic.py ; fm mutate wiring_acyclic.py
"""

from itertools import product

NAME = "_build_slots two-phase wiring (named first, then unnamed)"
N = 3
NAMES = (None, "a", "b")
REFSETS = (frozenset(), frozenset({"a"}), frozenset({"b"}), frozenset({"a", "b"}))

# Construction is deterministic, synchronous Python: there is no environment
# failure (crash/retry/reorder) between two slot.make() calls. The runtime
# failure modes (spawn, guards, cancellation) are outside this model.
FAILURE_ACTIONS = []


def init():
    out = []
    for names in product(NAMES, repeat=N):
        for refs in product(REFSETS, repeat=N):
            out.append({
                "names": names, "refs": refs, "phase": 1, "i": 0,
                "by_name": (), "rank": (-1,) * N, "edges": frozenset(), "next": 0,
            })
    return out


def _declared(s, r):
    """Index of the first slot that declares name r (any phase), or None."""
    for j, n in enumerate(s["names"]):
        if n == r:
            return j
    return None


def _build(s, i):
    by_name = dict(s["by_name"])
    edges = set(s["edges"])
    for r in s["refs"][i]:
        tgt = by_name.get(r, _declared(s, r))
        if tgt is not None and r in by_name:  # VISIBILITY GUARD — _ref_edges: `elif ref in by_name`
            edges.add((i, tgt))
    rank = list(s["rank"])
    rank[i] = s["next"]
    if s["names"][i] is not None:
        by_name[s["names"][i]] = i  # wiring.py:105 — later binding shadows
    return {**s, "by_name": tuple(sorted(by_name.items())), "rank": tuple(rank),
            "edges": frozenset(edges), "next": s["next"] + 1}


def actions(s):
    out = []
    i, phase = s["i"], s["phase"]
    if phase == 3:
        return out
    if i == N:
        out.append(("next_phase", {**s, "phase": phase + 1, "i": 0}))
        return out
    named = s["names"][i] is not None
    if phase == 1 and named:            # PHASE GUARD 1: named slots first, in order
        out.append(("build_named", {**_build(s, i), "i": i + 1}))
    elif phase == 2 and not named:      # PHASE GUARD 2: then every unnamed slot
        out.append(("build_unnamed", {**_build(s, i), "i": i + 1}))
    else:
        out.append(("skip", {**s, "i": i + 1}))
    return out


def _edges_ok(s):
    return all(s["rank"][v] >= 0 and s["rank"][v] < s["rank"][u] for (u, v) in s["edges"])


def _complete(s):
    """Visibility promised by the INVARIANT comments at _wiring.py:101/106."""
    if s["phase"] != 3:
        return True
    for i, n in enumerate(s["names"]):
        for r in s["refs"][i]:
            if n is not None:
                # named: sees the LATEST earlier named slot called r
                earlier = [j for j in range(i) if s["names"][j] == r]
                want = earlier[-1] if earlier else None
            else:
                every = [j for j in range(N) if s["names"][j] == r]
                want = every[-1] if every else None
            got = [v for (u, v) in s["edges"] if u == i and s["names"][v] == r]
            if (want is None) != (not got) or (want is not None and got != [want]):
                return False
    return True


INVARIANTS = {
    "edges_point_to_strictly_earlier_built_nodes": _edges_ok,
    "visibility_matches_documented_rule": _complete,
}

# (removed after `fm mutate` run 1: a STEP invariant "rank_is_construction_order"
#  was a tautology of the update itself — no mutant could break it.)

TERMINAL = lambda s: s["phase"] == 3

SOURCE = {
    "build_named": ("/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/_wiring.py:101", "named slots see only EARLIER named slots"),
    "build_unnamed": ("/Users/junior/workspace/screamingface/packages/url4/src/url4/dag/_wiring.py:106", "unnamed sources see ALL named slots"),
}
