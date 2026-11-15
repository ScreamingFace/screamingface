# External result comparison policy

Owner decisions: same question version, coverage, grading and metric; prompts may
differ if documented; exact, documented unit conversions are allowed. Unknown or
incompatible observations stay out of shared rankings.

## Enforcement

Use a small reviewed registry of board comparison profiles, pinned to the live
benchmark revision and case count. Each profile names the question-set digest,
grader, metric, units and range. A board without a reviewed profile admits no
external rows into ranking. Adding a profile requires a code review with evidence;
the imported row cannot define the board's requirements for itself.

Operators may keep unreviewed observations in storage. To qualify, an observation
needs `metadata.comparison` with matching scope, original value and units, an
explicit conversion, review date, prompt note, and public evidence links for the
question set, grading, coverage and units. The source URL, metric, observation date
and internal operator attribution are required for a reviewed import. These are
operator attestations backed by evidence, not automated proof of source truth.

Validate a supplied review before any write; a bad review rolls back the batch.
Recompute eligibility on every read against the current board/profile and score.
Legacy, missing, malformed, stale and mismatched reviews yield false. The public
API adds `ranking_eligible`, default false; it never exposes internal attribution.
The portal accepts only literal `true`, including during mixed-version rollouts.
Unreviewed records remain in the separate API baselines collection, never ranks,
summary cards or score bars. No public write API or automatic source fetch.

Support identity, percentage/fraction conversions, and correct-count to accuracy
using the full verified case count. Compute with decimal arithmetic, check source
and target bounds, and require the supplied score to equal the converted value.
Keep original precision: conversion adds no claim of more accurate measurement.
Unsupported conversions (including Elo to accuracy and ambiguous error rates) need
an explicit evidenced implementation, not an operator-supplied formula.

## SAT-English disposition

The 206 pinned source records match. Prompt differences are allowed, but the
authors' first-capital-letter parser differs from Inspect's answer-marker parser.
Historical raw replies and completed-run coverage are unverified. Both existing
dev observations therefore remain ineligible; neither is imported into production.
Converting 93.2% and 70.4% to 0.932 and 0.704 does not repair grading differences.

## Delivery

Backend follow-up on #1683; fail-closed presentation guard on #1644. No new database
migration: reviews use the existing bounded metadata column. No live data edits,
paid evaluations, merge, deployment or Linear updates in this unit.
