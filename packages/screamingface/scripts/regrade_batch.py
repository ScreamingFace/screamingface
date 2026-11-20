"""Re-grade only OME-1958's 47 explicit board/source/target transitions (Unix).

Run from packages/screamingface after the revision bump is deployed:
    uv run python scripts/regrade_batch.py                         # read-only preview
    uv run python scripts/regrade_batch.py --apply --log /path/to/regrade.jsonl
    uv run python scripts/regrade_batch.py --benchmark inspect-mmlu_pro

For dev, select both services explicitly (an apply override requires both):
    uv run python scripts/regrade_batch.py --apply --log /path/to/dev-regrade.jsonl \
        --engine-url https://fusion.dev.screamingface.ai \
        --scoreboard-url https://leaderboard.dev.screamingface.ai

regrade_transitions.json fixes the scope. Every selected board must serve its exact target;
missing boards, missing source metadata, unknown revisions and truncated reads stop the batch.
Only the declared source revision is discovered. Explicitly select public boards for rollout;
the three unlisted WMDP boards cannot participate in a public batch.

Use one persistent log path on one operator machine for all scheduled runs. Its persistent
`.lock` sidecar excludes overlapping processes. Never rotate/delete either file while running.
Records are fsynced; a valid final record missing its newline is retained and repaired. Only
an undecodable unterminated tail is truncated. Complete invalid records require inspection.
Version-2 keys distinguish score IDs from spec IDs and escape CLI delimiters. Older ambiguous
keys require manual reconciliation into a new journal before resuming; never discard unresolved
owner work. Keep the archived original as evidence.

Permanent refusals and uncached rows are not retried automatically, but remain unresolved
(exit 1), even if a later discovery no longer lists them. After an owner decision, record it:
    uv run python scripts/regrade_batch.py --log /path/to/regrade.jsonl \
        --resolve 'ENTRY_KEY=Fresh run linked at ...'
The entry key is printed and stored in each log record. Resolution only updates the local
log; it never re-grades. Keep the note as evidence of the actual owner action. Retrying the same
key and note is safe after interruption; a conflicting note is refused.

Optional --when-revision inspect-mmlu_pro=4efebd6cc74c2dca waits while that board serves
its declared source revision. The guard must name a selected board and its exact target;
all selected boards still have to pass target validation before any replay.
Exit 0: dry run, waiting, or all logged entries resolved; 1: unresolved entries;
2: invalid input, read/log failure or another batch is running.
Every replay uses stored replies only. Changed judge requests require OME-1979.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import httpx
from regrade_batch_log import (
    NO_RETRY,
    RESOLVED,
    LogError,
    entry_key,
    locked_journal,
)
from regrade_batch_log import (
    BatchAlreadyRunning as BatchAlreadyRunning,
)

TRANSITIONS: dict[str, dict[str, str]] = json.loads(
    Path(__file__).with_name("regrade_transitions.json").read_text()
)

#: Rows per board page; the Scoreboard clamps any larger ``top`` to this (MAX_LEADERBOARD_TOP).
_TOP: int = 200
_TIMEOUT_S: float = 30.0
_EXIT_OK: int = 0
_EXIT_SOME_REFUSED: int = 1
#: Permanent in the SDK, but a deploy in progress, never the entry: a later run tries again.
_RETRIED_ANYWAY: frozenset[str] = frozenset({"already_current"})


class BoardReadError(RuntimeError):
    """A public Scoreboard read failed, so the entry list would be incomplete."""


class Entry(NamedTuple):
    """One leaderboard row on an older revision: what to re-grade, or why it cannot be."""

    benchmark_id: str
    revision: str
    spec_id: str
    #: None when the row has no pinned cache: it cannot be re-graded.
    pinned_cache: str | None
    score_id: str | None


class _Regrader(Protocol):
    """The one SDK call the loop needs, so a test can stand in for ``sf.Client``."""

    leaderboards: Any

    def regrade(self, score_id: str, *, expected_target_revision: str) -> Any:
        """Re-grade one score and return the new board entry."""


def _get(http: httpx.Client, path: str, **params: str | int) -> Any:
    """GET a public Scoreboard path as JSON; any failure is a ``BoardReadError``."""

    try:
        response: httpx.Response = http.get(path, params=params or None)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise BoardReadError(f"GET {path} answered {exc.response.status_code}") from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise BoardReadError(f"GET {path} failed: {exc}") from exc


def find_entries(http: httpx.Client, benchmark_ids: Sequence[str] = ()) -> list[Entry]:
    """Read only the 47 declared source revisions, after validating every target."""
    wanted = set(benchmark_ids) or set(TRANSITIONS)
    if wanted - TRANSITIONS.keys():
        raise BoardReadError(f"unknown OME-1958 boards: {sorted(wanted - TRANSITIONS.keys())}")
    boards = {b["id"]: b for b in _get(http, "/v1/benchmarks")["benchmarks"]}
    for board_id in sorted(wanted):
        board = boards.get(board_id, {})
        if (
            board.get("visibility") != "public"
            or board.get("revision") != TRANSITIONS[board_id]["target"]
        ):
            raise BoardReadError(
                f"{board_id}: expected public target {TRANSITIONS[board_id]['target']}"
            )
    entries: list[Entry] = []
    for board_id in sorted(wanted):
        entries.extend(_source_entries(http, board_id))
    return entries


def _source_entries(http: httpx.Client, board_id: str) -> list[Entry]:
    """Fail closed if a source page cannot enumerate the entire ranked population."""
    source = TRANSITIONS[board_id]["source"]
    revisions = _get(http, f"/v1/leaderboard/{board_id}/revisions")["revisions"]
    summary = next((r for r in revisions if r["revision"] == source), None)
    if summary is None:
        raise BoardReadError(f"{board_id}: declared source revision {source} is missing")
    count = summary["result_count"]
    if not isinstance(count, int) or not 0 <= count <= _TOP:
        raise BoardReadError(
            f"{board_id}: source result_count {count} exceeds safe page capacity {_TOP}"
        )
    page = _get(http, f"/v1/leaderboard/{board_id}", revision=source, top=_TOP)
    if len(page["entries"]) != count:
        raise BoardReadError(f"{board_id}: source page changed or was truncated; retry discovery")
    entries = []
    for row in page["entries"]:
        copy = row.get("pinned_cache")
        score_id = (
            str(_get(http, f"/v1/public/scores/by-pinned-cache/{copy}")["score_id"])
            if copy
            else None
        )
        entries.append(Entry(board_id, source, str(row["spec_id"]), copy, score_id))
    return entries


def board_revision(http: httpx.Client, board_id: str) -> str | None:
    """The revision a board serves now, read from the public board list; None if it has none."""

    for board in _get(http, "/v1/benchmarks")["benchmarks"]:
        if board["id"] == board_id:
            revision: object = board.get("revision")
            return None if revision is None else str(revision)
    raise BoardReadError(f"no board {board_id!r} on this Scoreboard")


def _outcome(regrader: _Regrader, entry: Entry) -> dict[str, object]:
    """Re-grade one entry and say what happened, in the log's words; never raises an SDK error."""

    from screamingface.errors import ScreamingFaceError

    try:
        new = regrader.regrade(
            str(entry.score_id), expected_target_revision=TRANSITIONS[entry.benchmark_id]["target"]
        )
    except ScreamingFaceError as exc:
        if exc.code == "already_regraded":
            return _existing_result(regrader, entry, exc)
        return _refusal(exc)
    return _verified_result(new, entry, "regraded", getattr(new, "id", None))


