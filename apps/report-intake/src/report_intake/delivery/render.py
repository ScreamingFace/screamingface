"""The one module that decides what a ticket carries. Everything else is transport.

**Named fields only — nothing here serializes an object wholesale.** Every value below is read
by attribute, which is what makes two exclusions structural rather than remembered:

- **`error.details` and `error.cause` do not travel.** They are arbitrary client-shaped JSON;
  spec §2.1 calls `details` "unbounded server JSON" and the classifier only bounds the two of
  their leaves that look like captured bodies. They stay in the row, where a responder reads them
  behind Cloudflare Access — not in a third-party tracker.
- **Unknown keys inside `client` and `context` do not travel.** Those two objects are the
  declared extension points and pydantic preserves whatever a future client puts there, so
  rendering them wholesale would forward a field this service has never seen — an `api_key` a
  client dropped into its own extras, say. Reading declared attributes excludes it by NAME, at
  the point of rendering, rather than by pattern-matching the value.

What does travel is spec §6's list: the envelope, `trace_id`, `ref`, the reporter's note,
`reply_to` when present, and the caller email when the mesh supplied one.

Two rendering rules follow from the input being client-controlled free text:

- **No client-controlled value reaches the body as free-form Markdown.** A multi-line field is
  fenced with a computed fence — long enough to survive a fence of its own inside the value — and
  a field rendered as a list item is collapsed to one bounded line. Both are the same rule seen
  from two sides: unfenced and unflattened, a `## Reporter` inside a `note` or a newline inside a
  `trace_id` forges a section in the ticket a triager reads, and the `Reporter` section is where
  the mesh-verified address is stated.
- **Nothing else is reshaped.** The title is one bounded line because a tracker requires it, and
  the fenced blocks carry their text verbatim — so the fail-closed re-check in `dispatch.py`
  still sees what would travel. The one thing this module ADDS is a label: a `reply_to` that does
  not look like an address is labelled as such (see :func:`_reporter_bullets`). The value beside
  it is untouched, and so is `TicketContent.reply_to`, which a sink routes on.

INVARIANT: this renders from `ReportDocument` — a typed view of the PERSISTED payload — and not
from `BoundedReport`. `OME-1010` re-delivering a stored row (`ReportDocument.model_validate(
row.payload)`) therefore renders a byte-identical body to the inline attempt, rather than a
second, subtly different rendering of the same report. It is also why `truncations` is absent:
the §2.4 marks are already in-band in the strings below, and the out-of-band record is not
persisted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..reports.schema import (
    Benchmark,
    Candidate,
    Client,
    Context,
    Correlation,
    Error,
    Frontend,
    ReportDocument,
    Runtime,
)
from .ports import TicketContent

TITLE_MAX_CHARS = 120
"""Long enough for a type and the informative head of a message, short enough to read in a list.
Linear allows far more; a title nobody can scan is not a better title."""

BULLET_MAX_CHARS = 256
"""Ample for every field rendered as a bullet — §2.4 already caps the `client` and `context`
strings at 256 bytes — and a bound for the three that §2.4 caps nowhere: `error.type` and the
`correlation` ids. See :func:`one_line`."""

_BACKTICKS = re.compile("`+")
_WHITESPACE = re.compile(r"\s+")


def render_ticket(*, ref: str, document: ReportDocument, caller_email: str | None) -> TicketContent:
    """Spec §6's ticket content for one report — strings only, and never the report itself."""
    return TicketContent(
        ref=ref,
        title=_title(ref, document.error),
        body=_body(ref, document, caller_email),
        trace_id=document.correlation.trace_id,
        reply_to=document.reply_to,
        caller_email=caller_email,
    )


def _title(ref: str, error: Error) -> str:
    """One bounded line, prefixed with the `ref` so a triager can find the row it came from.

    The ONE place a value is reshaped: `type` and `message` are free text, and a tracker title is
    neither multi-line nor unbounded. Nothing is lost by it — the body below carries both
    verbatim inside a fence, which is also what keeps the re-check in `dispatch.py` honest about
    what actually travels.
    """
    summary = _WHITESPACE.sub(" ", f"{error.type}: {error.message}").strip()
    return _shortened(f"[{ref}] {summary}")


