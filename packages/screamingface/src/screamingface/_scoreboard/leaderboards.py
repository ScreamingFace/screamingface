"""Typed Leaderboard adapters at the Scoreboard HTTP seam."""

from __future__ import annotations

import asyncio
import enum
import logging
import math
import platform
import random
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version

# WHY the aliased import rather than `import json`: `json` is also the request-body keyword
# every call builder passes, so the module name stays out of this namespace.
from json import dumps as _json_dumps
from typing import Final
from urllib.parse import quote
from uuid import UUID

import httpx

from screamingface._core.attempts import _Attempt
from screamingface._core.ports import (
    AsyncCacheVersionFreezer,
    SyncCacheVersionFreezer,
    _FreezeOutcome,
    _FreezeUnavailable,
    _FrozenCacheVersion,
    _ReplayBinding,
)
from screamingface._notices import ClientNotice
from screamingface._scoreboard.calls import (
    _invalid,
    _Resend,
    _ScoreboardCall,
    call_async,
    call_sync,
)
from screamingface._scoreboard.replay_pin import _ReplayPin
from screamingface._scoreboard.submission_notice import (
    display_submission_notice,
    prepare_submission_notice,
)
from screamingface._ui.leaderboard_view import LeaderboardCatalog
from screamingface.errors import LeaderboardError, ReplayUnavailable
from screamingface.leaderboard import (
    CacheVersionPublication,
    Leaderboard,
    LeaderboardBaseline,
    LeaderboardCacheVersion,
    LeaderboardEntry,
    LeaderboardInfo,
    LeaderboardNotice,
    LeaderboardRankingNotice,
    LeaderboardReportedResult,
    LeaderboardScore,
)
from screamingface.report import CandidateResult, ReplayProvenance
from screamingface.url4 import Url4

_logger = logging.getLogger(__name__)

_BENCHMARKS_PATH = "/v1/benchmarks"
_LEADERBOARD_PATH = "/v1/leaderboard"
_SCORES_PATH = "/v1/scores"
_RESULTS_PATH = "/v1/results"
_AUTHOR_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
_MAX_AUTHORS = 10
_MAX_AUTHOR_LENGTH = 255
# INVARIANT (OME-1247): these mirror the Scoreboard's `validate_bounded_models` and `ModelRoute`
# exactly — 32 routes, 255 characters each, 4096 bytes serialized. The board already refuses a
# payload past any of them, so without a matching guard here the mismatch surfaces only in the
# field, after a release, as a 422 on the WHOLE submission: `models` fails validation and takes
# `ScoreSubmission` with it. The route GRAMMAR was deliberately mirrored across the two ends for
# this reason; the bounds were not, which is the gap this closes.
_MAX_MODELS = 32
_MAX_MODEL_LENGTH = 255
_MAX_MODELS_BYTES = 4096
# FEATURE: OME-1307 (E14) editable submission metadata. Contract C5 fixes a 15 s SDK timeout for
# the PATCH and one re-send after a connection error.
_METADATA_EDIT_OPERATION = "edit the submission metadata on"
_METADATA_EDIT_TIMEOUT_S = 15.0
_METADATA_EDIT_TRANSPORT_RETRIES = 1
_SUBMIT_OPERATION = "submit a score to"
# FEATURE: OME-1307 (E14) contract C4: a 30 s timeout and two re-sends with backoff after a
# connection error or a 5xx. The idempotency key (`run_id`) makes a re-send safe.
_SUBMIT_TIMEOUT_S = 30.0
_SUBMIT_RESENDS = 2
_SUBMIT_BACKOFF_BASE_S = 0.5
# WHY bounded: a long notebook session submits many runs, and the receipt cache must not grow
# without end. The freeze is idempotent (CV-D3), so a cache that dropped an entry only costs one
# more freeze call.
_RECEIPT_CACHE_SIZE = 32
_CACHE_VERSION_WARNING = "cache_version_unavailable"
_SUBMIT_CODES: Final[Mapping[int, str]] = {
    400: "invalid_score_submission",
    401: "scoreboard_authentication_required",
    403: "score_submission_forbidden",
    409: "score_submission_conflict",
    422: "invalid_score_submission",
}
# WHY a status fallback beside the coded body (D7 X-8): a proxy or a board before E14a can send a
# status with no `{"detail": {"code": ...}}` body, and the SDK must still give a typed code.
_METADATA_EDIT_CODES: Final[Mapping[int, str]] = {
    401: "identity_not_verified",
    403: "not_submission_owner",
    404: "unknown_score",
    412: "metadata_revision_conflict",
    422: "invalid_submission_metadata",
    428: "precondition_required",
}
# FEATURE: OME-1307 (E14) contract C6: a 10 s timeout, no re-send, no fallback. A grant has no side
# effect, so the request is replay-safe, but a retry would only delay the caller's error (RP-19).
_REPLAY_GRANTS_PATH = "/v1/replay-grants"
_REPLAY_GRANT_OPERATION = "request a replay grant from"
_REPLAY_GRANT_TIMEOUT_S = 10.0
# INVARIANT: mirrors the engine and gateway limit of C1 (2,048 UTF-8 bytes), so the SDK refuses a
# grant that the engine would refuse, before the run and its spend.
_MAX_GRANT_BYTES = 2048
_REPLAY_GRANT_CODES: Final[Mapping[int, str]] = {
    404: "replay_pin_not_found",
    410: "cache_version_withdrawn",
    422: "invalid_replay_pin",
}
# FEATURE: OME-1307 (E14) contract C10: the owner publishes the cache version of a result. The
# request is idempotent (PB-D5), so it is replay-safe.
_PUBLISH_OPERATION = "publish the cache version on"
_PUBLISH_CODES: Final[Mapping[int, str]] = {
    403: "not_result_owner",
    409: "not_publishable",
    503: "publish_unavailable",
}


