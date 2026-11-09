#!/usr/bin/env python3
"""Regression checks for write-only reporting steps in fork pull requests."""

from __future__ import annotations

import pathlib
import unittest


class ForkWorkflowGuardTests(unittest.TestCase):
    def test_screamingface_coverage_comment_skips_fork_pull_requests(self) -> None:
        """Fork PRs keep the coverage threshold but cannot write a coverage comment."""
        repo = pathlib.Path(__file__).resolve().parents[3]
        workflow = (repo / ".github/workflows/screamingface-tests.yml").read_text()
        test_step = workflow.split("- name: Test and coverage", 1)[1].split(
            "- name: Test report", 1
        )[0]
        coverage_step = workflow.split("- name: Coverage report", 1)[1].split(
            "- name: Verify deterministic notebooks", 1
        )[0]

        self.assertIn("--cov-fail-under=95", test_step)
        self.assertNotIn("head.repo.full_name", test_step)
        self.assertIn("orgoro/coverage@v3.3", coverage_step)
        self.assertIn("github.event_name == 'pull_request'", coverage_step)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            coverage_step,
        )


if __name__ == "__main__":
    unittest.main()
