"""Same target: does HTTP answer 404 in exactly the cases direct answers 404?"""
from _dispatch_spec import ASSUME, VARS, direct_outcome, http_outcome  # noqa: F401

NAME = "HTTP dispatch vs direct dispatch: 404"


def OLD(v):
    return http_outcome(v).startswith("404")


def NEW(v):
    return direct_outcome(v).startswith("404")