class _Unset(enum.Enum):
    UNSET = "UNSET"


UNSET: Final = _Unset.UNSET


class Leaderboards:
    """Synchronous public Leaderboards bound to one Client."""

    def __init__(
        self,
        request: Callable[..., httpx.Response],
        scoreboard_url: str,
        freezer: SyncCacheVersionFreezer | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._request = request
        self._scoreboard_url = scoreboard_url
        self._freezer = freezer
        self._sleep = sleep
        self._receipts = _ReceiptCache()

    def list(self) -> Sequence[LeaderboardInfo]:
        return self._call(_list_call())

    def get(self, benchmark_id: str, *, top: int = 50) -> Leaderboard:
        return self._call(_leaderboard_call(benchmark_id, top))

    def submit(
        self,
        candidate_result: CandidateResult,
        *,
        authors: Sequence[str] | None = None,
        paper_url: str | None = None,
        revision_of: str | None = None,
    ) -> LeaderboardScore:
        draft = _SubmitDraft.of(
            candidate_result, authors=authors, paper_url=paper_url, revision_of=revision_of
        )
        # WHY here: after the input checks and the partial-submission advisory, so `-W error`
        # still aborts before any engine call, as before.
        score = self._call(draft.call(self._cache_version(candidate_result)))
        display_submission_notice(draft.notice)
        return score

    def _cache_version(self, candidate_result: CandidateResult) -> _FreezeOutcome:
        pending = self._receipts.pending(candidate_result, self._freezer)
        if isinstance(pending, _PendingFreeze):
            return self._receipts.keep(pending.key, pending.freezer.freeze(pending.trace_id))
        return pending

    def get_score(self, score_id: UUID | str) -> LeaderboardScore:
        return self._call(_score_call(score_id))

    def update_submission(
        self,
        score_id: UUID | str,
        *,
        expected_revision: int,
        authors: Sequence[str] | None | _Unset = UNSET,
        paper_url: str | None | _Unset = UNSET,
    ) -> LeaderboardScore:
        return self._call(_metadata_edit_call(score_id, expected_revision, authors, paper_url))

    def _replay_grant(self, pin: _ReplayPin, benchmark_id: str) -> _ReplayBinding:
        """C6: the grant for one pinned run. Unreachable, slow or 5xx is `ReplayUnavailable`."""
        return self._call(_replay_grant_call(pin, benchmark_id))

    def publish_cache_version(self, result_id: UUID | str) -> CacheVersionPublication:
        return self._call(_publish_call(result_id))

    def _call[T](self, call: _ScoreboardCall[T]) -> T:
        return call_sync(self._request, self._scoreboard_url, call, self._sleep)


class AsyncLeaderboards:
    """Asynchronous public Leaderboards bound to one AsyncClient."""

    def __init__(
        self,
        request: Callable[..., Awaitable[httpx.Response]],
        scoreboard_url: str,
        freezer: AsyncCacheVersionFreezer | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._request = request
        self._scoreboard_url = scoreboard_url
        self._freezer = freezer
        self._sleep = sleep
        self._receipts = _ReceiptCache()

    async def list(self) -> Sequence[LeaderboardInfo]:
        return await self._call(_list_call())

    async def get(self, benchmark_id: str, *, top: int = 50) -> Leaderboard:
        return await self._call(_leaderboard_call(benchmark_id, top))

    async def submit(
        self,
        candidate_result: CandidateResult,
        *,
        authors: Sequence[str] | None = None,
        paper_url: str | None = None,
        revision_of: str | None = None,
    ) -> LeaderboardScore:
        draft = _SubmitDraft.of(
            candidate_result, authors=authors, paper_url=paper_url, revision_of=revision_of
        )
        # WHY here: after the input checks and the partial-submission advisory, so `-W error`
        # still aborts before any engine call, as before.
        score = await self._call(draft.call(await self._cache_version(candidate_result)))
        display_submission_notice(draft.notice)
        return score

    async def _cache_version(self, candidate_result: CandidateResult) -> _FreezeOutcome:
        pending = self._receipts.pending(candidate_result, self._freezer)
        if isinstance(pending, _PendingFreeze):
            return self._receipts.keep(pending.key, await pending.freezer.freeze(pending.trace_id))
        return pending

    async def get_score(self, score_id: UUID | str) -> LeaderboardScore:
        return await self._call(_score_call(score_id))

    async def update_submission(
        self,
        score_id: UUID | str,
        *,
        expected_revision: int,
        authors: Sequence[str] | None | _Unset = UNSET,
        paper_url: str | None | _Unset = UNSET,
    ) -> LeaderboardScore:
        return await self._call(
            _metadata_edit_call(score_id, expected_revision, authors, paper_url)
        )

    async def _replay_grant(self, pin: _ReplayPin, benchmark_id: str) -> _ReplayBinding:
        return await self._call(_replay_grant_call(pin, benchmark_id))

    async def publish_cache_version(self, result_id: UUID | str) -> CacheVersionPublication:
        return await self._call(_publish_call(result_id))

    async def _call[T](self, call: _ScoreboardCall[T]) -> T:
        return await call_async(self._request, self._scoreboard_url, call, self._sleep)


def _list_call() -> _ScoreboardCall[LeaderboardCatalog]:
    return _ScoreboardCall(
        "GET",
        _BENCHMARKS_PATH,
        replay_safe=True,
        decode=lambda payload, _url: _decode_list(payload),
    )


def _leaderboard_call(benchmark_id: str, top: int) -> _ScoreboardCall[Leaderboard]:
    selected = _benchmark_id(benchmark_id)
    limit = _top(top)
    return _ScoreboardCall(
        "GET",
        f"{_LEADERBOARD_PATH}/{quote(selected, safe='')}",
        replay_safe=True,
        decode=lambda payload, _url: _decode_leaderboard(payload),
        params={"top": limit},
        missing=("unknown_leaderboard", f"Leaderboard {selected!r} is not registered"),
    )


def _score_call(score_id: UUID | str) -> _ScoreboardCall[LeaderboardScore]:
    selected = _score_id(score_id)
    return _ScoreboardCall(
        "GET",
        f"{_SCORES_PATH}/{selected}",
        replay_safe=True,
        decode=_decode_score,
        missing=("unknown_score", f"Score {str(selected)!r} was not found"),
    )


def _metadata_edit_call(
    score_id: UUID | str,
    expected_revision: int,
    authors: Sequence[str] | None | _Unset,
    paper_url: str | None | _Unset,
) -> _ScoreboardCall[LeaderboardScore]:
    selected = _score_id(score_id)
    revision = _expected_revision(expected_revision)
    body = _metadata_patch(authors, paper_url)
    return _ScoreboardCall(
        "PATCH",
        f"{_SCORES_PATH}/{selected}",
        replay_safe=True,
        decode=_decode_score,
        operation=_METADATA_EDIT_OPERATION,
        codes=_METADATA_EDIT_CODES,
        json=body,
        headers={"If-Match": f'"{revision}"'},
        timeout=_METADATA_EDIT_TIMEOUT_S,
        missing=("unknown_score", f"Score {str(selected)!r} was not found"),
        resend=_EDIT_RESEND,
    )


def _replay_grant_call(pin: _ReplayPin, benchmark_id: str) -> _ScoreboardCall[_ReplayBinding]:
    return _ScoreboardCall(
        "POST",
        _REPLAY_GRANTS_PATH,
        replay_safe=True,
        decode=lambda payload, url: _decode_replay_binding(payload, pin, url),
        operation=_REPLAY_GRANT_OPERATION,
        codes=_REPLAY_GRANT_CODES,
        json={"pin": pin.text, "benchmark_id": benchmark_id},
        timeout=_REPLAY_GRANT_TIMEOUT_S,
        on_failure=_replay_failure,
    )


def _publish_call(result_id: UUID | str) -> _ScoreboardCall[CacheVersionPublication]:
    selected = _result_id(result_id)
    return _ScoreboardCall(
        "POST",
        f"{_RESULTS_PATH}/{selected}/publish",
        replay_safe=True,
        decode=lambda payload, _url: _decode_publication(selected, payload),
        operation=_PUBLISH_OPERATION,
        codes=_PUBLISH_CODES,
        missing=("unknown_result", f"Result {str(selected)!r} was not found"),
    )


@dataclass(frozen=True, slots=True)
class _SubmitDraft:
    """A checked submission that has no receipt yet: the payload, and the notebook notice."""

    candidate_result: CandidateResult
    payload: Mapping[str, object]
    notice: ClientNotice | None

    @classmethod
    def of(
        cls,
        candidate_result: CandidateResult,
        *,
        authors: Sequence[str] | None,
        paper_url: str | None,
        revision_of: str | None,
    ) -> _SubmitDraft:
        payload = _submission(
            candidate_result, authors=authors, paper_url=paper_url, revision_of=revision_of
        )
        return cls(candidate_result, payload, prepare_submission_notice(candidate_result))

    def call(self, outcome: _FreezeOutcome) -> _ScoreboardCall[LeaderboardScore]:
        """The POST that carries the receipt, or the local warning when there is none."""
        payload = dict(self.payload)
        warning = _attach_cache_version(payload, self.candidate_result, outcome)
        return _ScoreboardCall(
            "POST",
            _SCORES_PATH,
            replay_safe=True,
            decode=lambda body, url: _with_warning(_decode_score(body, url), warning),
            operation=_SUBMIT_OPERATION,
            codes=_SUBMIT_CODES,
            json=payload,
            headers={"Idempotency-Key": self.candidate_result.run_id},
            timeout=_SUBMIT_TIMEOUT_S,
            retry_uncoded_409=True,
            resend=_SUBMIT_RESEND,
        )


@dataclass(frozen=True, slots=True)
class _PendingFreeze[F]:
    """A freeze the caller must run, with the key to keep its outcome under."""

    key: tuple[str, str]
    trace_id: str
    freezer: F


class _ReceiptCache:
    """The frozen versions of this client's submits, so a resubmit of one run freezes once."""

    def __init__(self) -> None:
        self._kept: OrderedDict[tuple[str, str], _FrozenCacheVersion] = OrderedDict()

    def pending[F](
        self, candidate_result: CandidateResult, freezer: F | None
    ) -> _FreezeOutcome | _PendingFreeze[F]:
        """The kept or unavailable outcome, or the freeze the caller has to run."""
        trace_id = candidate_result.trace_id
        if trace_id is None or freezer is None:
            return _FreezeUnavailable("no_trace" if trace_id is None else "freeze_unconfigured")
        key = (candidate_result.run_id, trace_id)
        kept = self._kept.get(key)
        return _PendingFreeze(key, trace_id, freezer) if kept is None else kept

    def keep(self, key: tuple[str, str], outcome: _FreezeOutcome) -> _FreezeOutcome:
        """Keep a frozen version for a resubmit of one run (SC-20), never an unavailable one."""
        if isinstance(outcome, _FrozenCacheVersion):
            self._kept[key] = outcome
            while len(self._kept) > _RECEIPT_CACHE_SIZE:
                self._kept.popitem(last=False)
        return outcome


def _attach_cache_version(
    payload: dict[str, object],
    candidate_result: CandidateResult,
    outcome: _FreezeOutcome,
) -> str | None:
    """Put the receipt on the payload, or return the local warning when there is none (SC-E1).

    INVARIANT: `trace_id` rides ONLY with a receipt. `ScoreSubmission` is `extra="forbid"`, so a
    plain submit must not carry a key that an older board would refuse.
    INVARIANT: no trace id, receipt or author reaches the log line. The reason is a token.
    WHY not `warnings.warn`: it comes before the POST, and under `-W error` it would raise and
    stop a submit that SC-E1 says must go on. The field and the log line give both signals.
    """
    if isinstance(outcome, _FrozenCacheVersion):
        payload["cache_version_receipt"] = outcome.receipt
        payload["trace_id"] = candidate_result.trace_id
        return None
    warning = f"{_CACHE_VERSION_WARNING}: {outcome.reason}"
    _logger.warning("%s (run_id=%s)", warning, candidate_result.run_id)
    return warning


def _with_warning(score: LeaderboardScore, warning: str | None) -> LeaderboardScore:
    return score if warning is None else replace(score, cache_version_warning=warning)


def _submit_backoff(resend: int) -> float:
    """0.5 s before the first re-send and 1 s before the second, each with up to 25% jitter."""
    return _SUBMIT_BACKOFF_BASE_S * 2 ** (resend - 1) * (1 + 0.25 * random.random())


def _replay_unavailable(scoreboard_url: str, error: LeaderboardError) -> ReplayUnavailable:
    return ReplayUnavailable(
        "Could not get a replay grant from the Scoreboard",
        scoreboard_url=scoreboard_url,
        status=error.status,
        permanent=False,
    )


def _replay_failure(scoreboard_url: str, error: LeaderboardError) -> ReplayUnavailable | None:
    # WHY `_scoreboard_down` is looked up here: one rule, one patch point, for C4 and C6 alike.
    return _replay_unavailable(scoreboard_url, error) if _scoreboard_down(error) else None


def _scoreboard_down(error: LeaderboardError) -> bool:
    """The board did not answer, or answered 5xx. Any other refusal is its verdict.

    C4 re-sends a submit only then, never after a 4xx (SC-E2); C6 (RP-19) raises
    `ReplayUnavailable` for a replay grant only then.
    """
    return error.code == "scoreboard_unreachable" or (error.status or 0) >= 500


def _down(_outcome: _Attempt, error: LeaderboardError) -> bool:
    # WHY a `def` that looks the name up at call time: the rule stays patchable in this module.
    return _scoreboard_down(error)


def _submit_resend_backoff(resend: int) -> float:
    # WHY a `def` that looks the name up at call time: `_submit_backoff` stays patchable.
    return _submit_backoff(resend)


def _transport_failed(outcome: _Attempt, _error: LeaderboardError) -> bool:
    """The request never got an answer: a connection or timeout error, not another `httpx` one."""
    return isinstance(outcome, httpx.TransportError)


# C4: two re-sends with backoff after a connection error or a 5xx.
_SUBMIT_RESEND: Final = _Resend(_SUBMIT_RESENDS, when=_down, backoff=_submit_resend_backoff)
# C5: one re-send at once after a connection error. A response, whatever its status, is final.
_EDIT_RESEND: Final = _Resend(_METADATA_EDIT_TRANSPORT_RETRIES, when=_transport_failed)


def _decode_list(payload: object) -> LeaderboardCatalog:
    root = _mapping(payload, "Leaderboard list")
    rows = _array(root.get("benchmarks"), "Leaderboard list benchmarks")
    values = tuple(_decode_info(row) for row in rows)
    if len({value.id for value in values}) != len(values):
        _invalid("Leaderboard list contains duplicate ids")
    return LeaderboardCatalog(values)


def _decode_leaderboard(payload: object) -> Leaderboard:
    root = _mapping(payload, "Leaderboard")
    try:
        return Leaderboard(
            benchmark=_decode_info(root.get("benchmark")),
            entries=tuple(_decode_entry(row) for row in _array(root.get("entries"), "entries")),
            baselines=tuple(
                _decode_baseline(row) for row in _array(root.get("baselines"), "baselines")
            ),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


def _decode_score(payload: object, scoreboard_url: str | None = None) -> LeaderboardScore:
    root = _mapping(payload, "Leaderboard score")
    metadata = root.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        _invalid("Leaderboard score metadata must be an object or null")
    try:
        return LeaderboardScore(
            id=UUID(_text(root.get("id"), "Leaderboard score id")),
            version=_integer(root.get("version"), "Leaderboard score version"),
            benchmark_id=_text(root.get("benchmark_id"), "Leaderboard score benchmark_id"),
            spec_id=_text(root.get("spec_id"), "Leaderboard score spec_id"),
            url4=Url4(_text(root.get("url4_expression"), "Leaderboard score url4_expression")),
            submitted_by=_optional_text(root.get("submitted_by"), "Leaderboard score submitted_by"),
            submitted_at=_timestamp(root.get("submitted_at"), "Leaderboard score submitted_at"),
            score=_number(root.get("score"), "Leaderboard score score"),
            total_questions=_integer(
                root.get("total_questions"), "Leaderboard score total_questions"
            ),
            correct_questions=_optional_integer(
                root.get("correct_questions"), "Leaderboard score correct_questions"
            ),
            ran_with_providers=tuple(
                _text(item, "Leaderboard score provider")
                for item in _array(
                    root.get("ran_with_providers"),
                    "Leaderboard score ran_with_providers",
                )
            ),
            ran_at_local=_optional_timestamp(
                root.get("ran_at_local"), "Leaderboard score ran_at_local"
            ),
            client_name=_optional_text(root.get("client_name"), "Leaderboard score client_name"),
            client_version=_optional_text(
                root.get("client_version"), "Leaderboard score client_version"
            ),
            client_platform=_optional_text(
                root.get("client_platform"), "Leaderboard score client_platform"
            ),
            verified_by_screamingface=_boolean(
                root.get("verified_by_screamingface"),
                "Leaderboard score verified_by_screamingface",
            ),
            metadata=metadata,
            scoreboard_url=scoreboard_url,
            authors=_decode_authors(root.get("authors"), "Leaderboard score authors"),
            ranking_notice=_decode_ranking_notice(root),
            paper_url=_optional_text(root.get("paper_url"), "Leaderboard score paper_url"),
            metadata_revision=_optional_integer(
                root.get("metadata_revision"), "Leaderboard score metadata_revision"
            ),
            reported_result=_decode_reported_result(root.get("reported_result")),
            reported_results_count=_optional_integer(
                root.get("reported_results_count"), "Leaderboard score reported_results_count"
            ),
            notices=_decode_notices(root.get("notices")),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


def _decode_replay_binding(payload: object, pin: _ReplayPin, scoreboard_url: str) -> _ReplayBinding:
    """C6 `200` body to a binding. A grant that breaks its limit is refused BEFORE the run."""
    root = _mapping(payload, "Replay grant")
    grant = _replay_grant_text(root.get("grant"), scoreboard_url)
    try:
        result_id = UUID(_text(root.get("result_id"), "Replay grant result_id"))
        return _ReplayBinding(
            grant=grant,
            result_id=result_id,
            score_id=UUID(_text(root.get("score_id"), "Replay grant score_id")),
            cache_version_id=UUID(
                _text(root.get("cache_version_id"), "Replay grant cache_version_id")
            ),
            expires_at=_timestamp(root.get("expires_at"), "Replay grant expires_at"),
            # OD-8: only a `date` pin resolves to a baseline the caller did not name.
            pinned_baseline_result_id=result_id if pin.kind == "date" else None,
        )
    except ValueError as exc:
        _invalid(str(exc), exc)


def _replay_grant_text(value: object, scoreboard_url: str) -> str:
    """The opaque grant, trimmed of outer whitespace only.

    INVARIANT: never decoded, verified or logged here (RP-D2).
    """
    if not isinstance(value, str) or not value.strip():
        reason = "the grant must be non-blank text"
    elif len(value.strip().encode()) > _MAX_GRANT_BYTES:
        reason = f"the grant must be at most {_MAX_GRANT_BYTES} UTF-8 bytes"
    else:
        return value.strip()
    raise LeaderboardError(
        f"Invalid Scoreboard replay grant: {reason}",
        scoreboard_url=scoreboard_url,
        code="invalid_replay_grant",
        permanent=True,
    )


def _decode_publication(result_id: UUID, payload: object) -> CacheVersionPublication:
    root = _mapping(payload, "Cache version publication")
    state = _text(root.get("state"), "Cache version publication state")
    if state not in ("requested", "published"):
        _invalid("Cache version publication state must be requested or published")
    try:
        return CacheVersionPublication(
            result_id=result_id,
            state="requested" if state == "requested" else "published",
            release_url=_optional_text(
                root.get("release_url"), "Cache version publication release_url"
            ),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


def _decode_reported_result(value: object) -> LeaderboardReportedResult | None:
    if value is None:
        return None
    root = _mapping(value, "Leaderboard reported result")
    version = root.get("cache_version")
    return LeaderboardReportedResult(
        id=UUID(_text(root.get("id"), "Leaderboard reported result id")),
        is_original=_boolean(root.get("is_original"), "Leaderboard reported result is_original"),
        reporter=_optional_text(root.get("reporter"), "Leaderboard reported result reporter"),
        cache_version=None if version is None else _decode_cache_version(version),
        publication_state=_optional_text(
            root.get("publication_state"), "Leaderboard reported result publication_state"
        ),
    )


def _decode_cache_version(value: object) -> LeaderboardCacheVersion:
    root = _mapping(value, "Leaderboard cache version")
    coverage = _text(root.get("coverage_status"), "Leaderboard cache version coverage_status")
    if coverage not in ("complete", "partial"):
        _invalid("Leaderboard cache version coverage_status must be complete or partial")
    return LeaderboardCacheVersion(
        id=UUID(_text(root.get("id"), "Leaderboard cache version id")),
        sha256=_text(root.get("sha256"), "Leaderboard cache version sha256"),
        entry_count=_integer(root.get("entry_count"), "Leaderboard cache version entry_count"),
        call_count=_integer(root.get("call_count"), "Leaderboard cache version call_count"),
        coverage_status="complete" if coverage == "complete" else "partial",
    )


def _decode_notices(value: object) -> tuple[LeaderboardNotice, ...]:
    if value is None:
        return ()
    return tuple(_decode_notice(item) for item in _array(value, "Leaderboard score notices"))


def _decode_notice(value: object) -> LeaderboardNotice:
    root = _mapping(value, "Leaderboard notice")
    return LeaderboardNotice(
        code=_text(root.get("code"), "Leaderboard notice code"),
        details={key: item for key, item in root.items() if key != "code"},
    )


def _decode_ranking_notice(root: Mapping[str, object]) -> LeaderboardRankingNotice | None:
    if "ranking_notice" not in root:
        return None
    notice = _mapping(root["ranking_notice"], "Leaderboard score ranking notice")
    code = _text(notice.get("code"), "Leaderboard score ranking notice code")
    if code != "benchmark_revision_mismatch":
        _invalid("Leaderboard score ranking notice has an unsupported code")
    return LeaderboardRankingNotice(
        code="benchmark_revision_mismatch",
        submitted_benchmark_revision=_optional_text(
            notice.get("submitted_benchmark_revision"),
            "Leaderboard score ranking notice submitted_benchmark_revision",
        ),
        registered_benchmark_revision=_text(
            notice.get("registered_benchmark_revision"),
            "Leaderboard score ranking notice registered_benchmark_revision",
        ),
    )


def _cost_text(cost: Decimal | None) -> str | None:
    """The run's cost as it crosses the wire: a decimal string, or None (OME-1029).

    INVARIANT: a STRING, never a float and never a raw Decimal. The payload is handed to `json=`,
    whose `json.dumps` raises TypeError on a Decimal; a float would silently lose precision on what
    Scoreboard stores as DECIMAL(12, 6). `str()` is already this SDK's idiom for the same value —
    see `_report_primitives.Usage.as_dict`.

    INVARIANT: None stays None and is never coerced to 0. Absent means "no cost was reported";
    0 means "this run genuinely cost nothing", which a fully cache-served run legitimately does.
    OME-770's D10 and OME-923's frontier rule both depend on telling those apart — a null read as
    zero would place an unpriced run at the cheapest end of the Pareto frontier, asserting
    something about money nobody measured.

    Scoreboard owns normalisation (quantization, sub-quantum rounding, sign-zero); nothing is
    re-implemented here, or the two would drift.
    """
    return None if cost is None else str(cost)


def _published_cost(candidate_result: CandidateResult) -> dict[str, object]:
    """The cost the board may show for this run: its spend, unless the cache served any call.

    FEATURE (OME-1441, spec 2026-09-30-cached-run-not-complete): stop publishing fake $0 costs.
    A cache hit spends nothing upstream, so a cached run's spend understates what the run costs,
    and until the board ranks on spend plus saving (`OME-1382`) that spend would rank as exact.

    INVARIANT (D1): ANY hit publishes `partial` with no amount, whatever the local status. The
    status sent is then a function of the hit count alone: `partial` means "the cache served some
    calls, so no amount is published", and `unavailable` keeps meaning "no hits, and the spend
    itself could not be priced". Only the published pair changes; the local result keeps its
    true spend and status.

    AIDEV-NOTE: this widens `partial` beyond the board's own wording ("saving evidence exists",
    `scores/schemas.py`). The board accepts the pair; its definition is updated by `OME-1442`.
    Relax to "any hit without a `reported` price" once `OME-1382` ranks on spend plus saving; a
    reported hit's saving then completes the cost instead of hiding it.
    """
    if candidate_result.cache_hits > 0:
        return {"run_cost_usd": None, "run_cost_status": "partial"}
    return {
        "run_cost_usd": _cost_text(candidate_result.usage.cost_usd),
        "run_cost_status": candidate_result.run_cost_status,
    }


def _submission(
    candidate_result: CandidateResult,
    *,
    authors: Sequence[str] | None = None,
    paper_url: str | None = None,
    revision_of: str | None = None,
) -> dict[str, object]:
    if not isinstance(candidate_result, CandidateResult):
        raise TypeError("candidate_result must be an sf.CandidateResult")
    selected_authors = _submission_authors(authors)
    selected_paper_url = None if paper_url is None else _paper_url_text(paper_url)
    selected_revision_of = None if revision_of is None else _revision_of_text(revision_of)
    payload: dict[str, object] = {
        "version": 1,
        "benchmark_id": candidate_result.benchmark.id,
        "spec_id": candidate_result.name,
        "url4_expression": candidate_result.url4,
        "score": _score_value(candidate_result),
        "total_questions": len(candidate_result.cases),
        "models": _submission_models(candidate_result.models),
        "ran_with_providers": list(_providers(candidate_result.models)),
        "ran_at_local": _timestamp_text(candidate_result.completed_at),
        # INVARIANT (OME-1252 / OME-1251 D1): the amount and its status travel as a validated
        # PAIR. The board refuses `complete` without an amount and an amount beside any other
        # status, so sending a mismatched pair only moves a 422 from submit time into the field.
        # `_run_cost_status` on the result already enforces the same rule at construction.
        **_published_cost(candidate_result),
        "client": {
            "name": "screamingface",
            "version": _package_version(),
            "platform": platform.system().lower() or None,
        },
        "metadata": {
            "benchmark_revision": candidate_result.benchmark.revision,
            "candidate_kind": candidate_result.kind,
            "run_id": candidate_result.run_id,
        },
    }
    # INVARIANT (OME-1053): absence means "use the authenticated submitter" while a supplied
    # list is exact. Never send null or auto-add an identity the caller did not name.
    if selected_authors is not None:
        payload["authors"] = list(selected_authors)
    # INVARIANT (E14a, C4): like `authors`, absent means "not given". A board before E14a is
    # `extra="forbid"`, so sending null would 422 a normal submit.
    if selected_paper_url is not None:
        payload["paper_url"] = selected_paper_url
    # INVARIANT (E14, C4): like `paper_url`, absent means "not given", and a board before E14
    # refuses an unknown key.
    if selected_revision_of is not None:
        payload["revision_of"] = selected_revision_of
    # INVARIANT (OME-1326, OME-1251 D5): sent beside the spend, never added to it; the board sums
    # the two at the point of use. Omitted when absent rather than sent as null, so an uncached
    # run's payload is unchanged and a board that predates the field 422s only cached runs.
    if candidate_result.cache_saved_cost_usd is not None:
        payload["cache_saved_cost_usd"] = _cost_text(candidate_result.cache_saved_cost_usd)
    # INVARIANT (E14, C4): absent for a plain run, and a board before E14 refuses an unknown key.
    if candidate_result.replay is not None:
        payload["replay"] = _replay_block(candidate_result.replay)
    return payload


def _replay_block(replay: ReplayProvenance) -> dict[str, object]:
    """The C4 `replay` block. A replay run with no counters is refused before any HTTP call.

    WHY refuse (OD-10, SC-D7): a replay must never show as an independent result, and C4 needs
    integer counts. Zeros would state a fact nobody measured.
    """
    if replay.coverage == "unknown":
        raise ValueError(
            "this replay run has no replay counters from the SF Engine, "
            "so it cannot be submitted as a replay"
        )
    block = replay.to_dict()
    del block["coverage"]
    return block


def _submission_models(models: Sequence[str]) -> list[str]:
    """The declared routes, refused here rather than by the board's 422.

    INVARIANT: raise, never silently drop the field. Omitting `models` when it is over-cap
    would let the submission succeed and the entry be classified from `ran_with_providers` —
    which is the `OME-1145` bug this whole chain exists to fix. A visible local failure beats
    an invisible wrong answer on the public board.

    WHY this lives at the submission boundary and not on `Pipeline`: the caps are the
    leaderboard's, not the toolkit's. Composing a 40-model ensemble locally stays legal;
    only publishing it to a board that will refuse it does not.

    Each message names the offending value as well as the limit. "at most 32 routes" tells a
    user nothing actionable when they do not know they built 41.
    """
    selected = list(models)
    if len(selected) > _MAX_MODELS:
        raise ValueError(f"models must name at most {_MAX_MODELS} routes, not {len(selected)}")
    for route in selected:
        if len(route) > _MAX_MODEL_LENGTH:
            raise ValueError(
                f"each model route must be at most {_MAX_MODEL_LENGTH} characters, not {len(route)}"
            )
    # INVARIANT: measured the way the board measures it — compact separators, `ensure_ascii=False`,
    # then encoded. Any other spelling makes the two ends disagree about what a byte is, and the
    # disagreement only appears on a payload near the limit.
    encoded = len(_json_dumps(selected, ensure_ascii=False, separators=(",", ":")).encode())
    if encoded > _MAX_MODELS_BYTES:
        raise ValueError(
            f"models must serialize to at most {_MAX_MODELS_BYTES} bytes, not {encoded}"
        )
    return selected


def _submission_authors(authors: Sequence[str] | None) -> tuple[str, ...] | None:
    if authors is None:
        return None
    if isinstance(authors, (str, bytes)) or not isinstance(authors, Sequence):
        raise TypeError("authors must be a sequence of email addresses")
    selected = tuple(authors)
    if not selected:
        raise ValueError("authors must contain at least one email address")
    if len(selected) > _MAX_AUTHORS:
        raise ValueError(f"authors must contain at most {_MAX_AUTHORS} email addresses")
    for author in selected:
        if not isinstance(author, str):
            raise TypeError("each author must be an email address string")
        if len(author) > _MAX_AUTHOR_LENGTH or _AUTHOR_EMAIL.fullmatch(author) is None:
            raise ValueError("each author must be a valid email address of at most 255 characters")
    return selected


def _expected_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected_revision must be an integer")
    if value < 1:
        raise ValueError("expected_revision must be positive")
    return value


def _paper_url_text(value: object) -> str:
    # WHY the type is the only rule: the Scoreboard is the one validator of paper URLs (MD-E5),
    # so the SDK never drifts from it.
    if not isinstance(value, str):
        raise TypeError("paper_url must be a string or None")
    selected = value.strip()
    if not selected:
        raise ValueError("paper_url must be non-blank text or None")
    return selected


def _revision_of_text(value: object) -> str:
    # WHY the type and blankness are the only rules: the registry owns the name grammar (SR-E2),
    # so the SDK never drifts from it.
    if not isinstance(value, str):
        raise TypeError("revision_of must be a string or None")
    selected = value.strip()
    if not selected:
        raise ValueError("revision_of must be non-blank text or None")
    return selected


def _metadata_patch(
    authors: Sequence[str] | None | _Unset,
    paper_url: str | None | _Unset,
) -> dict[str, object]:
    """The C5 body: only the fields the caller gave.

    INVARIANT: `None` is a value here (it clears the field, MD-E7) and is sent as JSON null.
    "Not given" is the `UNSET` sentinel, which sends no key. This differs from `submit`, where
    `authors=None` means "do not send the key".
    """
    if authors is _Unset.UNSET and paper_url is _Unset.UNSET:
        raise ValueError("update_submission needs authors or paper_url")
    body: dict[str, object] = {}
    if authors is not _Unset.UNSET:
        if authors is None:
            body["authors"] = None
        else:
            selected = _submission_authors(authors)
            assert selected is not None
            body["authors"] = list(selected)
    if paper_url is not _Unset.UNSET:
        body["paper_url"] = None if paper_url is None else _paper_url_text(paper_url)
    return body


def _score_value(candidate_result: CandidateResult) -> float:
    """The Engine's benchmark-native score, submitted verbatim (OME-866).

    INVARIANT: the Engine-side Benchmark is the sole scoring authority — the Client
    never derives a replacement from Case grades, normalizes, or bounds the value.
    The only universal facts about a rankable score are that it exists and is finite
    (DRACO is fractional, HealthBench worst-30 is negative), so those are the only
    checks made before HTTP.

    WHY the explicit isfinite: NaN used to be rejected as a side effect of the deleted
    0..1 range check; without this guard `json.dumps(nan)` would emit invalid JSON.
    """
    score = candidate_result.score
    if score is None:
        raise ValueError("an unscored CandidateResult cannot be submitted")
    if not math.isfinite(score):
        raise ValueError("CandidateResult score must be a finite number for the Scoreboard")
    return score


def _providers(models: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(model.split("/", 1)[0] for model in models))


def _package_version() -> str | None:
    try:
        return version("screamingface")
    except PackageNotFoundError:
        return None


def _decode_info(value: object) -> LeaderboardInfo:
    root = _mapping(value, "Leaderboard benchmark")
    try:
        return LeaderboardInfo(
            id=_text(root.get("id"), "Leaderboard benchmark id"),
            display_name=_text(root.get("display_name"), "Leaderboard benchmark display_name"),
            description=_optional_text(
                root.get("description"), "Leaderboard benchmark description"
            ),
            dataset_url=_optional_text(
                root.get("dataset_url"), "Leaderboard benchmark dataset_url"
            ),
            created_at=_timestamp(root.get("created_at"), "Leaderboard benchmark created_at"),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


def _decode_entry(value: object) -> LeaderboardEntry:
    root = _mapping(value, "Leaderboard entry")
    try:
        return LeaderboardEntry(
            rank=_integer(root.get("rank"), "Leaderboard entry rank"),
            spec_id=_text(root.get("spec_id"), "Leaderboard entry spec_id"),
            score=_number(root.get("score"), "Leaderboard entry score"),
            total_questions=_integer(
                root.get("total_questions"), "Leaderboard entry total_questions"
            ),
            ran_with_providers=tuple(
                _text(item, "Leaderboard entry provider")
                for item in _array(root.get("ran_with_providers"), "ran_with_providers")
            ),
            submitted_at=_timestamp(root.get("submitted_at"), "Leaderboard entry submitted_at"),
            submitted_by=_optional_text(root.get("submitted_by"), "Leaderboard entry submitted_by"),
            verified_by_screamingface=_boolean(
                root.get("verified_by_screamingface"), "Leaderboard entry verified_by_screamingface"
            ),
            url4=Url4(_text(root.get("url4_expression"), "Leaderboard entry url4_expression")),
            authors=_decode_authors(root.get("authors"), "Leaderboard entry authors"),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


def _decode_baseline(value: object) -> LeaderboardBaseline:
    root = _mapping(value, "Leaderboard baseline")
    metadata = root.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        _invalid("Leaderboard baseline metadata must be an object or null")
    try:
        return LeaderboardBaseline(
            id=UUID(_text(root.get("id"), "Leaderboard baseline id")),
            benchmark_id=_text(root.get("benchmark_id"), "Leaderboard baseline benchmark_id"),
            model_name=_text(root.get("model_name"), "Leaderboard baseline model_name"),
            score=_number(root.get("score"), "Leaderboard baseline score"),
            source=_text(root.get("source"), "Leaderboard baseline source"),
            source_url=_optional_text(root.get("source_url"), "Leaderboard baseline source_url"),
            imported_at=_timestamp(root.get("imported_at"), "Leaderboard baseline imported_at"),
            metadata=metadata,
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _invalid(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        _invalid(f"{label} must be an array")
    return value


def _decode_authors(value: object, label: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    selected = _array(value, label)
    if not selected:
        _invalid(f"{label} must not be empty")
    # WHY no email validation: public Scoreboard JSON strips email domains before returning
    # authors. These are public credit identifiers, while full email syntax and the write-side cap
    # belong only to submissions. Preserve every nonblank value exactly as the read contract says.
    return tuple(_public_author(author, f"{label} item") for author in selected)


def _public_author(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{label} must be non-blank text")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{label} must be non-blank text")
    return value.strip()


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(f"{label} must be an integer")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _invalid(f"{label} must be a number")
    return float(value)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        _invalid(f"{label} must be a boolean")
    return value


def _timestamp(value: object, label: str) -> datetime:
    selected = _text(value, label)
    try:
        parsed = datetime.fromisoformat(selected.replace("Z", "+00:00"))
    except ValueError as exc:
        _invalid(f"{label} must be an ISO 8601 timestamp", exc)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _invalid(f"{label} must include a UTC offset")
    return parsed


def _optional_timestamp(value: object, label: str) -> datetime | None:
    return None if value is None else _timestamp(value, label)


def _timestamp_text(value: datetime) -> str:
    text = value.isoformat()
    return text[:-6] + "Z" if text.endswith("+00:00") else text


def _benchmark_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("benchmark_id must be a string")
    selected = value.strip().removeprefix("/")
    if not selected:
        raise ValueError("benchmark_id must be non-empty")
    return selected


def _score_id(value: object) -> UUID:
    return _uuid_argument(value, "score_id")


def _result_id(value: object) -> UUID:
    return _uuid_argument(value, "result_id")


def _uuid_argument(value: object, name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a UUID or string")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid UUID") from exc


def _top(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("top must be an integer")
    if value < 1:
        raise ValueError("top must be positive")
    return value


__all__ = ["AsyncLeaderboards", "Leaderboards"]
