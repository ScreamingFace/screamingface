---
ticket: OME-750
stack: scoreboard
status: done
started: 2026-08-06
finished: 2026-08-06
---

# OME-750 — scoreboard ships Python 3.13 but tests only 3.12

## Intent

`OME-747` moved `apps/scoreboard/Dockerfile` to Python 3.13 on both build stages,
generalizing "every Python matrix in the repo runs 3.12/3.13" from aigateway and
url4-cloud without checking scoreboard, whose `scoreboard-tests.yml` pins a scalar
`python-version: "3.12"` — no matrix. Scoreboard now ships an interpreter its CI never
tests. Fix: extend the workflow to the same `["3.12", "3.13"]` matrix shape as its
siblings, so the shipped interpreter is actually exercised.

This is a CI/workflow config change, not application code — no new product behavior,
so there is no new `apps/scoreboard/tests/**` unit test to write (per sdlc-python's own
TDD framing, there is no failing pytest case a YAML matrix change would "demand").
Verification instead is: (a) the scoreboard suite actually passes when run under both
3.12 and 3.13 locally, and (b) the `OME-749` audit script's `ci_matrix` probe reports
the corrected matrix, per the ticket's own explicit Verify section.

## Planned changes

- `.github/workflows/scoreboard-tests.yml` — add `strategy: matrix: python-version:
  ["3.12", "3.13"]` to the `test` job, and point `actions/setup-python`'s
  `python-version` at `${{ matrix.python-version }}`, mirroring
  `.github/workflows/aigateway-tests.yml` exactly.

## Test plan

- No new pytest test (declarative CI config, no new application behavior).
- Run `uv run pytest` (+ruff+pyright, i.e. the full scoreboard gate suite) under both
  Python 3.12 and 3.13 locally to prove the shipped interpreter is actually green, not
  just declared.
- Run `uv run .claude/scripts/audit_dependabot_ignores.py` and confirm its detail line
  for the scoreboard `python >=3.14` entry now reads
  `scoreboard-tests.yml python-version = ['3.12', '3.13']`.

## Acceptance

- `scoreboard-tests.yml`'s `test` job runs a `["3.12", "3.13"]` matrix.
- The scoreboard gate suite (ruff/pyright/pytest ≥80% cov) passes under both versions.
- The audit script's reported matrix values for the scoreboard entry include both
  `3.12` and `3.13`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `.github/workflows/scoreboard-tests.yml` only, exactly as planned —
  added `strategy.matrix.python-version: ["3.12", "3.13"]` to the `test` job and pointed
  `actions/setup-python` at `${{ matrix.python-version }}`, mirroring
  `aigateway-tests.yml`'s pattern verbatim (+4/−1 lines).
- **Commits:** `b80f73e1` ci(scoreboard): test the Python 3.13 interpreter it already ships ·
  `e596e2c4` ci(scoreboard): name the reporter per matrix leg, publish coverage once.
  Opened as [#516](https://github.com/ScreamingFace/screamingface/pull/516); CI green.
- **Gates:** `uv run --python 3.12 .claude/scripts/run_gates.py scoreboard --base
  origin/main --skip-append-only` → ALL GATES GREEN. Re-ran the same suite under
  `--python 3.13` (fresh `.venv`, no cached 3.12 artifacts) → ALL GATES GREEN — this is
  the substantive proof the ticket asked for (the shipped interpreter is now actually
  exercised, not just declared). `uv run .claude/scripts/audit_dependabot_ignores.py`
  now reports `scoreboard-tests.yml python-version = ['3.12', '3.13']` for the
  scoreboard entry, verbatim match to the ticket's own Verify section. The `python
  >=3.14` ignore for scoreboard correctly stays "blocking" (unaffected — this fix adds
  3.13 coverage, not 3.14, by design).
- **Deviations:** none. No new pytest test was added — this is a declarative CI-config
  fix with no new application behavior, so there is no failing test case it could have
  demanded; verification is the dual-interpreter gate run + the audit probe above,
  matching the ticket's own explicit Verify section rather than an invented unit test.
  `--skip-append-only` used only because the flag is orthogonal to this change (no test
  files touched at all); not a weakening of that gate.

## Review pass (2026-08-14) — three findings, all valid

| Finding | Fix |
|---|---|
| `dorny/test-reporter` name is static while the job is a 2-leg matrix | interpolate `(${{ matrix.python-version }})` |
| the coverage step runs once per leg, so twice concurrently on a PR | guard to the 3.12 leg |
| the `audit_dependabot_ignores.py` AIDEV-NOTE cites scoreboard as *the* scalar case | re-pointed |

**The reporter name mattered more than it looks:** both legs published identically-named check runs,
so a 3.13-only failure was indistinguishable from the passing 3.12 report — which defeats the entire
point of adding the 3.13 leg. Both sibling workflows the PR claims to match "exactly" already
interpolate the version; this one didn't.

**The coverage step** had no `continue-on-error`, so two concurrent runs risk a create/update race
failing the step on an otherwise-green PR, on top of duplicate comments. Guarded to 3.12 — the
shipped floor in `requires-python`, so it is the leg whose number to publish.

**The stale note is a case of this PR invalidating its own justification.** The note explained why the
scalar branch exists by naming scoreboard as the scalar case — and this PR is what gave scoreboard a
list. Verified the branch is still needed before re-pointing rather than deleting: `charts.yml:59`,
`url4-tests.yml:113` and `url4-cloud-tests.yml:102` all still pin a scalar.

**Gates:** all green.
