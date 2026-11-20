"""OME-1958: move every old leaderboard entry onto its Benchmark's new revision with a re-grade.

    uv run --isolated python scripts/regrade_batch.py                     # dry run: list only
    uv run --isolated python scripts/regrade_batch.py --apply             # re-grade and log
    uv run --isolated python scripts/regrade_batch.py --apply --benchmark inspect-mmlu_pro

Run from ``packages/screamingface``, after the bump is deployed and the board shows the new
revision. Think of it as a loop over what each board used to show: for every public board, the
entries still on an older revision are re-graded one by one with ``Client.regrade`` (OME-1909),
which replays the entry's pinned cache at no Candidate cost and posts a new entry credited to the
original submitter.

Stages, in the order they run:

1. Find the entries (``find_entries``), public reads only, no login: each board's revisions
   (``/v1/leaderboard/{id}/revisions``), then the board at every older revision
   (``?revision=``), then each row's score id from its pinned cache
   (``/v1/public/scores/by-pinned-cache/{copy}``). A row with no pinned cache cannot be
   re-graded; it is logged as ``no_pinned_cache`` for the owner to decide (a paid rerun).
2. Skip what an earlier run of this log already settled (``settled_ids``): a new entry, an
   ``already_regraded`` answer, or a permanent refusal. A crash or a Ctrl+C is fixed by running
   the same command again.
3. Re-grade each remaining entry (``regrade_all``) and append one JSON line per entry to the log.
   The SDK refuses, before any run and at no cost, an entry its Benchmark does not list in
   ``regradable_from`` (``not_regradable``: the Cases changed) or one that is already current.

Worked example: ``inspect-mmlu_pro`` moved from ``145edec84bfc2324`` to ``4efebd6cc74c2dca``.
Its board at ``145edec84bfc2324`` shows 3 rows: two with a pinned cache, one without. The dry
run lists 3 lines; ``--apply`` logs two ``regraded`` lines naming each new score id and one
``no_pinned_cache`` line naming the row's spec. Run again: both re-graded ids are settled, so
nothing is posted twice.

Every call of a re-grade, Candidate and judge, replays from the pinned cache, so the run makes
no model call. A Benchmark whose judge request changed misses on every judged Case and is
refused (``regrade_incomplete``); re-judging is OME-1979.

Exit status: 0 when every entry was re-graded or settled, 1 when any was refused or failed.
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

#: Rows per board page; the Scoreboard clamps any larger ``top`` to this (MAX_LEADERBOARD_TOP).
_TOP: int = 200
_TIMEOUT_S: float = 30.0
_EXIT_OK: int = 0
_EXIT_SOME_REFUSED: int = 1
#: Outcomes a later run never retries: the entry moved, or the SDK said it never will.
_SETTLED: frozenset[str] = frozenset({"regraded", "already_regraded", "refused_permanently"})
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

    def regrade(self, score_id: str) -> Any:
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
    """Every row each public board shows at a revision older than its current one (stage 1).

    ``benchmark_ids`` narrows the boards; empty means every board. A private board is skipped:
    the Scoreboard never re-grades a private score.
    """

    boards: list[Mapping[str, Any]] = _get(http, "/v1/benchmarks")["benchmarks"]
    wanted: set[str] = set(benchmark_ids)
    entries: list[Entry] = []
    for board in boards:
        board_id: str = str(board["id"])
        current: str | None = board.get("revision")
        if (wanted and board_id not in wanted) or current is None:
            continue
        if board.get("visibility") != "public":
            continue
        # WHY no 404 fallback: a public board always answers its revisions, so a 404 here means
        # a Scoreboard older than OME-1708; skipping would report "0 entries" and move nothing.
        revisions: list[Mapping[str, Any]] = _get(http, f"/v1/leaderboard/{board_id}/revisions")[
            "revisions"
        ]
        for summary in revisions:
            old: str = str(summary["revision"])
            if old == current or not summary.get("result_count"):
                continue
            page: Mapping[str, Any] = _get(
                http, f"/v1/leaderboard/{board_id}", revision=old, top=_TOP
            )
            for row in page["entries"]:
                copy: str | None = row.get("pinned_cache")
                score_id: str | None = (
                    str(_get(http, f"/v1/public/scores/by-pinned-cache/{copy}")["score_id"])
                    if copy
                    else None
                )
                entries.append(Entry(board_id, old, str(row["spec_id"]), copy, score_id))
    return entries


def settled_ids(log_path: Path) -> set[str]:
    """The source score ids an earlier run of this log already settled (stage 2)."""

    if not log_path.exists():
        return set()
    settled: set[str] = set()
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        record: Mapping[str, Any] = json.loads(line)
        if record.get("outcome") in _SETTLED and record.get("source_score_id"):
            settled.add(str(record["source_score_id"]))
    return settled


def _outcome(regrader: _Regrader, entry: Entry) -> dict[str, object]:
    """Re-grade one entry and say what happened, in the log's words; never raises an SDK error."""

    from screamingface.errors import ScreamingFaceError

    try:
        new = regrader.regrade(str(entry.score_id))
    except ScreamingFaceError as exc:
        return _refusal(exc)
    return {"outcome": "regraded", "new_score_id": str(new.id)}


