---
ticket: OME-1448
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Recovery notice

## Intent

Make recovery discoverable when a notebook next opens after an interrupted evaluation, using the existing ClientNotice information component. The user explicitly steered away from an always-visible pre-run banner; healthy runs stay quiet.

## Planned changes

- Add `_results/recovery_notice.py` for informational copy and best-effort presentation.
- Persist lifecycle/owner markers during preparation, report opening, rendering and export; detect pending evaluations with dead owners when the notebook next initializes a transport.
- Add tests for early sync/async preparation, exact recovery call, opt-out, rich/headless presentation and display failure.
- Add a preview to the existing Report Browser notebook and document the notice.

## Test plan

Write failing notice and preparation tests first. Verify escaping through existing notice renderer, no false guarantee before candidate completion, no notice with storage disabled, and no presentation error affecting evaluation. Run full SDK gates and visually inspect live notebook.

## Acceptance

One notice per detected interrupted evaluation with completed tickets, with exact report ID/directory. Active and successful runs, opt-out, headless and legacy metadata remain quiet. Shared info notice UI; no new report section or styling. Full gates pass and user sees preview.

## Outcome

- **Actual files:** recovery notice/lifecycle helpers; evaluation preparation and report construction; sync/async transport initialization; notebook display and JSON export lifecycle; 23 new targeted tests; README, spec and changelog; preview screenshot. The existing notebook was edited through the UI and saved outside the repository.
- **Commits:** `feat(screamingface): surface recovery after interrupted evaluations` (this iteration).
- **Gates:** All SDK gates green including append-only against HEAD, Ruff/format, Pyright, full tests at >=95% coverage, notebook determinism, wheel/sdist build and distribution checks. Focused recovery/report suite passed (54 tests), followed by final notice tests (23 passed). The full suite includes the small decode/export crash-and-recovery simulation.
- **Visual verification:** Existing shared informational notice rendered in the live JupyterLab notebook. Saved `docs/work/assets/OME-1448-recovery-notice.png`. No styles changed; existing light/dark variants remain shared with other ClientNotice users.
- **Wisdom review:** Show discovery after interruption rather than announcing every successful run. Durable owner/state markers and POSIX process liveness avoid treating active or healthy history as a crash. Lifecycle writes, metadata discovery and presentation are best effort. Legacy records and non-POSIX owner inference remain conservative; explicit recovery stays available independently.
- **Deviations:** User steered the notice from pre-run to post-interruption before commit. No previous committed tests were altered. A new test fixture initially failed typechecking and was corrected. The separate HTML theme-preview page was rejected by browser origin/security policy; no protections were changed or bypassed. The authorized existing notebook was used for the live preview instead.
