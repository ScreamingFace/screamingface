---
ticket: OME-914
stack: repo
status: in_progress
started: 2026-08-28
finished:
---

# OME-914 / OME-945 — Repoint the remaining org references, and link the README issue tracker

Executed as ONE unit on one branch: `OME-914` is the docs/portal/public-docs half and
`OME-945` is the PyPI-metadata/README half of the same sweep. Follow-up to `OME-910`, which
deliberately fixed only the references a GitHub org redirect cannot cover.

## Intent

The repo moved from the `OpenMined` org to `ScreamingFace`. GitHub's redirect still resolves
every stale link, so this is hygiene, not breakage — but the redirect is revocable, and a
reader who copies a stale URL out of the docs spreads it further. Repoint every live
`github.com/OpenMined/screamingface` reference to the canonical org, leave every reference
whose whole point is to name the OLD org, and give the README's "just open an issue" sentence
a real destination so reporters land on the tracker instead of guessing.

## Planned changes

### The URL sweep (OME-914)

Rewrite `github.com/OpenMined/screamingface` → `github.com/ScreamingFace/screamingface` in:

- `CONTRIBUTING.md` (clone URL)
- `apps/scoreboard/portal/{benchmark,data,index,spec}.html`
- `apps/screamingface-studio/src-tauri/tauri.conf.json` (live updater endpoint)
- `packages/screamingface/scripts/build_notebooks.py` + the generated
  `packages/screamingface/examples/06_draco.ipynb` (both sides, so the determinism gate holds)
- `public-docs/src/navigation/sf-client.ts`, `public-docs/src/pages/learn/*.vue`,
  `public-docs/src/pages/sf-client/guides/*.vue`
- `docs/` — `PROJECT-OVERVIEW.md`, `plan/`, `spec/`, `tasks/`, `work/`, `scream-lisbon-digest.md`

Plus three bare-prose (non-URL) references that name THIS repo as a live fact:

- `.claude/README.md` — "Everything Claude-related in `OpenMined/screamingface`"
- `docs/plan/2026-07-15-url4-pypi-release-cicd.md` — the **pending** Trusted Publisher owner action
- `docs/spec/2026-07-15-url4-pypi-release-cicd-spec.md` — the same pending owner action

### The README issue link (OME-945)

- `README.md` — turn "just open an issue" into a link to the issues page.

## Deliberately NOT touched

The exclusion rule this unit applies: **a reference stays when naming the old org IS the
point of the sentence, or when the path belongs to a different repo.**

| Left alone | Why |
|---|---|
| `apps/aigateway/CHANGELOG.md`, `apps/aigateway-ui/CHANGELOG.md`, `apps/screamingface-engine/CHANGELOG.md`, `packages/url4/CHANGELOG.md` (103 occurrences) | Correct when written; rewriting falsifies release history. Ticket-mandated. |
| `OpenMined/sf-installer` in `release-aigateway.yml` / `release-aigateway-ui.yml` | A genuinely different repo, still OpenMined-owned. Ticket-mandated. |
| `OpenMined/screamingface-brand` (9 occurrences across `docs/plan/`, `docs/spec/`, `docs/tasks/`, `docs/work/`) | **Different repo.** Prefix-matches the sweep pattern — the pattern guards on a trailing `-`. |
| `OpenMined/screamingface-benchmarks` (`docs/PROJECT-OVERVIEW.md`) | **Different (private) repo.** Same prefix hazard. |
| The `AIDEV-NOTE (OME-910)` blocks in `.github/workflows/release-screamingface.yml` and `release-url4.yml` | They name the old org as the STALE value that no longer matches the OIDC claim. Rewriting makes the sentence self-contradicting ("an entry registered against `ScreamingFace/screamingface` no longer matches"). Also outside the ticket's file list. |
| `docs/work/2026-08-20-OME-910-repoint-org-refs.md` | Historical assertions *about* the old string ("No `OpenMined/screamingface` occurrence remains…"). Zero URL hits in the file. |

`packages/screamingface/pyproject.toml` and `packages/url4/pyproject.toml` needed **no
change** — see Deviations.

## Test plan

No behaviour change, so nothing to RED/GREEN. Verification is by grep and by the affected
packages' own gates:

- `grep -rn "github.com/OpenMined/screamingface"` returns only the CHANGELOG hits plus the two
  sibling-repo paths (`-brand`, `-benchmarks`).
- No sibling-repo path (`-brand`, `-benchmarks`, `sf-installer`) was rewritten.
- `run_gates.py screamingface` green — the notebook determinism gate proves the generator and
  the committed notebook still agree after both were edited.
