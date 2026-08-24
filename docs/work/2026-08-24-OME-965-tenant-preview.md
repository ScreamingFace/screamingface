---
ticket: OME-965
stack: repo
status: done
started: 2026-08-24
finished: 2026-08-24
---

# OME-965 — implement tenant Preview automation

## Intent

Complete the tenant-owned half of pull-request Preview environments. Build only changed images,
publish them through the dedicated Azure identity, manage the bounded Preview lifecycle, and give
the pull-request author exact access and observability instructions.

## Planned changes

- `.github/scripts/preview_contract.py`
- `.github/scripts/test_preview_contract.py`
- `.github/workflows/preview-images.yml`
- `.github/workflows/preview-admission.yml`
- `.github/workflows/repo-checks.yml`
- `CONTRIBUTING.md`
- `docs/spec/2026-08-24-ome-965-tenant-preview.md`
- `docs/plan/2026-08-24-ome-965-tenant-preview.md`
- this ledger

## Test plan

- Run the Preview contract unit tests.
- Run repository checks.
- Validate workflow YAML and security invariants.
- Run one Engine-only live fixture after the automation merges.

## Acceptance

- Only same-repository pull requests receive Preview registry access.
- Only affected deployable images build.
- Engine selection builds the paired benchmark image from the exact Engine image.
- Exact-revision readiness precedes the `preview` label.
- Three-slot admission and 72-hour expiry are serialized.
- The pull-request comment contains URLs, access commands, and SigNoz filters.
- The fixture Preview creates, qualifies, and deletes without manual cluster changes.

## Outcome

- **Actual files:** The planned helper, tests, workflows, checks, contributor guide, and
  work artifacts changed.
- **Commits:** `test: define tenant preview contract` and
  `feat: automate tenant preview environments`.
- **Gates:** 11 contract tests pass. Ruff check, Ruff format, Python compilation,
  YAML parsing, and `git diff --check` pass.
- **External state:** All required status, component, and image labels exist in the tenant repo.
- **Deviations:** Linear was unavailable. The owner-authorized OME-965 work item continues
  as the repository-wide Preview automation unit.
- **Access follow-up:** Replace the error-prone token sequence with a trusted-main helper.
  The helper handles Cloudflare login, GitHub identity, safe download, and kubeconfig validation.
- **Output follow-up:** Show exact deployment log commands and explain the pull-request namespace limit.
