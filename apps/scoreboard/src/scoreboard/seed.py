from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from .config import Settings
from .db import close_db, init_db
from .scores.schemas import BenchmarkSchema, Visibility
from .scores.store import ScoreStore

SEED_BENCHMARKS_ENV = "SCOREBOARD_SEED_BENCHMARKS_JSON"
# FEATURE: benchmark descriptions on the leaderboard (OME-904). The Engine's benchmark
# definitions are the ONLY place a benchmark's prose is written; this deployment names which
# Engine to ask, and nothing else. A values override can therefore change the Engine consulted
# but can no longer carry, alter, or omit the text itself.
ENGINE_URL_ENV = "SCOREBOARD_SEED_ENGINE_URL"
_CATALOG_PATH = "/v1/benchmarks"
# The catalogue is a small static document behind an ETag; a deploy hook should not hang on it.
_FETCH_TIMEOUT_SECONDS = 15.0
# WHY retry at all: an unreachable Engine is survivable and exits zero, which means Kubernetes
# never retries this Job — `backoffLimit` only fires on a non-zero exit. A Helm upgrade that
# rolls Scoreboard and Engine together can land this single GET inside the Engine's restart
# window, and without an in-process retry that release's benchmark changes silently miss the
# board until somebody deploys again.
_FETCH_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0


class EngineCatalogUnavailable(RuntimeError):
    """The Engine benchmark catalogue could not be read.

    INVARIANT: every transport, status, and payload failure surfaces as this one type. No
    `httpx` or `json` exception escapes this module, so a deploy log names the thing that
    failed rather than leaking a library's internals.
    """


class SeedBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    dataset_url: str | None = None
    # INVARIANT: must match the Engine benchmark's computed REVISION exactly — a submission
    # carries the Engine's value, and the two are compared for comparability (OME-775).
    # Optional because the retained legacy demo entries have no Engine revision.
    revision: str | None = Field(default=None, max_length=64)
    # OME-894: `private` keeps a benchmark listed in the catalogue but scopes every score-bearing
    # read path to the caller.
    # INVARIANT: None means "not stated in configuration", NOT "public". An omitted key must leave
    # a live board's visibility alone — writing "public" here would let a routine deploy un-private
    # a running challenge, which is exactly what happened before this was found in review.
    visibility: Visibility | None = None
    # Short editorial line for the portal catalogue's "Focus" column (OME-874). Optional: it is
    # copy someone writes, not a value the Engine derives.
    focus: str | None = Field(default=None, max_length=120)


class _CatalogEntry(BaseModel):
    """One benchmark as the Engine publishes it at ``GET /v1/benchmarks``.

    AIDEV-NOTE: this is one half of a cross-app contract that no single test can run, because
    the two apps have separate virtualenvs and neither may import the other. The producer half
    is pinned by ``test_the_catalog_keeps_the_field_names_the_leaderboard_seeds_from`` in
    apps/screamingface-engine — rename a field here or there and BOTH must change together, in
    one pull request. ``tests/fixtures/engine_catalog.json`` is a recorded real response that
    keeps this side honest between such changes.

    AIDEV-NOTE: ``extra="ignore"`` deliberately, opposite to :class:`SeedBenchmark`'s
    ``extra="forbid"``. A configured entry is written by hand here, so a typo must fail the
    deploy; the catalogue is written by another service that will keep growing fields
    (``case_count``, ``href``, ``check_surface``, whatever comes next), and a board that
    refuses to seed because the Engine added a field is a board that breaks on someone else's
    release. Read the fields the board displays; ignore the rest.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    # WHY optional here while the Engine requires it: rejecting an entry costs the benchmark
    # its whole ROW — no board entry, and a submission against it refused — which is a far
    # bigger failure than a row that reads plain (owner decision, 2026-08-20). The Engine
    # already refuses to define a benchmark without a description, so requiring it again here
    # buys nothing and can only turn missing text into a missing benchmark. Require it where
    # it is written; tolerate it where it is read.
    #
    # INVARIANT: blank normalizes to None, never to a placeholder sentence. The reader-facing
    # wording lives in the client that renders it (`leaderboard_view.py` prints "No description
    # published." for an absent one) — prose written into this database could never be told
    # apart from prose an author actually wrote.
    description: str | None = None
    revision: str = Field(min_length=1, max_length=64)
    focus: str | None = Field(default=None, max_length=120)
    dataset_url: str | None = None

    @field_validator("description", "focus", mode="after")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """Treat whitespace-only display text as absent, so the client's fallback renders."""

        return value if value is not None and value.strip() else None

    def as_seed(self) -> SeedBenchmark:
        # The Engine calls it `title`; this board's column is `display_name`. One mapping site.
        return SeedBenchmark(
            id=self.id,
            display_name=self.title,
            description=self.description,
            dataset_url=self.dataset_url,
            revision=self.revision,
            focus=self.focus,
        )


