"""`report-intake queue …` — the drain path for the queue `QueueSink` fills.

**The `reports` table is the queue** (spec §9): a row marked `queued` means an agent will file it
through MCP during triage. Until this module there was nothing that could name those rows.
`cli.py` ran uvicorn and stopped, spec §1 removed `GET /v1/reports/{ref}`, and plan §13's
verification step — "confirm `queue list` shows it, file it via MCP" — described a command that
did not exist. A queued report was findable by grepping pod logs or opening the database.

**This is cluster-internal tooling, reached by `kubectl exec`, and it is deliberately NOT an HTTP
surface.** The endpoint spec §1 removed was removed on its merits — an unauthenticated service
with a by-ref read is a service whose refs are worth guessing — and a route added here under a
different name would be that same endpoint. The rule is enforced rather than remembered:
`tests/unit/test_triage_read_containment.py` fails if anything under `routes/` names one of the
store's three triage reads.

Three rules shape the output.

**Every value in the table is client-controlled, so every cell is flattened through
`render.one_line`.** A `trace_id` carrying a newline would otherwise end its row and print the
rest as a second one — a report forged into the listing an agent triages from, which is
`render.py`'s Markdown problem with a different renderer. Escape sequences are already gone by
this point: `bind()` control-strips the payload at intake (§2.4) and keeps only tab and newline,
both of which the flattener collapses.

**`show` prints the ticket body VERBATIM or not at all**, and that is the one place nothing is
reshaped. The body is what an agent pastes into Linear, so it has to be the body the sink would
have sent — byte for byte, rendered by `render_ticket` from the stored payload exactly as
`retry.py` re-renders it. The header block above it is fixed-width labels whose values are one
line by construction, so "the body is everything after the first blank line" is a property a
caller can rely on. What it must NEVER do is soften a body: a body that fails
`dispatch.content_in` is refused outright rather than redacted, because this command is the second
road from a stored report into a Linear ticket and the sink already refused to drive the first
(see `_printable`). Verbatim-or-refused, never verbatim-ish.

**stdout is the data; stderr is the commentary.** The table, and only the table, goes to stdout.
Counts, the "there may be more" note, and every refusal go to stderr, so `queue list | grep` sees
rows rather than prose.

There is no environment guard here and none is needed: this command runs inside a container whose
server process already refused to start on a `REPORT_INTAKE_*` name matching no `Settings` field
(`main._reject_unknown_environment`). A pod an operator can `exec` into is a pod that passed it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any, NamedTuple

from pydantic import ValidationError
from tortoise.exceptions import BaseORMException

from .config import Settings
from .db import close_db, init_db
from .delivery.dispatch import content_in
from .delivery.ports import TicketContent
from .delivery.render import one_line, render_ticket
from .reports.models.report import (
    REF_MAX_LENGTH,
    TICKET_ID_MAX_LENGTH,
    TICKET_URL_MAX_LENGTH,
)
from .reports.pipeline import StorageUnavailable
from .reports.schema import ReportDocument
from .reports.store import ReportStore, TriageReport

DEFAULT_LIMIT = 20
"""How many rows `queue list` shows when nobody says. Matches `retry.BATCH_LIMIT` — not because
the two are related, but because both answer "how much of this queue fits in front of one reader
at once", and one number is easier to hold than two."""

EXIT_OK = 0
EXIT_REFUSED = 1
"""The command was understood and answered no: no such `ref`, an unreadable payload, a ticket
already recorded. A fact about the data, distinguishable from both of the codes below."""
EXIT_STORAGE = 3
"""The database would not answer. Not `1`, because a script retrying a transient outage must not
also retry a mistyped `ref`; not `2`, which is argparse's own for a usage error."""

_UNREACHABLE = (StorageUnavailable, BaseORMException, OSError)
"""Everything that means "the database would not answer", from BOTH sides of the connection.

`StorageUnavailable` is what `ReportStore` raises once a connection exists. The other two are what
OPENING one raises, which the store never sees: an unreachable Postgres host is asyncpg's
`ConnectionRefusedError` or `socket.gaierror` (both `OSError`), and a sqlite file that cannot be
opened is a `BaseORMException`. Named as one tuple so `EXIT_STORAGE` cannot come to mean "the
database answered badly" while "the database was never reached" quietly keeps `EXIT_REFUSED`.
"""

_ABSENT = "-"
"""A field the report did not carry. Rendered rather than left blank, so every column keeps a
value at its own offset and a row cannot look like it has fewer cells than it has."""

