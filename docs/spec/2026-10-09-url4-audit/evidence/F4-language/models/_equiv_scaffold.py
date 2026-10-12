"""Truth table + predicate comparison.  Run:  fm equiv thisfile.py

Two uses:
  1. ONE predicate P  -> print its truth table, find unreachable rows and
     variables that cannot change the answer.
  2. TWO predicates   -> is the rewrite equivalent, stricter, weaker, or
     neither? Never invert a guard by hand; check it.

Boolean mode is exhaustive over 2^len(VARS) rows, so the answer is exact.
For non-boolean domains define state() instead - see `fm scaffold policy`.
"""
NAME = "discount eligibility, before and after the rewrite"

VARS = ["is_member", "has_coupon", "is_first_order", "is_blocked"]


# ASSUME rules out combinations the system cannot produce. A row excluded
# here is a case your code handles that can never happen.
def ASSUME(v):
    return not (v["is_blocked"] and v["is_member"])


# The rule as it is written today.
def OLD(v):
    return (v["is_member"] or v["has_coupon"]) and not v["is_blocked"]


# The rule after the "simplification". De Morgan is where these go wrong.
def NEW(v):
    return not (not v["is_member"] and not v["has_coupon"]) and not v["is_blocked"]
