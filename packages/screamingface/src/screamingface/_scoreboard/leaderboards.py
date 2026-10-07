"""Typed Leaderboard adapters at the Scoreboard HTTP seam."""

from __future__ import annotations

import math
import platform
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version

# WHY the aliased import rather than `import json`: `_sync_json` and `_async_json` both take a
# parameter named `json`, so the module name is shadowed inside exactly the functions most
# likely to want it. Importing the one callable under its own name removes the trap.
from json import dumps as _json_dumps
from typing import Literal, NoReturn
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx

from screamingface._scoreboard.submission_notice import (
    display_submission_notice,
    prepare_submission_notice,
)
from screamingface._ui.leaderboard_view import LeaderboardCatalog
from screamingface.errors import LeaderboardError
from screamingface.leaderboard import (
    Leaderboard,
    LeaderboardBaseline,
    LeaderboardEntry,
    LeaderboardInfo,
    LeaderboardRankingNotice,
    LeaderboardScore,
    ScoreMetadataEvent,
)
from screamingface.report import CandidateResult
from screamingface.url4 import Url4

_BENCHMARKS_PATH = "/v1/benchmarks"
_LEADERBOARD_PATH = "/v1/leaderboard"
_SCORES_PATH = "/v1/scores"
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
# FEATURE: OME-1307 — mirrors the Scoreboard's `paper_url` bound (http(s), 1 to 2048 characters).
_MAX_PAPER_URL_LENGTH = 2048
_SUBMIT_OPERATION = "submit a score to"
_EDIT_OPERATION = "edit a score on"
_EVENTS_OPERATION = "read score metadata events from"
# WHY a 409 is retryable on these two and not elsewhere: the board answers it when it changed under
# the request (a resubmit race, or its visibility flipping), and a retry sees one consistent view.
_CONFLICT_HINTS = {_SUBMIT_OPERATION: "Retry the submission.", _EDIT_OPERATION: "Retry the edit."}
_STATUS_CODES: dict[str, dict[int, str]] = {
    _SUBMIT_OPERATION: {
        400: "invalid_score_submission",
        401: "scoreboard_authentication_required",
        403: "score_submission_forbidden",
        409: "score_submission_conflict",
        422: "invalid_score_submission",
    },
    _EDIT_OPERATION: {
        401: "scoreboard_authentication_required",
        403: "score_edit_forbidden",
        409: "score_edit_conflict",
        422: "invalid_score_edit",
    },
    _EVENTS_OPERATION: {
        401: "scoreboard_authentication_required",
        403: "score_events_forbidden",
    },
}


class _Unset:
    """The type of `_UNSET`: "argument not given", distinct from an explicit None."""

    __slots__ = ()

    def __repr__(self) -> str:
        # WHY a fixed repr: the public-surface snapshot renders defaults, and a default object's
        # memory address would change on every run.
        return "UNSET"


_UNSET = _Unset()


