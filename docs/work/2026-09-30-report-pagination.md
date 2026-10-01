---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-09-30
finished: 2026-09-30
---

> Superseded on 2026-10-01 by [the combined durable-results contract](../spec/2026-10-01-durable-report-results.md). The final UI uses pagination only; search, filters, sorting, CSV, and automatic display-time export were removed by user request.

# Bounded notebook report browsing

## Intent

Preserve the complete Report while bounding notebook output. User approved the summary,
search/filter/page/detail/export UX and requested a local JupyterLab trial and draft PR.

## Planned changes

Report widget, bounded static fallback, streaming JSON export, regression tests and a
synthetic ContractEval-sized demonstration notebook.

## Test plan

Measure existing rendering growth; assert bounded output for 4,182 long Cases, global
filtering/sorting, duplicate identities across Candidates, paging boundaries, escaping,
lossless streaming export and export errors. Run the SDK gates and notebook UI smoke.

## Acceptance

Existing summary styling; only one page and one detail loaded into widget state;
complete results recoverable from disk; all/filtered exports distinct; no paid calls.

## Validation evidence

- Original `pytest tests/test_report_browser.py -q -s` on 4,182 synthetic Cases:
  115,208,221 HTML bytes; the 500,000-byte output assertion failed.
- Bounded static output for the same fixture: 323,250 bytes. Interactive widget state
  is tested below 100,000 bytes; only 25 Case labels and one selected detail are present.
- Full export equals `to_json()` byte-for-byte without calling whole-Report `to_dict()`
  or `to_json()`. Failed writes preserve an existing complete export.
- JupyterLab smoke: Next page, search finds Case 4,182, filtered CSV exports one Case,
  full-content page 2 reaches the contract's final text. JSON download HTTP 200,
  application/json, attachment, 62,342,523 bytes for the synthetic demo.
- Full gate runner passed append-only, lint, formatting and pyright, then stalled in
  an existing transport disconnect test after 699 passed. Unchanged main at fd565a2f
  reproduces the same test timeout. With 15-second diagnostic timeouts, the two
  synchronous/asynchronous disconnect tests fail; the remaining report regression was fixed.
- Broad suite excluding those two existing reconnect tests: 2,091 passed, 26 skipped,
  28 deselected (26 paid tests plus 2 reconnect tests), 96.20% coverage.
- Final focused report suite: 90 passed; final lint, formatting and pyright clean.
- Additional focused tests cover failed/ungraded filtering, duplicate Case IDs across
  Candidates, global score sorting, export errors, download base URLs, and full-text escaping.
- Notebook-generation checks, wheel/sdist build and distribution-content checks passed.

## Outcome

Implementation and local trial complete; draft PR for review. Changes stay in the Client SDK.
The Report remains in kernel memory; this bounds display/serialization duplication, not
Engine ingestion. Interactive display creates a persistent sidecar snapshot and needs a live
kernel. Category filtering uses retained metadata and is hidden when none is available.

**Deviation:** the draft is intentionally opened with the two baseline reconnect tests
recorded as failing/stalled; no existing tests were weakened or edited. No Linear comment or
closure was posted. Screenshot: `assets/OME-1422-report-browser.png`.
