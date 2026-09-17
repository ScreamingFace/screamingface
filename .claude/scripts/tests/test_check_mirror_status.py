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
            "2026-08-04-ome-734-dependabot-triage.md", "OME-734", "in_review"
        )
        self.tree.ledger("2026-08-04-OME-734-dependabot-triage.md", "OME-734", "done")
        violations, notes = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-734"])
        self.assertEqual([n.ticket for n in notes], [])

    def test_pairs_when_filenames_do_not_line_up_at_all(self):
        self.tree.mirror("2026-01-01-OME-900-mirror-name.md", "OME-900", "in_review")
        self.tree.ledger(
            "2026-07-07-OME-900-totally-different-slug.md", "OME-900", "done"
        )
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-900"])

    def test_frontmatter_ticket_id_beats_the_filename(self):
        # Filename says OME-111; the frontmatter (authoritative) says OME-222.
        self.tree.mirror("2026-01-01-OME-111-misnamed.md", "OME-222", "in_review")
        self.tree.ledger("2026-01-01-OME-222-real.md", "OME-222", "done")
        violations, notes = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-222"])
        self.assertEqual([n.ticket for n in notes], [])

    def test_ticket_id_falls_back_to_the_filename_when_frontmatter_has_none(self):
        (self.tree.tasks / "2026-01-01-ome-555-no-id.md").write_text(
            "---\nstatus: in_review\nclosed:\n---\n"
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
        self.tree.mirror("2026-01-01-OME-601-x.md", "OME-601", "in_review")
        self.tree.ledger("2026-01-01-OME-601-first.md", "OME-601", "in_progress")
        newest = self.tree.ledger("2026-06-01-OME-601-followup.md", "OME-601", "done")
        violations, _ = self.tree.run()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].ledger_path, newest)
        self.assertEqual(violations[0].ledger_status, "done")

    # ── rule: ledger done ────────────────────────────────────────────────────
    def test_ledger_done_with_mirror_in_review_is_a_violation(self):
        self.tree.mirror("m.md", "OME-1", "in_review")
        self.tree.ledger("2026-01-01-OME-1-x.md", "OME-1", "done")
        violations, _ = self.tree.run()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].ticket, "OME-1")
        self.assertEqual(violations[0].ledger_status, "done")
        self.assertEqual(violations[0].mirror_status, "in_review")
        self.assertEqual(violations[0].reason, "ledger-done-mirror-not-done")

    def test_ledger_done_with_mirror_done_but_empty_closed_is_a_violation(self):
        self.tree.mirror("m.md", "OME-2", "done")  # closed: (empty)
        self.tree.ledger("2026-01-01-OME-2-x.md", "OME-2", "done")
        violations, _ = self.tree.run()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].reason, "ledger-done-mirror-not-closed")
        self.assertEqual(violations[0].mirror_status, "done")

    def test_ledger_done_with_mirror_closed_literal_null_is_a_violation(self):
        self.tree.mirror("m.md", "OME-3", "done", closed="null")
        self.tree.ledger("2026-01-01-OME-3-x.md", "OME-3", "done")
        violations, _ = self.tree.run()
        self.assertEqual(
            [v.reason for v in violations], ["ledger-done-mirror-not-closed"]
        )

    def test_ledger_done_with_mirror_done_and_closed_date_is_clean(self):
        self.tree.mirror("m.md", "OME-4", "done", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-4-x.md", "OME-4", "done")
        violations, notes = self.tree.run()
        self.assertEqual(violations, [])
        self.assertEqual(notes, [])

    def test_ledger_completed_spelling_still_requires_a_done_mirror(self):
        self.tree.mirror("m.md", "OME-5", "in_review")
        self.tree.ledger("2026-01-01-OME-5-x.md", "OME-5", "completed")
        violations, _ = self.tree.run()
        self.assertEqual(
            [v.reason for v in violations], ["ledger-done-mirror-not-done"]
        )

    def test_ledger_done_with_mirror_canceled_is_a_violation(self):
        self.tree.mirror("m.md", "OME-6", "canceled", closed="2026-02-02")
        self.tree.ledger("2026-01-01-OME-6-x.md", "OME-6", "done")
        violations, _ = self.tree.run()
        self.assertEqual([v.mirror_status for v in violations], ["canceled"])

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
            MIRROR.format(ticket="OME-19", status="in_review", closed="")
        )
        self.tree.ledger("2026-01-01-OME-19-x.md", "OME-19", "done")
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-19"])

    # ── reporting / exit code ────────────────────────────────────────────────
    def test_violations_are_sorted_by_ticket_number_not_lexically(self):
        for n in (9, 100, 20):
            self.tree.mirror(f"m{n}.md", f"OME-{n}", "in_review")
            self.tree.ledger(f"2026-01-01-OME-{n}-x.md", f"OME-{n}", "done")
        violations, _ = self.tree.run()
        self.assertEqual([v.ticket for v in violations], ["OME-9", "OME-20", "OME-100"])

    def test_report_names_every_offender_by_path_and_statuses(self):
        mirror = self.tree.mirror("2026-01-01-OME-21-x.md", "OME-21", "in_review")
        self.tree.ledger("2026-01-01-OME-21-x.md", "OME-21", "done")
        violations, notes = self.tree.run()
        text = check_mirror_status.render(violations, notes)
        self.assertIn(str(mirror), text)
        self.assertIn("OME-21", text)
        self.assertIn("in_review", text)

    def test_exit_code_is_one_when_a_violation_exists(self):
        self.tree.mirror("m.md", "OME-22", "in_review")
        self.tree.ledger("2026-01-01-OME-22-x.md", "OME-22", "done")
        self.assertEqual(check_mirror_status.run(self.tree.tasks, self.tree.work), 1)

    def test_exit_code_is_zero_when_only_notes_exist(self):
        self.tree.mirror("m.md", "OME-23", "in_review")
        self.assertEqual(check_mirror_status.run(self.tree.tasks, self.tree.work), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
