---
ticket: OME-1135
stack: screamingface
status: done
started: 2026-09-24
finished: 2026-09-24
---
# Keep the evaluation summary row stable

## Intent
Keep the table consistently spaced below the progress bar before usage arrives, as approved by the owner. Extends the existing activity-widget spec and plan.

## Planned changes
Render the existing receipt row with “0 model calls” when no usage is available. Reuse its existing spacing; no fixed blank panel or invented token/cost values.

## Test plan
Add a regression for initial summary presence and its transition to actual usage. Run Client gates and inspect the rendered initial/populated states.

## Acceptance
The summary line exists at 0% and after usage, keeping the table position consistent. Existing accounting and cached-run wording remain unchanged.

## Outcome
Implementation: reused the existing receipt container with a zero-call fallback; no CSS changes or invented cost/token values. The new regression failed before the fix. Migrated the prior collapse assertion to the explicitly owner-approved persistent summary; all subsequent usage assertions remain intact. Wisdom review: minimal presentation-only fallback, no shared interfaces, accounting, schema, or security changes. Browser policy blocked local-file visual preview; generated HTML is available for manual inspection. Full Client gates passed: lint, format, types, full tests with 95% coverage, notebook checks, build and distribution. Used the explicit append-only exception only for the owner-requested old collapse assertion migration. Commit: fix(client): preserve initial evaluation summary spacing.
