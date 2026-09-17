#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""MIRROR STATUS gate (OME-1215).

CLAUDE.md rule 1: a unit's status is closed in BOTH Linear and its `docs/tasks/` mirror.
Nothing enforced the mirror half, so a mirror can disagree with the `docs/work/` ledger of
its own work and nobody finds out — the disagreement is silent by construction, only ever
surfaced by someone grepping. `OME-1133` hand-swept a batch and it drifted straight back.
This is the thing that notices.

WHAT IT ASSERTS, AND WHY IT IS NARROW. **Linear is the status authority** (CLAUDE.md), not
this gate and not the ledger. A ledger records one UNIT of work; a mirror tracks the
TICKET, and a ticket can outlive several units. So a finished unit whose ticket is still
In Progress or In Review is a legal state, not drift — 24 such pairs exist in this repo
right now, five of them with a PR open. The gate therefore asserts only what a ledger can
PROVE, and it never forces a mirror to `done`:

    ledger done                -> mirror status NOT in {backlog, todo}
    ledger blocked             -> mirror blocked, or another STOP state
    ledger in_progress|planned -> mirror anything EXCEPT done

The `done` row is the narrow one: a finished unit of work disproves exactly one thing —
that the ticket was never started. It says nothing about whether the ticket may close, so
the gate does not ask for a `done` mirror or a `closed:` date. Closing the ticket stays a
Linear decision made by a human with the Linear view in front of them.

WAIVERS. Each of the three rows has a verified counterexample in this repo (see
`WAIVERS`), all of one shape: a ledger is per UNIT and permanent, while the mirror tracks a
Linear state that moves on its own — an epic pushed back to Backlog, a design unit finished
for a ticket Linear never started, a ticket closed by a *different* unit while this one's
ledger stays truthfully `blocked`. Rather than bend the statuses to fit the rule, each is
waived by ticket WITH the evidence read from Linear, and pinned to the exact
`(mirror_status, ledger_status)` pair verified — move either side and the gate fires again.

Reported but never failed (they are legitimate, not drift):
  * a waived pair — listed above, with its evidence, and re-checked whenever either
    status moves;
  * a mirror with no ledger — issues are routinely filed before work starts;
  * a ledger whose status is outside the rule table above (`in_review`, `reverted`, …) —
    the table is implemented literally and is never widened by guesswork;
  * a mirror with no ticket id or no `status:` at all.

Exit 0 when there are no violations (notes do not fail), 1 when there are, 2 on a
structural error (a missing docs directory).

