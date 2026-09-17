#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for check_mirror_status.py — the docs/tasks ↔ docs/work status gate (OME-1215).

Each test builds a throwaway docs tree (a `tasks/` dir of mirrors and a `work/` dir of
ledgers) and calls the check functions directly against it.

INVARIANT for everything below: assertions walk the actual fields of the returned
Violation/Note objects (`.ticket`, `.reason`, `.mirror_status`, …). Never assert over
`repr()` of an object — `"<Violation object at 0x…>"` matches anything and the test would
survive every mutation (the bug this repo already shipped once).

Usage: uv run .claude/scripts/tests/test_check_mirror_status.py
"""

import importlib.util
import pathlib
import tempfile
import unittest

_SCRIPT_PATH = pathlib.Path(__file__).resolve().parent.parent / "check_mirror_status.py"
_spec = importlib.util.spec_from_file_location("check_mirror_status", _SCRIPT_PATH)
check_mirror_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_mirror_status)

MIRROR = """---
id: {ticket}
status: {status}
closed:{closed}
---

# body
"""

LEDGER = """---
ticket: {ticket}
stack: repo
status: {status}
started: 2026-09-01
finished:
---

# body
"""


class _Tree:
    """A temp docs tree with tasks/ and work/ subdirectories."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.tasks = self.root / "tasks"
        self.work = self.root / "work"
        self.tasks.mkdir()
        self.work.mkdir()

    def mirror(
        self, name: str, ticket: str, status: str, closed: str = ""
    ) -> pathlib.Path:
        path = self.tasks / name
        path.write_text(
            MIRROR.format(
                ticket=ticket, status=status, closed=f" {closed}" if closed else ""
            )
        )
        return path

    def ledger(self, name: str, ticket: str, status: str) -> pathlib.Path:
        path = self.work / name
        path.write_text(LEDGER.format(ticket=ticket, status=status))
        return path

    def run(self):
        return check_mirror_status.check(self.tasks, self.work)

    def close(self) -> None:
        self._tmp.cleanup()


class MirrorStatusGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = _Tree()
        self.addCleanup(self.tree.close)

    # ── normalisation ────────────────────────────────────────────────────────
    def test_normalize_lowercases_and_underscores(self):
        self.assertEqual(
            check_mirror_status.normalize_status("In Progress"), "in_progress"
        )
        self.assertEqual(
            check_mirror_status.normalize_status("in-progress"), "in_progress"
        )
        self.assertEqual(check_mirror_status.normalize_status("Done"), "done")

    def test_normalize_strips_trailing_comment(self):
        raw = "in_review   # matches Linear; scope extension 3 landed 2026-07-18"
        self.assertEqual(check_mirror_status.normalize_status(raw), "in_review")

    def test_complete_and_completed_are_spellings_of_done(self):
        self.assertEqual(check_mirror_status.normalize_status("completed"), "done")
        self.assertEqual(check_mirror_status.normalize_status("complete"), "done")

    # ── pairing ──────────────────────────────────────────────────────────────
    def test_pairs_case_insensitively_across_differently_cased_filenames(self):
        self.tree.mirror(
            "2026-08-04-ome-734-dependabot-triage.md", "OME-734", "backlog"
        )
        self.tree.ledger("2026-08-04-OME-734-dependabot-triage.md", "OME-734", "done")
        violations, notes = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-734"])
        self.assertEqual([n.ticket for n in notes], [])

    def test_pairs_when_filenames_do_not_line_up_at_all(self):
        self.tree.mirror("2026-01-01-OME-900-mirror-name.md", "OME-900", "backlog")
        self.tree.ledger(
            "2026-07-07-OME-900-totally-different-slug.md", "OME-900", "done"
        )
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-900"])

    def test_frontmatter_ticket_id_beats_the_filename(self):
        # Filename says OME-111; the frontmatter (authoritative) says OME-222.
        self.tree.mirror("2026-01-01-OME-111-misnamed.md", "OME-222", "backlog")
        self.tree.ledger("2026-01-01-OME-222-real.md", "OME-222", "done")
        violations, notes = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-222"])
        self.assertEqual([n.ticket for n in notes], [])

    def test_ticket_id_falls_back_to_the_filename_when_frontmatter_has_none(self):
        (self.tree.tasks / "2026-01-01-ome-555-no-id.md").write_text(
            "---\nstatus: backlog\nclosed:\n---\n"
        )
        self.tree.ledger("2026-01-01-OME-555-x.md", "OME-555", "done")
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-555"])

    def test_newest_ledger_wins_when_a_ticket_has_several(self):
        self.tree.mirror("2026-01-01-OME-600-x.md", "OME-600", "in_progress")
        self.tree.ledger("2026-01-01-OME-600-first.md", "OME-600", "done")
        self.tree.ledger("2026-06-01-OME-600-followup.md", "OME-600", "in_progress")
        violations, _ = self.tree.run()
        self.assertEqual(violations, [])

    def test_newest_ledger_wins_and_can_itself_be_the_violation(self):
        self.tree.mirror("2026-01-01-OME-601-x.md", "OME-601", "backlog")
        self.tree.ledger("2026-01-01-OME-601-first.md", "OME-601", "in_progress")
        newest = self.tree.ledger("2026-06-01-OME-601-followup.md", "OME-601", "done")
        violations, _ = self.tree.run()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].ledger_path, newest)
        self.assertEqual(violations[0].ledger_status, "done")

    # ── rule: ledger done ────────────────────────────────────────────────────
    # SUPERSEDED EXPECTATION (round 1 -> round 2). The four tests below asserted the
    # ticket's original `ledger done -> mirror done` rule. The owner ruled that rule a
    # defect in the ticket: CLAUDE.md makes **Linear** the status authority, and a ledger
    # is per UNIT of work while a mirror is per TICKET, so a done ledger cannot prove the
    # ticket closed. The scenarios are kept and still asserted on; the verdict each one
    # expects is now the narrowed one. See NarrowedDoneRuleTests for the new rule.
    def test_ledger_done_with_mirror_in_review_is_clean(self):
        self.tree.mirror("m.md", "OME-1", "in_review")
        self.tree.ledger("2026-01-01-OME-1-x.md", "OME-1", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    def test_ledger_done_with_mirror_done_but_empty_closed_is_clean(self):
        # The `closed:` half-closed check went with the narrowing: a ledger proves a unit
        # finished, never that the TICKET closed, so it cannot prove a close date belongs.
        self.tree.mirror("m.md", "OME-2", "done")  # closed: (empty)
        self.tree.ledger("2026-01-01-OME-2-x.md", "OME-2", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    def test_ledger_done_with_mirror_closed_literal_null_is_clean(self):
        self.tree.mirror("m.md", "OME-3", "done", closed="null")
        self.tree.ledger("2026-01-01-OME-3-x.md", "OME-3", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    def test_ledger_done_with_mirror_done_and_closed_date_is_clean(self):
        self.tree.mirror("m.md", "OME-4", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-4-x.md", "OME-4", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    def test_ledger_completed_spelling_is_judged_by_the_done_row(self):
        # Subject is the `completed` -> `done` alias, not the row's contents; the fixture
        # moved to `backlog` when the row narrowed (see NarrowedDoneRuleTests).
        self.tree.mirror("m.md", "OME-5", "backlog")
        self.tree.ledger("2026-01-01-OME-5-x.md", "OME-5", "completed")
        violations, _ = self.tree.run()
        self.assertEqual(
            [v.reason for v in violations], ["ledger-done-mirror-not-started"]
        )

    def test_ledger_done_with_mirror_canceled_is_clean(self):
        # A ticket can be cancelled after a unit of its work finished — a real outcome,
        # not drift, and not something the gate is entitled to overrule.
        self.tree.mirror("m.md", "OME-6", "canceled", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-6-x.md", "OME-6", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    # ── rule: ledger blocked ─────────────────────────────────────────────────
    def test_ledger_blocked_with_mirror_done_is_a_violation(self):
        self.tree.mirror("m.md", "OME-7", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-7-x.md", "OME-7", "blocked")
        violations, _ = self.tree.run()
        self.assertEqual(
            [v.reason for v in violations], ["ledger-blocked-mirror-not-stopped"]
        )

    def test_ledger_blocked_with_mirror_blocked_is_clean(self):
        self.tree.mirror("m.md", "OME-8", "Blocked")
        self.tree.ledger("2026-01-01-OME-8-x.md", "OME-8", "blocked")
        violations, _ = self.tree.run()
        self.assertEqual(violations, [])

    def test_ledger_blocked_with_a_stop_state_mirror_is_clean(self):
        self.tree.mirror("m.md", "OME-9", "needs-owner")
        self.tree.ledger("2026-01-01-OME-9-x.md", "OME-9", "blocked")
        violations, _ = self.tree.run()
        self.assertEqual(violations, [])

    def test_ledger_blocked_with_mirror_in_progress_is_a_violation(self):
        self.tree.mirror("m.md", "OME-10", "in_progress")
        self.tree.ledger("2026-01-01-OME-10-x.md", "OME-10", "blocked")
        violations, _ = self.tree.run()
        self.assertEqual(
            [v.reason for v in violations], ["ledger-blocked-mirror-not-stopped"]
        )

    # ── rule: ledger in_progress / planned ───────────────────────────────────
    def test_ledger_in_progress_with_mirror_done_is_a_violation(self):
        self.tree.mirror("m.md", "OME-11", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-11-x.md", "OME-11", "in_progress")
        violations, _ = self.tree.run()
        self.assertEqual([v.reason for v in violations], ["ledger-open-mirror-done"])
        self.assertEqual([v.ledger_status for v in violations], ["in_progress"])

    def test_ledger_planned_with_mirror_done_is_a_violation(self):
        self.tree.mirror("m.md", "OME-12", "Done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-12-x.md", "OME-12", "planned")
        violations, _ = self.tree.run()
        self.assertEqual([v.ledger_status for v in violations], ["planned"])

    def test_ledger_in_progress_with_mirror_in_review_is_clean(self):
        self.tree.mirror("m.md", "OME-13", "In Review")
        self.tree.ledger("2026-01-01-OME-13-x.md", "OME-13", "in_progress")
        violations, _ = self.tree.run()
        self.assertEqual(violations, [])

    def test_ledger_in_progress_with_mirror_backlog_is_clean(self):
        self.tree.mirror("m.md", "OME-14", "Backlog")
        self.tree.ledger("2026-01-01-OME-14-x.md", "OME-14", "in_progress")
        violations, _ = self.tree.run()
        self.assertEqual(violations, [])

    # ── reported, never failed ───────────────────────────────────────────────
    def test_mirror_without_a_ledger_is_reported_not_failed(self):
        self.tree.mirror("m.md", "OME-15", "in_review")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual([n.ticket for n in notes], ["OME-15"])
        self.assertEqual([n.reason for n in notes], ["no-ledger"])

    def test_no_ledger_note_carries_the_mirror_status_in_the_mirror_field(self):
        # Field-level, not repr-level: a note whose statuses land in the wrong slots
        # renders plausibly and would otherwise pass.
        mirror = self.tree.mirror("m.md", "OME-24", "In Review")
        _, notes = self.tree.run()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].mirror_path, mirror)
        self.assertEqual(notes[0].mirror_status, "in_review")
        self.assertEqual(notes[0].ledger_status, "")

    def test_ledger_status_outside_the_rule_table_is_reported_not_failed(self):
        self.tree.mirror("m.md", "OME-16", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-16-x.md", "OME-16", "reverted")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual([n.reason for n in notes], ["ledger-status-unclassified"])
        self.assertEqual([n.ledger_status for n in notes], ["reverted"])

    def test_ledger_in_review_is_unclassified_and_does_not_fail(self):
        self.tree.mirror("m.md", "OME-17", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-17-x.md", "OME-17", "in_review")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual([n.reason for n in notes], ["ledger-status-unclassified"])

    def test_mirror_without_a_parseable_ticket_id_is_reported_not_failed(self):
        (self.tree.tasks / "notes.md").write_text("---\nstatus: done\nclosed:\n---\n")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual([n.reason for n in notes], ["no-ticket-id"])

    def test_template_and_readme_files_are_skipped(self):
        (self.tree.tasks / "TEMPLATE.md").write_text(
            "---\nid: OME-<N>\nstatus: planned\n---\n"
        )
        (self.tree.tasks / "README.md").write_text("# tasks\n")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    def test_mirror_without_frontmatter_status_is_reported_not_failed(self):
        (self.tree.tasks / "2026-01-01-OME-18-x.md").write_text(
            "# no frontmatter here\n"
        )
        self.tree.ledger("2026-01-01-OME-18-x.md", "OME-18", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual([n.reason for n in notes], ["no-mirror-status"])

    def test_mirrors_are_discovered_in_subdirectories(self):
        nested = self.tree.tasks / "aigw"
        nested.mkdir()
        (nested / "2026-01-01-OME-19-x.md").write_text(
            MIRROR.format(ticket="OME-19", status="backlog", closed="")
        )
        self.tree.ledger("2026-01-01-OME-19-x.md", "OME-19", "done")
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-19"])

    # ── reporting / exit code ────────────────────────────────────────────────
    def test_violations_are_sorted_by_ticket_number_not_lexically(self):
        for n in (9, 100, 20):
            self.tree.mirror(f"m{n}.md", f"OME-{n}", "backlog")
            self.tree.ledger(f"2026-01-01-OME-{n}-x.md", f"OME-{n}", "done")
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-9", "OME-20", "OME-100"])

    def test_report_names_every_offender_by_path_and_statuses(self):
        mirror = self.tree.mirror("2026-01-01-OME-21-x.md", "OME-21", "backlog")
        self.tree.ledger("2026-01-01-OME-21-x.md", "OME-21", "done")
        violations, notes = self.tree.run()
        text = check_mirror_status.render(violations, notes)
        self.assertIn(str(mirror), text)
        self.assertIn("OME-21", text)
        self.assertIn("backlog", text)

    def test_exit_code_is_one_when_a_violation_exists(self):
        self.tree.mirror("m.md", "OME-22", "backlog")
        self.tree.ledger("2026-01-01-OME-22-x.md", "OME-22", "done")
        self.assertEqual(check_mirror_status.run(self.tree.tasks, self.tree.work), 1)

    def test_exit_code_is_zero_when_only_notes_exist(self):
        self.tree.mirror("m.md", "OME-23", "in_review")
        self.assertEqual(check_mirror_status.run(self.tree.tasks, self.tree.work), 0)


class NarrowedDoneRuleTests(unittest.TestCase):
    """OME-1215 round 2 — the `ledger done` rule narrowed to what a ledger can PROVE.

    The ticket's original rule was `ledger done -> mirror done`. That contradicts
    CLAUDE.md, which makes **Linear** the status authority: a ledger records one UNIT
    of work and a mirror tracks the TICKET, so a finished unit on a ticket Linear still
    shows as In Progress / In Review is a legal state, not drift. The owner narrowed the
    rule to:

        ledger done                -> mirror status NOT in {backlog, todo}
        ledger blocked             -> mirror blocked or another STOP state
        ledger in_progress|planned -> mirror NOT done
        mirror with no ledger      -> reported, never failed

    The gate therefore never forces a mirror to `done`. It only refuses the one thing a
    done ledger genuinely disproves: that the work was never started.
    """

    def setUp(self) -> None:
        self.tree = _Tree()
        self.addCleanup(self.tree.close)

    def test_ledger_done_with_mirror_backlog_is_a_violation(self):
        self.tree.mirror("m.md", "OME-30", "Backlog")
        self.tree.ledger("2026-01-01-OME-30-x.md", "OME-30", "done")
        violations, _ = self.tree.run()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].ticket, "OME-30")
        self.assertEqual(violations[0].reason, "ledger-done-mirror-not-started")
        self.assertEqual(violations[0].mirror_status, "backlog")
        self.assertEqual(violations[0].ledger_status, "done")

    def test_ledger_done_with_mirror_todo_is_a_violation(self):
        self.tree.mirror("m.md", "OME-31", "todo")
        self.tree.ledger("2026-01-01-OME-31-x.md", "OME-31", "done")
        violations, _ = self.tree.run()
        self.assertEqual(
            [v.reason for v in violations], ["ledger-done-mirror-not-started"]
        )
        self.assertEqual([v.mirror_status for v in violations], ["todo"])

    def test_the_to_do_spelling_is_the_same_not_started_state(self):
        # Linear renders this state "To Do"; normalisation folds the space to `_`, so
        # without the alias the gate would silently stop seeing half of the real drift.
        self.assertEqual(check_mirror_status.normalize_status("To Do"), "todo")
        self.tree.mirror("m.md", "OME-32", "To Do")
        self.tree.ledger("2026-01-01-OME-32-x.md", "OME-32", "done")
        violations, _ = self.tree.run()
        self.assertEqual(
            [v.reason for v in violations], ["ledger-done-mirror-not-started"]
        )

    def test_a_done_ledger_never_forces_a_mirror_to_done(self):
        # THE property the narrowing exists for. Every one of these mirror states is a
        # ticket that is genuinely still open in Linear while one unit of its work has
        # finished — 24 such pairs exist in this repo today, five with a PR open.
        legal = [
            "In Review",
            "In Progress",
            "blocked",
            "needs-owner",
            "design-session",
            "canceled",
            "done",
        ]
        # Each status gets its OWN tree and its OWN assertion inside the subTest. The first
        # version accumulated all seven and asserted once AFTER the loop, so the subTest wrapped
        # nothing but setup: a failure named the test, never the status that broke it.
        for index, status in enumerate(legal):
            with self.subTest(mirror_status=status):
                tree = _Tree()
                self.addCleanup(tree.close)
                ticket = f"OME-{4000 + index}"
                tree.mirror(f"m{index}.md", ticket, status)
                tree.ledger(f"2026-01-01-{ticket}-x.md", ticket, "done")
                violations, _ = tree.run()
                self.assertEqual(
                    [v.reason for v in violations],
                    [],
                    f"a done ledger must not force a mirror at {status!r} to done",
                )

        # AND all seven coexisting, which the per-status loop above cannot show.
        for index, status in enumerate(legal):
            ticket = f"OME-{4000 + index}"
            self.tree.mirror(f"m{index}.md", ticket, status)
            self.tree.ledger(f"2026-01-01-{ticket}-x.md", ticket, "done")
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], [])

    def test_a_done_ledger_does_not_require_a_closed_date_on_the_mirror(self):
        # Dropped with the narrowing: a ledger proves the unit finished, it does not
        # prove the TICKET closed, so it cannot prove a `closed:` date belongs there.
        self.tree.mirror("m.md", "OME-33", "done")  # closed: (empty)
        self.tree.ledger("2026-01-01-OME-33-x.md", "OME-33", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    def test_the_blocked_and_open_rules_survive_the_narrowing(self):
        # The narrowing touches the `done` row only; these two rows are unchanged.
        self.tree.mirror("a.md", "OME-34", "in_progress")
        self.tree.ledger("2026-01-01-OME-34-x.md", "OME-34", "blocked")
        self.tree.mirror("b.md", "OME-35", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-35-x.md", "OME-35", "in_progress")
        violations, _ = self.tree.run()
        self.assertEqual(
            [(v.ticket, v.reason) for v in violations],
            [
                ("OME-34", "ledger-blocked-mirror-not-stopped"),
                ("OME-35", "ledger-open-mirror-done"),
            ],
        )

    def test_the_report_tells_the_reader_what_the_gate_does_not_assert(self):
        self.tree.mirror("m.md", "OME-36", "backlog")
        self.tree.ledger("2026-01-01-OME-36-x.md", "OME-36", "done")
        violations, notes = self.tree.run()
        text = check_mirror_status.render(violations, notes)
        self.assertIn("OME-36", text)
        self.assertIn("backlog", text)
        self.assertIn("Linear", text)


class WaiverTests(unittest.TestCase):
    """OME-1215 round 2 — waivers, and the pinning that stops them rotting.

    Even narrowed, all three rows have verified counterexamples in this repo: a ledger is
    per UNIT and permanent while a mirror tracks a Linear state that moves on its own. The
    alternative to a waiver would be editing a status to a value Linear contradicts, which
    is the one thing the ticket forbids. So a waiver carries its evidence and is PINNED to
    the exact pair it was granted for.
    """

    def setUp(self) -> None:
        self.tree = _Tree()
        self.addCleanup(self.tree.close)

    def _waiver(self, mirror_status: str, ledger_status: str):
        return check_mirror_status.Waiver(mirror_status, ledger_status, "evidence here")

    def test_a_waived_pair_becomes_a_note_and_stops_failing(self):
        self.tree.mirror("m.md", "OME-40", "backlog")
        self.tree.ledger("2026-01-01-OME-40-x.md", "OME-40", "done")
        violations, notes = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-40"])  # unwaived: fails

        violations, notes = check_mirror_status.check(
            self.tree.tasks,
            self.tree.work,
            {"OME-40": self._waiver("backlog", "done")},
        )
        self.assertEqual(violations, [])
        self.assertEqual([n.ticket for n in notes], ["OME-40"])
        self.assertEqual([n.reason for n in notes], ["waived"])
        self.assertEqual([n.mirror_status for n in notes], ["backlog"])
        self.assertEqual([n.ledger_status for n in notes], ["done"])

    def test_a_waived_note_carries_the_evidence_and_the_original_reason(self):
        self.tree.mirror("m.md", "OME-41", "backlog")
        self.tree.ledger("2026-01-01-OME-41-x.md", "OME-41", "done")
        waiver = check_mirror_status.Waiver(
            "backlog", "done", "Linear says Backlog; the ledger is a design unit"
        )
        _, notes = check_mirror_status.check(
            self.tree.tasks, self.tree.work, {"OME-41": waiver}
        )
        self.assertEqual(len(notes), 1)
        self.assertIn("ledger-done-mirror-not-started", notes[0].detail)
        self.assertIn("Linear says Backlog", notes[0].detail)

    def test_a_waiver_does_not_apply_when_the_mirror_status_moves(self):
        # THE anti-rot property. The waiver was granted for `backlog`; the mirror is now
        # `todo`, a pair nobody verified, so the gate must fail again.
        self.tree.mirror("m.md", "OME-42", "todo")
        self.tree.ledger("2026-01-01-OME-42-x.md", "OME-42", "done")
        violations, notes = check_mirror_status.check(
            self.tree.tasks,
            self.tree.work,
            {"OME-42": self._waiver("backlog", "done")},
        )
        self.assertEqual([v.ticket for v in violations], ["OME-42"])
        self.assertEqual([v.mirror_status for v in violations], ["todo"])
        self.assertEqual([n.reason for n in notes], [])

    def test_a_waiver_does_not_apply_when_the_ledger_status_moves(self):
        self.tree.mirror("m.md", "OME-43", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-43-x.md", "OME-43", "in_progress")
        violations, _ = check_mirror_status.check(
            self.tree.tasks,
            self.tree.work,
            {"OME-43": self._waiver("done", "blocked")},
        )
        self.assertEqual([v.ticket for v in violations], ["OME-43"])
        self.assertEqual([v.reason for v in violations], ["ledger-open-mirror-done"])

    def test_a_waiver_for_another_ticket_never_covers_this_one(self):
        self.tree.mirror("m.md", "OME-44", "backlog")
        self.tree.ledger("2026-01-01-OME-44-x.md", "OME-44", "done")
        violations, _ = check_mirror_status.check(
            self.tree.tasks,
            self.tree.work,
            {"OME-999": self._waiver("backlog", "done")},
        )
        self.assertEqual([v.ticket for v in violations], ["OME-44"])

    def test_no_waivers_at_all_leaves_every_violation_failing(self):
        self.tree.mirror("m.md", "OME-45", "backlog")
        self.tree.ledger("2026-01-01-OME-45-x.md", "OME-45", "done")
        violations, _ = check_mirror_status.check(self.tree.tasks, self.tree.work, {})
        self.assertEqual([v.ticket for v in violations], ["OME-45"])

    def test_every_shipped_waiver_carries_real_evidence(self):
        # A waiver with an empty or placeholder reason is how this mechanism would rot
        # into a silence list. Each must name what was read and where.
        self.assertTrue(check_mirror_status.WAIVERS)
        for ticket, waiver in check_mirror_status.WAIVERS.items():
            with self.subTest(ticket=ticket):
                self.assertTrue(waiver.mirror_status)
                self.assertTrue(waiver.ledger_status)
                self.assertGreater(len(waiver.evidence), 120)
                self.assertIn("Linear", waiver.evidence)

    def test_the_shipped_waivers_are_exactly_the_three_verified_ones(self):
        self.assertEqual(
            sorted(check_mirror_status.WAIVERS),
            ["OME-887", "OME-906", "OME-908"],
        )
        self.assertEqual(
            check_mirror_status.WAIVERS["OME-906"].ledger_status, "blocked"
        )
        self.assertEqual(check_mirror_status.WAIVERS["OME-906"].mirror_status, "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
