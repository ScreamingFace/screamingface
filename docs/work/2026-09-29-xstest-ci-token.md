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
  safety-board scoring). Four named deviations from inspect's xstest run: (1) the judge is
  the house gpt-5.4, not the default gpt-4o (owner decision); (2) the score is the mean grade
  (C=1, P=0.5, I=0), while inspect reports `refusal_rate` = 100 × (P + I) / N — e.g. 200 C,
  40 P, 10 I gives inspect 20.0 and the board 0.88; convert with
  `100 × (1 − correct / scored cases)`, never `1 − score`; (3) the eval's generic system
  message ("You are a helpful assistant.") is not sent, as with musr; (4) its generate config
  (temperature 0, 256 max tokens) is not applied — no imported board applies one.
- **Review round (PR #1112):** fixed — kind `up.sh` now passes the secret (or skips gated
  boards on purpose) and a test pins every image builder; the refusal_rate deviation is named
  and pinned, and the importer flags an eval's own `metrics=`; a token-present test; the
  `{criterion}` guard parses the template; the paid smoke's token no longer reaches
  `uv sync`; a `SKIPPED` marker names the reason at runtime, and PR builds key the cache on
  token presence; the refusal message points at the repo secret.
- **Why PR builds get the token:** the preview and test builds bake the image from the PR's
  own code, so a same-repo PR author with write access could read the token. Accepted: it is
  a read-only, fine-grained token scoped to reading public-but-gated datasets, and the
  alternative (skipping xstest on every PR) would leave its bake untested until main. Fork
  PRs never receive it. Moving to a bot account later is a new secret value, no code change.
- **Owner-verify:** DONE 2026-09-29 — `HF_TOKEN_BENCHMARKS` set with `gh secret set` (write
  role is enough); a re-run of #1112's image build baked `inspect-xstest_safe` with 250 cases
  (run 36534539095; before the secret it skipped). Still to watch: the first main build after
  merge; a paid smoke press now includes `xstest_safe`, and local recipes need `HF_TOKEN` (or a
  `huggingface-cli login`) from an account that accepted XSTest's terms to include it.
