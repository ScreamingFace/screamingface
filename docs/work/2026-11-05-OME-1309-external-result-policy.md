---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-05
finished: 2026-11-05
---

# Apply the external-result comparison policy

## Intent

Audit the SAT-English candidates and prevent unverified or incompatible imports
from entering shared rankings under the owner's agreed policy.

## Planned changes

- Comparison profiles and validator under `scores/`; baseline store/read schema.
- Import guide, policy spec, audit and tests; portal guard in the existing UI PR.

## Test plan

Failing tests first: missing/forged evidence, incompatible questions or grader,
partial coverage, conversions and bounds, atomic rollback, stale revisions,
replacement observations and private attribution. Run full scoreboard gates.

## Acceptance

Only fully reviewed compatible observations are rankable. Original values and
conversion evidence survive import. SAT-English candidates remain ineligible.

## Outcome

- Added reviewed board profiles, bounded evidence schema, exact conversion checks,
  import validation and computed public eligibility. Existing metadata stores the
  review; no new database migration or dependency.
- Read paths revoke eligibility for changed scope, malformed metadata or replaced
  observations. A regression test exposed a revision change between the baseline
  read and community snapshot; response validation now removes stale approval.
- RED/GREEN: missing eligibility and bad reviews initially failed. All 48 focused
  policy cases now pass, including public/private API output and rollback.
- Full scoreboard gates: ALL GATES GREEN; repository mirror-status gate passes.
- Portal companion in #1644: explicit-true eligibility, prompt-note disclosure,
  16 passing cases locally and in UTC+14, all scoreboard gates green. Feeding the
  current dev payload into the real page scripts yields zero ranked rows and no
  summary/score bars for its two unreviewed trial candidates.
- Rechecked the pinned sources and wheel hash. Both SAT-English candidates remain
  ineligible: answer extraction differs and historical coverage is unverified.
  Public dev/prod scope matches the documented 206-case revision. Audit and remote
  evidence links are in `apps/scoreboard/docs/external-result-comparison.md`.
- Review: profiles cannot be declared by an input row; no arbitrary conversion
  formula; internal attribution stays private. Evidence is operator-reviewed, not
  machine proof of source truth. Profile additions require review.
- Commits: `feat(scoreboard): require reviewed evidence for external result ranks`;
  companion `fix(scoreboard): rank only approved external results`.
- Deviations: stacked on #1683 to reuse provenance fields. Existing published-field
  approval manifest extended for the owner-authorized eligibility boolean. No new
  Linear issue or update, deployment, live data mutation, paid run or E20 closure.
