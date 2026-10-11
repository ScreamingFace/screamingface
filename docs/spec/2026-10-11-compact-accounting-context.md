# Compact accounting context and cache

User authorized the next draft slice from #1156 on 2026-10-11. #1241 and #1269 are merged.

Derive exact global operation/judge attribution, nullable unattributed run cost and consistency using bounded per-Case iteration. Preserve public accounting rows, report JSON, Named Scores, archive savings and inherited assertions. Persist only compact derived context beside saved indices; bind it to index and candidate metadata, validate cached values, rebuild stale/damaged caches, and preserve derived values when optional cache writes fail.

Use context for current run/case cost disclosures without changing HTML or controls. Do not eagerly decode all Cases during recovery to populate the optional cache. No public API, schema, dependency, Engine, notebook pagination/browser or lifecycle changes. Full HTML rendering still materializes its output; public accounting still materializes requested rows.
