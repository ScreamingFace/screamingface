---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done
started: 2026-11-09
finished: 2026-11-09
---

# fidelity-sweep — a Fidelity Record for every catalogue Benchmark

## Intent

OME-1471 shipped the record format, the check script and the audit agent with one calibration
record (IFEval). `just engine fidelity-check` read `1 fresh, 93 no record`. This unit runs the
`sf-benchmark-fidelity` agent over every Benchmark the catalogue declares and lands one record per
Benchmark under `apps/screamingface-engine/docs/benchmarks-fidelity/`, so the Leaderboard's
"our score beside the paper's number" claim has a reviewed verdict behind it for every row.

Order (owner, 2026-11-09): first the nine Benchmarks on the Asana SOTA board (FrontierScience,
MuSiQue, ARC-AGI-2, MMLU-Pro, FRAMES, HLE, MMMU, MathVista, LAB-Bench), then every Benchmark that
already has Leaderboard entries, then the rest.

## Planned changes

- `apps/screamingface-engine/docs/benchmarks-fidelity/<id>.md` — one per catalogue id, written
  from the agent's report after every cited `file:line` is opened and checked.
- Nothing else: the agent is read-only on the checkout, bumps no pin, edits no Case, scorer or
  README. Anything it finds is a finding in the record, not a fix.

## Test plan

- No new code. `just engine fidelity-check` must read `fresh` for every record landed and
  `0 orphan record`; it exits 1 on a malformed record or a `parity_test` path that does not exist.

## Acceptance

- Every record in the PR reads `fresh`; its `audited_at` is the branch base sha.
- Every `match` cell names a command and output lines or two source locations; every
  `unverified` / `not-comparable` carries its reason in the front matter.
- PRs stacked by batch (board nine → scored → rest), each one reviewable.

## Outcome

- **Actual files:** 93 new records under `apps/screamingface-engine/docs/benchmarks-fidelity/`
  (IFEval's was already there), plus this ledger. No code, pin, Case, scorer or README changed.
- **Commits:** three stacked branches off `main` at `43d3942f6`:
  `fidelity-sweep-pr1` `48fe0ec5b` (19 SOTA-board records) →
  `fidelity-sweep-pr2` `d9ed5a3e2` (36 Leaderboard-scored records) →
  `fidelity-sweep-pr3` `4bc371b87` (the remaining 38) + this ledger.
- **Gates:** `uv run --isolated --extra inspect python scripts/fidelity_check.py` on `pr3` →
  `94 fresh  0 stale  0 no record  0 orphan record`, exit 0. No test suite ran: the sweep adds
  no code. Every load-bearing `file:line` in each record was opened by the calling session with
  `sed -n` before the record was copied in.
- **Verdicts (94 records):** 2 comparable-to-paper (IFEval, PubMedQA) · 23 comparable-to-inspect ·
  30 not-comparable · 39 unverified. By slice: board nine = 10 / 3 / 6 (inspect / unverified /
  not-comparable); scored 36 = 1 paper, 4 inspect, 21 unverified, 10 not-comparable; the rest
  38 = 9 inspect, 15 unverified, 14 not-comparable. The three recurring causes of `unverified`
  are (a) inspect_evals' system message folded into the user turn, (b) the Task's
  `GenerateConfig` (temperature 0, max_tokens) not applied because the importer never reads
  `task.config`, and (c) a Named Deviation that adopts a later inspect_evals fix, whose moved
  Cases depend on the Candidate's reply wording. The recurring cause of `not-comparable` is a
  house judge where the paper used another model.
- **Undeclared findings handed to the owner (each is a Deviation in its record, not a fix):**
  ARC-AGI-2 pydantic grid coercion; HealthBench Professional and worst-30 skip the paper's
  length adjustment; CyberSecEval MITRE FRR scores a provider-field refusal 1.0; medxpert's
  turn 2 sends a JSON object in one user message where the harness sends assistant+user turns,
  on all 2,450 Cases, while the row's Named Deviation claims the official protocol for solo
  models; gsm8k and winogrande serve `fewshot=0` where inspect_evals' default is 10 and 5 shots,
  with no Named Deviation; medqa's Frontier Score is a 4-option number against our 5-option
  Cases; AIR-Bench and simpleqa fail a Case on a blank judge reply where inspect marks it
  not-attempted; BBEH's prompt suffix carries line breaks the paper's source does not.
- **Deviations from the plan:**
  - Records in pr2 and pr3 carry `audited_at: 48fe0ec5b` (pr1's head) rather than their own
    base sha: the agents audited the pr1 worktree, and the commits between are records only,
    so the audited code is identical.
  - Agents ran on Opus after the first wave (owner call on cost). Two network outages killed
    22 in-flight audits, which were re-dispatched; results were unaffected.
  - Sibling records that reached different verdicts for the same situation were aligned by
    the calling session before copy-in (LAB-Bench DbQA, AIME 2024/2025, ChemBench), so a
    reviewer reading a family together sees one rule.
  - Known template nit, left for a follow-up outside this sweep: inspect_ai's GitHub tag is
    `0.3.263` (no `v`), so every record's `references.inspect_ai` link to `tree/v0.3.263`
    404s; `scripts/fidelity_check.py`'s pin regex accepts only `v`-tags or shas. Fix TEMPLATE,
    the agent's example and the regex together.
  - The authors' HellaSwag repository is DMCA-blocked on GitHub (HTTP 451), so that record's
    `original_harness` points at the Software Heritage archive of the same commit.
- **Owner verify at PR-open:** file the sweep ticket under an epic and backfill `ticket:` here
  and in the three PR bodies; the two `fewshot=0` rows and the medxpert turn-2 layout are
  owner decisions (declare or change), not sweep edits.