class Leaderboards:
    """Synchronous public Leaderboards bound to one Client."""

    def __init__(self, request: Callable[..., httpx.Response], scoreboard_url: str) -> None:
        self._request = request
        self._scoreboard_url = scoreboard_url

    def list(self) -> Sequence[LeaderboardInfo]:
        return _decode_list(
            _sync_json(
                self._request,
                self._scoreboard_url,
                "GET",
                _BENCHMARKS_PATH,
                replay_safe=True,
            )
        )

    def get(self, benchmark_id: str, *, top: int = 50) -> Leaderboard:
        selected = _benchmark_id(benchmark_id)
        limit = _top(top)
        return _decode_leaderboard(
            _sync_json(
                self._request,
                self._scoreboard_url,
                "GET",
                f"{_LEADERBOARD_PATH}/{quote(selected, safe='')}",
                replay_safe=True,
                params={"top": limit},
                missing=("unknown_leaderboard", f"Leaderboard {selected!r} is not registered"),
            )
        )

    def submit(
        self,
        candidate_result: CandidateResult,
        *,
        authors: Sequence[str] | None = None,
        paper_url: str | None = None,
    ) -> LeaderboardScore:
        payload = _submission(candidate_result, authors=authors, paper_url=paper_url)
        notebook_notice = prepare_submission_notice(candidate_result)
        score = _decode_score(
            scoreboard_url=self._scoreboard_url,
            payload=_sync_json(
                self._request,
                self._scoreboard_url,
                "POST",
                _SCORES_PATH,
                json=payload,
                headers={"Idempotency-Key": candidate_result.run_id},
                replay_safe=True,
                operation=_SUBMIT_OPERATION,
            ),
        )
        display_submission_notice(notebook_notice)
        return score

    def get_score(self, score_id: UUID | str) -> LeaderboardScore:
        selected = _score_id(score_id)
        return _decode_score(
            scoreboard_url=self._scoreboard_url,
            payload=_sync_json(
                self._request,
                self._scoreboard_url,
                "GET",
                f"{_SCORES_PATH}/{selected}",
                replay_safe=True,
                missing=("unknown_score", f"Score {str(selected)!r} was not found"),
            ),
        )

    def edit(
        self,
        score_id: UUID | str,
        *,
        authors: Sequence[str] | None | _Unset = _UNSET,
        paper_url: str | None | _Unset = _UNSET,
    ) -> LeaderboardScore:
        selected = _score_id(score_id)
        payload = _edit_payload(authors, paper_url)
        return _decode_score(
            scoreboard_url=self._scoreboard_url,
            payload=_sync_json(
                self._request,
                self._scoreboard_url,
                "PATCH",
                f"{_SCORES_PATH}/{selected}",
                json=payload,
                replay_safe=True,
                missing=("unknown_score", f"Score {str(selected)!r} was not found"),
                operation=_EDIT_OPERATION,
            ),
        )

    def metadata_events(self, score_id: UUID | str) -> tuple[ScoreMetadataEvent, ...]:
        selected = _score_id(score_id)
        return _decode_metadata_events(
            _sync_json(
                self._request,
                self._scoreboard_url,
                "GET",
                f"{_SCORES_PATH}/{selected}/metadata-events",
                replay_safe=True,
                missing=("unknown_score", f"Score {str(selected)!r} was not found"),
                operation=_EVENTS_OPERATION,
            )
        )


class AsyncLeaderboards:
    """Asynchronous public Leaderboards bound to one AsyncClient."""

    def __init__(
        self,
        request: Callable[..., Awaitable[httpx.Response]],
        scoreboard_url: str,
    ) -> None:
        self._request = request
        self._scoreboard_url = scoreboard_url

    async def list(self) -> Sequence[LeaderboardInfo]:
        return _decode_list(
            await _async_json(
                self._request,
                self._scoreboard_url,
                "GET",
                _BENCHMARKS_PATH,
                replay_safe=True,
            )
        )

    async def get(self, benchmark_id: str, *, top: int = 50) -> Leaderboard:
        selected = _benchmark_id(benchmark_id)
        limit = _top(top)
        return _decode_leaderboard(
            await _async_json(
                self._request,
                self._scoreboard_url,
                "GET",
                f"{_LEADERBOARD_PATH}/{quote(selected, safe='')}",
                replay_safe=True,
                params={"top": limit},
                missing=("unknown_leaderboard", f"Leaderboard {selected!r} is not registered"),
            )
        )

    async def submit(
        self,
        candidate_result: CandidateResult,
        *,
        authors: Sequence[str] | None = None,
        paper_url: str | None = None,
    ) -> LeaderboardScore:
        payload = _submission(candidate_result, authors=authors, paper_url=paper_url)
        notebook_notice = prepare_submission_notice(candidate_result)
        score = _decode_score(
            scoreboard_url=self._scoreboard_url,
            payload=await _async_json(
                self._request,
                self._scoreboard_url,
                "POST",
                _SCORES_PATH,
                json=payload,
                headers={"Idempotency-Key": candidate_result.run_id},
                replay_safe=True,
                operation=_SUBMIT_OPERATION,
            ),
        )
        display_submission_notice(notebook_notice)
        return score

    async def get_score(self, score_id: UUID | str) -> LeaderboardScore:
        selected = _score_id(score_id)
        return _decode_score(
            scoreboard_url=self._scoreboard_url,
            payload=await _async_json(
                self._request,
                self._scoreboard_url,
                "GET",
                f"{_SCORES_PATH}/{selected}",
                replay_safe=True,
                missing=("unknown_score", f"Score {str(selected)!r} was not found"),
            ),
        )

    async def edit(
        self,
        score_id: UUID | str,
        *,
        authors: Sequence[str] | None | _Unset = _UNSET,
        paper_url: str | None | _Unset = _UNSET,
    ) -> LeaderboardScore:
        selected = _score_id(score_id)
        payload = _edit_payload(authors, paper_url)
        return _decode_score(
            scoreboard_url=self._scoreboard_url,
            payload=await _async_json(
                self._request,
                self._scoreboard_url,
                "PATCH",
                f"{_SCORES_PATH}/{selected}",
                json=payload,
                replay_safe=True,
                missing=("unknown_score", f"Score {str(selected)!r} was not found"),
                operation=_EDIT_OPERATION,
            ),
        )

    async def metadata_events(self, score_id: UUID | str) -> tuple[ScoreMetadataEvent, ...]:
        selected = _score_id(score_id)
        return _decode_metadata_events(
            await _async_json(
                self._request,
                self._scoreboard_url,
                "GET",
                f"{_SCORES_PATH}/{selected}/metadata-events",
                replay_safe=True,
                missing=("unknown_score", f"Score {str(selected)!r} was not found"),
                operation=_EVENTS_OPERATION,
            )
        )


