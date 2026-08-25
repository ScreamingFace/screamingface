# OME-980 — Implementation plan: HealthBench preparation success summary

Spec: `docs/spec/2026-08-25-OME-980-healthbench-summary.md` · Stack:
`screamingface-engine` · Branch: `OME-980-healthbench-summary`

## 1. Pin the regression

- Add a HealthBench-specific CLI test that patches `_prepare()` with the current summary mapping.
- Assert that `main()` returns zero and renders the professional and declared worst-30 counts.
- Keep this test family-specific because preparer signatures differ between benchmark families.

## 2. Repair the lookup

- Update the stale `worst30_cases` read to `declared_worst30_cases`.
- Do not rename the preparer's audit field or change benchmark preparation behavior.

## 3. Verify and publish

- Run the focused test through RED and GREEN.
- Run `python3 .claude/scripts/run_gates.py screamingface-engine`.
- Complete the work ledger, review the diff, commit with `Refs: OME-980`, push, and open a draft PR.