_UNREADABLE = "?"
"""A field that lives in the payload, on a row whose payload no longer validates. The row still
appears: it is still awaiting triage, and a listing that silently dropped it would leave the one
report needing a human the only one nobody can see."""


class _Column(NamedTuple):
    heading: str
    limit: int
    """The widest this cell may print. It binds only on a pathological value — the column is
    otherwise sized to its own content, so a listing with no `reply_to` does not reserve 320
    characters for one."""


_COLUMNS = (
    _Column("REF", REF_MAX_LENGTH),
    _Column("OCCURRED AT", 25),
    _Column("ERROR", 48),
    _Column("TRACE ID", 32),
    _Column("REPLY TO", 40),
    _Column("MESH CALLER", 40),
)
"""Plan §13's listing, in the order a triager reads it. The last two are two different things and
are labelled so nobody merges them: `REPLY TO` is whatever the reporter typed, `MESH CALLER` is
what the mesh verified — the same distinction `render.py`'s `Reporter` section draws."""

_SEPARATOR = "  "
"""Two spaces, and that is load-bearing: `one_line` collapses every run of whitespace inside a
cell to a single space, so a run of two is always a column boundary and never part of a value."""


def list_queued(args: argparse.Namespace) -> int:
    """`queue list` — the reports awaiting triage."""
    return _with_store(lambda store: _print_queue(store, args.limit))


def show(args: argparse.Namespace) -> int:
    """`queue show <ref>` — the ticket an agent files."""
    return _with_store(lambda store: _print_ticket(store, args.ref))


def mark_filed(args: argparse.Namespace) -> int:
    """`queue mark-filed <ref> --ticket-id … --ticket-url …` — the row is somebody's now.

    The two flags are checked BEFORE the database is opened: an unusable ticket reference is a
    fact about the command line and needs no row to establish, so a typo costs a connection to
    nothing.
    """
    ref, ticket_id, ticket_url = args.ref, args.ticket_id, args.ticket_url
    refusal = _ticket_argument("--ticket-id", ticket_id, TICKET_ID_MAX_LENGTH) or _ticket_argument(
        "--ticket-url", ticket_url, TICKET_URL_MAX_LENGTH
    )
    if refusal is not None:
        return _refused(refusal, EXIT_REFUSED)
    return _with_store(lambda store: _record_filed(store, ref, ticket_id, ticket_url))


def positive(value: str) -> int:
    """`--limit`'s type. A zero or negative limit is a listing that shows nothing, which reads
    exactly like an empty queue — so it is refused as a usage error instead."""
    limit = int(value)
    if limit < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, not {limit}")
    return limit


def _with_store(work: Callable[[ReportStore], Awaitable[int]]) -> int:
    """Open the database, run one command against a `ReportStore`, close it again.

    The store is constructed with the same two windows `create_app` gives it, though neither
    command reads one — a store built with a different idempotency TTL is a store that would
    behave differently if a future command ever recorded anything, and there is no reason for the
    console's to differ from the service's.

    **Migrations are not applied here**, for the same reason the service does not apply them: the
    schema is `tortoise migrate`'s to run. A console session that quietly migrated a database
    would be one replica doing DDL while the others serve.
    """
    settings = Settings()
    return asyncio.run(_inside_database(settings, work))


async def _inside_database(
    settings: Settings, work: Callable[[ReportStore], Awaitable[int]]
) -> int:
    store = ReportStore(
        idempotency_ttl=timedelta(hours=settings.idempotency_ttl_h),
        retention=timedelta(days=settings.retention_days),
    )
    try:
        # `init_db` IS INSIDE THE GUARD, and that placement is the whole of `EXIT_STORAGE`'s
        # promise. Outside it, a database that cannot be reached escaped as a traceback and
        # Python's default exit code `1` — which is `EXIT_REFUSED`, the code a mistyped `ref`
        # gets. DEPLOYMENT.md tells operators only `3` is worth retrying, and unreachable-database
        # is the outage every deployed install actually meets: `values.yaml` calls the sqlite
        # default a smoke test, so the real connection is a Postgres URL over the network.
        await init_db(settings.database_url)
        return await work(store)
    except _UNREACHABLE as exc:
        # `OSError` is what an unreachable host raises before tortoise has anything to say —
        # asyncpg surfaces `ConnectionRefusedError` and a bad hostname surfaces `socket.gaierror`,
        # both of which are `OSError` and neither of which is a `BaseORMException`. `sqlite3`'s
        # "unable to open database file" arrives as a `BaseORMException`. All three are the same
        # answer to an operator: the database would not answer, so try again.
        return _refused(f"{exc}. The service reports this as a 503; try again.", EXIT_STORAGE)
    finally:
        # Safe after a failed `init_db`: `Tortoise.close_connections` walks a connection map that
        # is empty when nothing was ever opened.
        await close_db()


