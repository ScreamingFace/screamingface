"""Unbounded inductive-invariant proof with z3.  Run:  fm prove thisspec.py

fm check explores a FINITE state space. This proves the invariant for ALL
states, at every scope, by Park induction:

    Init ⟹ I          (initiation)
    I ∧ Next ⟹ I'     (consecution)

If consecution fails you get a CTI - a counterexample to induction. That does
NOT mean I is false. It means I is too weak. Strengthen it and re-run.

  fm prove thisspec.py --bmc 5   is it actually false, or only too weak?
  fm prove thisspec.py --k 2     2-induction, for facts that span two steps
  fm prove thisspec.py --synth   ask spacer for the strengthening
"""
from z3 import Int, And, Or, Not, Implies

NAME = "bank transfer"

CAP = 100


def state(k):
    return {"a": Int(f"a{k}"), "b": Int(f"b{k}")}


def init(s):
    return And(s["a"] == 60, s["b"] == 40)


# Naming the actions lets `fm prove` tell you WHICH one broke the invariant.
ACTIONS = {
    "a_to_b": lambda s, t: And(s["a"] >= 1, t["a"] == s["a"] - 1, t["b"] == s["b"] + 1),
    "b_to_a": lambda s, t: And(s["b"] >= 1, t["b"] == s["b"] - 1, t["a"] == s["a"] + 1),
}


def inv(s):
    # What we CARE about: no account exceeds the cap, and none goes negative.
    #
    #   s["a"] <= CAP  is TRUE of every reachable state, but it is NOT
    #   INDUCTIVE on its own: from the unreachable state a=100,b=1 one step
    #   reaches a=101. Conservation is the STRENGTHENING that closes it.
    #
    # Delete the `a + b == CAP` clause and re-run with --bmc 4 to see the CTI.
    return And(s["a"] >= 0, s["b"] >= 0,
               s["a"] <= CAP, s["b"] <= CAP,
               s["a"] + s["b"] == CAP)


# OPTIONAL termination argument. Define `variant(s)` and fm prove checks that
# it is >= 0 and strictly decreases on every step. No variant, no termination
# proof - this is the only termination argument that exists.
#
# This transfer system does NOT terminate (money moves back and forth), so the
# variant is commented out. Uncomment it to see the failure report.
#
# def variant(s):
#     return s["a"]
