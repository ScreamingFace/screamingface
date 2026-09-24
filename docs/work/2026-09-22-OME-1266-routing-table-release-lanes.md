---
ticket: OME-1266
stack: repo
status: done
started: 2026-09-22
finished: 2026-09-22
---

# OME-1266 — Correct the release lanes in the working-in-this-repo routing table

Branch from `origin/main` at `99e2d4b2`.

## Intent

The `working-in-this-repo` skill is the routing map — where you look to answer "how does this
component ship?". Two of its seven release lanes are wrong, and the error has already cost
something: during `OME-1181` I told the owner the scoreboard deploy was a manual tag they had to
cut. False in both halves, and it came straight from this table.

## Verified before writing

`release-please-config.json` lists **all seven** documented components, including the two the
skill says are outside it:

| row | skill says | truth |
| -- | -- | -- |
| `apps/scoreboard` | "**Manual** tag … **not** in release-please" | in release-please, `release-type: python` |
| `packages/url4` | "manual `url4-v*`" | in release-please; `release-url4.yml`'s own header says *"when release-please pushes a `url4-v*` tag"* |

The `on: push: tags:` trigger is real in both workflows, which is what made the error plausible.
Release-please pushes that tag; a human does not.

Six `dev-build-*.yml` workflows exist, all identical in shape: GHCR + `acropenmined.azurecr.io`,
immutable `main-<shortsha>`. The table mentions the dev build for only two of them.

## SCOPE WIDENED — three components are absent from the table entirely

Found while verifying, not in the ticket as filed:

| path | tracked files | CI | CODEOWNERS | in release-please |
| -- | -- | -- | -- | -- |
| `apps/analytics` | 24 | `analytics-tests.yml`, `dev-build-analytics.yml` | @sergio-bershadsky @HupBaHa | **no** |
| `apps/screamingface-studio` | 97 | **none found** | @itstauq | **no** |
| `apps/desktop` | 2 | — | — | — |

`analytics` and `studio` get rows: a routing map that omits a component cannot route to it, and
both have owners and tracked code. That is inside "fix the routing table" even though the ticket
did not name them.

`apps/desktop` does **not** get a row. Its only two tracked files are
`out/main/index.js` and `out/preload/index.js` — build artifacts left behind by the July 2026
teardown that `CLAUDE.md` says removed the app. A `release-desktop.yml` also still exists.
Deleting committed build output and a dead workflow is a code change, not a documentation fix,
and it needs an owner decision. **Raised as a finding, not touched.**

## Planned changes

- `.claude/skills/working-in-this-repo/SKILL.md` — the two release-lane cells, dev-deploy
  information on every row that has a `dev-build-*.yml`, rows for `analytics` and
  `screamingface-studio`, and the shared dev hostnames

## Test plan

**None.** Documentation only, in a skill file with no executable content. The check that matters
is that every claim is verified against the repo, which the Intent records.

## Acceptance

- no row claims a component is outside release-please when it is in it
- every component with a `dev-build-*.yml` says so
- `analytics` and `screamingface-studio` are listed
- the shared dev hostnames are findable from the routing skill
- `check_loop_parity.py` passes (this skill has no shared region, but confirm)

## Outcome

- **Actual files:** `.claude/skills/working-in-this-repo/SKILL.md` only, as planned, plus this
  ledger and the `docs/tasks/` mirror.

- **Gates:** `check_loop_parity.py` — **LOOP PARITY OK**. No other gate applies: this skill has
  no executable content and is in no stack's `run_gates.py` scope. Verified instead by reading
  every claim back against `release-please-config.json`, the six `dev-build-*.yml` workflows,
  `.github/CODEOWNERS`, and the tracked-file listing for each path.

- **Deviations:**

  1. **Scope widened from 2 wrong cells to 4 cells, 2 new rows and 2 notes.** The ticket named
     the scoreboard and url4 release lanes. Verifying them surfaced that the aigateway and
     engine rows also omitted their dev builds while two other rows mentioned theirs, and that
     `apps/analytics` and `apps/screamingface-studio` were absent from the table entirely. A
     routing map that omits a component cannot route to it, so both got rows.

  2. **`apps/screamingface-studio` has NO gating CI.** 97 tracked files, a CODEOWNERS entry
     (@itstauq), three stacks, and no workflow covering the path. Its row says so explicitly and
     calls it a gap rather than a decision, because I could not establish which it is.

  3. **`apps/analytics` has no release lane at all.** Not in `release-please-config.json`, no
     `release-analytics.yml`. Its only artifact is the dev image. Recorded as the fact it is,
     not smoothed over.

  4. **`apps/desktop` documented, not fixed.** Its two tracked files are build artifacts under
     `out/` left by the July 2026 teardown, and `release-desktop.yml` still exists. Deleting
     committed build output and a dead workflow is a code change needing an owner decision, so
     the skill now warns that the directory is not a component and the removal stays open.

  5. **The ticket's "dead dev URL" premise was wrong, and I filed it that way.** I had assumed
     the `nip.io` addresses in the `DEPLOYMENT.md` runbooks were a stale dev pointer, because one
     of them failed when I tried it. Reading them showed they are **examples** of using `nip.io`
     for a throwaway k3s smoke test without real DNS. They are correct as written and were left
     alone. The real gap was that the routing skill never named the shared dev endpoints at all;
     it does now.
