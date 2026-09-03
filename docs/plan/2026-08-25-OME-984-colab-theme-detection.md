# OME-984 — Implementation plan: shared notebook theme detection

Spec: `docs/spec/2026-08-25-OME-984-colab-theme-detection.md` · Stack: screamingface ·
Branch: `OME-984-colab-theme-detection`

## 1. Pin every independent theme block

- Add one parameterized contract test for shared widgets, Leaderboards, both notice variants, and
  both provider-logo variants.
- Confirm only the shared widget block currently passes the Colab selector contract.

## 2. Centralize host detection

- Extract the repeated browser/Colab/JupyterLab/VS Code selector matrix into one internal helper.
- Reuse it without changing any surface's light or dark declarations.

## 3. Verify and publish

- Run focused Leaderboard, notice, connection, and theme-contract tests.
- Run `python3 .claude/scripts/run_gates.py screamingface`.
- Complete the ledger, review the generated CSS ordering, commit, push, and open a draft PR.