class _Catalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[object]


@dataclass(slots=True)
class CatalogRead:
    """One catalogue response, split into what this board can use and what it cannot."""

    rows: list[SeedBenchmark] = field(default_factory=list)
    """Entries this board can register, in the Engine's own order."""

    rejected: list[str] = field(default_factory=list)
    """Entries the board could not read — reported rather than silently dropped."""


@dataclass(slots=True)
class SeedReport:
    """What one seeding pass did, in the terms the deploy log and its exit code need."""

    seeded: list[BenchmarkSchema] = field(default_factory=list)
    """Rows written this pass, Engine-published first."""

    shadowed: list[str] = field(default_factory=list)
    """Configured ids the Engine also publishes; the configured copy was ignored."""

    refused: list[str] = field(default_factory=list)
    """Configured ids not written at all, because writing them could undo an Engine seed."""

    rejected: list[str] = field(default_factory=list)
    """Catalogue entries the board could not read."""

    engine_error: str | None = None
    """Why the catalogue could not be read, when it could not."""

    bootstrap_failed: bool = False
    """The catalogue was unreadable AND this board has never been seeded from one."""


def fetch_engine_benchmarks(
    engine_url: str,
    *,
    client: httpx.Client | None = None,
    attempts: int = _FETCH_ATTEMPTS,
    retry_delay: float = _RETRY_DELAY_SECONDS,
) -> CatalogRead:
    """Read the Engine's benchmark catalogue and return it as rows this board can register.

    Think of it as copying a menu from the kitchen that cooks the food, rather than retyping it
    at the front desk: the Engine defines each benchmark and writes the words describing it,
    and this function carries those words across unchanged.

    Stage 1 — address the catalogue: ``{engine_url}/v1/benchmarks``. Public and read-only, so
    the seed job holds no Engine credential.
    Stage 2 — fetch it, following redirects, retrying only what a retry can fix: a transport
    failure or a 5xx. A 4xx will not become a 200 by asking again, and neither will a mangled
    body, so both fail immediately.
    Stage 3 — read the envelope, then each entry INDEPENDENTLY. One unusable entry is reported
    and skipped; it does not reject its siblings. Refusing the batch would mean every untouched
    benchmark silently keeps its old text because one of them outgrew a column.
    Stage 4 — map each usable entry onto a seed row, renaming ``title`` to ``display_name``.

    Worked example: a catalogue of two entries where DRACO carries a 200-character focus line
    (the board stores 120) returns ``rows=[ifeval]`` and ``rejected=["draco"]`` — IFEval's text
    still refreshes, and DRACO's problem is named in the deploy log rather than swallowed.

    Args:
        engine_url: origin of the Engine to ask, with or without a trailing slash.
        client: an HTTP client to use instead of opening one — the injection seam the tests
            drive; production passes nothing and gets a timeout-bounded client.
        attempts: how many times to ask before calling the Engine unreachable.
        retry_delay: seconds to wait between attempts.

    Returns:
        A :class:`CatalogRead` holding the usable rows and the ids of any unusable entries.

    Raises:
        EngineCatalogUnavailable: the catalogue could not be reached, answered an error status,
            or was not a readable catalogue document at all.

    AIDEV-NOTE: this is SYNCHRONOUS on purpose and blocks its caller — `httpx.Client` plus
    `time.sleep`, up to roughly 49s worst case (3 attempts x 15s timeout + 2 x 2s backoff).
    That is harmless in the one-shot seed Job it was written for, where nothing else shares the
    event loop, but `seed_from_sources` is `async` and could tempt a caller into running this
    from a live server. Do not: convert to `httpx.AsyncClient` first.
    """

    url = engine_url.rstrip("/") + _CATALOG_PATH
    http = client if client is not None else httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS)
    try:
        payload = _read_catalog(http, url, attempts=attempts, retry_delay=retry_delay)
    finally:
        if client is None:
            http.close()

    try:
        entries = _Catalog.model_validate(payload).data
    except ValidationError as exc:
        raise EngineCatalogUnavailable(f"{url} answered an unreadable catalog: {exc}") from exc

    read = CatalogRead()
    for position, entry in enumerate(entries):
        try:
            read.rows.append(_CatalogEntry.model_validate(entry).as_seed())
        except ValidationError:
            read.rejected.append(_entry_label(entry, position))
    return read


