> Superseded on 2026-10-01 by [the combined durable-results contract](../spec/2026-10-01-durable-report-results.md). The final UI uses pagination only; search, filters, sorting, CSV, and automatic display-time export were removed by user request.

# OME-1422 — bounded Report display

Approved in the originating user conversation: compact summary, searchable/filterable
Case browser, explicit pagination, selected Case detail, and lossless full export.
Keep existing visual language and report.v1 semantics. Never embed the full export in
large notebook output. Persist a JSON snapshot before interactive rendering. Widgets
hold only the current page and selected detail; filters apply to all Candidate Results.
Long full content is readable in bounded text pages. Static HTML remains a bounded,
explicitly labeled preview when notebook widgets are unavailable.

JSON preserves every original field. CSV is an analysis convenience, with exact nested
Case content included as JSON. Filtered CSV is explicitly labeled and never replaces
the complete JSON snapshot. No engine/evaluation/storage protocol changes.
