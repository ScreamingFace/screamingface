---
ticket: OME-1269
stack: screamingface-engine
status: done
started: 2026-09-29
finished: 2026-09-29
---

# xstest-ci-token — CI token for gated datasets and the xstest_safe board (OME-1269, PR 3 of 3)

## Intent

Ship XSTest's safe half: 250 harmless prompts that sound dangerous, graded by an LLM judge for
over-refusal. It needs two mechanisms the bake lacked (a gated dataset needs a token; a
judged board may have no answer key) and the CI wiring that hands the bake a read-only token.
Spec: `docs/spec/2026-09-29-inspect-task-route-bake.md` §2b.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py` — `gated`,
  `has_answer_key`, the token rule in `prepare_snapshot`.
- `boards.py` — `_check_answer_key_opt_in`; the `xstest_safe` board. `importer.py` — the
  Hub gate observation. `pins.py` — the importer's pins.
- `apps/screamingface-engine/Dockerfile.benchmark`; workflows `dev-build-screamingface-engine`,
  `release-screamingface-engine`, `preview-images`, `screamingface-engine-tests`,
  `screamingface-paid-inspect-smoke`.
- Tests in `test_inspect_snapshots.py`, `test_judged_board_assembly.py`,
  `test_inspect_importer.py`, and the two board-registry files.

## Test plan

Empty key still refused without the opt-in; the opt-in bakes an empty target but still needs
a question; gated without a token refuses by name, skips with the switch, never skips a public
board; assembly refuses the opt-in without a judge or with a judge prompt that reads the key;
the importer observes the gate; the board's judge prompt equals upstream's.

## Acceptance

Ticket acceptance 4 for `xstest_safe` (250, ids equal to inspect's own load); acceptance 6 as
far as it can be checked before merge (see Owner-verify).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** one on `OME-1269-ci-token-xstest`, stacked on `OME-1269-pubmedqa-board`.
- **Gates:** ruff check, ruff format --check, pyright (0 errors), check_layering OK,
  `pytest --cov` 4606 passed / 44 skipped, coverage 93.67%; inspect lane 480 passed;
  `.github/scripts/test_preview_contract.py` 19 passed; the five workflows parse as YAML.
- **Real checks (read-only token, passed only as an env var, file deleted after):** the
  importer writes the `xstest_safe` row with 250 cases and `gated=True`; the production bake
  gives 250 cases whose ids and prompts equal inspect's own `xstest(subset="safe")`, each with
  an empty target. With no token (cached login hidden) the bake refuses by name; with the skip
  switch it warns and writes nothing.
- **Secret pattern probe:** a throwaway image with the same RUN shape sees the token with
  `--secret id=hf_token,...` and not without it; the token appears 0 times in
  `docker history --no-trunc`.
- **Deviations:** the unsafe subset is not shipped (owner decision; OME-1400 designs
  safety-board scoring). The judge is the house gpt-5.4, not inspect's default gpt-4o (owner
  decision). The eval's generic system message ("You are a helpful assistant.") is not baked,
  as with musr. The eval's `GenerateConfig(temperature=0, max_tokens=256)` is not reproduced:
  no imported board reproduces a task's generate config.
- **Owner-verify:** (1) set the `HF_TOKEN_BENCHMARKS` repo secret with
  `gh secret set HF_TOKEN_BENCHMARKS --repo ScreamingFace/screamingface` BEFORE this merges, or
  the next main build fails by name; (2) watch that main build bake `inspect-xstest_safe`;
  (3) a paid smoke press now includes `xstest_safe`.
