---
ticket: OME-1439
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# inverted-grade-views — show the inverted_grade mark in the catalogue and the notebook report

## Intent

PR 3 of the OME-1400 stack (spec `docs/spec/2026-09-30-safety-refusal-score.md` §5, ticket
OME-1439). PR 2 put `inverted_grade` into report.json; a researcher in a notebook should see it
before choosing a Benchmark (the catalogue listing and a Benchmark's card) and while reading a
result (the report view's header). Plain words, existing styles only.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/catalog_contract.py` + `_engine/catalog.py`
  — decode the catalogue entry's `inverted_grade` (absent → False, non-bool refused).
- `packages/screamingface/src/screamingface/discovery.py` — `Benchmark.inverted_grade`.
- `packages/screamingface/src/screamingface/_ui/cards.py` — an "inverted grade" chip on the
  listing row and an explanatory line on the Benchmark card, only for a flipped Benchmark.
- `packages/screamingface/src/screamingface/_ui/report_view.py` — one plain line under the
  report header for a flipped Benchmark.
- `tests/public_surface_snapshot.json`, `CHANGELOG.md`.

## Test plan

- The listing's `Benchmark` carries the mark from the catalogue (absent → False, non-bool refused).
- A flipped Benchmark's listing row has the chip and its card the line; an ordinary one has
  neither (its markup is unchanged).
- The report view of a flipped Benchmark's report says each Case scores 1 − the eval's grade;
  an ordinary report's header is unchanged.

## Acceptance

- `sf.benchmarks` listing, a Benchmark's card and the notebook report view show the mark in
  plain words for `xstest_unsafe`, and nothing for every other Benchmark.
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`CONTEXT.md`, `_engine/catalog_contract.py`, `_engine/catalog.py`,
  `discovery.py`, `_ui/cards.py`, `_ui/report_view.py`, snapshot, CHANGELOG), plus the new
  `tests/test_inverted_grade_views.py`; both OME-1400 and OME-1439 mirrors closed here (last PR).
- **Commits** (hashes after the rebase onto PR 2's review fixes): `62874543d`
  feat(screamingface): show the refusal-rate mark in the catalogue and report view (PR 3 of the
  OME-1400 stack) · `94e166439` docs(screamingface): say the catalogue mark needs both Engine
  changes deployed · then the review-fix commit: plain attribute access in the report view so
  pyright catches a rename, the catalogue decoder reads the shared `INVERTED_GRADE_KEY`, and its
  docstring no longer names PRs by number · then the glossary commit: `CONTEXT.md` gains
  **Inverted Grade**, the entry spec §5 promised, so OME-1400 closes with every spec line delivered.
- **Gates:** `run_gates.py screamingface --skip-append-only` green (ruff, format, pyright,
  pytest + coverage ≥95%, notebooks, build, distribution). The skip is owner-approved for the
  regenerated public-surface snapshot (`Benchmark` gains a defaulted field). Visual check: the
  listing chip, card line and report header line rendered headless with the existing styles.
- **Deviations:** one shared sentence (`INVERTED_GRADE_MEANING` in `_ui/cards.py`) serves all
  three views, so a researcher meets the same words everywhere.
