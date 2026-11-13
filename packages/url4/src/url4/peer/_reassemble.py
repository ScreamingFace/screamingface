"""Rebuild the eval-path expression from an HTTP ingress query.

Split from :mod:`url4.peer._dispatch` (module-size cap) by reason to change: this module
changes when the ingress param rules change (which params are transport, which re-attach
as the ``;``-chain); ``_dispatch`` changes when the dispatch order changes.
``url4.peer._dispatch`` re-exports every name here, so no import path moves.
"""

from __future__ import annotations

from collections.abc import Mapping

from url4.wire.subrequest import TRANSPORT_ONLY_PARAMS, decode_expression_http

# Transport-level query params a node consumes itself rather than re-attaching
# to the expression (spec §11.6.3). The ingress set is broader than the spec's
# transport-only rule: it also drops params this node consumes itself
# (delivery/cb/meta/v) and `processor`. The eval path consumes `processor` for
# its §27.3 delegation; endpoint calls do not reassemble an expression, so the
# value reaches the handler in request.params.
# INVARIANT: _TRANSPORT_PARAMS is DERIVED from TRANSPORT_ONLY_PARAMS, so the two
# can never disagree about resume/rid.
_TRANSPORT_PARAMS = TRANSPORT_ONLY_PARAMS | frozenset({"delivery", "cb", "meta", "v", "processor"})


def reassemble(q: str, params: Mapping[str, str]) -> str:
    """Rebuild the eval-path expression, re-attaching non-transport params.

    The dual-convention decode lives with the wire codec
    (:func:`url4.wire.subrequest.decode_expression_http` — one owner, spec §3.4).
    ``broadcast`` and friends keep their §9 semantics by riding the trailing
    ``;`` chain the envelope decode reads (a flag param decodes to value "").
    """
    text = decode_expression_http(q)
    for key, value in params.items():
        if key not in _TRANSPORT_PARAMS:
            text += f";{key}" if value == "" else f";{key}={value}"
    return text


__all__ = ["_TRANSPORT_PARAMS", "reassemble"]
