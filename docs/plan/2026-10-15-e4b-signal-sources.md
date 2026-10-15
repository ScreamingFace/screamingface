# Plan: E4b part 3 — signal sources v1

Spec: [docs/spec/2026-10-15-e4b-signal-sources/](../spec/2026-10-15-e4b-signal-sources/00-overview.md).
Ledger: written at the start of the build (`docs/work/2026-10-15-e4b-signal-sources.md`).

## 1. Approach

- Base: branch `OME-1601-e4b-combine-extensions` (E4b part 1, PR #1409) at `0f4b9e292`. When part 1
  merges, move this branch onto `origin/main` with `git rebase --onto origin/main
  OME-1601-e4b-combine-extensions e4b-signal-sources`.
- One spec, one branch, one PR (ans:Q10). The units are commits on `e4b-signal-sources`, in the
  order below. They share `S/_signals.py`, the v1 schema snapshots, `README.md` and `CHANGELOG.md`,
  so a linear order avoids conflicts.
- Each unit: a full unit spec (files, signatures, data shapes, exemplar, edge cases), then RED, then
  GREEN, then a design review against the PRD as the rubric, then one fix round. A structural finding
  means a re-spec, not a second fix round.
- TDD inside each unit follows the PRD §7 order: CHAR rows first, then RED → GREEN → REFACTOR.
- Unit 1 is risk-first: it records the two gateway answers that the parser and the failure mapping
  depend on, before any product code.

## 2. Units

| # | Unit | PRD rows | Main files |
|---|---|---|---|
| 0 | docs | — | this plan, the spec |
| 1 | characterize the gateway (local stack `~/sf-local`) | LC-E1 shape, C3, C4; RC#8 model choice | a trimmed reply with `logprobs` and `top_logprobs` (synthetic text) and the refusal answer, saved as `ET/data/logprobs/*.json`; a short note in the ledger: the pinned model, the refusing model, the status and code of the refusal, and the decision on D1 |
| 2 | declared signals and verbalized | DS#1–15, VB#1–10 | `S/fusion.py` (`signals=`), `S/_signals.py` (`is_signal_name`), new `S/signal_sources.py` (`Verbalized`, later `Logprob`, `Entropy`), `S/_evaluation/combine_spec.py`, `S/_evaluation/combine_evidence.py`, `S/combine_evidence.py`, `S/__init__.py`; `E/combine/spec.py` (`signals`), `E/combine/endpoint.py` (`_signal_values`, plan-level key check), `E/combine/evidence.py` (`declared`), reuse of `E/combine/operators/extract.py` regex checks; spec and evidence schema snapshots; public surface |
| 3 | logprob capture | LC#1–14 | `E/world/model_response.py` or a new `E/world/reply_logprobs.py` (`reply_logprobs`), `E/world/connector.py` (terminal round), `E/operation_calls.py` (`reply_logprobs`), `E/world/combine.py` (`LogprobReader`), `E/combine/ports.py` (port), `E/benchmarks/contract.py` and `E/benchmarks/failure_classes.py` (`logprobs_unsupported`), the SDK failure-code mirror |
| 4 | logprob and entropy sources | LP#1–11, EN#1–10 | `S/signal_sources.py` (`Logprob`, `Entropy`), member params in `S/_evaluation/candidate.py`, `sources` emission (`_claim_accounting_sources`), weight refusals in `S/reducer.py`; `E/combine/endpoint.py` (forms, entropy read), `E/combine/spec.py` (`sources_expected`) |
| 5 | recipes, README, CHANGELOG, paid test | RC#1–9 | SDK recipe builders, `ET/data/combine_contract/recipe_s12..s16.url4`, engine run tests, README "Signal sources", CHANGELOG, `ST/paid/` |

69 TDD rows in total.

## 3. Order and dependencies

```mermaid
flowchart LR
    U0[0 docs] --> U1[1 characterize] --> U2[2 declared + verbalized] --> U3[3 logprob capture] --> U4[4 logprob + entropy] --> U5[5 recipes]
```

- Unit 1 comes first, because LC#9 (the refusal mapping) and the fake replies of every logprob test
  use the recorded shapes. If unit 1 shows that the refusal is not distinct, stop and ask the owner
  about a gateway code (spec §7 D1) before unit 3.
- Unit 2 gives the declaration a first source (`verbalized`) that needs no change to the call path.
- Unit 4 needs the declaration (unit 2) and the capture (unit 3).

## 4. Gates per unit

- Engine: a `uv sync --dev` venv (do not install the `inspect` extra), then
  `uv run .claude/scripts/run_gates.py screamingface-engine --base <parent>`.
- SDK: `uv sync --extra notebook` (as CI does), then
  `uv run .claude/scripts/run_gates.py screamingface --base <parent>`.
- Repo: `uv run .claude/scripts/run_gates.py repo --base <parent>`.
- Unit 1 changes no product code; only the repo gate and the fixtures' format check run.
- Append-only: the edited pinned tests are listed in an owner approval manifest (§6). No
  `--skip-append-only` without it.

## 5. Exit criteria

| Criterion | Closed by |
|---|---|
| An undeclared name fails before any member call | DS#4, DS#10 |
| Every declared name has a value per member in the evidence, with its source in `declared` | DS#11, DS#12 |
| A stated confidence weights a vote | VB#8, RC#2 |
| Logprob and entropy values match the hand-computed oracles | LC#3, LP#1, EN#1–2 |
| A raw logprob or an entropy is never a vote weight | LP#4, EN#7 |
| A model without logprobs fails with `logprobs_unsupported` | LC#9, RC#9 |
| A cache hit gives the same numbers | LC#8 |
| No token text in logs or evidence | LC#5 |
| No byte change for existing recipes, call bodies or fixtures | DS#1, LC#1, RC#1 |
| One pinned OpenRouter model returns logprobs live | RC#8 |
| Each user decision with a testable effect is pinned by a test | test-plan §2 |

## 6. User actions

1. Approve the spec and this plan (plain words), including the proposed items P1–P11 and the scope
   notes N1–N3 in the overview.
2. After unit 1: confirm the pinned model and, if needed, a gateway code for the refusal (D1).
3. Approve the edits to pinned tests when each unit asks for them:
   - unit 2: `ST/test_signals.py:33-35`, the `combine-spec.v1` and `combine-evidence.v1` snapshots,
     `ST/public_surface_snapshot.json`;
   - unit 3: `ET/test_e4b_catalog_pins.py:13-20`, and `ET/test_failure_classes.py` and
     `ST/unit/test_failure_code_conformance.py` if they enumerate the codes;
   - unit 4: the public surface.
4. At PR-open: file the leaf under OME-1290.