Usage: uv run .claude/scripts/check_mirror_status.py [--tasks DIR] [--work DIR]
"""

import argparse
import dataclasses
import pathlib
import re
import sys

# Pairing is by TICKET ID, case-insensitively — the two trees do NOT use the same
# filenames: `docs/tasks/2026-08-04-ome-734-dependabot-triage.md` is lowercased while its
# ledger is `docs/work/2026-08-04-OME-734-dependabot-triage.md`, and some pairs share no
# slug at all. Never match on filename.
TICKET_RE = re.compile(r"\b(OME-\d+)\b", re.IGNORECASE)
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$")
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# Files in docs/tasks that are not mirrors of a unit of work.
SKIP_NAMES = {"TEMPLATE.md", "README.md"}

# Spellings of the same state seen in the live tree.
STATUS_ALIASES = {
    "complete": "done",
    "completed": "done",
    "closed": "done",
    # Linear renders this state "To Do"; normalisation folds the space to `_` first.
    "to_do": "todo",
}

DONE = "done"
STOP_STATES = {
    "blocked",
    "needs-owner",
    "needs_owner",
    "design-session",
    "design_session",
}
OPEN_LEDGER_STATES = {"in_progress", "planned"}

# The only mirror states a `done` ledger disproves: work that finished cannot also have
# never been started. Everything else — in_review, in_progress, blocked, canceled, done —
# is a legal ticket state for a finished unit, because Linear, not the ledger, decides
# when the TICKET closes.
NOT_STARTED_STATES = {"backlog", "todo"}


@dataclasses.dataclass(frozen=True)
class Waiver:
    """One ticket where the rule table is verifiably wrong, with the evidence.

    A waiver is PINNED to the exact `(mirror_status, ledger_status)` pair it was granted
    for. Move either side and the waiver stops applying and the gate fires again — so a
    waiver can excuse the state someone looked at, and can never silently cover the next
    drift on the same ticket. Waived pairs are still printed, as notes.
    """

    mirror_status: str
    ledger_status: str
    evidence: str


# Every rule row below has a verified counterexample in this repo, all of one shape: a
# ledger is per UNIT and permanent, while a mirror tracks a Linear state that moves on its
# own — backwards, or to Done through a different unit's work. Each entry was checked
# against Linear via MCP on 2026-09-17 and carries what was read.
WAIVERS: dict[str, Waiver] = {
    "OME-887": Waiver(
        "backlog",
        "done",
        "Linear OME-887 is Backlog (statusType backlog), label `deferred`. Its state "
        "history shows In Progress -> Backlog on 2026-09-03: the owner moved a started "
        "epic back. The ledger (docs/work/2026-09-10-OME-887-rolling-activity-limits.md) "
        "is a finished DESIGN unit on that epic. The mirror matches Linear; the gate's "
        "premise — that a done unit proves the ticket left backlog — is false here.",
    ),
    "OME-908": Waiver(
        "backlog",
        "done",
        "Linear OME-908 is Backlog with a single state-history entry: it has never left "
        "Backlog since it was filed on 2026-08-20. Labels `design-session`, `human`. The "
        "ledger is the finished design-session write-up. A design unit can complete for a "
        "ticket Linear never started, so the mirror is right and the rule is wrong.",
    ),
    "OME-906": Waiver(
        "done",
        "blocked",
        "Linear OME-906 is Done (completedAt 2026-08-24T16:06:27Z). The ledger is "
        "correctly and permanently `blocked`: it records the unit stopping at step 5 "
        "because the measurement disproved its own plan. The ISSUE was then resolved by a "
        "different unit — c157ed7a `Bound the event bridge by a memory budget, not an "
        "event count (#672)`. An abandoned unit and a closed ticket are both true.",
    ),
}


@dataclasses.dataclass(frozen=True)
class Violation:
    ticket: str
    reason: str
    mirror_path: pathlib.Path
    ledger_path: pathlib.Path
    mirror_status: str
    ledger_status: str
    detail: str


@dataclasses.dataclass(frozen=True)
class Note:
    ticket: str
    reason: str
    mirror_path: pathlib.Path
    mirror_status: str
    ledger_status: str
    detail: str


def normalize_status(raw: str) -> str:
    """Lower-case, strip a trailing `# …` comment, fold `-` to `_`, apply aliases.

    The live tree holds `In Progress`, `Backlog`, `in-progress` and
    `in_review   # matches Linear; scope extension 3 (read surface) landed 2026-07-18`
    as values of the same field, so normalising is not optional.
    """
    value = raw.split("#", 1)[0].strip().strip("\"'")
    value = value.lower().replace("-", "_").replace(" ", "_")
    return STATUS_ALIASES.get(value, value)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs of a leading `---` block, as raw strings.

    Deliberately line-based rather than a YAML load: these files are hand-written and the
    tree contains values that a strict loader chokes on (unquoted `#` comments, bare
    `[repo]` lists, empty keys). A gate that crashes on a malformed mirror reports
    nothing; one that reads the keys it understands reports everything else.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line[:1] in (
            " ",
            "\t",
            "-",
        ):  # nested mapping/sequence entry — not top level
            continue
        match = FRONTMATTER_KEY_RE.match(line)
        if match and match.group(1) not in fields:
            fields[match.group(1)] = match.group(2).strip()
    return fields


def ticket_id(fields: dict[str, str], path: pathlib.Path) -> str | None:
    """The unit's ticket, upper-cased. Frontmatter wins; the filename is the fallback."""
    for key in ("ticket", "id"):
        match = TICKET_RE.search(fields.get(key, ""))
        if match:
            return match.group(1).upper()
    match = TICKET_RE.search(path.name)
    return match.group(1).upper() if match else None


def _sort_key(path: pathlib.Path) -> tuple[str, str]:
    """Newest-last ordering: the `YYYY-MM-DD` filename prefix, then the name."""
    match = DATE_PREFIX_RE.match(path.name)
    return (match.group(1) if match else "", path.name)


