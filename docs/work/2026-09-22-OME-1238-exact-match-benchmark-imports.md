---
ticket: OME-1238
stack: screamingface-engine
status: in_progress
started: 2026-09-22
finished:
---

# OME-1238 — Import the remaining exact-match benchmarks the roadmap names

## Intent

Land the roadmap-named exact-match boards that exist at inspect_evals 0.20.0 (aime24,
aime25) as standard imported rows, and send the rest back to product as scope
corrections. Empirical probe result (2026-09-22, all four targets): **zero import with
the importer as-is** — at 0.20.0 the eval modules import `hf_dataset` from
`inspect_evals.utils.huggingface`, a fully-variadic `(*args, **kwargs)` retry wrapper,
so the recorder's signature-bind buries every real kwarg in the `kwargs` bucket and the
conserved-kwargs guard refuses everything ("hf_dataset kwarg(s) kwargs are not
reproduced"). AIME additionally keeps its prompt template in
`inspect_evals.utils.aime_common`, which `_template_attribute` (task-module-only search)
cannot resolve. GPQA at this pin is not a gated HF dataset (ticket premise stale): it
downloads a sha256-pinned CSV from OpenAI's public blob — no `hf_dataset` at all. HLE
loads its dataset in a helper module and grades with a judge spec (model-graded) — out
of the single-shot deterministic pipeline on both counts.

Unit shape (three PRs off this ticket + one scope-correction comment):

1. **PR1 (this ledger's first iteration):** importer fix — bind through a fully
   variadic wrapper by falling back to `inspect_ai.dataset.hf_dataset`'s signature, and
   flatten any VAR_KEYWORD bucket after binding; extend prompt-template resolution to
   search `inspect_evals`-rooted modules when the task module has no match (exactly-one
   match required, refuse otherwise). Unblocks OME-1253/OME-1256 as well.
2. **PR2:** import aime24 (rows + catalogue prose + board test entries).
3. **PR3:** import aime25 (same).
4. **Ticket comment:** scope corrections — MATH500/RouterBench/HotpotQA absent upstream
   (already verified in the ticket), TruthfulQA task-local mapper refusal, GPQA
   CSV-loader family (premise correction), HLE model-graded.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py` — recorder
  signature fallback + VAR_KEYWORD flattening in `introspect_task`; cross-module
  search in `_template_attribute`.
- `apps/screamingface-engine/tests/` — importer tests for both behaviours (locate the
  existing importer test module and extend it).
- PR2/PR3: generated rows in `pins.py` / `prepare.py` / `boards.py` + per-board test
  entries in the imported-boards test module.
- `docs/tasks/2026-09-21-import-remaining-exact-match-benchmarks.md` — mirror (created
  in PR1; ticket predates this ledger without one).

## Test plan

- RED: a fake eval module whose `hf_dataset` is a `(*args, **kwargs)` pass-through
  wrapper (mirroring `inspect_evals.utils.huggingface.hf_dataset`) — importer must
  record the real kwargs (path/split/sample_fields/revision), not refuse on `kwargs`.
- RED: same wrapper called positionally (path positional) — facts still bind correctly.
- RED: a prompt template defined in a sibling module (not the task module) — resolved
  to `sibling_module:ATTR`; ambiguous (two modules hold the same object) still refuses.
- Existing importer tests stay green and unmodified (append-only).
- PR2/PR3: per-board definition assertions (key, dataset, revision is 40-hex, case
  count, scorer ref, no check surface question — free-text board keeps it on) + offline
  full-bake sanity per the runbook.

## Acceptance

- `python -m screamingface_engine_inspect.importer inspect_evals.aime2024.aime2024:aime2024 --key aime24`
  (and aime2025) emits the three rows with correct split/revision facts.
- GPQA and HLE still refuse loudly (no silent widening of the importable family).
- Gates green (`run_gates.py screamingface-engine`).
- Boards `inspect-aime24` / `inspect-aime25` appear in the imported group of
  `sf.benchmarks.list()` after PR2/PR3.
- Scope-correction comment posted on OME-1238.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — PR1 `importer.py` + `test_inspect_importer.py`
  (3 appended tests) + this ledger + the mirror; PR2/PR3 each: generated rows in
  `pins.py`/`prepare.py`/`boards.py`, `_EXPECTED_FAMILIES` entry + declaration
  roster row + appended fixture bake test.
- **Commits:** `0e89314` fix(screamingface-engine): bind the importer through
  inspect_evals' variadic hf_dataset wrapper (PR #1009, ready); `843ae35`
  feat: import the aime24 board (PR #1010, draft, base #1009); `ec99846`
  feat: import the aime25 board (PR #1011, draft, base #1010).
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN on PR1;
  `--skip-append-only` on PR2/PR3 (prior-test extension paths — owner sign-off
  requested on the ticket). Full-bake offline verified: aime24 30/30 at
  `8d88b28…`, aime25 30/30 at `563bb84…`.
- **Deviations:**
  - "No importer changes" premise false — PR1 exists (wrapper binding +
    cross-module template resolution); pre-sanctioned by the ticket's own
    refusal policy ("extend the importer for this family").
  - GPQA reclassified: not gated-HF at 0.20.0 but a sha256-pinned CSV from
    OpenAI's blob — new snapshot family, sent back to product on the ticket.
  - HLE reclassified: judge-graded at 0.20.0 — outside this pipeline, sent
    back to product.
  - Importer pins-import sort vs ruff-isort mismatch found (`*_DATA_DIR`
    pins); `ruff check --fix` applied in PR2, follow-up noted on the ticket.
