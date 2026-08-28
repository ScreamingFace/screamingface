---
id: OME-1034
linear_url: https://linear.app/openmined/issue/OME-1034/fix-the-broken-readme-quickstart-and-the-docs-errors-a-first-time-user
status: done
type: task
priority: P2
labels: [py-screamingface, autonomous, agentic]
created: 2026-08-28
closed: 2026-08-28
---

# Fix the broken README quickstart and the docs errors a first-time user hits

An external tester ran `screamingface==0.1.1.post5` on macOS against the published docs and the
top-level README. Line 1 of the README's ensemble example raises `TypeError` — `sf.Fusion` takes a
keyword-only `synthesizer` with no default. The README also promises an `sf.from_url4(...)` entry
point that does not exist, and `sf.__version__`, the first thing anyone types to check what they
installed, raises `AttributeError`.

Fifteen line-level corrections, verified against `main` at `9d5f015b`:

- Items 1-3 — broken code and a wrong return-type claim in the two READMEs.
- Item 4 — add and export `sf.__version__`, pinned by test against the installed distribution
  metadata so it cannot drift from `pyproject.toml`. This is the only code change, and the reason
  the landing leaf is `py-screamingface`.
- Items 5-7 — docs-site corrections: the ports FAQ tells users to kill a process when the CLI
  would have moved the port; links inside the orange "Note:" callouts render as plain body copy;
  the Pipelines page opens with a diagram of a Fusion.
- Items 8-13 — prose fixes in the tester's own wording.
- Items 14-15 — link the LANL *Beyond Leaderboards* paper (OpenReview `XSIYfTm2h7`), and give the
  benchmark CTA a destination.

Owner decisions carried in the ticket: fix the README rather than add an `sf.from_url4` alias, and
point the benchmark CTA at GitHub Issues rather than the unmerged report-intake service
(`OME-1002`).

Out of scope: `github.com/OpenMined` → `github.com/ScreamingFace` URL rewrites (`OME-914` /
`OME-945`, landing separately), and null per-member `usage` / `duration_ms` (`OME-699`,
`OME-1030` / `OME-1031` / `OME-1032`).

Ledger: `docs/work/2026-08-28-OME-1034-readme-and-docs-fixes.md`.
