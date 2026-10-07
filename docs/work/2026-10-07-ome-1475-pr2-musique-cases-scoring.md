---
ticket: OME-1475
stack: screamingface-engine
status: done
started: 2026-10-07
finished: 2026-10-07
---

# ome-1475-pr2-musique-cases-scoring — the MuSiQue-Ans scoring core (PR 2 of 4)

## Intent

The second slice of the MuSiQue-Ans Benchmark (spec `docs/spec/2026-10-07-OME-1475-musique-ans.md`,
plan section "PR 2"). It adds the pure pieces the Benchmark is built from, with nothing
registered yet, so nothing is served: the Case Source pins, the byte-frozen prompt, the reply
parser that reads the
Candidate's committed `Supporting paragraphs:` and `Answer:` lines, and a thin typed wrapper over
the paper's own scoring code, copied verbatim from `StonyBrookNLP/musique@922ac98f`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/musique/` (new):
  `__init__.py`, `revision_inputs.py`, `prompts.py`, `answering.py`, `grading.py`,
  `vendor/{__init__.py, metric.py, answer.py, support.py, LICENSE}`
- `apps/screamingface-engine/pyproject.toml`: `musique/vendor` beside `ifeval/vendor` in ruff
  `extend-exclude`, pyright `ignore`, coverage `omit`
- `apps/screamingface-engine/tests/fixtures/musique/dev_two_rows.jsonl` (new, two real dev Cases)
- `apps/screamingface-engine/tests/unit/test_musique_{vendor,grading,answering,prompts}.py`

## Test plan

- Vendored code is the paper's code: each copied file, its one import line restored, hashes to
  the upstream sha256.
- Scorer parity: the spec's reply table, `Denver, CO` against `Denver` + `Denver, Colorado`,
  both-empty support, empty prediction.
- Parser: last label wins, markdown, mixed case, empty label line takes the next non-empty line,
  missing lines, duplicate and non-integer support tokens.
- Prompt: the fixture's first Case renders to a hand-written literal, byte for byte.

## Acceptance

- Every listed test passes; ruff, ruff format, pyright and the layering gate are clean on the
  touched paths; no network call and no model call anywhere.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. New package `benchmarks/musique/` (`__init__.py`,
  `revision_inputs.py`, `prompts.py`, `answering.py`, `grading.py`,
  `vendor/{__init__.py, metric.py, answer.py, support.py, LICENSE}`); the two-Case fixture;
  four test files; `pyproject.toml` excludes `musique/vendor` from ruff, pyright and
  coverage beside `ifeval/vendor`.
- **Commits:** one commit on `OME-1475-pr2-musique-cases-scoring`,
  `feat(screamingface-engine): score MuSiQue-Ans replies with the paper's own scorer (OME-1475, PR 2 of 4)`.
- **Gates:** from `apps/screamingface-engine`: `uv run pytest tests/unit/test_musique_*.py -q`
  70 passed · `uv run ruff check` clean · `uv run ruff format --check` 757 files already
  formatted · `uv run pyright` (whole project) 0 errors · `check_layering.py` OK. Free extra
  checks, not committed: Case Preparation over the real local dev file (download replaced)
  prepared all 2,417 Cases with hop split 2hop 1,252 · 3hop 760 · 4hop 405, matching the spec;
  the wrapper's per-Case scores averaged over all 2,417 Cases equal the official
  `AnswerMetric`/`SupportMetric` totals to 1e-12 on synthetic predictions.
- **Deviations:**
  - **Case Preparation moved to PR 3.** The pre-push gate's full suite failed
    `test_the_family_guard_covers_every_family_preparer_package`: every
    `benchmarks/<family>/prepare.py` must belong to a registered Benchmark, and registration is
    PR 3. `prepare.py` and `test_musique_prepare.py` (written and green here) move to PR 3
    unchanged; the plan was updated in PR 1. The Case Preparation deviations below travel with
    them.
  - `prepare(out)` returns the audit summary (the plan said `None`): the asset-bundle port is
    `Callable[[Path], Mapping]` and every built-in preparer returns its summary. `emit` returns
    it and adds a `hop_types` count.
  - The count check lives in `parse_rows(data, *, expected_count=EXPECTED_CASES)`; the plan
    named the check but not its home. `prepare` passes the pin at call time.
  - `validate_row` is a little stricter than "2 to 4 supporting": the id prefix must be one of
    the six known hop types and the supporting count must equal its hop count (true on every
    pinned Case); titles and paragraph texts must be non-empty; `question_decomposition` must be
    present.
  - `Paragraph` is a frozen dataclass in `prompts.py` (the plan named the type, not its home).
    The template is exposed as `CASE_TEMPLATE`, `PARAGRAPH_TEMPLATE`, `PARAGRAPH_SEPARATOR` for
    PR 3's revision hash. The rendered input has no trailing newline, as the spec's block ends.
  - The prompt test pins the frame as a hand-written literal and the real 9,261-character Case
    by its sha256, computed from the spec's template by a standalone script before
    `prompts.py` existed, rather than a 9,261-character literal.
  - `vendor/LICENSE` has one trailing space and the final blank line trimmed, so the repo's
    whitespace hooks pass without touching `.pre-commit-config.yaml`; its words are unchanged and
    the vendor docstring says so. The three `.py` files are byte-identical but for the import.
  - The parser cuts an `Answer:` value at a same-line `Supporting paragraphs:` label and the
    reverse, so the two labels never swallow each other; support numbers are ASCII digit runs.
