---
ticket: OME-1557
stack: screamingface
status: done
started: 2026-10-09
finished: 2026-10-09
---

# Fusion quorum review fixes

## Intent

Fix the two reproduced review defects in PR #1340: composed quorum members lose
upstream binding values, and default-valued metadata can bypass policy validation.
The user explicitly authorized both fixes and pushing to the existing PR branch.

## Planned changes

- URL4 expression lowering: capture enclosing reference values before executing a
  nested group, using the existing required GuardNode scope boundary.
- SDK URL4 validation: validate policy when executable instructions or metadata
  declare quorum/optional/required settings.
- Append regressions for URL4 scope capture, SDK composition and replay, and Engine
  gateway request contents. Preserve all existing tests and public signatures.

## Test plan

- Demonstrate failing dispatch-content and metadata-rejection tests before fixes.
- Assert prior Pipeline output reaches every member, upstream executes once, nested
  Fusion synthesis receives resolved outer outputs, and member-only quorum remains.
- Reject omitted and explicitly reset metadata through Python export and replay.
- Run URL4, SDK, and Engine card gates, including full suites and coverage.
- Re-run the review's scratch reproductions against the final code.

## Acceptance

- No literal compiler bindings reach model inputs in the reproduced compositions.
- Executable policy and Recipe metadata must agree even when metadata claims defaults.
- Required/optional behavior, cancellation, and legacy compilation stay protected.
- Push a normal follow-up commit to the current PR branch after green gates.

## Outcome

- Actual files: the URL4 lowerer, SDK replay validator and changelog; three new
  regression test modules; two Engine candidate fixtures and appended gateway
  regressions; this ledger, spec, and plan. No existing test assertions changed.
- Commits: follow-up commit `fix(client): preserve quorum inputs and validate replay policy`
  on reviewed parent `9b923b3689a9de758f6d80cb786df17aafc6c811`.
- Gates: all three `run_gates.py` stack runs passed against the reviewed parent.
  URL4 coverage 98.32% (95% floor), SDK 96.26% (95% floor), Engine 94.19% (80% floor).
  SDK notebook, package build, and distribution checks passed. URL4 suppression and
  module-size ratchets passed; Engine layering passed. Full suites ran with four
  xdist workers for SDK/Engine; no paid calls were enabled.
- Regression evidence: the original six URL4 scope cases and sixteen SDK
  composition/metadata cases failed before production changes, then passed. Added
  a further quorum-floor regression and two Engine request-content cases, for 25
  new regression cases. Both original scratch reproductions now behave correctly;
  100 deterministic nested Recipe export/execution probes pass.
- Wisdom review: reused the existing required execution scope boundary rather
  than adding protocol parameters or input sources; upstream work remains shared
  and does not affect the quorum count. Validation checks both executable policy
  and metadata, with no public-interface or cache-identity changes.
- Deviations: URL4's shared lowerer owns the scope defect; the SDK's compiled form
  stays unchanged. Existing OME-1557 and PR #1340 remain the scope of this follow-up.