def _sync_json(
    request: Callable[..., httpx.Response],
    scoreboard_url: str,
    method: str,
    path: str,
    *,
    replay_safe: bool,
    params: Mapping[str, object] | None = None,
    json: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    missing: tuple[str, str] | None = None,
    operation: str = "load",
) -> object:
    try:
        response = request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
            replay_safe=replay_safe,
        )
    except httpx.HTTPError as exc:
        _unreachable(scoreboard_url, exc)
    return _response_json(response, scoreboard_url, missing, operation)


async def _async_json(
    request: Callable[..., Awaitable[httpx.Response]],
    scoreboard_url: str,
    method: str,
    path: str,
    *,
    replay_safe: bool,
    params: Mapping[str, object] | None = None,
    json: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    missing: tuple[str, str] | None = None,
    operation: str = "load",
) -> object:
    try:
        response = await request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
            replay_safe=replay_safe,
        )
    except httpx.HTTPError as exc:
        _unreachable(scoreboard_url, exc)
    return _response_json(response, scoreboard_url, missing, operation)


def _response_json(
    response: httpx.Response,
    scoreboard_url: str,
    missing: tuple[str, str] | None,
    operation: str,
) -> object:
    if response.status_code == 404 and missing is not None:
        code, message = missing
        raise LeaderboardError(
            message,
            scoreboard_url=scoreboard_url,
            code=code,
            status=404,
            permanent=True,
        )
    if not response.is_success:
        details = _error_details(response)
        suffix = f" ({details})" if isinstance(details, str) and details else ""
        conflict_hint = _CONFLICT_HINTS.get(operation) if response.status_code == 409 else None
        raise LeaderboardError(
            f"Could not {operation} the Scoreboard: HTTP {response.status_code}{suffix}",
            scoreboard_url=scoreboard_url,
            code=_status_code(response.status_code, operation),
            status=response.status_code,
            permanent=(
                response.status_code < 500 and response.status_code != 429 and conflict_hint is None
            ),
            details=details,
            hint=conflict_hint,
        )
    try:
        return response.json()
    except ValueError as exc:
        _invalid("response must be JSON", exc)


def _error_details(response: httpx.Response) -> object:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, Mapping):
        text = _detail_text(payload.get("detail"))
        if text is not None:
            return text
    return payload


def _detail_text(detail: object) -> str | None:
    """A flat `detail` string as it came; the board's coded refusals as `code: message`."""
    if isinstance(detail, str):
        return detail
    # `{code, message}` is how the board refuses (`not_score_owner`, ...); surface both.
    if (
        isinstance(detail, Mapping)
        and isinstance(detail.get("code"), str)
        and isinstance(detail.get("message"), str)
    ):
        return f"{detail['code']}: {detail['message']}"
    return None


def _status_code(status: int, operation: str) -> str:
    return _STATUS_CODES.get(operation, {}).get(status, "scoreboard_contract_error")


