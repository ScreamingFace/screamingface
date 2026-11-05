# E20: external results in the leaderboard

Owner revision, 2026-11-03: imported results belong in the regular table, share
sorting and normal rank numbers, and are distinguished visually by gray styling.
Remove the separate section, explanatory paragraph, repeated external labels and
comparison-note column. “Original result ↗” replaces the recipe action in the existing “Run Locally” column. Non-reproducibility
remains available through hover and screen-reader text. Comparison notes use a
native “Comparison” disclosure in the model cell, readable by touch, keyboard and
screen readers without adding a notes column.

Merge the community top 50 and eligible imported baselines, sort by descending score,
then take the combined top 50 and assign ordinal ranks. On equal scores keep the
existing community order and place community rows before external rows; external
ties retain API order. Limiting after the merge is necessary: assigning ranks to
all external rows below the fetched community page would omit unseen competitors.
Header sorting changes display order, never the score-based ranks.

Summaries and table score tracks describe the displayed rows. Cost-based frontier
claims and replay actions remain community-only. The cost/score chart remains
community-only and retains every fetched community point even when imports push
those runs outside the combined table's top 50. Score-only bars include external
results in gray. The count is labelled “Results shown”. External rows do not
invent cost, authors, providers or run dates; show unknown fields as dashes. The
“Added” column shows community submission dates and first import dates, with an
“Imported on” tooltip on external rows. It does not claim to show source run dates
or when a source was last read.

Preserve native scores, safe text rendering and structural absolute HTTP(S) URL
validation. No new backend/API, migration, dependencies or production import.
Owner policy revision, 2026-11-05: require matching questions/version, complete
coverage, grading and metric; allow documented prompt differences and exact unit
conversions. The portal ranks only baselines whose API `ranking_eligible` is
literal `true`. Missing eligibility from an older API, false, or metadata flags
never grant a rank. Unreviewed rows do not enter summaries or score bars. Prompt
notes in a validated `metadata.comparison` review also use the Comparison disclosure.
The existing SAT-English dev trials have incompatible grading and unverified run
coverage; they remain stored but will not rank. Import history, source health and
the remaining E20 delivery work stay open. Linear writes still require approval.
