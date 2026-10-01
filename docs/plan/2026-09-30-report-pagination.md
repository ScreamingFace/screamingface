> Superseded on 2026-10-01 by [the combined durable-results contract](../spec/2026-10-01-durable-report-results.md). The final UI uses pagination only; search, filters, sorting, CSV, and automatic display-time export were removed by user request.

# OME-1422 implementation plan

1. Add regression for unbounded Report HTML; measure the original output.
2. Stream the existing report.v1 serialization to disk, preserving its field order.
3. Bound static preview, embedded download and failure/detail rendering.
4. Add notebook widget adapter with global search/status/Candidate/category filters,
   sorting, 25-case pages, selected detail and paged full content, JSON/CSV links.
5. Add offline synthetic demonstration, exercise JupyterLab, run SDK gates.
6. Commit and open a draft PR referencing OME-1422; leave JupyterLab running.