def _existing_result(regrader: _Regrader, entry: Entry, exc: Any) -> dict[str, object]:
    from screamingface.errors import ScreamingFaceError

    existing = getattr(exc, "existing_score_id", None)
    if existing is None:
        return _invalid_result("already_regraded did not name an existing score")
    try:
        new = regrader.leaderboards._public_score(existing)
    except ScreamingFaceError as read_error:
        return _invalid_result(f"cannot verify existing score: {read_error.code}")
    return _verified_result(new, entry, "already_regraded", str(existing))


def _invalid_result(message: str) -> dict[str, object]:
    return {"outcome": "refused_retryable", "code": "regrade_result_mismatch", "message": message}


def _verified_result(new: Any, entry: Entry, outcome: str, score_id: Any) -> dict[str, object]:
    """Only evidence for this exact source/target transition can settle its journal entry."""
    if (
        score_id is None
        or not str(score_id).strip()
        or getattr(new, "benchmark_id", None) != entry.benchmark_id
        or getattr(new, "benchmark_revision", None) != TRANSITIONS[entry.benchmark_id]["target"]
        or str(getattr(new, "regraded_from", None)) != entry.score_id
        or (outcome == "already_regraded" and str(getattr(new, "score_id", None)) != score_id)
    ):
        return _invalid_result(
            "returned score does not prove the declared source/target transition"
        )
    return {"outcome": outcome, "new_score_id": str(score_id)}


