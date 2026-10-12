"""Policy: identity holdings are served ONLY through an @identity reference that the
identity's own handler admitted.

OLD = the policy (what must hold).  NEW = what the code serves (per adapter).
NEW weaker than OLD = a path that serves identity holdings around the gate.

Facts about one holdings resolution:
  static        the io world is StaticIOLayer (test double) rather than Url4Node
  identity_ref  the reference is @name[/coll]   (else it is @[/coll], a SELF ref)
  key_collides  SELF ref whose collection text equals "<name>/<coll>" (or "<name>")
  handler_ok    the identity handler returns (does not raise a 403 code)
Encodings (code read, then confirmed by probe_identity.py):
  Url4Node      _dispatch.fetch_holdings :104-117 - identity -> node._identities[name](coll);
                SELF -> resolve_shelf(node._self_holdings, coll): separate dicts.
  StaticIOLayer static.py:95-97,105-113 - ONE dict keyed by _holdings_key, which maps
                (None, "emily/secret") and ("emily", "secret") to the same key.
"""
NAME = "identity gate: served-identity-data implies admitted-by-identity-handler"
VARS = ["static", "identity_ref", "key_collides", "handler_ok"]


def ASSUME(v):
    # a collision is a property of a SELF ref; the static layer has no handler (gate = presence)
    return not (v["identity_ref"] and v["key_collides"]) and not (v["static"] and not v["handler_ok"])


def OLD(v):  # the policy
    return v["identity_ref"] and v["handler_ok"]


def NEW(v):  # what the code hands out as some identity's holdings
    if v["static"]:
        return v["identity_ref"] or v["key_collides"]
    return v["identity_ref"] and v["handler_ok"]
