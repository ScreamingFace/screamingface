# OME-985 — Implementation plan: Client 0.1.1.post5

Spec: `docs/spec/2026-08-25-OME-985-client-post5.md` · Stack: screamingface · Branch:
`OME-985-client-post5`

## 1. Bump package metadata

- Change `packages/screamingface/pyproject.toml` from `0.1.1.post4` to `0.1.1.post5`.
- Regenerate `packages/screamingface/uv.lock` so its local package entry matches.

## 2. Verify the artifact

- Check the lock against the manifest.
- Build the wheel and verify its distribution metadata reports `0.1.1.post5`.
- Run `python3 .claude/scripts/run_gates.py screamingface`.

## 3. Publish the change

- Complete the ledger, commit with `Refs: OME-985`, push, and open a draft PR.
- Keep release-please reconciliation explicitly out of this narrow manual bump.
