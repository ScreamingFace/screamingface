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

No url4 grammar change and no new schema id. One new failure code (`logprobs_unsupported`). The SDK
preflight refuses a model that the gateway catalog marks without logprobs before any spend. A small
aigateway change (an own error code for the refusal) is part of this part only if unit 1 shows that
the refusal cannot be told apart (ans:Q13).

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
| [declared-signals](prd/declared-signals.md) | existing | 4 / 3 / 10 | 16 |
| [logprob-capture](prd/logprob-capture.md) | existing | 4 / 5 / 10 | 20 |
| [verbalized](prd/verbalized.md) | planned | 4 / 3 / 7 | 11 |
| [logprob](prd/logprob.md) | planned | 8 / 4 / 6 | 14 |
| [entropy](prd/entropy.md) | planned | 4 / 3 / 8 | 13 |
| [recipes](prd/recipes.md) | existing | 3 / 2 / 4 | 9 |
| **Total** | | **27 / 20 / 45** | **83** |

## 5. Interview ledger

The prompt is the E4b epic (OME-1290) and the gap analysis of 2026-10-15. Q1–Q4 are the roadmap
decisions DB-1, DB-7, DB-3 and DB-2 of that day. Q5–Q11 are the part 3 interview of the same day.
Q12–Q13 came after the design review of the spec, the same day.

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
| Q12 | P6: under a quorum panel the evidence shows `missing`, not `logprobs_unsupported`. Accept? | "Accept, show code elsewhere (Recommended)" | recommended |
| Q13 | May part 3 include a small aigateway change that gives the refusal its own error code, if unit 1 shows it cannot be told apart? | "Yes, small change allowed (Recommended)" | recommended |

## 6. Global decisions [proposed]

| # | Decision | Where |
|---|---|---|
| P1 | A declared name matches `^[a-z][a-z0-9_]{0,31}$`, is not an E4a key, and does not start with `logprob`, `entropy`, `verbalized` or `consistency`. The reserved prefixes keep the E4a pins for `logprob_mean` true, so only one pinned SDK case changes. | [erd §1](erd.md), DS-D1, DS-D2 |
| P2 | At most 8 names and one `entropy` per Fusion; a declaration needs a reducer Fusion. | [erd §1](erd.md) DS-I1..I3 |
| P3 | `logprob` and `entropy` need each member to be one OpenRouter model call (no Recipe member). | [erd §1](erd.md) DS-I4 |
| P4 | The numbers come from the terminal round of a call; token text is never kept. | [logprob-capture](prd/logprob-capture.md) |
| P5 | A 200 reply without logprobs gives None values, not a failure; only the gateway refusal is `logprobs_unsupported`. | LC-E3, LC-E1 |
| P6 | APPROVED by the owner (ans:Q12). Under a quorum panel, a member refused for logprobs shows `missing` in the evidence (the panel carries no code). The author sees `logprobs_unsupported` through `observation.failed(code)` in the activity view of the run (E/world/connector.py:250-251, E/activity/observer.py:134,160). The server log line is for operators only. | LC-E2 |
| P7 | `sf.Verbalized` reads the last 65,536 characters (under the 1 MiB read cap) with RE2, not the last 1024 characters of regex@1; worst case 256 × 8 × 64 KiB = 128 MiB of RE2 input per step. The pattern has exactly one group (new `check_signal_pattern` on `check_regex_pattern`). | [verbalized](prd/verbalized.md) §3–4 |
| P8 | Entropy is in nats and adds a residual term for the unlisted mass. | [entropy](prd/entropy.md) §3 |
| P9 | `sf.Entropy` as a vote weight is refused, with a hint to use `order="min"`. | EN-E2 |
| P10 | `prob = exp(mean)`; an underflow to 0.0 gives None. | LP-D4 |
| P11 | The evidence gets an optional `declared` map; the read key stays in `signal`. | [erd §5](erd.md) |
| P12 | The injected `logprobs` and `top_logprobs` params go into `parameter_assignments`, so the SDK preflight (S/_evaluation/model_parameters.py:153-225) refuses a model that the catalog marks unsupported with `unsupported_model_parameter`, before any spend. The runtime `logprobs_unsupported` covers every model the catalog does not know. WHY: the author sees the problem at once, and earlier, which honors ans:Q5 (orchestrator decision). | LC-E4, C2 |
| P13 | The refusal mapping lives in `_observed_round_trip` (it holds the request body); the message is fixed engine text; `logprobs_unsupported` joins `ENGINE_ERROR_CODES` (OME-941), so no upstream can send it. | [logprob-capture](prd/logprob-capture.md) Delta 4–5 |
| P14 | The weight refusals (raw logprob, entropy) live in the `sf.Fusion` constructor, the only object that sees the declaration and the rules. | LP-E1, EN-E2 |
| P15 | One member reader: `_read_member_accounting` returns the accounting numbers and the reply logprobs from one fingerprint index. | C5 |
| P16 | The url4 → Python rebuild accepts `signals` and drops the injected member params. | C9, DS-D8, DS-D10 |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | The exact gateway answer to an OpenRouter refusal under `require_parameters` | decided (ans:Q13): unit 1 records it; if distinct, the engine maps it; if not, unit 1 adds the aigateway code `unsupported_parameters` with its own test (LC-E5, C4b) |
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
- **N4** A frozen-copy entry over 2,000,000 bytes (request plus reply) is not stored, and the capture
  reports `failed` (LC-D9).