def _shortened(title: str) -> str:
    if len(title) <= TITLE_MAX_CHARS:
        return title
    return title[: TITLE_MAX_CHARS - 1].rstrip() + "…"


def _body(ref: str, document: ReportDocument, caller_email: str | None) -> str:
    return _joined(
        [
            _section("Report", _report_bullets(ref, document)),
            _section("Error", _error_blocks(document.error)),
            _section("Client", _client_bullets(document.client)),
            _section("Context", _context_bullets(document.context)),
            _section("Correlation", _correlation_bullets(document.correlation)),
            _section("Reporter", _reporter_bullets(document.reply_to, caller_email)),
            _section("Note", _fenced(document.note) if document.note else ""),
        ]
    )


def _report_bullets(ref: str, document: ReportDocument) -> str:
    return _bullets(
        (
            ("ref", ref),
            ("schema", document.schema_),
            ("occurred at", document.occurred_at.isoformat()),
        )
    )


def _error_blocks(error: Error) -> str:
    """The error's named fields. `details` and `cause` are deliberately absent — see the module
    docstring; they are the two members that are arbitrary JSON rather than a stated field."""
    return _joined(
        [
            _bullets(
                (
                    ("type", error.type),
                    ("code", error.code),
                    ("status", error.status),
                    ("permanent", error.permanent),
                    ("retryable", error.retryable),
                )
            ),
            _quoted("message", error.message),
            _quoted("hint", error.hint),
            _quoted("notes", "\n".join(f"- {note}" for note in error.notes)),
            _quoted("traceback", error.traceback),
        ]
    )


def _client_bullets(client: Client) -> str:
    return _bullets(
        (
            ("name", client.name),
            ("version", client.version),
            ("host", client.host),
            ("platform", client.platform),
            ("runtime", _versioned(client.runtime)),
            ("frontend", _versioned(client.frontend)),
            ("user agent", client.user_agent),
        )
    )


def _context_bullets(context: Context | None) -> str:
    if context is None:
        return ""
    return _bullets(
        (
            ("engine host", context.engine_host),
            ("benchmark", _benchmark(context.benchmark)),
            ("candidate", _candidate(context.candidate)),
        )
    )


def _correlation_bullets(correlation: Correlation) -> str:
    """All three are claims, never credentials (`OME-966`) — they join a report to a trace and
    authorize nothing, here or anywhere else."""
    return _bullets(
        (
            ("trace id", correlation.trace_id),
            ("run id", correlation.run_id),
            ("gateway call id", correlation.gateway_call_id),
        )
    )


def _reporter_bullets(reply_to: str | None, caller_email: str | None) -> str:
    """Two addresses that mean different things, labelled so a responder cannot confuse them:
    one is whatever the client typed, the other is what the mesh verified.

    The reply address carries a SECOND label when it does not look like an address at all. That is
    this service's half of spec §9's "accepted, unverified": `reply_to` is deliberately never
    syntax-checked at the route (see :attr:`ReportDocument.reply_to`), because refusing a typo
    would lose a whole diagnosable report over the one field nothing is authoritative on — so the
    ticket is where the cost is paid. Without the mark the failure is silent in the worst
    direction: `bob@openmindorg` reads as an address at a glance, a triager answers it, the mail
    bounces into somebody's sent folder days later, and by then the report is closed and the
    reporter is still waiting.
    """
    return _bullets(
        (
            (_reply_to_label(reply_to), reply_to),
            ("mesh-verified caller", caller_email),
        )
    )


def _reply_to_label(reply_to: str | None) -> str:
    """Which of the two reply-to labels this value gets. `None` never renders a bullet at all —
    `_bullets` drops it — so the ordinary label is the safe answer there."""
    if reply_to is None or _looks_like_an_address(reply_to.strip()):
        return "reply-to (self-asserted)"
    return "reply-to (self-asserted, does not look like an address)"


