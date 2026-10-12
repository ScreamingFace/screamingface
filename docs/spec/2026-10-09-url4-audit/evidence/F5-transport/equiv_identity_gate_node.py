"""Same policy, Url4Node only (static=False fixed): the node's own paths."""
from equiv_identity_gate import NAME as _N, OLD, NEW as _NEW  # noqa: F401
NAME = _N + " (Url4Node only)"
VARS = ["identity_ref", "key_collides", "handler_ok"]
def ASSUME(v):
    return not (v["identity_ref"] and v["key_collides"])
def NEW(v):
    return _NEW({**v, "static": False})
