---
ticket: OME-1471
stack: repo
status: done
started: 2026-11-09
finished: 2026-11-09
---

# fidelity-agent-fixes — four gaps the first Imported-Benchmark audits found in the fidelity agent

## Intent

The first two audits of Imported Benchmarks (ZeroBench, MaCBench; dry runs against PRs #1706 and
#1705) worked, and showed four gaps in `.claude/agents/sf-benchmark-fidelity.md`: the verdict
rule did not say which wins when bounds already exceed tolerance while items are still open; the
strongest evidence (the authors' own recorded replies) was not in the recipe; nothing said what to
do with a gated dataset; and bare file names made two same-named files indistinguishable. This
unit closes OME-1471's own acceptance, so it carries `Refs: OME-1471` and no new ticket.

## Planned changes

- `.claude/agents/sf-benchmark-fidelity.md` — verdict precedence; recorded-replies recipe;
  gated-dataset fallbacks; citation prefixes, no bare file names.
- `docs/spec/2026-11-06-OME-1471-benchmark-fidelity.md` §2.3, `CONTEXT.md` (Fidelity Verdict),
  `apps/screamingface-engine/docs/benchmarks-fidelity/README.md` — the same precedence wording.
- `apps/screamingface-engine/docs/benchmarks-fidelity/ifeval.md` — its citations given tree
  prefixes, so the one committed record follows the new rule.
- `docs/tasks/2026-10-05-OME-1471-benchmark-fidelity.md` — one line for this PR.

## Test plan

- Prose only; no code changes. `run_gates.py repo` (mirror gate) green.
- `just engine fidelity-check` still reads `ifeval` fresh after the record's citation edit.
- Every citation in `ifeval.md` opened again after re-prefixing.

## Acceptance

- The verdict rule states its precedence identically in the agent file, spec, glossary and README.
- The agent file names the recorded-replies check, the gated-dataset fallbacks and the citation
  prefixes, each with the audit that motivated it.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus Step 1 of the calling-session section (give bare names their prefix).
- **Commits:** see the PR.
- **Gates:** `run_gates.py repo` green; `just engine fidelity-check` → ifeval fresh, 93 no record (the record's citation edit does not touch the fingerprint). Every re-prefixed citation in `ifeval.md` reopened: ours, fork and inspect_evals lines checked against the pinned files; Google's `evaluation_lib.py:121-130,188-211` at `0eebfd4` checked for the first time and correct.
- **Deviations:** no new ticket; this PR finishes OME-1471's acceptance (owner merged #1700 and asked for the follow-up). The ZeroBench and MaCBench records from the dry runs are not in this PR; they belong to #1706 and #1705.
