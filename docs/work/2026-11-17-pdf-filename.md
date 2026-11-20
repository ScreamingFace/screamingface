---
ticket: OME-1942
stack: screamingface-engine
status: implemented
started: 2026-11-17
finished:
---

# pdf-filename — a url4 PDF always reaches the model with a filename

## Intent

A url4 `src=` attachment has no filename, so the engine sent the PDF as a file part without one. OpenAI models (via OpenRouter) then ignore the file, or reject it with 400, and the run still answers (gpt-4o-mini read nothing in the image-input matrix). Every file part now carries a filename.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/attachment_parts.py`: `_part` always sets `filename`; default `attachment.<ext>` from the media type (`attachment.pdf` pinned; `mimetypes` for others; bare `attachment` when unknown).
- `tests/unit/test_attachment_parts.py`: two appended tests; four expected parts gain `filename` (owner-approved, `.claude/test-change-approvals/OME-1942.json`).

## Test plan

- `test_a_pdf_without_a_filename_gets_a_default_one` (RED before the fix), `test_a_given_filename_is_kept`.

## Acceptance

- Every file part sent to the gateway has a `filename`; a given filename is kept; engine and repo gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the approval file and the OME-1942 mirror.
- **Commits:** see PR.
- **Gates:** engine and repo green vs origin/main (see PR).
- **Deviations:** the ticket asked for the URL's last path segment as the name. url4 never records the source URL on an attachment, so that needs a url4 change; owner chose the engine default now (`attachment.pdf`). Also not done here: why the gateway returned 200 when the provider answered 400 (left on the ticket as a follow-up).
