"""Best-effort, factual credit notice once per evaluation, before execution."""

from __future__ import annotations

import asyncio
import warnings
from datetime import UTC, datetime

import httpx

from screamingface._environment import SDK_PACKAGE_ROOT
from screamingface._evaluation.model import Candidate
from screamingface.credit import CreditAmount, CreditStatus, _decode, _path
from screamingface.errors import ScreamingFaceError
from screamingface.warnings import EvaluationWarning


def _fresh_zero(amount: CreditAmount, now: datetime) -> bool:
    return (
        amount.status == "available"
        and amount.amount_usd == 0
        and amount.as_of is not None
        and amount.as_of.tzinfo is not None
        and 0 <= (now - amount.as_of).total_seconds() <= 300
    )


def zero_notice(status: CreditStatus) -> str | None:
    if status.connection_token is None:
        return None
    now = datetime.now(UTC)
    labels = [
        label
        for label, amount in (
            ("account credit", status.account),
            ("key allowance", status.key),
        )
        if _fresh_zero(amount, now)
    ]
    if not labels:
        return None
    return (
        "OpenRouter reported zero "
        + " and zero ".join(labels)
        + " within the last five minutes. The run will still be attempted."
    )


def _needed(candidates: tuple[Candidate, ...]) -> bool:
    return any(
        candidate.replay_frozen_copy is None
        and any(model.startswith("openrouter/") for model in candidate.models)
        for candidate in candidates
    )


def _emit(response: httpx.Response) -> None:
    notice = zero_notice(_decode(response, "openrouter"))
    if notice is not None:
        try:
            warnings.warn(notice, EvaluationWarning, skip_file_prefixes=(SDK_PACKAGE_ROOT,))
        except EvaluationWarning:
            # INVARIANT: warnings-as-errors must not turn credit visibility into admission.
            pass


def check_sync(client: httpx.Client, candidates: tuple[Candidate, ...]) -> None:
    if not _needed(candidates):
        return
    try:
        # WHY: use the transport's existing identity, and respect the Gateway's cache/backoff.
        # No retry marker: a best-effort notice must not delay execution with retry backoff.
        response = client.get(_path("openrouter", refresh=False), timeout=1)
        _emit(response)
    except (httpx.HTTPError, ScreamingFaceError):
        pass


async def check_async(client: httpx.AsyncClient, candidates: tuple[Candidate, ...]) -> None:
    if not _needed(candidates):
        return
    try:
        async with asyncio.timeout(1):
            response = await client.get(_path("openrouter", refresh=False), timeout=1)
        _emit(response)
    except (httpx.HTTPError, ScreamingFaceError, TimeoutError):
        pass
