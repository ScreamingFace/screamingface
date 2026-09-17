#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""MIRROR STATUS gate (OME-1215).

CLAUDE.md rule 1: a unit's status is closed in BOTH Linear and its `docs/tasks/` mirror.
Nothing enforced the mirror half, so mirrors drift: 20+ of them sat at `in_review` for
units whose `docs/work/` ledger said `done` and whose PRs had merged weeks earlier.
`OME-1133` hand-swept a batch and it drifted straight back, because the disagreement is
silent by construction — it is only ever found by someone grepping.

This is the thing that notices. For every mirror that has a ledger:

    ledger done              -> mirror done AND `closed:` set (not empty, not null)
    ledger blocked           -> mirror blocked, or another STOP state
    ledger in_progress|planned -> mirror anything EXCEPT done

Reported but never failed (they are legitimate, not drift):
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

# `closed:` values that mean "not actually closed".
UNSET_CLOSED = {"", "null", "none", "~", "tbd", "-"}


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
    mirror_fields: dict[str, str],
    ledger: pathlib.Path,
    ledger_status: str,
) -> Violation | Note | None:
    if ledger_status == DONE:
        if mirror_status != DONE:
            return Violation(
                ticket,
                "ledger-done-mirror-not-done",
                mirror,
                ledger,
                mirror_status,
                ledger_status,
                f"ledger is done; mirror is {mirror_status!r} — close the mirror",
            )
        closed = mirror_fields.get("closed", "").split("#", 1)[0].strip().strip("\"'")
        if closed.lower() in UNSET_CLOSED:
            return Violation(
                ticket,
                "ledger-done-mirror-not-closed",
                mirror,
                ledger,
                mirror_status,
                ledger_status,
                f"mirror is done but `closed:` is {closed or 'empty'} — half-closed",
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


def check(
    tasks_dir: pathlib.Path, work_dir: pathlib.Path
) -> tuple[list[Violation], list[Note]]:
    """Every mirror judged against its ledger. Violations fail; notes only report."""
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
        mirror_status, mirror_fields = _status_of(mirror)
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
        verdict = _judge(
            ticket, mirror, mirror_status, mirror_fields, ledger, ledger_status
        )
        if isinstance(verdict, Violation):
            violations.append(verdict)
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
            "Close the mirror (status + `closed:`) to match its ledger. Never stamp a mirror "
            "`done` to clear this gate — if the true status is unclear, that is a "
            "Confidence-Gate decision: STOP and ask."
        )
    return "\n".join(lines)


def run(tasks_dir: pathlib.Path, work_dir: pathlib.Path) -> int:
    violations, notes = check(tasks_dir, work_dir)
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
