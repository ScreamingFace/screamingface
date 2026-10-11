---
ticket: OME-1571
stack: screamingface
status: done
started: 2026-10-11
finished: 2026-10-11
---

# Report pagination — fourth SDK slice

## Intent

Extract bounded notebook report browsing from #1156 after #1241, #1269 and #1345 merged. Browse every retained Case without embedding all payloads in notebook state; preserve exact identities and complete exports.

## Planned changes

Add private navigation/browser/file-link adapters, bounded static report previews and inline downloads, private disk identity iteration and notebook display integration. Adapt the source slice to retain merged Named Scores, archive costs, atomic export and compact accounting. Add ipyevents only to the optional notebook extra for Case-click focus synchronization. No lifecycle or Engine changes.

## Test plan

New regression files first: pagination boundaries, exact numeric/string/padded IDs, candidate filtering/focus, disk reads limited to page payloads, async rapid clicks and failure recovery, full streamed download, bounded static and widget state, fallback display and metadata preservation. Inherited tests unchanged except the explicitly approved notebook-extra allowlist. Independent Standards/Spec reviews and full SDK gates. Render actual before/after report screenshots in light and dark.

## Acceptance

25 Case results per live page; previous/next, exact go-to, all/candidate filtering and linked Candidate names. Full export on demand; static preview explicitly labelled, oversized Cases previewed, optional notebook dependencies remain optional. No lost report fields or dead controls. Draft from current main with a focused issue under OME-1294, review/gates green and screenshots supplied.

## Outcome

Implementation and screenshots complete. On 2026-10-11 the owner explicitly approved adding ipyevents to the optional notebook extra and updating the exact dependency allowlist test. The byte-exact approval is recorded in `.claude/test-change-approvals/OME-1571.json`. The original source/navigation regressions were RED on main (23 failures, 2 existing export checks passed). Added typed/padded identity, page-only disk reads, merged-field preservation and failure regressions; 42 pagination tests pass. Independent Standards and Spec findings were fixed and rechecked: synchronous navigation rollback (2 RED regressions), optional Jupyter server discovery fallback (3 RED regressions), plus async Candidate-filter rollback (1 RED regression). Browser inspected actual SDK first/last-page output in light/dark and verified Case 6 / $0.1000 DOM selection.

Initial full SDK run: Ruff/format/Pyright passed; 2,736 pytest tests passed, 26 skipped, 96.06% coverage; the sole failure is `test_the_notebook_extra_stays_lean_enough_for_a_hosted_notebook`, whose exact allowlist excludes ipyevents. Notebook/build/distribution checks also passed separately. The approved scoped test edit is applied. The final full SDK run passed every gate: approved append-only test check, Ruff lint/format, Pyright, parallel pytest (96.06% coverage, 95% required), notebook validation, wheel/sdist build and distribution checks. The mirror/ledger status check passed. ipyevents runtime dependencies are only ipywidgets; authoring dependencies are separate docs/test extras. No other inherited tests or snapshots changed.

Actual files match the plan, plus the scoped approval manifest/test change and committed screenshot assets. Wisdom review: keep widget adapters private and optional, preserve merged domain/export contracts, and use the existing exporter and compact accounting rather than duplicate truth. Deviations: two reproduced failure paths were hardened; the notebook-extra test change was explicitly approved. Commit: `feat(screamingface): paginate notebook report results (OME-1571)`.

Main base 4fbdfdce2d4ace85b5fb8411f3cbb69a921fa9d1; source #1156 b3b503d668eb7c78b7daed780eea39e510e6c7a3. Isolated clone reused because macOS denies shared-checkout reads.