def _refusal(exc: Any) -> dict[str, object]:
    """A refusal as a log record: permanent ones need owner action; retryable ones run again.

    WHY ``already_regraded`` is its own outcome: the board already holds this source's re-grade
    at this revision (a ``LeaderboardError`` naming it), so the entry moved and is settled.
    WHY ``already_current`` is never settled here: the board listed the entry as old, so an
    Engine answering that its revision is current is an Engine pod not yet updated (a rolling
    deploy). Settling it would skip the entry on every later run.
    """

    permanent: bool = exc.permanent is True and exc.code not in _RETRIED_ANYWAY
    return {
        "outcome": "refused_permanently" if permanent else "refused_retryable",
        "code": exc.code,
        "message": exc.message,
    }


def regrade_all(
    regrader: _Regrader,
    entries: Iterable[Entry],
    log_path: Path,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    resolutions: Mapping[str, str] | None = None,
    scope: str = "https://leaderboard.screamingface.ai",
) -> dict[str, int]:
    """Hold the log lock through replay; count unresolved outcomes across all runs."""
    counts: dict[str, int] = {}
    with locked_journal(log_path, scope.rstrip("/"), TRANSITIONS) as journal:
        journal.resolve(resolutions or {}, now().isoformat())
        for entry in entries:
            journal.check_current()
            transition = TRANSITIONS.get(entry.benchmark_id)
            if transition is None or entry.revision != transition["source"]:
                raise LogError(f"entry outside OME-1958 source transitions: {entry}")
            record: dict[str, Any] = {
                "at": now().isoformat(),
                "benchmark_id": entry.benchmark_id,
                "revision": entry.revision,
                "target_revision": transition["target"],
                "spec_id": entry.spec_id,
                "source_score_id": entry.score_id,
            }
            key = entry_key(record)
            previous = journal.records.get(key)
            if previous and previous["outcome"] in NO_RETRY:
                counts["skipped"] = counts.get("skipped", 0) + 1
                continue
            record.update(
                {"outcome": "no_pinned_cache"}
                if entry.score_id is None
                else _outcome(regrader, entry)
            )
            journal.append(record)
            outcome = str(record["outcome"])
            counts[outcome] = counts.get(outcome, 0) + 1
            print(f"{outcome:<20} {key} {record.get('code', '')}")
        unresolved = [r for r in journal.records.values() if r["outcome"] not in RESOLVED]
        counts["unresolved"] = len(unresolved)
        for record in unresolved:
            print(f"unresolved {record['entry_key']}: {record['outcome']}")
    return counts


