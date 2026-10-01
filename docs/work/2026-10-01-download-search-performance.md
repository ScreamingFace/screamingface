---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
---
# Download wording and search latency

Owner approved Download instead of Export and reports slow search. Change idle/failure
labels to Download, preserving disabled Preparing… and ready download link. Diagnose
with the existing 46,002-case synthetic fixture, timing search separately from recovery.
Keep complete field search, Unicode-insensitive substring matching, page reset, bounded
memory and complete download. Avoid adding a huge duplicate full-text index by default.

Plan: reproduce and measure baseline, isolate read/decode/serialization costs, implement
only the demonstrated improvement with a regression test, then run SDK gates and refresh
the notebook and existing draft PR. Explain residual whole-dataset scanning costs clearly.

Owner steering: page changes are also slow, especially rapid repeated clicks. Extend the
same unit to measure page rendering separately and keep its work off the notebook event
loop. Disable both navigation buttons and search during one page load; ignore queued
clicks until it finishes, preserve the old page on disk errors, and restore controls.

Owner correction supersedes the initial disable/ignore plan: pagination must remain
clickable. Requests now advance a requested position, coalesce over 75 ms, and discard
stale worker results. Boundaries alone disable navigation. Search stays submitted on
Enter/blur, with an explicit placeholder; downloads alone stay disabled while preparing.

Diagnosis and measurements (synthetic fixture, warm local index; model calls excluded):
- Search scanned 46,002 decoded CaseResult objects and rebuilt their JSON: 5.856s.
  SQL substring matching in the existing index avoids reconstruction: 1.830s, same 11
  answer 4181 matches. Unicode casefold and literal percent/underscore/quotes verified.
- Ten backend page renders took 62.332s because accounting projected every candidate
  repeatedly. Restricting visible owners alone reduced this to 4.130s. The final compact
  accounting context preserves global model attribution, consistency and remainder,
  while pages read only displayed cases: 0.028s for ten renders. HTML stays 303,200 bytes
  per fixture page. These timings exclude recovery/startup, browser transfer and paint.
- Judge attribution now streams evidence; neither contexts nor lookup cache retains
  prompts, CaseResult objects or a full accounting row collection. No full-text sidecar
  or disk schema migration was added. Full-content searches still read saved bytes.

Live JupyterLab: five rapid native Next clicks reached 126–150 without disabling
navigation; the final full-text query found 11 last-case matches across candidates.
Cleared search restored the original first page. Download is the idle/failure label;
Preparing… remains disabled/spinning, and the ready control remains Download.
Screenshot updated at docs/work/assets/OME-1422-report-browser.png.

## Verification and review
Final full SDK gates green: Ruff lint/format, Pyright, full test suite at >=95% coverage,
notebook validation, build and distribution. Regression tests prevent CaseResult rebuilds
in disk search, full-case accounting rescans on pages, lost rapid clicks and publication
of an outdated in-flight render. They preserve Unicode/literal query handling, disk-error
page restoration, global accounting inconsistency and cross-case model conflicts.
New interaction tests are isolated in test_report_interactions.py to keep files focused.

Final UI verification used the compact accounting context, not just the intermediate
visible-owner optimization. Five rapid clicks were accepted and completed within the
browser action/snapshot call; full-text search and clear both updated the displayed cases.
The unchanged JSON export/recovery contracts remain covered by the SDK suite.

Review: the cached context holds only attribution maps and consistency/remainder;
row generation is shared with the existing accounting implementation. No raw inputs,
outputs or complete accounting rows are retained there. Existing local indices work
without migration. Navigation accepts input while its worker renders, then publishes
only the newest requested position. Full-content search still performs an O(bytes)
scan, so its speed depends on the report and disk; it is not a token/full-text index.
No Engine, public saved-report interface or report.v1 changes.

Commit: fix(client): keep report browsing responsive. Existing draft PR #1156.
