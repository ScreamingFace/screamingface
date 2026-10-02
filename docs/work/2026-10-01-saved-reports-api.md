---
ticket: OME-1448
stack: screamingface
status: done
started: 2026-10-01
---
# Saved reports interface

Owner approved replacing the unshipped sf.runs namespace with sf.reports.list/get.
List one item per evaluation, using its persisted evaluation ID; standalone URL4
results use their saved key. Get/get_async reopen the whole group, preserving local
integrity checks, missing-artifact downloads and partial-report errors. Keep destination
copying and make explicit delete remove the same group that get returns. Accept saved
candidate keys/Engine IDs for existing storage remediation without exposing candidate
records in the report list. No duplicate public recovery aliases.

Plan: rename runs module, group lightweight manifest metadata, update docs, public
snapshot, tests, memory script and notebook. Test multi-candidate grouping, independent
evaluations, standalone tickets, unknown IDs, group deletion and partial reports.
Run full SDK gates and refresh the notebook. No stored-file schema migration required.

## Outcome and review
Replaced the unshipped runs module with reports and updated the public surface snapshot
and changelog. SavedReportInfo exposes id, expected candidate names, store directory,
aggregate bytes and whether all candidate result files exist. Listing decodes no cases.
Get/get_async reuse the existing integrity, download and partial-report implementation;
delete targets the entire group and its evaluation manifest, with a path guard.
Candidate keys and Engine IDs remain accepted as lookup inputs for saved remediation.
No stored result schema changes or extra recovery aliases.

18 focused persistence/recovery tests pass, including multi-candidate grouping, separate
and standalone reports, missing candidates, unknown IDs, and group deletion. All SDK
gates pass: lint, format, Pyright, full suite with >=95% coverage, notebooks, build and
distribution. Initial expected API tests were red before implementation. Existing tests
were migrated only for the owner-approved namespace and grouped listing contract.

JupyterLab restarted and displayed one saved report for the 11-candidate fixture;
get(saved[0].id) reopened all 46,002 results without model calls. Updated the notebook,
README, storage remediation, memory script and PR description. Screenshot saved at
docs/work/assets/OME-1448-saved-reports-api.png.

Review: the public interface names match list/get conventions and the returned Report.
Group-wide deletion matches group-wide retrieval. Recovery stays inside the existing
implementation; no speculative wrapper layers, schema changes or security changes.
Commit: feat(client): expose saved reports through list and get. Existing draft PR #1156.
