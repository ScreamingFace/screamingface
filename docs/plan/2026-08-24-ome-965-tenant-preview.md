# OME-965 — tenant Preview automation plan

## Implementation

1. Add failing classification and lifecycle contract tests.
2. Add a standard-library Preview contract helper.
3. Add the same-repository selective image workflow.
4. Add the serialized queue and expiry workflow.
5. Add repository checks for workflow contracts.
6. Add the developer workflow to contributing guidance.
7. Create the managed GitHub labels.
8. Run local contract, repository, and workflow validation.
9. Open and merge the tenant automation pull request after review and green checks.
10. Open an Engine-only fixture pull request and run the live Preview qualification.
11. Replace the manual access-token sequence with one trusted access helper.
12. Add copy-ready debug commands and the correct SigNoz namespace field.

## Files

- `.github/scripts/preview_contract.py`
- `.github/scripts/preview_access.sh`
- `.github/scripts/test_preview_contract.py`
- `.github/workflows/preview-images.yml`
- `.github/workflows/preview-admission.yml`
- `.github/workflows/repo-checks.yml`
- `CONTRIBUTING.md`
- specification, plan, and work records

## Verification

- Path classification covers happy, boundary, rename, chart-only, shared-package, and root inputs.
- Lifecycle planning enforces three slots and 72-hour expiry.
- Workflow contract tests reject `pull_request_target`, fork OIDC, missing exact tags, and missing labels.
- The sample Engine pull request proves image publication, Argo deployment, Runner Jobs, access,
  observability, and deletion.
