---
ticket: OME-1414
stack: repo
status: done
started: 2026-09-29
finished: 2026-09-29
---

# dependabot-sweep — Clear the open Dependabot backlog to zero

## Intent

13 Dependabot PRs are open (#940–#1066). Goal: zero open Dependabot PRs. Unlike OME-1171, the
owner decided to merge every green PR regardless of CODEOWNER (advisory only), and to clear the red
#1025 by re-verifying the aigateway LiteLLM runtime guard (separate unit, litellm-guard-1-102).
Release-please PRs (#852 #773 #768) are out of scope — merging them publishes releases.

## Planned changes

- `docs/work/2026-09-29-dependabot-sweep.md` — this ledger
- `docs/tasks/<date>-OME-1414-dependabot-sweep.md` — Linear mirror at PR-open

Merged on GitHub, squash, never `--admin`, in lockfile-cluster order:
#1023, #942, #991→#940, #990→#1021, #1026, #1024, #1022→#945, #985→#1066 (#1066 only after the
guard unit lands, so the packaged `litellm==1.102.0` never outruns aigateway's verified version).

## Test plan

No executable code. Safety = each PR's own CI green + `mergeStateStatus: CLEAN` at merge time,
re-checked between merges of PRs sharing a lockfile; `@dependabot rebase` on DIRTY/BEHIND.

## Acceptance

- `gh pr list --author app/dependabot --state open` returns `[]`.
- No red repo workflow on `main` after the last merge.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** this ledger, `docs/tasks/2026-09-29-OME-1414-dependabot-sweep.md`, and the
  OME-1405 mirror flipped to `done`. No application code in this unit (the guard work is
  OME-1405 / OME-1407).
- **Merged (squash, green, CLEAN, no `--admin`) — 22 Dependabot PRs:**
  - original backlog: #1023 #942 #991 #990 #1026 #1022 #985 #940 #1021 #1024 #945
  - superseding / late arrivals: #1117 #1119 #1122 #1126 #1127 #1128 #1130 #1131 #1132 #1133 #1135
  - plus the guard PR #1118 (OME-1405) — not a bot PR.
- **Closed by Dependabot as superseded (not merged):** #1025 → #1122, #1066 → #1119.
- **Result:** `gh pr list --author app/dependabot --state open` → 0 at 2026-09-29T17:06Z.
- **LiteLLM alignment:** `apps/aigateway/uv.lock` and `packages/screamingface/pyproject.toml`
  both at `1.102.1` on `main`; guard asserts `1.102.1` (OME-1407). Packaged pin never ran ahead
  of the guard: #1119 merged only after #1122.
- **Gates:** no `run_gates.py` — docs only. Safety = each PR's own CI at merge time.
- **Deviations:**
  1. **Scope grew 13 → 23.** Every merge triggered Dependabot refresh runs that superseded two
     PRs and opened ten new ones. Zero is a point-in-time state, not a durable one.
  2. **#945 rebased before merge** (`@dependabot rebase`) because #1022 had changed the same
     `package-lock.json`; vitest 5 coverage verified running (240 tests, v8 report).
  3. **litellm 1.102.1 released mid-sweep** → a second pin move (OME-1407) committed directly
     onto Dependabot's #1122 branch by owner choice. Treadmill follow-up: OME-1408.
  4. **Merge-loop bug:** a zsh loop over `$open` did not word-split, so a 90-min auto-merge loop
     merged nothing (errors swallowed by `|| continue`). Re-run under explicit `bash`.
  5. **CI runner backlog** for ~20 min after the burst of merges (jobs QUEUED, not failing).
  6. **Red `Dependabot Updates` runs on `main`** (cryptography, incl. dirs that no longer exist:
     `apps/server`, `apps/url4-cloud`, `apps/screamingface-studio/runtime`) — Dependabot's own
     security-refresh jobs against stale dependency-graph entries, same class OME-1171 noted.
  7. **Watch item:** #1133 moved `actions/setup-node` and `actions/upload-artifact` 6 → 7 in
     `screamingface-paid-inspect-smoke.yml`, which PR CI does not exercise; confirm on its next run.
