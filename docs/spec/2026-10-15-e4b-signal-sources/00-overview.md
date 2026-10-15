# E4b part 3: signal sources v1 — overview

**Status:** draft, waiting for review (2026-10-15). **Epic:** E4b (OME-1290). **Leaf:** filed at
PR-open.
**Base:** branch `OME-1601-e4b-combine-extensions` (E4b part 1, PR #1409) at `0f4b9e292`. When part 1
merges, move this branch onto `origin/main`.

## 1. Summary

E4a and E4b part 1 let a Fusion weight, pick, rank and filter members by a closed set of numbers:
cost, latency, tokens, a judge score and a JSON field. The epic's goal is a number that the run
measures from the answer itself. This part adds the first three such sources and the way to name
them:

- `sf.Fusion(signals={...})`: a Fusion declares named sources; rules read them with `sf.signal(name)`;
  every declared value goes into the evidence;
- `sf.Verbalized(pattern)`: a number that the member states in its text (`Confidence: 90`);
- `sf.Logprob("mean" | "sum" | "prob")`: the token log-probability of the member's reply;
- `sf.Entropy(top_logprobs=5)`: the mean token entropy of the reply.

`logprob` and `entropy` work on OpenRouter models only in v1. A model that cannot return logprobs
fails with the new code `logprobs_unsupported`.

No url4 grammar change and no new schema id. One new failure code (`logprobs_unsupported`). A gateway
change is possible only if unit 1 shows that the refusal cannot be told apart (see §7).

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `G/` = `apps/aigateway/src/aigateway/`,
`ET/` = `apps/screamingface-engine/tests/unit/`, `ST/` = `packages/screamingface/tests/`. Line numbers
are on base `0f4b9e292`.

**Epic map** (OME-1290 items that this part closes):

| Epic item | Status after this part |
|---|---|
| A1 a Fusion declares signals; an undeclared name fails before any call | done ([declared-signals](prd/declared-signals.md)) |
| A3 the evidence shows the value and its source | data done (`declared`); display is part 4 |
| B1 `verbalized` | done ([verbalized](prd/verbalized.md)) |
| B2 `logprob` (mean or sum; fails visibly without logprobs) | done, plus `prob` ([logprob](prd/logprob.md)) |
| B3 `entropy` | done ([entropy](prd/entropy.md)) |
| G1 record a logprob against a threshold | the value and the Filter pass are recorded (S16); the gate record is part 5 |
| K2 one verified provider path | OpenRouter, one pinned model ([recipes](prd/recipes.md)) |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| SDK (`S/fusion.py`, `S/_signals.py`, new `S/signal_sources.py`, `S/_evaluation/`) | user API, name rules, compile | declared-signals, verbalized, logprob, entropy |
| Engine combine core (`E/combine/`) | spec parse, declared values, evidence | declared-signals, verbalized, logprob, entropy |
| Engine world (`E/world/connector.py`, `E/world/model_response.py`, `E/world/combine.py`, `E/operation_calls.py`) | call params, reply logprobs, reader, failure code | logprob-capture |
| Engine contract (`E/benchmarks/contract.py`, failure classes) | the declared failure codes | logprob-capture |
| Contract data (`ET/data/combine_contract/`) | v1 schema snapshots, url4 fixtures | declared-signals, recipes |
| Docs (`packages/screamingface/README.md`, `CHANGELOG.md`) | user guidance | recipes |

## 3. Reading order

1. [erd.md](erd.md)
2. [prd/declared-signals.md](prd/declared-signals.md) (component, P0)
3. [prd/logprob-capture.md](prd/logprob-capture.md) (component, P0)
4. [prd/verbalized.md](prd/verbalized.md) (P1), [prd/logprob.md](prd/logprob.md) (P0),
   [prd/entropy.md](prd/entropy.md) (P1)
5. [prd/recipes.md](prd/recipes.md) (P1)
6. [contracts.md](contracts.md), [test-plan.md](test-plan.md)

## 4. PRD index

| PRD | Lifecycle | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|
| [declared-signals](prd/declared-signals.md) | existing | 4 / 3 / 9 | 15 |
| [logprob-capture](prd/logprob-capture.md) | existing | 4 / 3 / 8 | 14 |
| [verbalized](prd/verbalized.md) | planned | 3 / 3 / 7 | 10 |
| [logprob](prd/logprob.md) | planned | 5 / 4 / 6 | 11 |
| [entropy](prd/entropy.md) | planned | 4 / 3 / 5 | 10 |
| [recipes](prd/recipes.md) | existing | 3 / 2 / 3 | 9 |
| **Total** | | **23 / 18 / 38** | **69** |

## 5. Interview ledger

The prompt is the E4b epic (OME-1290) and the gap analysis of 2026-10-15. Q1–Q4 are the roadmap
decisions DB-1, DB-7, DB-3 and DB-2 of that day. Q5–Q11 are the part 3 interview of the same day.

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | DB-1: how does a recipe name the new sources? | "Declare, additive" | recommended |
| Q2 | DB-7: which provider path for the first logprob version? | "OpenRouter only" | recommended |
| Q3 | DB-3: where do the token-level methods (UniTE, span ensemble) go? | "Keep in E4b, later part" | against the recommendation ("Move to OME-1566") |
| Q4 | DB-2: `cost` or `cost_usd`? | "Keep cost_usd" | recommended |
| Q5 | A model that cannot return logprobs makes the member call fail. What happens? | "Member fails, clear code" | recommended |
| Q6 | Which tokens does `sf.Logprob` average or sum over? | "All reply tokens" | recommended |
| Q7 | A declared signal that no rule reads: compute and record it? | "Record every declared" | recommended |
| Q8 | Default `top_logprobs` k for entropy? | "k=5, author up to 20" | recommended |
| Q9 | `sf.Verbalized`: which match, what scale? | "Last match, raw number" | recommended |
| Q10 | How do we cut part 3? | "One spec, one PR" | recommended |
| Q11 | Which forms does `sf.Logprob` offer, given that vote weights must be > 0? | "Add \"prob\", refuse raw weights" | recommended |

## 6. Global decisions [proposed]

| # | Decision | Where |
|---|---|---|
| P1 | A declared name matches `^[a-z][a-z0-9_]{0,31}$`, is not an E4a key, and does not start with `logprob`, `entropy`, `verbalized` or `consistency`. The reserved prefixes keep the E4a pins for `logprob_mean` true, so only one pinned SDK case changes. | [erd §1](erd.md), DS-D1, DS-D2 |
| P2 | At most 8 names and one `entropy` per Fusion; a declaration needs a reducer Fusion. | [erd §1](erd.md) DS-I1..I3 |
| P3 | `logprob` and `entropy` need each member to be one OpenRouter model call (no Recipe member). | [erd §1](erd.md) DS-I4 |
| P4 | The numbers come from the terminal round of a call; token text is never kept. | [logprob-capture](prd/logprob-capture.md) |
| P5 | A 200 reply without logprobs gives None values, not a failure; only the gateway refusal is `logprobs_unsupported`. | LC-E3, LC-E1 |
| P6 | Under a quorum panel, a member refused for logprobs shows `missing` in the evidence (the panel carries no code); the run log names the code. | LC-E2 |
| P7 | `sf.Verbalized` reads the whole text under the 1 MiB cap with RE2, not the last 1024 characters of regex@1. | [verbalized](prd/verbalized.md) §3 |
| P8 | Entropy is in nats and adds a residual term for the unlisted mass. | [entropy](prd/entropy.md) §3 |
| P9 | `sf.Entropy` as a vote weight is refused, with a hint to use `order="min"`. | EN-E2 |
| P10 | `prob = exp(mean)`; an underflow to 0.0 gives None. | LP-D4 |
| P11 | The evidence gets an optional `declared` map; the read key stays in `signal`. | [erd §5](erd.md) |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | The exact gateway answer to an OpenRouter refusal under `require_parameters` | unit 1 records it; map it in the engine; a gateway code only if the answer is not distinct (escalate) |
| D2 | Display of signals in the report | part 4 |
| D3 | Several signals in one step, coefficients, abstain band | part 6 |
| D4 | `consistency@N` | part 7 |
| D5 | UniTE and the span ensemble | part 8 (ans:Q3) |

Scope notes:

- **N1** `sf.Logprob("sum")` favors short replies. The README says to prefer `mean` or `prob` across
  members.
- **N2** A Filter on a logprob threshold (S16) records the value and the pass; the larger model still
  runs. The skip is E4c.
- **N3** A reply over 1,000,000 bytes is not cached by the gateway, so its replay is a live call.

## 8. Owner-approved test edits (needed at build)

| File | Why |
|---|---|
| `ST/test_signals.py:33-35` | `sf.signal("cost")` becomes a valid name; the error moves to the Fusion (DS-D2) |
| `ET/test_e4b_catalog_pins.py:13-20` | the declared failure codes grow from 65 to 66 (`logprobs_unsupported`) |
| `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json` | new optional `signals` (frozen by `ET/test_wire_schema_freeze.py`) |
| `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` | new optional `declared` |
| `ST/public_surface_snapshot.json` | `Fusion.__init__` gets `signals`; new `Logprob`, `Entropy`, `Verbalized` |
| `ET/test_failure_classes.py`, `ST/unit/test_failure_code_conformance.py` (if they enumerate codes) | the new code; confirm at RED |

The E4a pins that use `logprob_mean` as an unknown key stay unchanged (P1):
`ST/test_signals.py:25-28`, `ST/unit/test_signal_key_conformance.py:110`,
`ET/test_combine_ports.py:130`, `ET/test_combine_spec.py:337`, `ET/test_combine_signals.py:146-152`,
`ET/test_combine_signal_ops.py:80-86`, and the fixtures `ET/fixtures/combine/flow/filter@1.json:53`
and `by_signal@1.json:23`. The E4a design record `docs/spec/2026-10-02-e4a-gap-closure/prd/signals.md`
(SG-E2) stays true for an undeclared `logprob_mean`.

## 9. What changes for related epics

- **E4b part 2** (evidence completeness, separate branch). Part 2 adds the status `excluded` with
  `no_signal`. After both merge, a member whose declared value is None and that a rule reads shows
  `excluded/no_signal`. The parts do not depend on each other; the second to merge rebases.
- **E4b part 4** shows the `declared` map and the values in the report.
- **E4c** reads the recorded logprob to skip a larger model.

## 10. Build errata

None yet.
