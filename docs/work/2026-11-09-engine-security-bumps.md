---
ticket: OME-1853
stack: screamingface-engine
status: done
started: 2026-11-09
finished: 2026-11-09
---

# engine-security-bumps — land Dependabot's four Engine security bumps and re-seal the three Benchmarks they change

## Intent

Dependabot PR #1566 bumps the Engine's `pypdf` 6.19.0 → 6.21.4, `certifi` 2026.7.22 → 2026.10.18,
`filelock` 3.32.6 → 4.2.1 and `pillow` 12.3.0 → 13.0.0, all four behind open high or critical
alerts on the Security tab (`OME-1853`). It is red on "Build the deployable images" because
three Benchmarks fail their Case Digest check: Pillow 13 re-encodes every MMMU multiple-choice
and MathVista picture to different PNG bytes, and pypdf 6.21 extracts cyse4's report text
differently. A Case id is the hash of its content, so all three Case sets change.

Owner ruling (2026-11-09, this session): bump all four for security, re-seal the three Case
Digests, and keep the three published revisions, since there are no official leaderboard runs
for these Benchmarks yet. The doc's rule ("changed Cases → move the id") is overridden on
purpose; each row says so.

## Planned changes

- `apps/screamingface-engine/pyproject.toml`, `apps/screamingface-engine/uv.lock` — the four
  bumps, cherry-picked from #1566 (`8efd60b74`) so the lock is the one CI already resolved.
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py` — new `case_digest`
  and `case_set_digest` for `cyse4_threat_intelligence`, `mmmu_multiple_choice`, `mathvista`,
  with a comment naming the old values, the cause and the hold ruling.
- `apps/screamingface-engine/tests/unit/inspect/test_benchmark_fingerprints.py` — the three
  computed fingerprints move; `test_published_revisions.py` does not.
- `docs/tasks/2026-11-09-OME-1853-security-tab-burndown.md` — mirror of the ticket.

## Test plan

- The Case Digests are sealed inside a linux/amd64 Engine image built from this branch, the
  same path CI's strict image build runs: `case_digest` must equal the values CI printed on
  #1566 (cyse4 `096a744d…`, mathvista `9a4a85c3…`, mmmu `419ddea2…`); `case_set_digest` comes
  from the same run.
- `tests/unit/inspect/test_benchmark_fingerprints.py` and `test_published_revisions.py`:
  fingerprints move, published ids hold.
- `uv lock --check`; ruff and pyright on the touched Python file.
- CI's "Build the deployable images" job green is the outside judge.

## Acceptance

- The four packages sit at the fixed versions on the Engine lock.
- The strict image build confirms all three Benchmarks' Cases.
- `inspect-mmmu_multiple_choice`, `inspect-mathvista` and `inspect-cyse4_threat_intelligence`
  keep their published ids (`5b008891134ef4c1`, `ca4cd0f692d18f0e`, `92558cfb773e64d2`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the ledger itself.
- **Commits:** `c9a084ff6` chore(deps): bump the screamingface-engine-python-security group
  (Dependabot's `8efd60b74`, cherry-picked unchanged); then this unit's commit
  `fix(screamingface-engine): re-seal MMMU, MathVista and cyse4 after the security bumps`.
- **Gates:** re-seal inside a linux/amd64 Engine image built from this branch (OrbStack,
  Rosetta): cyse4 587 Cases `096a744d…` in 317 s, mathvista 1000 `9a4a85c3…` in 100 s,
  mmmu_multiple_choice 847 `419ddea2…` in 689 s, every case_digest equal to the value CI's
  strict build printed on #1566; case_set_digest from the same runs. `tests/unit/inspect` with
  the inspect extra: 2,936 passed in 5 min 8 s (the two pin files alone: 188). `uv lock
  --check` clean; ruff, ruff format and pyright clean on the two touched Python files. CI's
  "Build the deployable images" job is the outside judge, pending at PR-open.
- **Deviations:** the doc's rule says a changed Case set moves the published id; the owner
  ruled to hold all three ids (no official leaderboard runs; cyse4 shows 4 non-official
  entries on production). Each row and each fingerprint literal carries that ruling.
- **Owner-verify:** CI image build green on the PR; then the next three PRs of OME-1853.