def _unreadable_body(url: str, response: httpx.Response, exc: Exception) -> str:
    """Explain a 200 that is not JSON, naming the cause an operator is most likely hitting.

    WHY this is worth a function: the obvious address to put in ``engineUrl`` is the Engine's
    PUBLIC hostname, and that host sits behind Cloudflare Access, which answers **200 with an
    HTML sign-in page**. Every layer below then behaves correctly — the status check passes,
    the parse fails, the failure is survivable, the job exits zero — and the feature is
    silently off. This message is the only thing between an operator and a long afternoon.
    """

    content_type = response.headers.get("content-type", "unknown")
    detail = f"{url} answered content-type {content_type} instead of JSON ({exc})"
    if "html" in content_type.lower():
        return (
            f"{detail}. A public hostname behind an authentication proxy answers 200 with a "
            "sign-in page: engineUrl must name the in-cluster Engine address, not the public one."
        )
    return detail


def _entry_label(entry: object, position: int) -> str:
    """Name an unusable entry the way a human reading the deploy log would look for it."""

    if isinstance(entry, dict):
        identifier = entry.get("id")
        if isinstance(identifier, str) and identifier:
            return identifier
    return f"entry #{position}"


def _read_catalog(
    http: httpx.Client,
    url: str,
    *,
    attempts: int,
    retry_delay: float,
) -> object:
    """Fetch and decode the catalogue document, retrying only what a retry can fix."""

    unreachable: EngineCatalogUnavailable | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            # WHY follow_redirects: httpx defaults to False, so an ordinary http->https or
            # trailing-slash redirect at the ingress would be reported as a permanent outage and
            # the board would never update again.
            response = http.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            unreachable = EngineCatalogUnavailable(f"{url} answered HTTP {status}")
            if status < 500:
                raise unreachable from exc
        except httpx.HTTPError as exc:
            unreachable = EngineCatalogUnavailable(f"{url} could not be reached: {exc}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # INVARIANT: BOTH belong here. `.json()` raises UnicodeDecodeError on a body that is
            # not valid UTF-8, and both types are ValueErrors — an uncaught one used to surface
            # from the CLI as a command-line usage error, blaming the operator's arguments for a
            # mangled Engine response.
            raise EngineCatalogUnavailable(_unreadable_body(url, response, exc)) from exc
        if attempt < attempts:
            time.sleep(retry_delay)
    raise (
        unreachable
        if unreachable is not None
        else EngineCatalogUnavailable(f"{url} was never asked")
    )


def _classify_configured(
    configured: Sequence[SeedBenchmark],
    published: set[str],
    engine_owned: set[str],
    report: SeedReport,
) -> list[SeedBenchmark]:
    """Split configured rows into the ones this pass may seed, recording why the rest were not.

    Shadowed: the Engine publishes this id, so its text wins (OME-904). Refused: the row claims an
    Engine benchmark this pass did not read from the Engine, which would let chart values
    impersonate published prose. Everything else is deployment-owned and seeded as given.
    """
    allowed: list[SeedBenchmark] = []
    for row in configured:
        if row.id in published:
            report.shadowed.append(row.id)
        elif row.revision is not None or row.id in engine_owned:
            report.refused.append(row.id)
        else:
            allowed.append(row)
    report.shadowed.sort()
    report.refused.sort()
    return allowed


def _with_configured_visibility(
    published_rows: Sequence[SeedBenchmark], configured: Sequence[SeedBenchmark]
) -> list[SeedBenchmark]:
    """Lift a deployment-declared `visibility` onto the Engine's published row.

    FEATURE: OME-894 — the entry challenge is Engine-published, and the Engine publishes no
    `visibility` because it is a Scoreboard concern, not an Engine one. A published row is
    otherwise shadowed wholesale, so without this the challenge could never be made private at
    all, and a board flipped by hand would be reset to public by the next deploy.

    INVARIANT: only `visibility` crosses over. The Engine stays the sole authority for every word
    of a benchmark's text (OME-904); this does not reopen chart-authored prose.
    """
    declared = {row.id: row.visibility for row in configured if row.visibility is not None}
    return [
        row.model_copy(update={"visibility": declared[row.id]}) if row.id in declared else row
        for row in published_rows
    ]


async def seed_from_sources(
    *,
    engine_url: str | None,
    configured: Sequence[SeedBenchmark],
    engine_rows: Sequence[SeedBenchmark] | None = None,
    client: httpx.Client | None = None,
    retry_delay: float = _RETRY_DELAY_SECONDS,
) -> SeedReport:
    """Register every benchmark this board should show, with the Engine as the only copy.

    Think of it as a merge with a fixed winner: whatever the Engine publishes is the truth, and
    configuration may only fill gaps the Engine leaves. The subtle part is what happens when
    the Engine says nothing — because "the Engine wins" is vacuous when there is nothing to
    win with, and that is exactly when stale configuration would walk back in.

    Stage 1 — ask whether this board has ever been seeded from a catalogue, BEFORE writing
    anything. Reading this afterwards would let the pass count its own writes and call an empty
    board healthy.
    Stage 2 — obtain the Engine's catalogue. There are two adapters for the same thing: a
    deployment fetches it over HTTP, and a local stack — where the board and the Engine share
    one virtualenv — hands its imported registry straight in as ``engine_rows``. Either way
    those rows are Engine-owned. A fetch failure is recorded, not raised: re-seeding refreshes
    a populated board, so failing a Scoreboard deploy on an unrelated service's health would
    cost availability and buy nothing.
    Stage 3 — decide what configuration is allowed to write. Two entries are refused outright:
    one asserting a ``revision`` the Engine did not publish in this same pass (a revision is
    the Engine's claim about its own benchmark, and configuration restating it is the second
    copy this ticket deletes), and one whose id names an existing Engine-owned row (any row
    carrying a revision). Without this, one transient Engine blip would let the deploy's own
    stale entries overwrite good rows with null descriptions — OME-904 reproduced by its fix.
    Stage 4 — Engine rows win over any surviving configured entry sharing their id.
    Stage 5 — write every row through the same idempotent registration as before.
    Stage 6 — an unreadable catalogue was survivable unless Stage 1 found no seeded row at all.

    Worked example: the Engine is down, and configuration still lists draco (revision
    ``1c58b30…``, no description) plus hle (no revision). draco is refused twice over — it
    asserts a revision, and it names an Engine-owned row — so the good draco row keeps its
    text; hle is written; the pass exits zero because Stage 1 saw a seeded row.

    Args:
        engine_url: the Engine to read, or None for a deployment that runs without one.
        configured: entries from deployment configuration — the retained legacy demos, plus
            anything the Engine does not publish.
        engine_rows: the Engine's benchmarks supplied directly, for a caller that already has
            the registry in process. Given these, nothing is fetched and ``engine_url`` is
            unused. Passing registry rows as ``configured`` instead would be a bug: they carry
            revisions, so the Stage 3 refusal would reject every one of them.
        client: an HTTP client to use instead of opening one (see
            :func:`fetch_engine_benchmarks`).
        retry_delay: seconds between catalogue attempts (see
            :func:`fetch_engine_benchmarks`).

    Returns:
        A :class:`SeedReport`; ``bootstrap_failed`` is the caller's non-zero exit signal, and
        ``refused``/``rejected`` are what the deploy log must show a human.
    """

    store = ScoreStore()
    # Stage 1 — read the prior state before this pass can contribute to it.
    seeded_before = await store.has_registered_revision()
    engine_owned = {row.id for row in await store.list_benchmarks() if row.revision is not None}

    report = SeedReport()
    published_rows: list[SeedBenchmark] = list(engine_rows) if engine_rows is not None else []
    if engine_rows is None and engine_url:
        try:
            read = fetch_engine_benchmarks(engine_url, client=client, retry_delay=retry_delay)
        except EngineCatalogUnavailable as exc:
            report.engine_error = str(exc)
        else:
            published_rows = read.rows
            report.rejected = read.rejected

    published_rows = _with_configured_visibility(published_rows, configured)

    allowed = _classify_configured(
        configured, {row.id for row in published_rows}, engine_owned, report
    )

    report.seeded = await seed_benchmarks([*published_rows, *allowed])
    report.bootstrap_failed = report.engine_error is not None and not seeded_before
    return report


_BENCHMARKS_ADAPTER = TypeAdapter(list[SeedBenchmark])


def load_benchmarks_json(raw_json: str) -> list[SeedBenchmark]:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid benchmark seed JSON: {exc.msg}") from exc

    try:
        return _BENCHMARKS_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid benchmark seed payload: {exc}") from exc


async def seed_benchmarks(benchmarks: Sequence[SeedBenchmark]) -> list[BenchmarkSchema]:
    store = ScoreStore()
    seeded: list[BenchmarkSchema] = []
    for benchmark in benchmarks:
        seeded.append(
            await store.register_benchmark(
                benchmark_id=benchmark.id,
                display_name=benchmark.display_name,
                description=benchmark.description,
                dataset_url=benchmark.dataset_url,
                revision=benchmark.revision,
                focus=benchmark.focus,
                visibility=benchmark.visibility,
            )
        )
    return seeded


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed scoreboard benchmark definitions.")
    parser.add_argument(
        "--benchmarks-json",
        default=None,
        help=f"JSON benchmark list. Defaults to ${SEED_BENCHMARKS_ENV}; empty list if unset.",
    )
    parser.add_argument(
        "--engine-url",
        default=None,
        help=(
            "Engine origin whose benchmark catalog supplies every published benchmark's text. "
            f"Defaults to ${ENGINE_URL_ENV}; omitted means seed configured entries only."
        ),
    )
    return parser


def _print_report(report: SeedReport) -> None:
    """Say what happened, in the terms an operator reading the deploy log needs."""

    for benchmark in report.seeded:
        print(f"seeded benchmark {benchmark.id}")
    for benchmark_id in report.shadowed:
        # Named rather than silent: an operator who added prose to the deploy values needs to
        # know it was ignored, and where the text they see actually comes from.
        print(f"ignored configured entry {benchmark_id}: the Engine publishes it")
    for benchmark_id in report.refused:
        print(
            f"REFUSED configured entry {benchmark_id}: it claims an Engine benchmark this run "
            "did not read from the Engine. Set seedBenchmarks.engineUrl, and keep revisions "
            "and descriptions out of deployment configuration."
        )
    for benchmark_id in report.rejected:
        print(f"REJECTED catalog entry {benchmark_id}: the board could not read it")
    if report.engine_error is not None:
        # WHY loud: this is the path where the feature is OFF. The deploy still succeeds and
        # the board still serves whatever it held, so nothing else here would tell anyone that
        # benchmark text just stopped being refreshed.
        print(f"WARNING engine catalog unavailable: {report.engine_error}")
        print(
            "WARNING benchmark text was NOT refreshed this deploy; the board is serving "
            "whatever the last successful seed wrote"
        )


async def _run(
    configured: Sequence[SeedBenchmark],
    engine_url: str | None,
    engine_rows: Sequence[SeedBenchmark] | None = None,
) -> int:
    if not configured and not engine_url and not engine_rows:
        print("no benchmarks configured")
        return 0

    settings = Settings()
    await init_db(settings.database_url)
    try:
        report = await seed_from_sources(
            engine_url=engine_url, configured=configured, engine_rows=engine_rows
        )
        _print_report(report)
        if report.bootstrap_failed:
            print("no benchmark carries an Engine revision: this board has never been seeded")
            return 1
    finally:
        await close_db()
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    raw_json = args.benchmarks_json or os.getenv(SEED_BENCHMARKS_ENV, "[]")
    engine_url = args.engine_url or os.getenv(ENGINE_URL_ENV) or None
    # WHY parse here rather than inside the run: `parser.error` must only ever describe a bad
    # argument. Wrapping the whole run in `except ValueError` swallowed unrelated ValueErrors
    # from deep inside it — a mangled Engine response surfaced as a command-line usage error.
    try:
        configured = load_benchmarks_json(raw_json)
    except ValueError as exc:
        parser.error(str(exc))
    exit_code = asyncio.run(_run(configured, engine_url))
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
