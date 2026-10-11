---
id: OME-1571
linear_url: https://linear.app/openmined/issue/OME-1571/paginate-notebook-report-results-with-exact-case-navigation-and
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
created: 2026-10-11
---

# Paginate notebook report results with exact Case navigation and complete downloads

Fourth SDK slice from #1156 after #1241, #1269 and #1345 merged. Parent epic OME-1294; related large-report bug OME-1422, umbrella OME-1448 and accounting OME-1570.

Browse 25 Case results per live page, filter Candidates and navigate exact retained IDs. Keep only page payloads in notebook state; bound static previews and inline JSON; prepare complete streamed JSON downloads on demand. Preserve merged report fields and compact accounting, with optional notebook dependencies and retryable sync/async failures.

Acceptance and implementation evidence: `docs/spec/2026-10-11-report-pagination.md`, corresponding plan and work ledger. Before/after screenshots are saved under `docs/screenshots/2026-10-11-report-pagination/`. Lifecycle discovery/notices remain a separate slice.

Live Colab verification revealed widget-manager incompatibility and an invalid localhost file link. Follow-up spec/plan/work: `2026-10-11-colab-report-compatibility`. Preserve Colab's compatible widgets, publish its page changes within callbacks, and use its native download API while retaining the Jupyter async/server-link path.

Colab follow-up verified: completed report paging, exact navigation, native Case clicks/filter focus and two actual complete JSON downloads pass in restarted Colab with widgets 7.7.1. All final SDK gates pass (96.18% coverage); two independent reviews have zero findings. The broader widgets-7 run’s 19 live-progress/headless failures all reproduce on unchanged main and remain documented. Draft remains open for owner review.