- `run_gates.py url4` green.
- public-docs: `vue-tsc --noEmit`, `vite build`, `oxlint`, `eslint`.

## Acceptance

- Every live in-repo reference to this repo names `ScreamingFace/screamingface`.
- Release history, the OIDC failure-mode notes, and the three sibling repos are untouched.
- The README's "open an issue" sentence links to the issues page.

## Outcome

- **Actual files:** 37 tracked files changed — the 34 swept files, plus `.claude/README.md` and
  `docs/spec/2026-07-15-url4-pypi-release-cicd-spec.md` (prose-only, no URL to sweep), plus
  `README.md` for the OME-945 link. Two planned targets turned out to need no change — see
  Deviations.
- **Commits:**
  - `00e61533` — docs(work): open the ledger and mirrors for the org repoint sweep
  - `0379e66d` — docs: repoint the remaining org references to ScreamingFace
  - `bad978f1` — docs(readme): link the issue tracker from the providers invitation
- **Gates:**
  - `run_gates.py screamingface` — ALL GATES GREEN (8 gates: append-only check, ruff check,
    ruff format, pyright, pytest `--cov-fail-under=95`, `check_notebooks.py`, `uv build`,
    `check_distribution.py`). The notebook gate is the load-bearing one here: it proves the
    generator and the committed notebook still agree after both sides were edited.
  - `run_gates.py url4` — ALL GATES GREEN (5 gates).
  - public-docs — `vue-tsc --noEmit`, `oxlint`, `eslint` and `vite build` all exit 0. Linters were
    run WITHOUT `--fix` so the gate reports rather than silently rewrites unrelated files.
- **Final grep:** 110 `github.com/OpenMined/screamingface` occurrences remain, every one
  deliberate — 103 in the four CHANGELOGs, 3 sibling-repo paths (`-benchmarks` in
  `docs/PROJECT-OVERVIEW.md` and `docs/scream-lisbon-digest.md`, `-brand` in
  `docs/work/2026-08-21-OME-928-cache-provenance-band.md`), and 4 in this ledger and the OME-914
  mirror, which quote the old string to document the exclusion rule.
- **Deviations:**
  - **`OME-945`'s first item was already satisfied on `main`.** Both
    `packages/screamingface/pyproject.toml` and `packages/url4/pyproject.toml` already declare
    `Homepage`, `Repository` and `Issues` under `ScreamingFace/…`. The ticket read the divergence
    as two-sided; it was one-sided — the docs were the only stale half. No edit made; the README
    link is the whole of OME-945.
  - **The ticket named `README.md` as carrying stale org URLs. It carries none** — its only
    GitHub link (the clone URL, line 109) was already canonical. Its only change is the OME-945
    issue link.
  - **`docs/PROJECT-OVERVIEW.md` and `docs/scream-lisbon-digest.md` were planned as sweep targets
    but needed no change** — their only hits are `OpenMined/screamingface-benchmarks`, a different
    (private) repo that prefix-matches the sweep pattern. Caught by the trailing-hyphen guard.
  - **Judgment call, flagged for review:** the two `2026-07-15` url4-PyPI documents were rewritten
    even though they are dated historical artifacts, because the reference sits under
    "Owner actions (post-merge, pre-publish)" — a checklist item that `OME-910` records as **still
    open**. That is a claim about work not yet done, not a claim about the past, so correcting it
    fixes a pending instruction rather than falsifying history. The CHANGELOG rule was applied in
    the opposite direction for the release-workflow `AIDEV-NOTE` blocks, where the old org is the
    stale value being described and rewriting would make the sentence contradict itself.
  - Branched from `upstream/main`; this clone's remote is named `upstream`, not `origin`.
  - The fresh worktree's `screamingface` venv lacked the `notebook` extra, so `pyright` failed on
    unresolved `ipywidgets` before any gate ran. Fixed with `uv sync --all-extras` in
    `packages/screamingface` — an environment gap, not a code change.

- **⚠️ OPEN — not done by this change:** the branch is committed locally only. Nothing was pushed,
  no PR was opened, and both issues remain **In Progress**. `OME-914` and `OME-945` close on merge
  with the card's `close_template`. A rebase on `main` is likely needed first: `OME-1034` is
  editing `README.md` and several `public-docs/src/pages/sf-client/` files concurrently, and this
  branch expects to land second.
- **⚠️ Still OPEN from `OME-910`, untouched here:** the PyPI Trusted Publisher entries for the
  `url4` and `screamingface` projects still name `OpenMined/screamingface` in the PyPI console.
  Repointing the docs does not repoint PyPI — that remains an owner action.
