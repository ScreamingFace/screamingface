# Plan — BTF-3 (binary) as a local inspect Task

Spec: `docs/spec/2026-11-17-btf3-local-task.md` (approved by the contributor, 2026-11-17).
Ledger: `docs/work/2026-11-17-btf3-local-task.md`. Worktree `.claude/worktrees/btf3-local-task`,
branch `btf3-local-task` from `origin/main@ce6b73839`. Loop: `sdlc-python` (failing test first,
tests append-only, hard stop after 10 failed fix attempts).

Paths are relative to `apps/screamingface-engine/` unless they start with `packages/` or `docs/`.

## Files

| File | New/edit | What |
|---|---|---|
| `src/screamingface_engine_inspect/local_tasks/btf3/__init__.py` | new | empty package |
| `…/btf3/btf3.py` | new | pins, the A.1 prompt, loader, scorer `btf3_brier`, metric `btf3_headline`, `@task btf3` |
| `…/btf3/vendor/__init__.py`, `vendor/study_btf_parse.py` | new | the study's `btf_parse` and its regexes, verbatim below our header, sha256-pinned |
| `…/btf3/README.md` | new | the card: data, prompt, reading, scoring, named deviations, licence, contamination |
| `tests/unit/inspect/test_local_task_btf3.py` | new | the Task's contract (below) |
| `prepare.py`, `benchmarks.py` | edit | the imported Case Preparation row and the hand-filled catalogue row |
| `answer_formats/_exact.py` | edit | the row's answer format, proved through the real scorer |
| `pyproject.toml` | edit | fence `btf3/vendor` off ruff, pyright and coverage, like the other vendors |
| shared tables | edit | stand-in metadata, declaration, family, failure policy (+ counts), published revision, fingerprint, whole-run metric |
| `packages/screamingface/scripts/build_notebooks.py`, `examples/23_btf3.ipynb` | edit/new | the example notebook |
| `docs/benchmarks-fidelity/btf3.md` (Engine docs) | new | the Fidelity Record from `sf-benchmark-fidelity` |

## Steps

1. **RED, the contract** with a small in-test parquet (no network): pins; wrong sha256 refused;
   duplicate id refused; the prompt equals the A.1 template filled with the row and
   `present_date[:10]`; target `"1"`/`"0"`; metadata keys; the template's sha256 equals the
   paper's A.1 (spec §11: not the study's shortened copy).
2. **RED, reading:** every example in `btf_parse`'s docstring and the spec's three rules
   (final line, earlier number, none; `65%` never read; `1.0`, `.35`, `*0.35*`).
3. **RED, scoring and headline:** value `1 − (f − y)²` with `brier` on the metadata; no forecast →
   left out; `candidate_abstained` left out; all left out → 0.0; the Task's shape.
4. **GREEN:** write `btf3.py` and the vendor file.
5. **Import:** `uv run python -m screamingface_engine_inspect.importer
   screamingface_engine_inspect.local_tasks.btf3.btf3:btf3 --key btf3 --whole-run-metric honour`;
   hand-fill the row (provenance, licence, named deviations, `coverage_declare`).
6. **Shared tables, answer format, notebook, README.**
7. **Gates** for both stacks; append-only expected red only on the shared tables.
8. **Fidelity record, then `sf-code-review`;** fix or declare findings.
9. **Commit locally** (Yiming Liao), PR draft in `.docs/pr-btf3.md`. Push and PR only on the
   contributor's OK.
