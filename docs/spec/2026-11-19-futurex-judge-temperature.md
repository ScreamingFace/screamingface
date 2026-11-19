# FutureX-Past Judge: stop sending temperature 0 — Spec

- **Status:** APPROVED 2026-11-19 — Q1 hold the id; Q2 add the guard; Q3 leave the four rows
- **Date:** 2026-11-19
- **Component:** `apps/screamingface-engine` (one landing)
- **Ledger:** `docs/work/2026-11-19-futurex-judge-temperature.md`
- **Ticket:** unfiled (a `bug`; filed at PR-open)

## 1. Problem

FutureX-Past fails every level-3 and level-4 Case on the hosted Engine with `scorer_error`.
Levels 1-2 and `futurex_past_study` work.

Cause chain (verified 2026-11-19):

1. The futurex_past row pins the Judge params
   `(("temperature", "0"), ("max_tokens", "4096"), ("web_search", "false"))` on
   `openrouter/openai/gpt-5.4` (`benchmarks.py`, the futurex_past `JudgeSpec`).
2. The gateway always sends `provider.require_parameters = true` on OpenRouter calls
   (`apps/aigateway/docs/openrouter-routing-controls.md`). The user cannot remove it.
3. OpenRouter lists 4 endpoints for `openai/gpt-5.4` (OpenAI x3, Azure). None lists
   `temperature` in `supported_parameters`. OpenRouter answers "No upstream endpoint for this
   model supports every requested parameter".
4. The scorer calls the Judge only for levels 3-4. A failed marking call fails the Case as
   `scorer_error` (a NAMED DEVIATION on the row).

Two more effects:

- **The router.** It uses the same Judge and params, so it fails too. A failed router call is
  forgiven: it falls back to the level default. So the router never ran on the hosted Engine.
- **The headline.** Under `coverage_declare`, a `scorer_error` Case leaves the denominator, and a
  missing level renormalises the 10/20/30/40 weights. So a run reports a levels-1-2 score as the
  headline, and the report does not say so.

The other 12 gpt-5.4 Judge rows send no temperature (owner decision on OME-1602; air_bench's row
says "no temperature, as on the other gpt-5.4 rows"). futurex_past is the only row that breaks
this rule.

## 2. Requirements

- **R1.** The futurex_past Judge sends no `temperature`. It keeps `max_tokens=4096` and
  `web_search=false`, in the house order `(("web_search", "false"), ("max_tokens", "4096"))`.
- **R2.** The row records a NAMED DEVIATION: Futurex-Eval asks its Judge at temperature 0; our
  gpt-5.4 Judge has no temperature control on OpenRouter, so it samples at the provider default.
- **R3.** A catalogue guard test: no row whose Judge model starts with `openrouter/openai/gpt-5`
  pins `temperature`. Offline, no network. WHY: the gateway forces `require_parameters`, and these
  models expose no temperature on OpenRouter, so such a pin fails every Judge call.
- **R4.** The futurex_past README and Fidelity Record say what the Judge sends now (Judge
  paragraph, the router sentence, the judge row of the record and its quoted row).
- **R5.** The revision follows the owner's answer to Q1.

## 3. Out of scope

- The other four rows with `temperature: 0` (hle, hle_diamond on `z-ai/glm-5.3-flash`;
  LAB-Bench 2 FigQA2 and TableQA2 on `anthropic/claude-sonnet-4.5`). Every OpenRouter endpoint for
  these models accepts `temperature` (checked 2026-11-19). No change.
- A live check of each Judge's params against OpenRouter. That needs the network; R3 is the
  offline subset.
- Any gateway change. `require_parameters` stays gateway-owned.
- Re-grading or deleting past runs.

## 4. Decisions needed from the owner

**Q1 — Revision: hold or bump?** The report asks for a bump. The repo rule
(`docs/adding-an-imported-benchmark.md`, "Changing a Benchmark's published revision", owner
decision 2026-10-22) says: same Cases with changed grading → hold the id, update only the
fingerprint literal. This fix does not change the Cases.

- *Hold (recommended, follows the rule):* `200cf4f72481ffb0` stays. Old results stay visible,
  but they are levels-1-2-only headlines beside correct new ones.
- *Bump (the report's request):* old results stop showing. Needs owner sign-off in the PR, a
  CHANGELOG line and a post to the team.

If no real results exist under `200cf4f72481ffb0` yet, a bump costs nothing. The owner knows that.

**Q2 — Add the guard test (R3)?** Recommended: yes. It is about 30 lines and needs no network.

**Q3 — Leave the four other `temperature: 0` rows unchanged?** Recommended: yes (section 3).

## 5. Acceptance

- The futurex_past JudgeSpec params contain no `temperature` (unit test).
- The guard test is red on `origin/main` and green after the fix.
- `uv run .claude/scripts/run_gates.py screamingface-engine` is green.
- No real Judge call in tests (rule: no network; reviewers run offline).

## 6. Proof after merge (owner, optional)

A small hosted run of futurex_past with a cached or cheap Candidate, limited to a few level-3/4
Cases: those Cases grade with no `scorer_error`. No full run (house rule: no full evals unasked).
