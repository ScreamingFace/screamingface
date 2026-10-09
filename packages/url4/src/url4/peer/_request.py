"""The intent-processor call every endpoint receives — :class:`Request`, and the awaitable helper.

Split out of :mod:`url4.peer._dispatch`. ``Request`` is the handler contract for every endpoint,
LLM calls included, so it is not specific to the code-pointer call: :mod:`url4.peer._dispatch`
and :mod:`url4.peer._code_pointer` both import it from here. This module is a leaf: it imports
the standard library and :mod:`url4.wire.rds` only, so the import direction is one-way.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from inspect import isawaitable
from typing import Literal

from url4.wire.rds import RdsValue


@dataclass(frozen=True)
class Request:
    """One decoded intent-processor call: ``GET <path>?[params&]q=(context)!intent``.

    ``context`` is opaque resolved data (see the module contract); ``params``
    are the decoded protocol params that preceded ``q=``.

    In RDS mode (``mode == "rds"``, a code-pointer call with no ``!`` tail): ``context`` is the
    input document's JSON text exactly as received, ``intent`` is ``""`` (the path is the code
    pointer), ``params`` are the query-tail params, and ``inputs`` is the document's ``inputs``.
    """

    path: str
    context: str
    intent: str
    params: Mapping[str, str]
    # WHY: the default keeps every 1.x handler working; only an RDS call sets the new fields.
    mode: Literal["llm", "rds"] = "llm"
    # INVARIANT: `inputs` is set if and only if `mode == "rds"` (contracts C1 `inputs`).
    inputs: Mapping[str, RdsValue] | None = None


async def _text(result: str | Awaitable[str]) -> str:
    return await result if isawaitable(result) else result
