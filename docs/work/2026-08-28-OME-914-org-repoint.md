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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
