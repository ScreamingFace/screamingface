---
ticket: OME-1839
parent: OME-1138
status: accepted  # owner approval 2026-10-29; changes during the work in §5
created: 2026-10-29
spec: docs/spec/2026-11-05-stage-e-catalog-catch-up.md
---

# Stage E catalog catch-up — plan (OME-1138)

Implements `docs/spec/2026-11-05-stage-e-catalog-catch-up.md`. Both land with the leaf's ledger. One leaf under `OME-1138`, one PR
in `screamingface-design`, and one docs PR here for the spec, plan, ledger and mirror. This mirrors
`OME-1380`: catalog PR #25 there, records in #1076 here.

## 1. Layout

The tools resolve their root as `Path(__file__).parents[2]`. They expect gateway source at
`<root>/apps/aigateway/src` and the catalog at `<root>/solutions/` in the same tree
(`solutions/README.md`, "Reproducible Coverage Checks"). Every run therefore happens in a tree
that carries both. In a `screamingface` worktree `solutions/` is untracked and never staged, and
the projector refuses to version there (§3), so the write runs in a copy of that worktree without
`.git`.

| Tree | Purpose |
|---|---|
| `.claude/worktrees/stage-e-catalog-catch-up` (branch `stage-e-catalog-catch-up` from `origin/main`) | tool tests and export against `main`; holds the ledger, spec and plan |
| a copy of that worktree without `.git` | projection (`project_models.py --write` and `--check`) |
| `.claude/worktrees/catalog-baseline-d35a465` (detached at `d35a46537`) | read-only baseline check; removed after step 2 |
| `screamingface-design-worktrees/stage-e-catalog-catch-up-2026-11-05` (branch from design `origin/main`) | the reviewed catalog delta and its README paragraph |

`solutions/` in both screamingface worktrees is design `origin/main`'s `solutions/`, plus `_tools/`
and `_coverage/` copied from the shared checkout. The shared checkout's `solutions/_tools/` is
backed up outside the repository before it is replaced after the merge (step 11).

## 2. Steps

1. **Ledger first.** Create `docs/work/2026-11-05-stage-e-catalog-catch-up.md` from the template
   (`ticket: unfiled`, Intent, Planned changes, Test plan, Acceptance). Set up the trees in §1, then
   run `uv sync --locked --project apps/aigateway` in each screamingface worktree.
2. **Baseline check, read-only in effect.** In the `d35a46537` tree, run
   `export_contracts.py --write`. It writes only the tree-local untracked `_coverage/contracts.json`
   and the two `openapi.yaml` copies. Then run `project_models.py --check`, and also
   `check_coverage.py --check`.
   - Classify every reported difference. It is either an edit made outside the projector (`5f05b70`
     and any other), or a card whose cited revision differs (the `5e1d30cc` card, and the five at
     `802bed9ae`).
   - Record the list in the ledger. This is the baseline work list; the owner decides what to do
     with each item (spec §8).
3. **RED.** Add failing tests in `solutions/_tools`, run with
   `uv run --locked --project apps/aigateway python -B -m unittest discover -s solutions/_tools -p 'test_*.py' -v`:
   - the extra-schema inventory is `{"usage_accounting"}`, and the `$defs` walk is gone; a model in
     both the OpenAPI and the extra inventory raises, identical or not;
   - the exporter imports no Profile model module, in any import form;
   - retirement list: a listed and absent slug is kept, set `deprecated` and its version is
     unchanged; a listed card missing either file, or its directory, raises; an unlisted
     disappearance raises; a listed slug that is generated again raises;
   - the successor list is closed, and only a successor card carries `relations: supersedes`;
   - in a Git checkout whose `HEAD` tracks no generated card while the working tree holds some,
     `--check` and `--write` refuse and nothing on disk changes.

   Confirm that each test fails for the stated reason. Existing tool tests change only within the
   owner-approved scope (spec §8, items 5, 8 and 9), and the ledger lists each change; anything
   beyond it stops for a question.
4. **GREEN.** Implement in the worktree copy of `_tools`. The five `OME-1413` successor cards are
   not reconciled into the tools; the retirement list keeps them as they are (spec §8, item 4).
   Retries are bounded at 10 per failing signal; on the 10th, stop with a loop diagnosis.
5. **Project `main`.** In the `main` tree, run `export_contracts.py --write`. Then, in a copy of
   the tree without `.git`, run `project_models.py --write` and copy the result back. Review the
   delta card by card:
   - the 17 cards on the retirement list are `deprecated` with version and body unchanged: twelve
     change status only and the five already deprecated do not change;
   - the 32 re-projected live cards advance once, and each change is attributed to the gateway
     commit that caused it, recorded in the ledger;
   - the two successor cards enter at v1 with `relations: supersedes`, and their status is set to
     `approved` by hand; the eight new models enter at `draft` v1;
   - both `openapi.yaml` files drop `ProfileState` and any schema only the retired routes used.

   Unexplained drift stops the step (README: "never accept unexplained drift").
