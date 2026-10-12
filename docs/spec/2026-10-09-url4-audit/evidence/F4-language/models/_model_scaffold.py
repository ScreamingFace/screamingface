"""Explicit-state model.  Run:  fm check thismodel.py

RECIPE
  1. state    - the smallest tuple of variables the bug you fear can live in
  2. init     - the initial state(s)
  3. actions  - EVERY transition, as (label, new_state), guards included
  4. failures - crash, restart, message loss, duplicate, reorder, partition.
                If you omit these you are modelling a system you do not have.
  5. invariants - what must NEVER be true
"""
NAME = "order lifecycle"

STATES = ["draft", "placed", "paid", "shipped", "cancelled"]

# The transition relation, written as a SET. Anything not here is illegal
# and must be REJECTED, not silently ignored. Missing pairs are most state bugs.
TRANSITIONS = {
    ("draft",  "place"):  "placed",
    ("placed", "pay"):    "paid",
    ("paid",   "ship"):   "shipped",
    ("placed", "cancel"): "cancelled",
    ("paid",   "cancel"): "cancelled",
}


def init():
    return [{"status": "draft", "paid": False, "shipped": False}]


def actions(s):
    out = []
    for (src, ev), dst in TRANSITIONS.items():
        if s["status"] != src:
            continue
        t = dict(s)
        t["status"] = dst
        if ev == "pay":
            t["paid"] = True
        if ev == "ship":
            t["shipped"] = True
        out.append((ev, t))
    # --- failure actions: model the world, not the happy path ---
    if s["status"] == "paid":
        out.append(("refund_timeout", {**s, "status": "cancelled"}))
    return out


INVARIANTS = {
    "shipped_implies_paid": lambda s: (not s["shipped"]) or s["paid"],
    "no_cancel_after_ship": lambda s: not (s["status"] == "cancelled" and s["shipped"]),
}

# Two-state predicates: checked on every transition, not on every state.
# This is TLA+'s [][P]_vars. It says things no single-state invariant can.
STEP_INVARIANTS = {
    "paid_is_permanent": lambda s, t: (not s["paid"]) or t["paid"],
}

# AG EF - from every reachable state, a terminal outcome is still reachable.
EVENTUALLY = {
    "settles": lambda s: s["status"] in ("shipped", "cancelled"),
}

# Coverage: fm check reports anything declared here that never happened.
# A transition that never fires is dead code or a wrong guard.
LABELS = ["place", "pay", "ship", "cancel", "refund_timeout"]
COVERAGE = {"status": STATES}

TERMINAL = lambda s: s["status"] in ("shipped", "cancelled")

# A GUARANTEE, not a possibility: once placed, the order WILL settle - given
# that the environment eventually runs `pay` and `ship` when they are enabled.
# Never list a failure action in FAIR: fairness forces an action to happen.
LEADS_TO = {
    "placed_settles": (lambda s: s["status"] == "placed",
                       lambda s: s["status"] in ("shipped", "cancelled")),
}
FAIR = ["pay", "ship"]

# Tie each action to the code it models. `fm check` reports a missing file, a
# line past the end, or - with a snippet - DRIFT when the code moved on.
# SOURCE = {
#     "pay":  ("src/orders.py:88", "def mark_paid"),
#     "ship": "src/orders.py:120",
# }

# The facts the verdict rests on, as constants. `fm check --challenge` makes
# each one false in turn and reports which properties depend on it.
# ASSUMPTIONS = {"REFUND_IS_IDEMPOTENT": "the gateway dedups refunds by order id"}
