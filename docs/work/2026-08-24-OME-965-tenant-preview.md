---
ticket: OME-965
stack: repo
status: in_progress
started: 2026-08-24
finished:
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

- **Actual files:** pending
- **Commits:** pending
- **Gates:** pending
- **Deviations:** pending
