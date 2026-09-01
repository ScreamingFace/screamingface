---
ticket: OME-1028
stack: repo
status: in_progress
started: 2026-08-27
finished:
---

# OME-1028 — Fix release-please token so releases are created by the repository

## Intent

The release-please CI/CD pipeline has failed on every push to `main` since 2026-08-23:
the action uses `RELEASE_PAT` (which has lost release-creation permission) instead of
the repository token, so the pending releases for `url4 1.5.0` and
`screamingface-engine 1.4.0` cannot be created. This unit switches the release-please
action to `GITHUB_TOKEN` so releases are created by the repository.

## Planned changes

- `.github/workflows/release-please.yml` — release-please action `token:` →
  `${{ secrets.GITHUB_TOKEN }}` (+ comment). Checkout step keeps `RELEASE_PAT`.
- `docs/tasks/2026-08-27-OME-1028-release-please-token.md` — mirror (this unit).
- `docs/work/2026-08-27-OME-1028-release-please-token.md` — ledger (this unit).

## Test plan

- No test suite applies (workflow YAML change). Verification is the next
  `Release Please` run on `main` creating the pending releases.

## Acceptance

- Release-please action uses the repository token; `RELEASE_PAT` remains only on the
  lockfile-sync checkout step.
- Next push to `main` creates the pending releases (url4 1.5.0, screamingface-engine 1.4.0).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `.github/workflows/release-please.yml` (token → GITHUB_TOKEN + comment); `docs/tasks/2026-08-27-OME-1028-release-please-token.md`; `docs/work/2026-08-27-OME-1028-release-please-token.md`
- **Commits:** 6f923601 — fix(ci): use the repository token for release-please releases
- **Gates:** n/a (workflow YAML change; no test suite applies)
- **Deviations:** none
