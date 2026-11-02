---
ticket: OME-1803
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# pdf-admission — refuse a run at admission when a model can't take PDFs

## Intent

Spec `OME-1760` (§3 item 4, §4 table) makes PDF refusal an engine admission rule: when a
Benchmark's Cases carry a PDF, every model of the linked Candidate (members, synthesizer,
reducer, nested Fusions) must list `pdf` in the gateway's published `/v1/models`
`input_modalities`, or the run fails with the permanent url4 `intent_error` naming each such
model, before any model is paid. The gateway's 422 `unsupported_content_part` stays the
backstop. This extends the picture admission that `OME-1548` (#1584) landed, reusing its port
(`ModelSightReader`), its one `/v1/models` read per run, and its owner-decided failure posture
(an unreadable list fails the run as retryable with nothing spent; a model the gateway does not
list lacks the modality).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/picture_admission.py`:
  per-modality need detection (`image_url` -> `image`, `file` -> `pdf`), a generic
  "models lacking a modality" helper, and a PDF refusal alongside the unchanged picture refusal.
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`: the unreadable-list
  message names pictures or PDFs, not pictures only.
- New tests: `apps/screamingface-engine/tests/unit/test_pdf_admission.py`.

## Test plan

- Unit: a Case with a `file` part needs `pdf`; a picture Case needs `image` only; a text Case
  needs nothing; a model whose list lacks `pdf`, or that the gateway does not list, is named.
- End to end through `Url4Executor` on a scripted gateway: a mixed Fusion whose member can't
  read PDFs is refused with permanent `intent_error` naming only that member, zero chat calls;
  a PDF-capable lineup runs with one model-list read; an image-only model (`text`,`image`) is
  refused for a PDF Benchmark; a PDF-only lineup on a picture Benchmark is still refused by the
  picture rule; an unreadable list fails a PDF run as retryable with zero chat calls.
- C9 unchanged: every existing `test_picture_admission.py` test passes untouched.

## Acceptance

- A PDF Benchmark run whose Candidate names a model without `pdf` fails before any chat call
  with `intent_error` naming the model; picture admission behaviour is unchanged; gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `benchmarks/picture_admission.py`, `world/connector.py`
  (unreadable-list message only), new `tests/unit/test_pdf_admission.py` (14 tests).
- **Commits:** see branch `OME-1803-pdf-admission` (one `feat(screamingface-engine)` commit).
- **Gates:** `run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN
  (append-only, ruff, ruff format, pyright, layering, pytest + coverage >= 80).
- **Deviations:** the brief assumed picture admission had not landed; `OME-1548` (#1584) was
  already on `main`, so this extends its port and inherits its owner-decided posture (unreadable
  `/v1/models` fails the run as retryable with nothing spent; an unlisted model lacks `pdf`)
  instead of choosing a new one. Same scope as pictures: Runner runs only, Candidate models only
  (graders are text-only, spec D6). One refusal names every gap when a file needs both types.
- Owner decisions (Sergey, 2026-11-02): when `/v1/models` can't be read, a PDF run fails closed the same way a picture run does; the PR opens before spec #1597 merges, with that dependency stated in the PR body.
