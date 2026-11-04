# Benchmark catalog summary

Owner approved 2026-11-03. Implements OME-1763 comment's option C and OME-1383.

GET /v1/benchmarks/summary returns {benchmarks: [{id, display_name, description,
focus, best_score}]}. Only listed benchmarks. Null best_score means no eligible
ranked submission, not zero. Preserve the existing top=1 card meaning: entries,
not baselines; no added verified flag filter. Registered revision and complete-run
rules match leaderboard ranking; legacy unpinned boards retain their behavior.
No recipes, authors, cost/frontier details or provenance. Existing /benchmarks stays
unchanged for SDK/private-board discovery. No stored or response cache introduced.

A single database statement joins benchmarks and eligible scores, selects the
newest best run per spec/revision, then the earliest claim among tied specs. It
returns at most one candidate per benchmark for decoding, matching top=1 ranking.
Registered scope is read in that statement. A second, final bulk visibility read
excludes boards made private during selection, matching the existing exit guard.
No participant-data await follows that check. Query count remains constant (two).

Homepage: names A-Z (ID tie-break); visible labeled search by name/ID, whitespace
trimmed and case-insensitive; Has scores checked by default; zero and negative
scores qualify. Search/filter before nine-card batches. Show total matching count,
clear-search action, and include-unscored action retaining the query. No matches
because of the score filter must not imply the benchmark is unsupported. Endpoint
failure shows an error, never an empty scored catalog. No frontend N+1 fallback.

Measure first usable cards, all-ready time, request count, payload bytes and server
latency. Network replay is a controlled model, not a production latency guarantee.

## Corrupt data handling (review, 2026-11-04)

A corrupt top candidate must not fail other catalog cards. Preserve the former
homepage's top=1 behavior: choose the same top candidate as ranking (including
per-spec newest-on-tie collapse), then decode it; if it is unreadable or its score
is non-finite, publish best_score=null for that benchmark. Do not promote a lower
candidate when top=1 would have dropped the selected row. Healthy cards and metadata
remain available. Two fixed reads and the final visibility check remain required.
