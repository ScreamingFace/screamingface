"""Policy comparison over non-boolean domains, with z3.
Run:  fm equiv thisfile.py

The question this answers: "is the new access rule strictly less permissive
than the old one?" That is two implications, and a witness for each direction
you do not get. Guessing it from the diff is how privilege escalations ship.

This is the class of question AWS's Zelkova answers for IAM policies.
"""
from z3 import Int, Bool, String, And, Or, Not, Implies

NAME = "document access policy, v1 vs v2"


def state(k):
    return {
        "role_level": Int(f"role_level{k}"),   # 0 viewer, 1 editor, 2 admin
        "is_owner": Bool(f"is_owner{k}"),
        "doc_sensitivity": Int(f"doc_sensitivity{k}"),   # 0..2
        "mfa": Bool(f"mfa{k}"),
    }


def ASSUME(s):
    return And(s["role_level"] >= 0, s["role_level"] <= 2,
               s["doc_sensitivity"] >= 0, s["doc_sensitivity"] <= 2)


def OLD(s):
    return Or(s["is_owner"], s["role_level"] >= 2,
              And(s["role_level"] >= 1, s["doc_sensitivity"] <= 1))


def NEW(s):
    # "we also require MFA for sensitive documents" - but did the rewrite
    # change anything else? Run it and read the witness.
    return Or(s["is_owner"],
              And(s["role_level"] >= 2, Or(s["mfa"], s["doc_sensitivity"] <= 1)),
              And(s["role_level"] >= 1, s["doc_sensitivity"] <= 1))