6. **Authored cards** (spec §3.3 and §8, item 6), each advanced exactly once:
   - `profile-defaults`, and the `config` datamodel with its two deprecated inputs;
   - every authored card the full scan found presenting deleted code, renamed hooks or retired
     routes as live;
   - solution `protocol/completions`;
   - a provenance paragraph in `solutions/README.md`.

   Then grep: no card outside the deprecated set cites a deleted module as live.
7. **Source-side gates:**
   - the tool test suite passes;
   - `ruff check` and `ruff format --check` pass on `solutions/_tools` with its `ruff.toml`, run
     from the repository root and from `solutions/_tools`;
   - `export_contracts.py` passes on `main` with no denied I/O attempt;
   - `project_models.py --check` reports no stale artifact in the copy without `.git`.

   `check_coverage.py` is not a gate here (spec §8, item 3).
8. **Import into the design tree.**
   - Copy only the changed files under `solutions/screamingface/` and `solutions/README.md`; never
     `_tools/` or `_coverage/`.
   - Validate with `NEXT_TELEMETRY_DISABLED=1 npx --yes @bershadsky/metaframework@0.7.0 check --dir ./solutions`:
     no errors beyond design `main`, and warnings compared one by one.
   - Run the `--since origin/main` evolution check as in `OME-1380`: it must list exactly the
     changed entities, each existing one advanced once or changed in status only.
9. **Ledger outcome.** Record the actual files, the reconciliation list, the per-card attribution,
   the gates and the deviations.
10. **PR-open, on the owner's explicit word for each external step.** Confirm the leaf first:
    - Title: "Retire the Profile-era models from the AIGateway catalog (Stage E catalog
      catch-up)".
    - Labels `aigateway`, `agentic`, `autonomous`; priority High; parent `OME-1138`; assignee me.
    - Rename both branches to `OME-N-…`.
    - Design PR with `Refs: OME-N`.
    - Screamingface docs PR with the spec, plan, ledger and `docs/tasks` mirror, using
      `pr_template.md`.
    - Both PRs carry no tool mentions and no attribution lines.
11. **Close.** Close comment and Done; close the mirror and ledger. Replace the shared checkout's
    `solutions/_tools/` with the reviewed copy, the owner-approved local edit made after the backup
    in §1. This is not the last leaf of `OME-1138`: `OME-1832` stays in Backlog, deferred until an
    Engine release lets the version-skew fallback go. The epic close-out is proposed only after
    that leaf is done or reparented, or the owner changes the close-out rule.

## 3. Risks

- **Reconciliation is larger than `5f05b70`.** The baseline check measures it before any write. If
  the list is long, report it before step 3 rather than growing the leaf silently.
- **Revision-only differences at the baseline.** The cards cite three revisions (`d35a46537`,
  `5e1d30cc`, `802bed9ae`). A single-revision baseline reports the other two as differences. They are
  expected; step 2 separates them from text edits.
- **Version semantics in file-only mode.** With no Git HEAD under `solutions/`, versions advance
  once per write when content differs (`project_model_versions.py`). Write once from a clean copy
  of design `main`; the `--since` check in step 8 catches a double bump. In a Git checkout where
  the catalog is untracked, every card would read as new and restart at version 1; the projector
  refuses that case before any write.
- **The local exporter's environment.** The exporter imports trusted gateway source under I/O
  tripwires and reads no `.env` or credentials (README). It runs only from the worktree's own
  `.venv`.

## 4. Not in this plan

Committing the tools to a repository; CI for them; renaming the runtime error codes; the
`aigateway-ui` decoder; authored prose for gateway features merged since `d35a46537` beyond what
re-projection produces.

## 5. How the plan changed during the work

The steps above state the plan as executed. They differ from the 2026-10-29 draft as follows,
each recorded in the ledger with the owner's decision (spec §8):

- Step 2 settled the baseline by experiment: the final tools cannot run at `d35a46537` by design,
  because the retirement list raises on a listed model that is generated again there.
- Step 3: the draft's "`supersedes` survives `--write`" test is dropped (spec §8, decision 4).
  16 existing tool tests change or go under the owner-approved scope (spec §8, decision 5): 14
  that encoded the Profile models or the `d35a46537` census, plus the two unit tests of
  `semantic()`, deleted with it.
- Step 4: the draft's reconciliation into the tools is dropped; the retirement list keeps the five
  successor cards.
- Step 5: projection moved to a root without a `.git` marker, because in a Git worktree the
  version step reads the catalog bucket from the code repository's `HEAD`, where it is untracked.
  The projector now refuses that case. `check_coverage.py --write` is not run (spec §8,
  decision 3).
- Step 6: the authored-card list is the full scan result (spec §8, item 6).
- Step 7: `check_coverage.py --check` is no longer a gate. The ruff gate runs from both
  directories, because with an explicit `--config` ruff resolves first-party modules against the
  working directory; the tools' `ruff.toml` now names them.
- Step 8: the catalog check in the design repository, which reads Git history, refused two
  narrowed generated models and the removal of two `config` properties (`E_DM_NOT_ADDITIVE`). The
  projection root has no Git history and cannot see this rule. Resolved by a successor swap and by
  deprecating the two properties (spec §8, items 7 and 8).
- Review of the tools (2026-11-06): three more projector refusals and the fixture changes they
  need (spec §8, item 9).