async def _print_queue(store: ReportStore, limit: int) -> int:
    rows = await store.awaiting_triage(limit=limit)
    if not rows:
        return _note("no reports are awaiting triage")
    for line in _table(rows):
        print(line)
    if len(rows) == limit:
        return _note(f"showing the newest {limit}; there may be more — raise --limit")
    return _note(f"{len(rows)} report(s) awaiting triage")


async def _print_ticket(store: ReportStore, ref: str) -> int:
    row = await store.read_for_triage(ref)
    if row is None:
        return _refused(_no_such_report(ref), EXIT_REFUSED)
    printable = _printable(row)
    if isinstance(printable, str):
        return _refused(printable, EXIT_REFUSED)
    # Every header value is one line by construction — `ref` is server-minted, `state` is one of
    # four literals, `title` is collapsed by `render._title`, and a ticket only reaches the
    # columns through `_ticket_argument` — so the blank line below is unambiguous.
    print(f"ref:    {printable.ref}")
    print(f"state:  {row.delivery_state}")
    if row.ticket_id is not None and row.ticket_url is not None:
        print(f"ticket: {row.ticket_id} {row.ticket_url}")
    print(f"title:  {printable.title}")
    print()
    print(printable.body)
    return EXIT_OK


def _printable(row: TriageReport) -> TicketContent | str:
    """The ticket this row renders to, or — as a string — the reason it must not be printed.

    Two refusals, and the second is the one this function exists for.

    A payload that no longer validates has no ticket to render at all. `render_ticket` reads named
    attributes off a `ReportDocument`, so there is nothing to print and nothing to paste.

    A body that carries CONTENT must not be printed even though it renders perfectly.
    `delivery/dispatch.py` runs `content_in` on this exact string before handing it to a sink, and
    a hit there marks the row `failed` and sends nothing. `queue show` is the OTHER path from a
    stored report to a ticket body — the module docstring calls the output "what an agent pastes
    into Linear" — so skipping the check here would walk a refused body into the ticket the check
    exists to keep it out of, by hand, with nothing on the output saying the service had already
    refused to send it. The route's own classifier cannot stand in for this: `classify_report` is
    scoped by JSON pointer and a marker can exist only once two innocent fields are RENDERED next
    to each other, which is the one form of a report the route never sees.

    The dispatcher's function is CALLED rather than re-implemented (`dispatch.content_in`): two
    spellings of one fail-closed check are two things to keep in step.
    """
    document = _document(row.payload)
    if document is None:
        return (
            f"report {row.ref} can no longer be read back from its stored payload, so there is no "
            f"ticket to render. The row is still in the table for a human to read."
        )
    content = render_ticket(ref=row.ref, document=document, caller_email=row.caller_email)
    refusal = content_in(content)
    if refusal is None:
        return content
    return (
        f"report {row.ref} renders a ticket body that {refusal}, so it is not printed here. The "
        f"ticket sink refuses this body for the same reason and sent nothing. The row is still in "
        f"the table for a human to read."
    )


async def _record_filed(store: ReportStore, ref: str, ticket_id: str, ticket_url: str) -> int:
    row = await store.read_for_triage(ref)
    refusal = _no_such_report(ref) if row is None else _already_filed(row, ticket_id)
    if refusal is not None:
        return _refused(refusal, EXIT_REFUSED)
    filed = await store.mark_filed(ref, ticket_id=ticket_id, ticket_url=ticket_url)
    if filed is None:
        # Between the read above and this write. The retention purge is the only thing that
        # deletes a row, and 90 days is a long time to have a triage session open — but "the row
        # went away" is still an answer, not something to report as a success.
        return _refused(_no_such_report(ref), EXIT_REFUSED)
    print(f"{ref} is filed as {ticket_id} ({ticket_url}) and is now delivered")
    return EXIT_OK


