"""Rebuildable small accounting projections beside immutable saved case indices."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import TYPE_CHECKING

from screamingface._results.store import atomic_json
from screamingface.accounting import _accounting_context, _AccountingContext

if TYPE_CHECKING:
    from screamingface.report import CandidateResult

_LOG = logging.getLogger(__name__)
_VERSION = 1


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _signature(candidate: CandidateResult) -> str:
    # INVARIANT: identity covers every non-case input used by the projection.
    path = candidate.cases._disk_path
    assert path is not None
    stat = path.stat()
    return _digest(
        [
            stat.st_size,
            stat.st_mtime_ns,
            candidate.kind,
            candidate.models,
            [asdict(op) for op in candidate.operations],
            [[m.operation_id, m.kind, m.models] for m in candidate.members],
            str(candidate.usage.cost_usd),
        ]
    )


def _decode(value: dict) -> _AccountingContext:
    operations, judges = value["operation_models"], value["judge_models"]
    for mapping in (operations, judges):
        if not isinstance(mapping, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()
        ):
            raise ValueError("invalid cached attribution")
    if not isinstance(value["consistent"], bool):
        raise ValueError("invalid cached consistency")
    remainder = value["unattributed_cost_usd"]
    if remainder is not None:
        remainder = Decimal(remainder)
        if not remainder.is_finite() or remainder < 0:
            raise ValueError("invalid cached remainder")
    return _AccountingContext(
        MappingProxyType(operations), MappingProxyType(judges), remainder, value["consistent"]
    )


def saved_accounting_context(candidate: CandidateResult) -> _AccountingContext:
    path = candidate.cases._disk_path
    if path is None:
        return _accounting_context(candidate)
    cache = path.with_suffix(".accounting.json")
    signature = _signature(candidate)
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if (
            saved["version"] == _VERSION
            and saved["signature"] == signature
            and saved["digest"] == _digest(saved["context"])
        ):
            return _decode(saved["context"])
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation):
        # WHY: a missing/stale/damaged optional cache must never make results unreadable.
        pass
    context = _accounting_context(candidate)
    value = {
        "operation_models": dict(context.operation_models),
        "judge_models": dict(context.judge_models),
        "unattributed_cost_usd": (
            str(context.unattributed_cost_usd)
            if context.unattributed_cost_usd is not None
            else None
        ),
        "consistent": context.consistent,
    }
    try:
        atomic_json(
            cache,
            {
                "version": _VERSION,
                "signature": signature,
                "digest": _digest(value),
                "context": value,
            },
        )
    except OSError:
        _LOG.warning("Could not cache report accounting; using derived values")
    return context
