---
ticket: OME-1455
stack: screamingface-engine
status: done
started: 2026-10-06
finished: 2026-10-06
---

# ome-1455-benchmark-provenance-values — sourced provenance for every registered Benchmark (PR 3 of 4)

## Intent

PR 2 (#1236) gave every Benchmark thirteen provenance slots and a strict conformance test that
65 Benchmarks pass only through a grandfather allowlist. This unit fills the slots for all 65
from sources a reviewer can click (eval.yaml, arXiv, the Hub card, the paper's leaderboard or a
model card), declares `NotPublished(reason=...)` where a fact genuinely does not exist, and
empties the allowlist, so from this PR on every Benchmark registered on main carries a sourced
cover sheet and the pages (PR 4) have something to show. Stacked on PR 2's branch.

## Planned changes

- Engine `screamingface_engine_inspect/benchmarks.py`: the 57 imported rows — mechanical fields
  re-emitted from the importer's own readers (paper, inspect porters, baseline, upstream size,
  licence, harness, notebook, authors, citation), then by hand: `frontier_score`
  with a source, `content_warning` on the Safeguards rows, `license_note` where OME-1273's
  licence decision names one.
- Engine built-in declarations: `ifeval`, `medxpert`, `contracteval`, `draco` (×2),
  `healthbench` (×2), `gdpval-text` — every field by hand from the paper or dataset card.
- Engine `tests/unit/inspect/test_benchmark_provenance_conformance.py`: `GRANDFATHERED = frozenset()`.
- Engine `tests/unit/inspect/test_benchmark_provenance_assembly.py`: the F2 size cross-check
  rows now exist, so its parametrization is non-empty.
- Scoreboard `tests/fixtures/engine_catalog.json`: regenerated with a row carrying provenance.
- Ledger, mirror, Linear comment with the per-Benchmark source table.

## Test plan

- The conformance test under the inspect extra with the allowlist emptied: zero gaps by name.
- Every revision golden byte-identical (`test_published_revisions.py`, the six literal pins).
- Every `harness_url` pinned and upstream; every `notebook` a real file; every handle valid —
  all already enforced by the validator and the conformance test; this PR makes them run on
  real rows.
- No test opens a socket; every `source_url` resolved once by hand, listed in the Outcome.

## Acceptance

- Spec §7, "After PR 3": allowlist empty, test green, every link pinned, every notebook real,
  every handle valid.
- The PR body carries one row per Benchmark naming the source of each hand-sourced value.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus one importer fix the real rows forced: `provenance_facts.py`
  splits a BibTeX line longer than 76 characters into adjacent literals (a seven-author
  `author={...}` line put every generated row over the 100-column lint gate), pinned by a new
  test in `tests/unit/inspect/test_importer_provenance.py`. The 57 imported rows were rebuilt
  by three one-off scripts kept in the session scratchpad, never committed: `apply_facts.py`
  (the importer's own `provenance_row_lines` over each row's eval.yaml + arXiv facts, read at
  the pinned inspect_evals 0.20.0), `fill_values.py` (the owner's licence
  decisions, content warnings, size notes, and the researched baselines and frontier scores
  after review), `fill_builtins.py` + `fill_builtin_scores.py` (the eight built-ins). The
  Scoreboard fixture `engine_catalog.json` was regenerated from the registry with every
  revision asserted unchanged.
