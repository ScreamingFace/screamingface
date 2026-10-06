# E14 implementation plan — rules for every PR

Spec: `docs/spec/2026-10-06-e14-reproducible-submission/` (approved by the owner on 2026-10-06).
Read `00-overview.md` §6 for the PR map, and the PRD that your PR names.

## Local only

- **Do not push. Do not open a PR. Do not file or change Linear issues.** Everything stays in the
  local worktree and branch you are given. (Owner instruction, 2026-10-06.)

## Process

1. Work only in your worktree. Never `cd` to the shared checkout. Never `git stash`.
2. Create the work ledger `docs/work/2026-10-06-<branch-name>.md` from `docs/work/TEMPLATE.md`
   (`ticket: unfiled`, `status: in_progress`). Fill `Outcome` at the end.
3. TDD: write the RED test first, run it, and see it fail for the right reason. Then GREEN. Then
   refactor on green. The PRD's TDD table is the test list, in that order. `CHAR` tests pass on
   today's code by design.
4. **Append-only tests:** do not edit or delete an existing test. If a change really needs one,
   STOP and report it as a question.
5. Commits: conventional commits, scoped to the component (for example
   `feat(scoreboard): …`). Several small commits are good. **No `Co-Authored-By` trailer.**
   End the message body with `Refs: OME-1307`.
6. Gates: from the worktree root run
   `python3 .claude/scripts/run_gates.py <stack> --base e14-reproducible-submission-spec`
   (for a stacked PR, `--base` is the parent branch named in your plan). The stack names are
   `scoreboard`, `aigateway`, `screamingface-engine`, `screamingface`. Run `uv sync` in the app
   directory first. For `screamingface`, run `uv sync --extra runtime --extra notebook`.
7. **No Docker on this machine.** Tests that need Postgres skip. Say which ones skipped. Never call
   a skipped test "passed".

## Code rules (from CLAUDE.md and the repo)

- Hexagonal: core never imports plugins. Plugins register into core registries.
- Match the exemplar file named in your plan: structure, naming, comment density, error style.
- Comments follow the repo idiom (`INVARIANT:`, `WHY`, `FEATURE: OME-1307 —`). Keep them short.
- No new abstractions, flags or helpers beyond the plan. Touch only the files the plan lists. If you
  must touch another file, report it as a deviation.
- Tortoise FKs: use the native `<attr>_id` column (`fields.ForeignKeyField("models.Score",
  related_name=…)` gives `score_id`). Do not use `source_field`. Use `on_delete=fields.CASCADE` for
  the new child tables.

## Report (your final message)

1. What you built (1–2 sentences) and the commit list (`git log --oneline <base>..HEAD`).
2. Deviations from the plan or PRD, each with the reason. An empty list is a claim.
3. Gate result lines, exactly as printed, and the list of skipped tests.
4. Open questions. If a design decision is missing, STOP and ask instead of guessing.