def _refusal(exc: Any) -> dict[str, object]:
    """A refusal as a log record: permanent ones are settled, retryable ones run again.

    WHY ``already_regraded`` is its own outcome: the board already holds this source's re-grade
    at this revision (a ``LeaderboardError`` naming it), so the entry moved and is settled.
    WHY ``already_current`` is never settled here: the board listed the entry as old, so an
    Engine answering that its revision is current is an Engine pod not yet updated (a rolling
    deploy). Settling it would skip the entry on every later run.
    """

    if exc.code == "already_regraded":
        return {"outcome": "already_regraded", "new_score_id": str(exc.existing_score_id)}
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
) -> dict[str, int]:
    """Re-grade every entry not yet settled and append one log line each (stages 2-3).

    Returns how many entries ended in each outcome this run, ``skipped`` included.
    """

    settled: set[str] = settled_ids(log_path)
    counts: dict[str, int] = {}
    with log_path.open("a") as log:
        for entry in entries:
            record: dict[str, object] = {
                "at": now().isoformat(),
                "benchmark_id": entry.benchmark_id,
                "revision": entry.revision,
                "spec_id": entry.spec_id,
                "source_score_id": entry.score_id,
            }
            if entry.score_id is None:
                record["outcome"] = "no_pinned_cache"
            elif entry.score_id in settled:
                counts["skipped"] = counts.get("skipped", 0) + 1
                continue
            else:
                record.update(_outcome(regrader, entry))
            outcome: str = str(record["outcome"])
            counts[outcome] = counts.get(outcome, 0) + 1
            log.write(json.dumps(record) + "\n")
            log.flush()
            print(f"{outcome:<20} {entry.benchmark_id} {entry.spec_id} {record.get('code', '')}")
    return counts


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the command line."""

    parser = argparse.ArgumentParser(description="Re-grade every old leaderboard entry (OME-1958).")
    parser.add_argument("--apply", action="store_true", help="re-grade; without it, list only")
    parser.add_argument(
        "--benchmark", action="append", default=[], help="a board id; repeat for several"
    )
    parser.add_argument("--log", type=Path, default=Path("regrade-log.jsonl"))
    parser.add_argument("--scoreboard-url", default=None, help="default: the SDK's")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    """List the entries to move; with ``--apply``, re-grade them and print the tally."""

    import screamingface as sf

    args: argparse.Namespace = _arguments(argv)
    client = sf.Client(**({"scoreboard_url": args.scoreboard_url} if args.scoreboard_url else {}))
    with httpx.Client(base_url=client.scoreboard_url, timeout=_TIMEOUT_S) as http:
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
    counts: dict[str, int] = regrade_all(client, entries, args.log)
    print(json.dumps(counts, sort_keys=True))
    failed: int = sum(n for name, n in counts.items() if name.startswith("refused"))
    return _EXIT_SOME_REFUSED if failed else _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
