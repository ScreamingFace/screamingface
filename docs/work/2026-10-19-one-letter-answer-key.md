---
ticket: OME-1654
stack: screamingface-engine
status: done
started: 2026-10-19
finished: 2026-10-19
---

# one-letter-answer-key — a run of letters is not one multiple-choice option

## Intent

Case Preparation checks that a multiple-choice Case's answer key names one option. It tested
the key against the letters joined as one string (`"ABCD"`), so `"BC"` passed as a substring.
inspect's `choice()` reads `"BC"` as two letters, B and C, so on a one-answer question every
such Case would score 0 with no error. Found in review of OME-1602 PR 5; no row is known to hit
it.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`: compare the key
  against the letters as a list.
- `apps/screamingface-engine/tests/unit/inspect/test_capture.py`: a run of letters is refused.

## Test plan

- "BC", "AB" and "ABCD" beside four choices are refused (failed before the fix).
- The existing key tests still pass: one letter, a choice's value (worldsense), a key naming no
  option.

## Acceptance

- The capture tests, ruff and pyright on the touched files are green.
- The PR's benchmark image build prepares every row's Cases with the fix, so a row that relied
  on the substring match would fail there by name.

## Outcome

- **Actual files:** as planned.
- **Commits:** one fix commit.
- **Gates:** `test_capture.py` (42 passed, the 3 new cases failed before the fix); ruff check
  and format, and pyright on the two files.
- **Deviations:** none.
