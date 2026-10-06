---
ticket: OME-1459
stack: repo
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1459-inspect-import-doc — Document what we take from an inspect eval and which ScreamingFace component runs each step

## Intent

One architecture page in the Engine's docs that answers, for every field of an inspect `Task`,
whether we take it, read it as a gate, or replace it with our own rule, and for every step of
inspect's `eval()`, which ScreamingFace component does it instead. Today that knowledge is spread
over the OME-1113 spec (pre-Task-replay), the OME-1273 spec (one fetch path), a stale how-to and
a chat transcript. The ticket (`OME-1459`) is the spec for this unit: it fixes the five sections,
the three verdicts and the acceptance list, so no separate `docs/spec` artifact is written.

## Planned changes

- `apps/screamingface-engine/docs/importing-an-inspect-eval.md` — new; the five sections from the
  ticket, every inspect claim pinned to inspect_ai `0.3.263` / inspect_evals `v0.20.0` lines.
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md` — a link to the new doc in its
  first screen.
- `docs/spec/2026-09-09-OME-1113-inspect-evals-import.md` — same link, first screen.
- `docs/spec/2026-09-30-OME-1273-task-replay-import.md` — same link, first screen.
- `docs/tasks/2026-10-02-OME-1459-inspect-import-doc.md` — mirror.

## Test plan

- No code changes, so no unit tests. Checks instead:
  - every `Task.__init__` parameter at inspect_ai 0.3.263 appears in table 1 exactly once
    (diff the signature against the table);
  - every GitHub permalink resolves to the quoted line (fetched and checked);
  - the doc uses only `CONTEXT.md` terms (grep for the banned synonyms: row, sample, dataset as a
    noun for Cases, question).

## Acceptance

- The five ticket acceptance points: doc at the path with the analogy + Before / After diagram and
  five sections; every `Task` field has one verdict and every `eval()` step names one component;
  every inspect claim cites a pinned line; the how-to and both specs link to it in their first
  screen; `CONTEXT.md` gains no term.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the two diagrams the doc embeds
  (`apps/screamingface-engine/docs/diagrams/inspect-import-before-after.{drawio,png}` and
  `inspect-eval-split.{drawio,png}` and `inspect-vs-screamingface-seams.{drawio,png}`, drawio `sf-dark`; the split PNG is palette-quantised to
  stay under the 500 KB `check-added-large-files` limit).
- **Commits:** `33f009bbd` docs(screamingface-engine): document what we take from an inspect eval and who runs each step; plus this ledger sha commit.
- **Gates:** no code, so no test gate. Checks run instead: all 37 `Task.__init__` parameters
  (33 + 4 deprecated aliases) appear in §1 exactly once (scripted grep against the signature);
  the 24 inspect source files cited are byte-identical between the installed 0.3.263 / 0.20.0
  packages and the GitHub tags (fetched and diffed), so every line number is a valid permalink;
  72 of the 74 GitHub links fetched with HTTP 200 (the other two are tag-tree pages with no raw
  form); every Engine `symbol · file:line` cited was printed and matched; glossary-banned words
  grepped (none left outside the exam analogy).
- **Deviations:** the ticket's table sketch put `name` under "read as a gate" and `metrics`
  under "take"; the code puts the Benchmark key on `--key` (required, `Task.name` is never
  read) and surfaces custom metrics only as a review flag, so the doc files `name` under
  "replace with ours" and `metrics` under "read as a gate". The ticket's "19 of 46 Benchmarks
  on Task replay" counts the open PR stack; on `main` it is 28 Benchmarks, all Hugging Face
  path, and the doc marks the three states (on main / in open PRs / later) rather than
  describing the stack as built. No sandbox or agentic refusal exists on `main` (an unknown
  solver gets a `TODO(review)` flag); the doc says so and marks the refusal-by-name as later.
  The how-to's grader-role line ("not supported yet", stale since OME-1370) is corrected in this
  PR after review, since the page it now links to says the opposite.
  Status marks were refreshed on 2026-10-02 after capture rendering landed as open PR #1219
  (the stack is now #1219 → #1191 → #1220 → #1221; #1194 and #1198 are closed): capture is 🔧,
  not ⏳, and `capture.py` lines cite #1219 at its tip `1c2967c31`. Review round 1 (2026-10-02)
  fixed: sevenllm's source is a Hub raw file, not GitHub; capture adds a rendering for Task-replay
  Benchmarks and does not delete the imitation one (OME-1460 does); gsm8k and sad are not under
  capture in the stack; the `no_network` grading test exists only on the Task-replay branches;
  OME-1460's "27" counts xstest's two rows as one, `main` has 28 Hugging Face-path rows.