def _ticket_number(ticket: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", ticket)
    return (int(match.group(1)) if match else 0, ticket)


def collect(
    directory: pathlib.Path,
) -> tuple[dict[str, list[pathlib.Path]], list[pathlib.Path]]:
    """Map ticket -> its files (oldest first), plus the files carrying no ticket id."""
    by_ticket: dict[str, list[pathlib.Path]] = {}
    orphans: list[pathlib.Path] = []
    for path in sorted(directory.rglob("*.md")):
        if path.name in SKIP_NAMES:
            continue
        fields = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        ticket = ticket_id(fields, path)
        if ticket is None:
            orphans.append(path)
            continue
        by_ticket.setdefault(ticket, []).append(path)
    for paths in by_ticket.values():
        paths.sort(key=_sort_key)
    return by_ticket, orphans


def _status_of(path: pathlib.Path) -> tuple[str, dict[str, str]]:
    fields = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    return normalize_status(fields.get("status", "")), fields


def _judge(
    ticket: str,
    mirror: pathlib.Path,
    mirror_status: str,
    ledger: pathlib.Path,
    ledger_status: str,
) -> Violation | Note | None:
    if ledger_status == DONE:
        if mirror_status in NOT_STARTED_STATES:
            return Violation(
                ticket,
                "ledger-done-mirror-not-started",
                mirror,
                ledger,
                mirror_status,
                ledger_status,
                f"ledger is done; mirror is {mirror_status!r} — a unit of this ticket's "
                "work finished, so the ticket cannot still be un-started",
            )
        return None
    if ledger_status == "blocked":
        if mirror_status in STOP_STATES:
            return None
        return Violation(
            ticket,
            "ledger-blocked-mirror-not-stopped",
            mirror,
            ledger,
            mirror_status,
            ledger_status,
            f"ledger is blocked; mirror is {mirror_status!r} — expected a STOP state",
        )
    if ledger_status in OPEN_LEDGER_STATES:
        if mirror_status == DONE:
            return Violation(
                ticket,
                "ledger-open-mirror-done",
                mirror,
                ledger,
                mirror_status,
                ledger_status,
                f"mirror is done while the ledger is {ledger_status!r} — one of them is wrong",
            )
        return None
    return Note(
        ticket,
        "ledger-status-unclassified",
        mirror,
        mirror_status,
        ledger_status,
        f"ledger status {ledger_status!r} is outside the rule table — not judged",
    )


def _waived(verdict: Violation, waivers: dict[str, Waiver]) -> Note | None:
    """The note a waiver turns this violation into, or None if none applies."""
    waiver = waivers.get(verdict.ticket)
    if waiver is None:
        return None
    # PINNED, deliberately: a waiver excuses the one pair someone verified, not the ticket.
    if (waiver.mirror_status, waiver.ledger_status) != (
        verdict.mirror_status,
        verdict.ledger_status,
    ):
        return None
    return Note(
        verdict.ticket,
        "waived",
        verdict.mirror_path,
        verdict.mirror_status,
        verdict.ledger_status,
        f"waived [{verdict.reason}] — {waiver.evidence}",
    )


def check(
    tasks_dir: pathlib.Path,
    work_dir: pathlib.Path,
    waivers: dict[str, Waiver] | None = None,
) -> tuple[list[Violation], list[Note]]:
    """Every mirror judged against its ledger. Violations fail; notes only report."""
    waivers = WAIVERS if waivers is None else waivers
    mirrors, mirror_orphans = collect(tasks_dir)
    ledgers, _ = collect(work_dir)

    violations: list[Violation] = []
    notes: list[Note] = []

    for path in mirror_orphans:
        notes.append(
            Note(
                "",
                "no-ticket-id",
                path,
                "",
                "",
                "no OME-N id in frontmatter or filename",
            )
        )

    for ticket in sorted(mirrors, key=_ticket_number):
        mirror = mirrors[ticket][-1]  # newest mirror wins, same rule as ledgers
        mirror_status, _ = _status_of(mirror)
        ledger_paths = ledgers.get(ticket)
        if not ledger_paths:
            notes.append(
                Note(
                    ticket,
                    "no-ledger",
                    mirror,
                    mirror_status,
                    "",
                    "no docs/work ledger for this ticket — filed before work started",
                )
            )
            continue
        if not mirror_status:
            notes.append(
                Note(
                    ticket,
                    "no-mirror-status",
                    mirror,
                    "",
                    "",
                    "mirror has no `status:` in its frontmatter",
                )
            )
            continue
        ledger = ledger_paths[-1]  # a follow-up ledger is the current truth
        ledger_status, _ = _status_of(ledger)
        verdict = _judge(ticket, mirror, mirror_status, ledger, ledger_status)
        if isinstance(verdict, Violation):
            note = _waived(verdict, waivers)
            notes.append(note) if note else violations.append(verdict)
        elif isinstance(verdict, Note):
            notes.append(verdict)
    return violations, notes


def render(violations: list[Violation], notes: list[Note]) -> str:
    lines: list[str] = []
    if violations:
        lines.append(
            f"✗ mirror status gate — {len(violations)} mirror(s) disagree with their ledger:"
        )
        for v in violations:
            lines.append(f"  {v.ticket}  [{v.reason}]")
            lines.append(
                f"    mirror: {v.mirror_path}  (status: {v.mirror_status or '—'})"
            )
            lines.append(
                f"    ledger: {v.ledger_path}  (status: {v.ledger_status or '—'})"
            )
            lines.append(f"    {v.detail}")
    else:
        lines.append("✓ mirror status gate — every mirror agrees with its ledger")
    if notes:
        lines.append(f"- {len(notes)} note(s), not failures:")
        for n in notes:
            label = n.ticket or n.mirror_path.name
            lines.append(f"    {label}  [{n.reason}]  {n.mirror_path}")
    if violations:
        lines.append(
            "Move the mirror out of backlog/todo to the state Linear shows. This gate never "
            "asks for `done` — Linear is the status authority, so if the true state is "
            "unclear, read it there; if it is still unclear, that is a Confidence-Gate "
            "decision: STOP and ask."
        )
    return "\n".join(lines)


def run(
    tasks_dir: pathlib.Path,
    work_dir: pathlib.Path,
    waivers: dict[str, Waiver] | None = None,
) -> int:
    violations, notes = check(tasks_dir, work_dir, waivers)
    print(render(violations, notes))
    return 1 if violations else 0


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", type=pathlib.Path, default=repo_root / "docs" / "tasks")
    ap.add_argument("--work", type=pathlib.Path, default=repo_root / "docs" / "work")
    args = ap.parse_args()
    for label, directory in (("--tasks", args.tasks), ("--work", args.work)):
        if not directory.is_dir():
            print(f"ERROR: {label} directory not found: {directory}")
            return 2
    return run(args.tasks, args.work)


if __name__ == "__main__":
    sys.exit(main())