def _unreachable(scoreboard_url: str, exc: httpx.HTTPError) -> NoReturn:
    raise LeaderboardError(
        "Could not reach the configured ScreamingFace Scoreboard",
        scoreboard_url=scoreboard_url,
        code="scoreboard_unreachable",
        permanent=False,
    ) from exc


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
            metadata_updated_at=_optional_timestamp(
                root.get("metadata_updated_at"), "Leaderboard score metadata_updated_at"
            ),
            cache_revision=_optional_text(
                root.get("cache_revision"), "Leaderboard score cache_revision"
            ),
            reproducible=_decode_reproducible(root.get("reproducible")),
            answer_seed=_optional_integer(root.get("answer_seed"), "Leaderboard score answer_seed"),
            # K8: an older board omits the count, and an omitted count reads as 0.
            reproduction_count=_integer(
                root.get("reproduction_count", 0), "Leaderboard score reproduction_count"
            ),
            last_reproduced_at=_optional_timestamp(
                root.get("last_reproduced_at"), "Leaderboard score last_reproduced_at"
            ),
            benchmark_revision=_optional_text(
                root.get("benchmark_revision"), "Leaderboard score benchmark_revision"
            ),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


def _decode_reproducible(value: object) -> Literal["complete", "partial"] | None:
    if value is None:
        return None
    if value == "complete":
        return "complete"
    if value == "partial":
        return "partial"
    _invalid("Leaderboard score reproducible must be 'complete', 'partial' or null")


def _decode_metadata_events(payload: object) -> tuple[ScoreMetadataEvent, ...]:
    return tuple(_decode_metadata_event(row) for row in _array(payload, "Score metadata events"))


