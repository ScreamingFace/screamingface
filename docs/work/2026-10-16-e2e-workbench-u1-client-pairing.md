---
ticket: OME-1637
stack: screamingface
status: in_progress
started: 2026-10-16
finished:
---

# e2e-workbench-u1-client-pairing — explicit scoreboard pairing + Access token seeding

## Intent

Unit 1 of the e2e notebook workbench (epic OME-1636). Close the publication hole where a
non-default engine silently paired with the hosted (public) leaderboard, and let a
person-started unattended run reach a hosted Engine through `SCREAMINGFACE_ACCESS_TOKEN`.

## Planned changes

Per `docs/plan/2026-10-16-e2e-workbench-u1-client-pairing-and-token.md` (tasks 1–2), plus the
user-facing snippet follow-up the breaking change requires.

## Test plan

`tests/test_default_client_pairing.py`, `tests/test_access_env_token.py` (sync + async +
malformed tokens), the existing auth/discovery/public-surface suites.

## Acceptance

`configure()`/env path raise without a scoreboard for a non-default engine; the default engine
in any spelling still pairs; a valid env token is used without a browser login; full SDK gates.

## Outcome

- **Commits:** spec + plan docs; `feat(screamingface)!: require an explicit scoreboard…`;
  `feat(screamingface): pre-seed the Access login…`; `docs: pair every non-default engine…`;
  `test(screamingface): AsyncClient sends a valid env Access token…`.
- **Gates (on the full workbench branch, unit 1 ⊂ it):** `pytest -n auto --cov` 4235 passed,
  35 skipped, coverage 97.02%; ruff, ruff format, pyright, `check_notebooks.py` clean. On this
  unit-1-only tree: see the PR checks.
- **Deviations:** origin compare is casefolded (an upper-case default host must not raise);
  `test_default_client_local_discovery`/`test_public_surface` changed to remove the leak
  (approved, `.claude/test-change-approvals/OME-1637.json`); examples `generated_by_version`
  regenerated to the current package version; `sf.Client(...)` deliberately unchanged.
- **Review round 1 (HupBaHa, CHANGES_REQUESTED on PR #1438):** blocker 1 — Access tokens are
  parsed once and strictly (finite `exp`/lifetime/expiry, NaN/Infinity refused, non-empty
  JSON header + decodable signature, future `nbf` rejected), no-echo test extended; blocker 2 —
  an Access challenge over plain HTTP raises `access_requires_https` and no token is sent
  over HTTP or ws (sync + async); non-blocking — the hosted-default check normalizes the
  scheme-default port (`:443`), "proves" → "asserts", umbrella spec/ledger updated to the
  real OME-1636/OME-1637 state.
