"""The RDS code-pointer half of dispatch — one JSON document of sources runs one registered handler.

Split out of :mod:`url4.peer._dispatch`: the code-pointer branch (``rds_call``, ``call_rds``,
``_raw_query_tail``) lives here, and the dispatch half imports it, never the reverse. The
handler contract (:class:`~url4.peer._request.Request`) lives in :mod:`url4.peer._request`.

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a URI intent runs one registered handler with the group's sources as a
# structured JSON document, and an LLM call on the same node keeps its meaning.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from url4.core._annotations import read_query_tail
from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.peer._request import Request, _text
from url4.wire.rds import RdsValue, decode_q_payload, decode_rds_document
from url4.wire.subrequest import split_expression_query

if TYPE_CHECKING:  # the node type only — this module never constructs one
    from url4.peer.server import Url4Node


def rds_call(query_string: str) -> tuple[dict[str, str], str, dict[str, RdsValue]] | None:
    """The RDS call a query string carries, as ``(params, document text, inputs)``, else ``None``.

    A request is RDS when its ``q=`` payload has no ``!`` tail and decodes to a valid v1 document
    (contracts C2 step 3). Any other request is an LLM call, and the caller keeps today's path.
    The query-tail params are read from the raw text before ``q=``, so the author's bytes reach
    :func:`~url4.core._annotations.read_query_tail` unchanged.
    """
    raw_params, raw_q = split_expression_query(query_string)
    document = None if raw_q is None else decode_q_payload(raw_q)
    inputs = None if document is None else decode_rds_document(document)
    if document is None or inputs is None:
        return None
    return read_query_tail(_raw_query_tail(raw_params)), document, inputs


def _raw_query_tail(raw_params: list[tuple[str, str | None]]) -> str:
    """The query-tail text, rebuilt from the raw pairs ``split_expression_query`` returned.

    INVARIANT: each pair keeps the author's bytes (a flag is ``k``, a valued param is ``k=v``), so
    the join is the query-tail as written and ``read_query_tail`` reads it unchanged.
    """
    return "&".join(key if value is None else f"{key}={value}" for key, value in raw_params)


async def call_rds(
    node: Url4Node,
    path: str,
    params: Mapping[str, str],
    document: str,
    inputs: Mapping[str, RdsValue],
) -> str:
    """Call the code pointer at ``path`` once with an RDS document — the one RDS owner.

    Both :func:`dispatch` and :func:`~url4.peer.direct.dispatch_direct` call this, so the RDS rules
    exist in one place. INVARIANT: an RDS request runs only a registered endpoint. A path with no
    endpoint is ``intent_error``, never the eval path and never a data route.
    """
    if path not in node._endpoints:
        raise ResolutionError(
            f"node {node.name!r} has no code pointer at {path!r}",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        )
    request = Request(
        path=path, context=document, intent="", params=params, mode="rds", inputs=inputs
    )
    try:
        result = await _text(node._endpoints[path](request))
    except Url4Error:
        raise
    except Exception as exc:
        # WHY: a failure inside the code pointer is the author's input failing, so it is permanent
        # and keeps the chained cause. Only a url4 error keeps its own code (contracts C7). The
        # message names the exception type only: its text can carry the author's data (SF7).
        raise ResolutionError(
            f"code pointer {path!r} failed: {type(exc).__name__}",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        ) from exc
    if not isinstance(result, str):
        raise ResolutionError(
            f"code pointer {path!r} returned {type(result).__name__}, not text",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        )
    return result