def _decode_metadata_event(value: object) -> ScoreMetadataEvent:
    root = _mapping(value, "Score metadata event")
    source = _text(root.get("source"), "Score metadata event source")
    if source not in ("patch", "resubmit"):
        _invalid("Score metadata event source must be 'patch' or 'resubmit'")
    try:
        return ScoreMetadataEvent(
            id=UUID(_text(root.get("id"), "Score metadata event id")),
            edited_by=_text(root.get("edited_by"), "Score metadata event edited_by"),
            edited_at=_timestamp(root.get("edited_at"), "Score metadata event edited_at"),
            source=source,
            # NOTE: events carry full addresses (an owner-only read), so the domain-stripping WHY on
            # `_decode_authors` does not apply; it only checks shape.
            old_authors=_decode_authors(
                root.get("old_authors"), "Score metadata event old_authors"
            ),
            new_authors=_decode_authors(
                root.get("new_authors"), "Score metadata event new_authors"
            ),
            old_paper_url=_optional_text(
                root.get("old_paper_url"), "Score metadata event old_paper_url"
            ),
            new_paper_url=_optional_text(
                root.get("new_paper_url"), "Score metadata event new_paper_url"
            ),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


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
    """The cost the board may show for this run: its spend, plus proof that its hits are priced.

    FEATURE (OME-1441): never publish a cached run's spend as its whole cost. FEATURE (OME-1463,
    D7 on OME-1251): the board now sums spend + reported saving + archive saving (OME-1382), so a
    cached run whose every hit carries a price publishes `complete` with its SPEND as the amount;
    the savings travel beside it and the board adds them.

    INVARIANT (spec 2026-10-02-OME-1463 D3): `complete` only with PROOF that no hit was unpriced:
    the Engine run summary's `unpriced_hits` == 0. No summary (`None`), any unpriced hit, or an
    unpriced spend -> `partial` with no amount. A missing price is never counted as $0. Only the
    published pair changes; the local result keeps its true spend and status.
    """
    if candidate_result.cache_hits > 0 and (
        candidate_result.cache_unpriced_hits != 0 or candidate_result.usage.cost_usd is None
    ):
        return {"run_cost_usd": None, "run_cost_status": "partial"}
    if candidate_result.cache_hits > 0:
        return {
            "run_cost_usd": _cost_text(candidate_result.usage.cost_usd),
            "run_cost_status": "complete",
        }
    return {
        "run_cost_usd": _cost_text(candidate_result.usage.cost_usd),
        "run_cost_status": candidate_result.run_cost_status,
    }


def _submission(
    candidate_result: CandidateResult,
    *,
    authors: Sequence[str] | None = None,
    paper_url: str | None = None,
) -> dict[str, object]:
    if not isinstance(candidate_result, CandidateResult):
        raise TypeError("candidate_result must be an sf.CandidateResult")
    selected_authors = _submission_authors(authors)
    selected_paper_url = None if paper_url is None else _paper_url(paper_url)
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
    # INVARIANT (OME-1307, K4): omitted when absent rather than sent as null, so a board that
    # predates `paper_url` 422s only a submission that names one.
    if selected_paper_url is not None:
        payload["paper_url"] = selected_paper_url
    # INVARIANT (OME-1326, OME-1251 D5): sent beside the spend, never added to it; the board sums
    # the two at the point of use. Omitted when absent rather than sent as null, so an uncached
    # run's payload is unchanged and a board that predates the field 422s only cached runs.
    if candidate_result.cache_saved_cost_usd is not None:
        payload["cache_saved_cost_usd"] = _cost_text(candidate_result.cache_saved_cost_usd)
    # INVARIANT (OME-1463, D7): the archive saving travels the same way, its own field, never added
    # to the spend or the reported saving. Omitted when absent, so a board that predates the field
    # rejects only archive-priced runs. AIDEV-NOTE: needs OME-1382's board half live first.
    if candidate_result.cache_saved_cost_archive_usd is not None:
        payload["cache_saved_cost_archive_usd"] = _cost_text(
            candidate_result.cache_saved_cost_archive_usd
        )
    payload.update(_cache_version_fields(candidate_result))
    return payload


def _cache_version_fields(candidate_result: CandidateResult) -> dict[str, object]:
    """The cache version and the sitting, only the parts the run has.

    INVARIANT (OME-1307, K4, cv C13): omitted rather than null, so a board that predates the
    fields 422s nothing a run without cache data submits. A zero seed is a sitting and is sent.
    """
    known = {
        "cache_revision": candidate_result.cache_revision,
        "reproducible": candidate_result.reproducible,
        "answer_seed": candidate_result.answer_seed,
    }
    return {name: value for name, value in known.items() if value is not None}


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


def _paper_url(value: object) -> str:
    """The paper link as the board will accept it, checked the way the board checks it.

    INVARIANT (OME-1307): mirrors the Scoreboard's `_validate_paper_url` so a link it would 422 is
    refused here. A wrong type is a TypeError, like the author checks; a bad value is a ValueError.
    The link is returned UNCHANGED.
    """
    if not isinstance(value, str):
        raise TypeError("paper_url must be a string")
    if not 1 <= len(value) <= _MAX_PAPER_URL_LENGTH:
        raise ValueError(f"paper_url must be 1 to {_MAX_PAPER_URL_LENGTH} characters")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("paper_url must not contain control characters")
    if any(char.isspace() for char in value):
        raise ValueError("paper_url must not contain whitespace")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("paper_url must use the http or https scheme")
    if not parts.hostname:
        raise ValueError("paper_url must name a host")
    # WHY `is not None`: `username` is "" (not None) for a bare `@`.
    if parts.username is not None or parts.password is not None:
        raise ValueError("paper_url must not contain user info")
    return value


def _edit_payload(
    authors: Sequence[str] | None | _Unset,
    paper_url: str | None | _Unset,
) -> dict[str, object]:
    """The PATCH body: an absent key means "unchanged", `paper_url=None` sends null to clear it.

    INVARIANT (OME-1307, K5): `authors=None` is refused here because the board answers it with a
    422; to go back to the derived submitter, pass `[submitted_by]`.
    """
    payload: dict[str, object] = {}
    if not isinstance(authors, _Unset):
        selected = _submission_authors(authors)
        if selected is None:
            raise ValueError("authors cannot be cleared; pass at least one email address")
        payload["authors"] = list(selected)
    if not isinstance(paper_url, _Unset):
        payload["paper_url"] = None if paper_url is None else _paper_url(paper_url)
    if not payload:
        raise ValueError("edit needs at least one of authors or paper_url")
    return payload


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
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise TypeError("score_id must be a UUID or string")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError("score_id must be a valid UUID") from exc


def _top(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("top must be an integer")
    if value < 1:
        raise ValueError("top must be positive")
    return value


def _invalid(message: str, cause: BaseException | None = None) -> NoReturn:
    error = LeaderboardError(
        f"Invalid Scoreboard Leaderboard response: {message}",
        code="invalid_leaderboard",
        permanent=True,
    )
    if cause is None:
        raise error
    raise error from cause


__all__ = ["AsyncLeaderboards", "Leaderboards"]
