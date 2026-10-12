---
ticket: OME-1571
stack: screamingface
status: done
started: 2026-10-11
finished: 2026-10-11
---

# Colab report compatibility — fix the live verification failures

## Intent

Fix the completed report rendering and download failures observed in live Colab for draft #1347. The owner authorized implementing and verifying both fixes. Keep bounded pages, full atomic JSON export, and existing Jupyter behavior.

## Planned changes

- Add a private notebook host adapter for active Colab detection, custom widget initialization, and native Case selection callbacks with cleanup.
- Admit supported ipywidgets 7.7.1 and 8 versions in the notebook extra so Colab's preinstalled compatible widgets are preserved; verify both versions locally and live in Colab before claiming support.
- Deliver Colab exports through google.colab.files.download on the kernel thread, retain a repeatable download button, and retry delivery without rewriting a prepared report.
- Prevent Jupyter file URLs from being advertised in Colab. Retain server-root/base-url links and saved-path fallback elsewhere.
- Add new regression tests; update notebook guidance, spec/plan and draft PR validation.

## Test plan

Write new tests first for active-host detection, optional imports, native delivery, full sync/async exports, repeat clicks, failures and retry, and compatible dependency constraints. Preserve all inherited tests. Run full SDK gates plus a widget-7 UI compatibility check. Rebuild the wheel and exercise paging, exact Case navigation, Candidate filter, ipyevents click synchronization and actual JSON download in live Colab. No paid evaluations.

## Acceptance

Live Colab renders the report, updates page contents/counts, preserves exact Case selection across filters, and downloads complete JSON. Download failures remain retryable; successful repeats do not export again. Both supported widget versions pass relevant local tests, all standard SDK gates pass, independent reviews find no remaining blockers, and the existing draft is updated.

## Outcome

Implemented and verified the completed-report Colab fixes. The optional extra preserves ipywidgets 7.7.1, enables its supported manager, publishes bounded page/export changes inside callbacks, uses native file downloads and native Case selection, and keeps Jupyter async/file-link/ipyevents behavior. Native callbacks carry only row identity, hold a weak browser reference and unregister on collection. Existing inherited tests and approval records are unchanged.

Tests were written RED before host/export/page/dependency fixes; the live Case-click failure demanded an additional RED bridge regression. All **59 focused report regressions pass under both widgets 8 and widgets 7.7.1**. The final required screamingface gate runner passed append-only validation, Ruff lint/format, Pyright, full parallel pytest with **96.18% coverage**, notebook validation, wheel/sdist build and distribution checks. Standards and Spec independently rechecked the final bridge: zero findings each.

In the signed-in fresh Colab notebook, install retained widgets 7.7.1 / ipyevents 2.0.4. After a session restart, the unmodified rebuilt wheel rendered 120 synthetic Case results without manual manager initialization. Actual browser actions verified Previous/Next, Case 59, boundary disablement, Candidate filtering, Case 56 DOM selection reaching Python and surviving reversed Candidate order, unknown-ID warning/recovery, and two native downloads. Both downloaded JSONs equal every field of the source, including all 120 entries. No paid calls ran. Screenshot and structured proof are in `docs/screenshots/2026-10-11-report-pagination/colab-*`.

The broader widgets-7 SDK run had **2733 passed, 26 skipped, 19 failed** before the final two bridge tests were added. Every one of those 19 failures reproduced against unchanged main 4fbdfdce: three existing live-progress tests expect widget-8 `tabbable`; the others reflect widget-7 importing ipykernel and activating progress in headless test transports. Completed reports are verified; this does not establish complete widgets-7 live-progress accessibility. Those unrelated baseline limitations remain explicit in README and PR validation.

## Wisdom

A passing mock of `files.download` does not prove browser delivery, and a visible CSS Case selection does not prove kernel identity. Verify both the real browser file and a later filter using the selected identity. Colab lazily instantiates displayed widget models; an unattached ipyevents model receives no clicks there. Native documented host callbacks solve that seam without changing Jupyter. Capture fresh-runtime controls before attributing failures to stale output or new dependencies.
