"""Does a direct call ever run a handler the HTTP node would not? (NEW weaker = escalation)
OLD = HTTP node runs SOME handler (endpoint, eval, or data); NEW = direct runs one."""
from _dispatch_spec import ASSUME, VARS, direct_outcome, http_outcome  # noqa: F401

NAME = "HTTP dispatch vs direct dispatch: a handler runs"


def OLD(v):
    return http_outcome(v) in ("endpoint", "eval", "data")


def NEW(v):
    return direct_outcome(v) in ("endpoint", "data")
