# E20: external results in the leaderboard

Owner revision, 2026-11-03: imported results belong in the regular table, share
sorting and normal rank numbers, and are distinguished visually by gray styling.
Remove the separate section, explanatory paragraph, repeated external labels and
comparison-note column. “Original result ↗” replaces the recipe action in the existing “Run Locally” column. Non-reproducibility
and comparison notes remain accessible through hover and screen-reader text.

Merge the community top 50 and valid imported baselines, sort by descending score,
then take the combined top 50 and assign ordinal ranks. On equal scores keep the
existing community order and place community rows before external rows; external
ties retain API order. Limiting after the merge is necessary: assigning ranks to
all external rows below the fetched community page would omit unseen competitors.
Header sorting changes display order, never the score-based ranks.

Summaries and table score tracks describe the displayed rows. Cost-based frontier
claims and replay actions remain community-only. The cost/score chart remains
community-only; score-only bars include external results in gray. External rows do not invent cost, authors, providers or run dates;
show unknown fields as dashes and the import date in a titled date cell.

Preserve native scores, safe text rendering and structural absolute HTTP(S) URL
validation. No new backend/API, migration, dependencies or production import.
This accepts shared ranking for this increment; import history, source health and
broader comparability policy remain E20 work. Linear writes still require approval.