def exit_status(counts: Mapping[str, int]) -> int:
    """Not retrying an entry does not mean its owner work is complete."""
    return _EXIT_SOME_REFUSED if counts.get("unresolved") else _EXIT_OK


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the command line."""

    parser = argparse.ArgumentParser(description="Re-grade the 47 declared OME-1958 transitions.")
    parser.add_argument("--apply", action="store_true", help="re-grade; without it, list only")
    parser.add_argument(
        "--benchmark", action="append", default=[], help="a board id; repeat for several"
    )
    parser.add_argument("--log", type=Path, default=Path("regrade-log.jsonl"))
    parser.add_argument("--engine-url", default=None, help="default: the SDK's")
    parser.add_argument("--scoreboard-url", default=None, help="default: the SDK's")
    parser.add_argument(
        "--when-revision",
        default=None,
        metavar="BOARD=REVISION",
        help="do nothing until BOARD serves REVISION (for a scheduled run)",
    )
    parser.add_argument(
        "--resolve",
        action="append",
        default=[],
        metavar="ENTRY_KEY=NOTE",
        help="record an owner decision in the log, without re-grading",
    )
    args = parser.parse_args(argv)
    # INVARIANT: an apply override must not silently leave the other service in production.
    if args.apply and ((args.engine_url is None) != (args.scoreboard_url is None)):
        parser.error("--apply overrides require both --engine-url and --scoreboard-url")
    unknown = set(args.benchmark) - TRANSITIONS.keys()
    if unknown:
        parser.error(f"unknown OME-1958 boards: {sorted(unknown)}")
    if args.when_revision:
        board, sep, target = args.when_revision.partition("=")
        if (
            not sep
            or board not in TRANSITIONS
            or target != TRANSITIONS[board]["target"]
            or (args.benchmark and board not in args.benchmark)
        ):
            parser.error("--when-revision must name a selected OME-1958 board and its exact target")
    if args.resolve and (args.apply or args.when_revision or args.benchmark):
        parser.error("--resolve is a separate log-only operation")
    for value in args.resolve:
        key, sep, note = value.partition("=")
        if not key or not sep or not note.strip():
            parser.error("--resolve requires ENTRY_KEY=NOTE")
    return args


def main(argv: Sequence[str]) -> int:
    """List the entries to move; with ``--apply``, re-grade them and print the tally."""

    import screamingface as sf

    args: argparse.Namespace = _arguments(argv)
    endpoints = {"engine_url": args.engine_url, "scoreboard_url": args.scoreboard_url}
    endpoints = {name: value for name, value in endpoints.items() if value is not None}
    client = sf.Client(**endpoints)
    if args.resolve:
        counts = regrade_all(
            client,
            [],
            args.log,
            scope=client.scoreboard_url,
            resolutions=dict(value.split("=", 1) for value in args.resolve),
        )
        return exit_status(counts)
    return _run(client, args)


def _run(client: Any, args: argparse.Namespace) -> int:
    """Preview or execute the selected batch after its deployment guard passes."""
    with httpx.Client(base_url=client.scoreboard_url, timeout=_TIMEOUT_S) as http:
        if args.when_revision:
            # WHY a guard: before the deploy the old entries are still current, so a scheduled
            # run waits here instead of logging a refusal per entry every half hour.
            board_id, _, wanted = str(args.when_revision).partition("=")
            served: str | None = board_revision(http, board_id)
            if served not in {TRANSITIONS[board_id]["source"], wanted}:
                raise BoardReadError(f"{board_id}: unexpected revision {served}")
            if served != wanted:
                print(f"waiting: {board_id} serves {served}, not {wanted}")
                counts = (
                    regrade_all(client, [], args.log, scope=client.scoreboard_url)
                    if args.apply and args.log.exists()
                    else {}
                )
                return exit_status(counts)
        entries: list[Entry] = find_entries(http, args.benchmark)
    for entry in entries:
        print(f"{entry.benchmark_id} {entry.revision} {entry.spec_id} {entry.score_id or '-'}")
    print(
        f"{len(entries)} entries on older revisions, {sum(e.score_id is None for e in entries)} "
        "with no pinned cache"
    )
    if not args.apply:
        return _EXIT_OK
    if not client.authenticated:
        client.login()
    counts = regrade_all(client, entries, args.log, scope=client.scoreboard_url)
    print(json.dumps(counts, sort_keys=True))
    return exit_status(counts)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (BoardReadError, LogError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