def _looks_like_an_address(value: str) -> bool:
    """A shape check, and the wording of the label says so — this is NOT validation and must never
    become it. Nothing branches on the answer except which label is printed.

    Deliberately calibrated to over-flag rather than under-flag. An exotic-but-legal address (a
    quoted local part with a space in it, a domain literal) is marked, and that costs a triager
    one second of double-checking; an unmarked typo costs the reporter their answer. RFC 5322 is
    not the standard being applied here and pulling in a validator that implemented it would trade
    that calibration for someone else's.
    """
    local, separator, domain = value.partition("@")
    return bool(
        separator
        and local
        and domain
        and "@" not in domain
        and "." in domain.strip(".")
        and _WHITESPACE.search(value) is None
    )


def _versioned(part: Runtime | Frontend | None) -> str | None:
    return f"{part.name} {part.version}" if part is not None else None


def _benchmark(benchmark: Benchmark | None) -> str | None:
    if benchmark is None:
        return None
    return " @ ".join(part for part in (benchmark.id, benchmark.revision) if part) or None


def _candidate(candidate: Candidate | None) -> str | None:
    if candidate is None:
        return None
    parts = (candidate.name, candidate.kind, ", ".join(candidate.models or ()))
    return " · ".join(part for part in parts if part) or None


def _bullets(pairs: Iterable[tuple[str, object | None]]) -> str:
    """A Markdown list of the pairs that have a value. An absent optional field is left out
    rather than rendered as `none`: spec §2.1 makes almost everything nullable, so a report full
    of `none` bullets buries the three lines that say what happened."""
    return "\n".join(
        f"- {label}: {one_line(value)}" for label, value in pairs if value not in (None, "")
    )


def one_line(value: object, *, limit: int = BULLET_MAX_CHARS) -> str:
    """A bullet's value, flattened and bounded — because a bullet IS one line, by definition.

    THIS IS THE FENCE FOR THE FIELDS THAT CANNOT HAVE ONE. `_quoted` fences the three free-text
    members, but everything rendered as a bullet goes in raw, and §2.4 deliberately keeps newlines
    (a traceback without them is unreadable), so a newline in a bullet value ends the list item
    and the rest of the string renders as Markdown at document level. A `trace_id` of
    `"t\\n\\n## Reporter\\n\\n- mesh-verified caller: someone@openmined.org"` therefore forged a
    second `## Reporter` section ABOVE the real one — and that line is the only place a triager
    sees who the mesh authenticated, so it is forged verified identity in the artifact a human
    acts on. Neither detector stops it: `classify_report` and `scan_text` look for prompt markers,
    not for Markdown structure.

    Collapsing whitespace removes the newline a forged heading needs and cannot damage a
    legitimate value, since a value that needs more than one line was never going to survive as a
    bullet. The length bound covers the members §2.4 gives no cap at all — `error.type` and the
    three `correlation` ids — which are otherwise limited only by the 64 KiB body.

    PUBLIC because `queue_cli.py` renders the same client-controlled values into a terminal
    table, where the identical trick has the identical cause: a newline inside a `trace_id` ends
    the row and the rest of the value prints as another one, forging a report in the listing an
    agent triages from. `limit` is a parameter rather than the module constant only because a
    table column is narrower than a bullet — the rule being applied is the same one.
    """
    collapsed = _WHITESPACE.sub(" ", str(value)).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _quoted(heading: str, text: str | None) -> str | None:
    return f"### {heading}\n\n{_fenced(text)}" if text else None


def _fenced(text: str) -> str:
    """A fenced block whose fence is longer than any backtick run inside it.

    Not decoration: `note`, `message` and `traceback` are client free text, so a value containing
    a fence of its own would otherwise close the block early and let the rest render as Markdown
    in the ticket.
    """
    fence = "`" * max(3, _longest_backtick_run(text) + 1)
    return f"{fence}\n{text}\n{fence}"


def _longest_backtick_run(text: str) -> int:
    return max((len(run) for run in _BACKTICKS.findall(text)), default=0)


def _section(heading: str, body: str) -> str | None:
    return f"## {heading}\n\n{body}" if body else None


def _joined(blocks: Iterable[str | None]) -> str:
    return "\n\n".join(block for block in blocks if block)


__all__ = ["BULLET_MAX_CHARS", "TITLE_MAX_CHARS", "one_line", "render_ticket"]
