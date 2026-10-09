"""Shared encoding of the two routers as functions of four facts about one target.

Mirrors the if-chains literally (no hand simplification):
  HTTP   peer/_dispatch.py:137-152 + dispatch_expression :164-182
  direct peer/direct.py:161-192
Facts:
  has_q     the query carries a depth-0 `q=` (extract_expression_params -> q is not None)
  endpoint  path in node._endpoints
  data      data_route(node, target, path) is not None
  eval      path == eval_path or path startswith eval_path + "/"
"""

VARS = ["has_q", "endpoint", "data", "eval"]


def ASSUME(v):
    # _check_routable (server.py:207-213): one registration per path, and the BARE
    # eval path is never registrable. An endpoint or data route UNDER it (/v1/x) is.
    return not (v["endpoint"] and v["data"])


def http_outcome(v):
    if v["has_q"]:
        if v["endpoint"]:
            return "endpoint"
        if v["eval"]:
            return "eval"
    if v["data"]:
        return "data"
    return "404:endpoint_not_found"


def direct_outcome(v):
    if v["endpoint"]:
        if not v["has_q"]:
            return "400:missing_intent"
        return "endpoint"
    if v["data"]:
        return "data"
    if v["eval"]:
        return "404:direct_eval_refused"
    return "404:endpoint_not_found"
