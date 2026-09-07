---
ticket: OME-1013
stack: repo
status: done
started: 2026-09-07
finished: 2026-09-07
---

# OME-1013 — Consolidate notebook error reporting

## Intent

Record the owner's direction to deliver private capture and the complete Copy/Report flow in
OME-1013, superseding OME-1014. Narrow OME-416 to version provenance and align the design with
the existing intake contract and two development hostnames. This iteration changes planning
and issue ownership; application implementation remains open in PR #756.

## Planned changes

- docs/spec/2026-09-07-OME-1013-notebook-error-reporting.md
- docs/plan/2026-09-07-OME-1013-notebook-error-reporting.md
- docs/tasks/2026-09-07-OME-1013-notebook-error-reporting.md
- docs/tasks/2026-09-07-OME-1014-reporting-consolidation.md
- docs/tasks/2026-09-07-OME-1003-client-reporting.md
- docs/tasks/2026-09-07-OME-416-version-provenance.md
- Linear OME-1013, OME-1014, OME-1003 and OME-416.

## Test plan

- Read current issues, relations, source contract, authentication and delivery implementations.
- Verify public/internal admission rejection with empty JSON (cannot create a valid report).
- Check document links and diff whitespace; reread changed Linear issues after updating.
- Specify successful live submissions and persistence/delivery checks as implementation gates.

## Acceptance

- One implementation ticket owns capture, copy, preview, note, routing and submission.
- OME-1014 remains as a superseded historical record, not a claim of shipped functionality.
- OME-416 retains its distinct version-provenance work.
- No public diagnostic registry is required; authentication is scoped to the report audience.
- Live admission checks are distinguished from unperformed successful end-to-end checks.

## Outcome

- **Actual files:** the seven planned spec/plan/task-mirror files plus this ledger (seven
  files total: one spec, one plan, four mirrors, one ledger). Updated all four Linear issues;
  reread their states and relations. OME-1014 is Duplicate of OME-1013, its blocker removed;
  OME-1003's completed prerequisite removed; OME-416 narrowed with existing metadata retained.
- **Commits:** this iteration's `docs(screamingface): consolidate notebook reporting scope` commit.
- **Gates:** current service schema/auth/persistence/delivery implementations inspected;
  public empty POST returned 403 with no storage; internal empty POST returned Access 302.
  Issue readback verified. Documentation links and staged whitespace checked before commit.
  No application test suite required for this documentation/issue-only iteration.
- **Deviations:** no application code, deployment configuration or valid test reports changed.
  kubectl has no current context configured in this session, so actual deployment sink/rows
  could not be inspected. Real Turnstile and internal Access successful submissions remain
  unverified. OME-1013 remains In Progress; this ledger marks only consolidation complete.
