# OME-1425 plan — "Closed weights" contrast

Spec: `docs/spec/2026-10-08-OME-1425-closed-weights-contrast.md`.

1. RED: new `apps/scoreboard/tests/unit/test_portal_weights_contrast.py`. It parses `portal.css` and `tokens.css` with `tinycss2` (new dev dependency, so no regex over CSS). It asserts:
   - the closed rule exists with selector `.status.status--closed:not(.on)` and colour `var(--ink-2)`;
   - both modifier rules beat `.status:not(.on)` on specificity;
   - the resolved `--ink-2` reaches at least 4.5:1 on `--bg` and `--surface` in the light and dark token blocks.
2. No new JS test. The markup class comes from `renderOpenness` in `benchmark.js`, which has no DOM-free test seam, and the change there is one class name.
3. GREEN: in `portal/portal.css`, add `.status.status--closed:not(.on) { color: var(--ink-2); }` and raise the open rule to `.status.status--open:not(.on)`. In `portal/benchmark.js`, emit `status status--closed` for closed rows. Update the comments that say closed takes the whisper tone.
4. Gates: the scoreboard card list (ruff, ruff format, pyright, pytest with coverage, the named node suites).