## 8. Owner-approved test edits (needed at build)

| File | Why |
|---|---|
| `ST/test_signals.py:33-35` | `sf.signal("cost")` becomes a valid name; the error moves to the Fusion (DS-D2) |
| `ET/test_failure_classes.py:88-110` | pins the exact set of declared codes; `logprobs_unsupported` joins it (certain) |
| `ET/test_e4b_catalog_pins.py:1-20` | its docstring, its test name and its count say "E4b adds no failure code" (65); part 3 adds one, so the file is rewritten for 66 |
| `ET/test_terminal_error_detail.py:332-349` | pins `ENGINE_ERROR_CODES` by hand; `logprobs_unsupported` joins it (P13) |
| `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json` | new optional `signals` (frozen by `ET/test_wire_schema_freeze.py`) |
| `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` | new optional `declared` |
| `ST/public_surface_snapshot.json` | `Fusion.__init__` gets `signals`; new `Logprob`, `Entropy`, `Verbalized` |
| `ST/unit/test_failure_code_conformance.py` | only if it enumerates the codes; confirm at RED (the SDK mirror `S/_report_primitives.py:22` is source, not a test) |

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

- **E1 (unit 2):** the verbalized reader reaches the combine core through the registry as a `SourceDescriptor`, because the layering gate forbids the core to import a plugin or `re2`.
- **E2 (unit 2):** `Answer.signals` keeps only the read key; the evidence `members[].signals` holds every declared name.
- **E3 (unit 2):** DS#16 covers only "authored params stay"; the drop of injected params moves to units 3 and 4 (LP#14, EN#13).
- **E4 (unit 2):** DS#7 tests the "one entropy" rule with a test-local source class, because `sf.Entropy` comes in unit 4.
- **E5 (unit 2):** the SDK `CombineSignal` keeps its E4a-only public constructor; a declared read uses the private `CombineSignal._declared`.
- **E6 (unit 2):** `by_signal@1` and `filter@1` accept the declared-name syntax in their arguments; the plan-level check refuses a name the spec does not declare.
- **E7 (unit 2):** VB#8 runs its own SDK-compiled fixture `verbalized_vote_candidate.url4`; it is not a README recipe (recipes are unit 5).
- **E8 (unit 2):** the append-only gate passes for the four pinned files only through the approval manifest `.claude/test-change-approvals/OME-1290.json`, which stays PENDING owner approval.
- **E9 (unit 2):** the DS#14 oracle `repr(rebuilt) == repr(fusion)` cannot pass: the url4 rebuild of a Vote keeps the pinned operator ids (`extract='last_line@1'`, `normalize='text@1'`), as `ST/test_judge_url4_round_trip.py:184` and `ST/test_reducer_recovery_preference.py` require. DS#14 asserts the exact rebuilt repr with the `@1` ids and the `signals` text instead. This is an edit of a RED-commit test; the owner must approve it.
- **E10 (review P3 #1):** the engine enforces the C1 rule "at most one `entropy`" too: a spec with two `entropy` sources is `combine_spec_invalid` ("signals declares more than one entropy source"; no name echoed). An entropy value is None, with one count-only warning per step, when the member's one source call asked for another `top_logprobs` than the declared one. The core reads the k from the source fingerprint in the context `sources`, not from `ReplyLogprobs.top_k`: the reader matches that exact fingerprint to the recorded call, and the connector sets `top_k` from the same body param, so both give the same k. The core compares the param text with `str(k)`, so another spelling of the same k (for example `" 5"`) reads as another k and gives None, the safe side; the SDK always writes the canonical text.
- **E11 (review P3 #3):** P14 now holds in the engine too, not only in the `sf.Fusion` constructor: a spec whose `weights` reads a declared `entropy` source, or a `logprob` source in the form `mean` or `sum`, is `combine_spec_invalid` at parse time ("weights.signal must not be an entropy or a non-prob logprob source"; no name echoed). `logprob` in the form `prob` stays a valid weight.
