---
ticket: OME-1551
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-02
finished:
---

# e2e-image-pdf — prove a url4 ensemble over an image and a PDF end to end on the local stack

## Intent

Closing proof for the OME-1529 execution path: run
`(https://<fixture>/chart.png, https://<fixture>/report.pdf)!"Does the chart appear in the report?"`
as an ensemble (members + fusion synthesizer) on the local stack (engine + aigateway), on top of the
open PR stack #1478 → #1482 → #1587 → #1588, and record every failure with its owning PR. No code
in the PR branches is changed; this branch carries only evidence.

## Planned changes

- `docs/work/2026-11-02-e2e-image-pdf.md` (this ledger, with the evidence appendix).
- `docs/work/2026-11-02-e2e-image-pdf/` — fixtures, harness scripts, trimmed logs (no secrets).

## Test plan

- Local fixture server (counts fetches) behind a public https tunnel (the url4 source guard is
  https-only and refuses loopback by default).
- Ensemble run over the PNG + PDF; checks per the OME-1551 acceptance list.
- Refusal path: a PDF to a model without `pdf` in `input_modalities`.

## Acceptance (OME-1551)

- Fixture server sees each URL fetched exactly once (pinned).
- Every member's and the synthesizer's gateway request carries the image and PDF parts.
- Answer checkable against unambiguous fixtures.
- Image tokens in cost.usage where the provider reports them.
- A text-only model in the ensemble is refused by name before any call.
- No base64 in logs or spans.
- Live test run locally.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:** n/a (evidence-only branch)
- **Deviations:**
