"""Typed Leaderboard adapters at the Scoreboard HTTP seam."""

from __future__ import annotations

import math
import platform
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from typing import NoReturn
from urllib.parse import quote
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
    LeaderboardScore,
)
from screamingface.report import CandidateResult
from screamingface.url4 import Url4

_BENCHMARKS_PATH = "/v1/benchmarks"
_LEADERBOARD_PATH = "/v1/leaderboard"
_SCORES_PATH = "/v1/scores"
_AUTHOR_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
_MAX_AUTHORS = 10
_MAX_AUTHOR_LENGTH = 255


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
    ) -> LeaderboardScore:
        payload = _submission(candidate_result, authors=authors)
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
                operation="submit a score to",
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
    ) -> LeaderboardScore:
        payload = _submission(candidate_result, authors=authors)
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
                operation="submit a score to",
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
        submission_conflict = response.status_code == 409 and operation == "submit a score to"
        raise LeaderboardError(
            f"Could not {operation} the Scoreboard: HTTP {response.status_code}{suffix}",
            scoreboard_url=scoreboard_url,
            code=_status_code(response.status_code, operation),
            status=response.status_code,
            permanent=(
                response.status_code < 500
                and response.status_code != 429
                and not submission_conflict
            ),
            details=details,
            hint="Retry the submission." if submission_conflict else None,
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
    if isinstance(payload, Mapping) and isinstance(payload.get("detail"), str):
        return payload["detail"]
    return payload


def _status_code(status: int, operation: str) -> str:
    if operation != "submit a score to":
        return "scoreboard_contract_error"
    return {
        400: "invalid_score_submission",
        401: "scoreboard_authentication_required",
        403: "score_submission_forbidden",
        409: "score_submission_conflict",
        422: "invalid_score_submission",
    }.get(status, "scoreboard_contract_error")


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
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc), exc)


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


def _submission(
    candidate_result: CandidateResult,
    *,
    authors: Sequence[str] | None = None,
) -> dict[str, object]:
    if not isinstance(candidate_result, CandidateResult):
        raise TypeError("candidate_result must be an sf.CandidateResult")
    selected_authors = _submission_authors(authors)
    payload: dict[str, object] = {
        "version": 1,
        "benchmark_id": candidate_result.benchmark.id,
        "spec_id": candidate_result.name,
        "url4_expression": candidate_result.url4,
        "score": _score_value(candidate_result),
        "total_questions": len(candidate_result.cases),
        "ran_with_providers": list(_providers(candidate_result.models)),
        "ran_at_local": _timestamp_text(candidate_result.completed_at),
        "run_cost_usd": _cost_text(candidate_result.usage.cost_usd),
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
    return payload


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