- **Commits:** `b794de845` values + fixture + importer fix · `4cd57edd1` ledger + mirror · PR [#1252](https://github.com/ScreamingFace/screamingface/pull/1252) (draft, base = PR 2's branch).
- **Gates:** `run_gates.py screamingface-engine --base upstream/main --skip-append-only` and
  `run_gates.py scoreboard --base upstream/main --skip-append-only` — see the PR body table;
  the SDK is untouched. Targeted before the gate: conformance + size cross-check + revision
  goldens + twins (208 passed), the whole inspect lane (1,181 passed), the Scoreboard
  catalogue-fixture tests (40 passed).
- **Deviations:** (1) **Sources, not all first-party.** Every frontier score and baseline has a
  URL that states the number, but the PR table's last column carries a reviewer note where the
  source is secondary (an aggregator, a third-party model card, a leaderboard) or stale (all
  eight AGIEval subsets have only GPT-4's 2023 per-subset numbers). Research was done by five
  web agents in parallel; every pick was reviewed and 11 were rejected for a `NotPublished`
  with the reason (numbers read off charts, computed averages, tool-augmented runs, a
  17-of-750-Sample run, metric mismatches). (2) **HealthBench rows cite the 2026 paper.** The
  pinned dataset `openai/healthbench-professional` (use cases consult / writing / research) is
  the HealthBench Professional benchmark of arXiv 2604.27470, not the 2025 HealthBench the
  module docstring cites; the provenance follows the dataset, the docstring is left for the
  owner. (3) **Licences beyond the cleared list** are written as the card or repo states them:
  `CC-BY-SA-3.0` (boolq), `CC-BY` with no version (winogrande), two custom texts with no SPDX
  id (paws `LicenseRef-PAWS`, race_h `LicenseRef-RACE-non-commercial`), `CC-BY-NC-4.0`
  (worldsense, owner decision), and `NotPublished` for piqa, the four cybermetric rows (owner
  decision on OME-1273) and gdpval-text (no licence on the dataset card or README). (4)
  **Five rows carry no `upstream_case_count`** with a comment saying why (eval.yaml names the
  wrong variant, or disagrees with the dataset at the pinned revision); mgsm_en carries 250
  (the English subset of eval.yaml's 2,750). (5) **DRACO's harness link is the dataset repo**
  at its pinned revision: the GitHub repo the docstring cites as protocol authority is not
  public. (6) **gdpval-text has no frontier score or baseline** on purpose: GDPval's published
  metric is a win rate against the expert deliverable, which this Benchmark does not score.
  (7) The verdict calls `xstest_unsafe`, `wmdp_bio` and `wmdp_cyber` saturated: true on the
  headroom rule, odd to read for a refusal or hazard-knowledge test; left for the pages PR to
  word, noted on the ticket.
- **Deviation (8), 2026-10-06:** `contributors` dropped from every row (57 imported, 8
  built-in) and from the regenerated Scoreboard fixture, following the owner's decision on
  PR 2 (#1236) to remove the field: who typed the row is git's fact, not provenance;
  `inspect_contributors` stays. Twelve fields per row now.
- **Deviation (9), 2026-10-06, after a source-by-source verification of the table:** nine
  values corrected in the rows and the table — gsm8k human → NotPublished (the paper reports
  no human solve rate); paws human → NotPublished (0.947 was rater agreement); medxpert human
  = 0.426 ("Expert (Pre-Licensed)", Text, Table 4); bbq frontier as_of 2026-05 → 2025-06 (HELM
  Safety v1.9.0 release); lab_bench dbqa 0.748 / seqqa 0.789 now cited to the EMBL AI Librarian
  paper (2607.28229, Table 4), the only place a per-dataset human figure is printed; onet_m6
  paper → OpenThaiGPT 1.5 (2411.07238), which documents the set; cyse4 keeps the CSE2 paper
  with a comment (it introduced the FRR set); mmlu gains `upstream_case_count=14042` (eval.yaml
  names it under the shot-variant tasks; dropped again after the rebase past the OME-1460
  fold, whose replay seals 13,937, as was xstest_unsafe's 250 for a 200-Case subset). Wording tightened in the row comments for AGIEval
  (best of four prompt settings; Avg column), SEvenLLM, RACE-H, CyberMetric, BBEH and the four
  rows whose as_of is the model's release month. Three left for the owner, see below. Body
  counts corrected: 51 size-checked rows (48 match, 3 deviations, 6 without a count), five
  licences outside the cleared list; the table carried six reviewer notes, not fourteen, and
  carries seventeen after this round.
- **Owner-verify:** frontierscience 0.252 (openai.com refused the verifier; secondary
  sources say 25%); mgsm_en licence (the loaded card says cc-by-sa-4.0, the OME-1273 decision
  says CC-BY-4.0 from the upstream LICENSE); piqa licence (the project page reportedly states
  AFL v3.0; the OME-1273 decision is unknown); the `--skip-append-only` press (PR 2's three items, plus the emptied
  allowlist and the regenerated Scoreboard fixture here); the reviewer notes in the PR
  table, chiefly: the HealthBench paper switch, the IFEval and MedXpertQA secondary sources,
  the four licence spellings outside the cleared list.
