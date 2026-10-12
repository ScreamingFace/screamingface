"""Same target, same node: is the DATA route served in exactly the same cases?"""
from _dispatch_spec import ASSUME, VARS, direct_outcome, http_outcome  # noqa: F401

NAME = "HTTP dispatch vs direct dispatch: data route served"


def OLD(v):
    return http_outcome(v) == "data"


def NEW(v):
    return direct_outcome(v) == "data"