def _already_filed(row: TriageReport, ticket_id: str) -> str | None:
    """Why this report must not be re-marked under a different ticket, or None.

    The ticket columns are the ticket's ADDRESS, which is why `record_delivery` never clears them
    either. Overwriting one silently would erase the only pointer this service holds to an issue
    that exists — and two ids on one report means one bug was filed twice, which somebody needs
    to see rather than have tidied away. Re-running the command with the SAME id is allowed and
    idempotent, because an agent repeating itself is not a second ticket.
    """
    if row.delivery_state != "delivered" or row.ticket_id == ticket_id:
        return None
    return (
        f"report {row.ref} is already recorded as filed under {row.ticket_id} "
        f"({row.ticket_url}), which is not {ticket_id}. If the report really was filed twice, "
        f"close the duplicate in Linear; this command will not overwrite the first."
    )


def _ticket_argument(flag: str, value: str, limit: int) -> str | None:
    """Why an operator-supplied ticket id or url is unusable, or None.

    Both are typed on a command line and land in a column another agent later reads back out
    through `show`, so the check is that the value is exactly one unpadded token: no whitespace to
    forge a second header line with, nothing empty, nothing past the column's width.
    """
    padded = any(character.isspace() for character in value)
    if not value or padded or value != one_line(value, limit=limit):
        return (
            f"{flag}={value!r} is not usable as a ticket reference: it must be one non-empty "
            f"token with no whitespace, at most {limit} characters."
        )
    return None


def _table(rows: Sequence[TriageReport]) -> list[str]:
    """The header and one line per report, every column padded to one width.

    Widths are computed across the header and every cell rather than declared, so the table is
    aligned by construction — a cell can be neither wider nor narrower than its column, and the
    right-hand columns cannot drift row to row.
    """
    grid = [tuple(column.heading for column in _COLUMNS), *(_cells(row) for row in rows)]
    widths = [max(len(line[index]) for line in grid) for index in range(len(_COLUMNS))]
    return [
        _SEPARATOR.join(
            cell.ljust(width) for cell, width in zip(line, widths, strict=True)
        ).rstrip()
        for line in grid
    ]


def _cells(row: TriageReport) -> tuple[str, ...]:
    document = _document(row.payload)
    if document is None:
        # The columns are still true — they are columns, not payload — so they are still shown.
        return _bounded(
            (row.ref, _UNREADABLE, _UNREADABLE, _UNREADABLE, row.reply_to, row.caller_email)
        )
    return _bounded(
        (
            row.ref,
            document.occurred_at.isoformat(timespec="seconds"),
            _error(document),
            document.correlation.trace_id,
            row.reply_to,
            row.caller_email,
        )
    )


def _bounded(values: Sequence[object | None]) -> tuple[str, ...]:
    return tuple(
        _ABSENT if value in (None, "") else one_line(value, limit=column.limit)
        for value, column in zip(values, _COLUMNS, strict=True)
    )


def _error(document: ReportDocument) -> str:
    """`type` with `code` beside it when there is one. Both are free text and unbounded by §2.4,
    which is why the column has a limit of its own."""
    error = document.error
    return f"{error.type} ({error.code})" if error.code else error.type


def _document(payload: Mapping[str, Any]) -> ReportDocument | None:
    """The stored payload as a typed report, or None when it no longer validates.

    Deliberately not shared with `retry.py`'s namesake, which logs at error and marks the row
    terminally `failed`. Both consequences would be wrong here: a console reading a row is not an
    attempt to deliver it, and a `queue list` that wrote to the table would be a listing with a
    side effect.
    """
    try:
        return ReportDocument.model_validate(payload)
    except ValidationError:
        return None


def _no_such_report(ref: str) -> str:
    return (
        f"no report has ref {ref!r}. Refs are server-minted (`r_` and 12 hex characters) and rows "
        f"are purged after the retention window."
    )


def _refused(reason: str, code: int) -> int:
    return _note(reason, code)


def _note(text: str, code: int = EXIT_OK) -> int:
    """Operator commentary. stderr, never stdout — stdout is the table (see the module docstring).

    stdout is flushed first, and not for tidiness: the two streams buffer differently the moment
    either is redirected — stderr unbuffered, stdout in blocks — so `queue list > file` printed
    the footer above the table it describes.
    """
    sys.stdout.flush()
    print(f"report-intake: {text}", file=sys.stderr)
    return code


__all__ = [
    "DEFAULT_LIMIT",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_STORAGE",
    "list_queued",
    "mark_filed",
    "positive",
    "show",
]
