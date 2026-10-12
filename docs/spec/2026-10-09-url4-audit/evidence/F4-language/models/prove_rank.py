"""Unbounded proof of the rank argument behind _wiring._build_slots acyclicity.

Abstraction (sound for _build_slots, _build_ctx_nodes, _inline_collection):
  next   — the construction rank the next built node receives (= nodes built so far)
  maxb   — the maximum rank stored in by_name/by_pos (-1 when empty)
  dep    — the rank of an arbitrary dependency chosen for the node being built
           (any value in by_name, i.e. -1 < dep <= maxb, or "none" = -1)
  last   — rank of the last built node; ldep = max dep rank it was wired to (-1: none)
  n      — number of slots (symbolic, unbounded)
Every edge is created by slot.make(edges) with edges ⊆ by_name/by_pos values, and
DagNode deps are never reassigned after construction (grep: no `.deps[...] =` in src/).
Run: fm prove prove_rank.py --bmc 6
"""
from z3 import Int, And, Or, Implies

NAME = "slot wiring: every edge points to a strictly lower construction rank"


def state(k):
    return {v: Int(f"{v}{k}") for v in ("next", "maxb", "last", "ldep", "n")}


def init(s):
    return And(s["next"] == 0, s["maxb"] == -1, s["last"] == -1, s["ldep"] == -1, s["n"] >= 0)


def _build(s, t, named):
    # the new node may be wired to ANY rank currently in by_name (or to nothing)
    return And(
        s["next"] < s["n"],
        t["last"] == s["next"],
        t["ldep"] >= -1, t["ldep"] <= s["maxb"],          # _ref_edges reads by_name only
        t["maxb"] == (s["next"] if named else s["maxb"]),  # named: by_name[name] = node
        t["next"] == s["next"] + 1,
        t["n"] == s["n"],
    )


ACTIONS = {
    "build_named": lambda s, t: _build(s, t, True),
    "build_unnamed": lambda s, t: _build(s, t, False),
}


def inv(s):
    return And(
        s["maxb"] < s["next"],                      # by_name holds only already-built nodes
        Or(s["last"] == -1, s["ldep"] < s["last"]),  # THE property (model-bug fix run 2: vacuous at init)
        Or(s["last"] == -1, s["last"] < s["next"]),
        s["ldep"] >= -1, s["next"] >= 0, s["next"] <= s["n"],
    )


def variant(s):
    return s["n"] - s["next"]
