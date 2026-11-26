# Router Recipe extension: `sf.Router`, Router in Fusion, BERT reference — overview

**Status:** approved by the owner 2026-11-19, reconciled 2026-11-19. Implementation spec for the
extension: it pins the exact contracts that cross delivery Units. With the plan it is normative for
every Unit; Units pin the items left open here by amending it before code (§9). No code, test,
approval-manifest or dependency change comes with this document.
**Epic:** OME-1306. **Leaves:** filed per landing at PR-open (§8).
**Base:** origin/main `31c1158e8`, which contains the E4c merge `baedbd47a` (PR #1733, final head
`59d5303`). Every file:line below is at `31c1158e8` unless marked as pilot or as the historical C19
old-reader baseline `455166b0d`.
Fresh-base reconciliation retained C1-C19 and added one integration obligation from OME-1809:
`benchmarks/picture_admission.py::run_model_routes` checks every model route a file-carrying run can
reach before the first call. Unit 5.2 keeps the LLMClassifier, candidate, default and Model-synthesizer
calls literal in the url4 block and makes ADMIT await the shared check before scoring CLASSIFY; Unit 6
proves the prepared carrier preserves the same admitted routes without exposing private routes.
**Governing design:** screamingface-design PR #35 at `3e903bd` (open, approved), under
`solutions/screamingface/product/`: `client/router-recipes.md`, `engine/router-execution.md`,
`engine/routing-inputs.md`, `engine/model-routing.md` and
`aigateway/component/provider-adapters/component/remote-endpoint/classification-capabilities.md`.

PR #35 is the single source of product behavior, architectural boundaries, invariants, replay
semantics and acceptance criteria. This spec only translates it into exact Python signatures, JSON
schemas, canonical hash bytes, url4 wiring, wire headers, rollout order, the Unit sequence and tests.
It re-decides nothing PR #35 decides. Where the two differ, PR #35 wins and this spec is corrected; a
needed design change goes to PR #35 first (§7).

## 1. Summary

A Router is an immutable, answer-producing Recipe. One classifier reads the incoming text, a
versioned pure policy picks one candidate Model or a subset, and the Engine runs only the picked
Models. A subset Router synthesizes internally and still returns one answer. The Router may sit
wherever a Model sits: Gate branch, Pipeline stage, Fusion member or synthesizer, Cascade stage.

| Call | Result |
|---|---|
| `client.route_answer(router, question)` | One typed answer or abstention, no benchmark, no implicit Fusion |
| `client.evaluate(router, benchmark=...)` | Router is the Candidate; no implicit synthesizer |
| `sf.Fusion(members=[router_a, sf.Model(...)], synthesizer=...)` | Two answers, then authored synthesis |
| `sf.Fusion(members=[router_a, router_b, router_c], synthesizer=...)` | Three selected answers, then synthesis |

The existing scalar `client.classify` and the pilot's `client.route_answer(profile, input)` keep their
wire, result and revision bytes.

## 2. Scope

In scope, across Units 5-9:

- Gateway: a structured-choice classification input and a SystemOne choice codec for the common
  Laya/Jev subset; strict input-capability and limits metadata in the classifier catalog; the
  upstream-attempts header on chat and classification responses; a `classify` frozen-copy entry
  kind; the Router run manifest in seal provenance.
- Engine: one routing application boundary shared by the named-profile mount and compiled Routers,
  owning metadata/access preflight, evidence validation, pure policy, selected dispatch ports,
  attempt facts and failure normalization; a Router runtime on the E4c branch substrate with one
  failure-completion mechanism; the inline entry adapter; the classification port with the choice
  input, operation-call recording, capture and replay; a run definition set that freezes every
  Router definition before execution; attempt facts for bound calls; a classifier catalog for SDK
  preflight.
- SDK: `sf.Router`, `sf.ScoringClassifier`, `sf.RoutingPolicy`, the `router` Recipe kind through
  every closed-kind consumer, `route_answer(router, question)`, reports and stored-report readers.
- url4: the `expand.at_most_one=true` package extension that bounds an expansion to zero sources or
  one named source (C19),
  so an abstained Router member is neither an answer nor a failure, and an older url4 reader that
  ignores the annotation still counts no source for it.
- `no_selection` in `screamingface.answer.v1`, readers before writers.
- Prepared definition and question inputs for requests that do not fit the qualified GET.
- A BERT fixed-label reference through the existing scalar classifier contract (Unit 8).

Out of scope: score thresholds, `match="best", select="all"`, composite or Router candidates,
`keep=` on a classifier, one classifier result shared by a Gate and a Router, package import or
automatic environment rebinding, a routing-result cache, model download, training or deployment,
and any live, paid or production call while writing this spec.

## 3. Units and dependencies

| Unit | Outcome | Depends on |
|---|---|---|
| Pilot landing | OME-1822/1823 pilot rebased on main with fresh exact approvals (§4) | Separate authorization |
| 5.1 Gateway | Structured-choice input, SystemOne codec, catalog `input_contracts` and `limits`, upstream-attempts header, seal-provenance `routers` reader and provenance read route; fake-HTTP acceptance | Fresh main only |
| 5.2 Engine | Shared routing core; named profiles use it; dynamic-choice profiles; Router runtime and failure completion; attempt facts; Engine classifier catalog | Pilot landed; 5.1 contract |
| 6 Router Recipe | Readers first; `sf.Router` kind; standalone evaluation; inline entry and `route_answer`; classify capture/replay, the run definition set and the run manifest; prepared inputs and their retained snapshot | 5.2; capability path (C12) |
| url4 leaf | The `expand.at_most_one=true` package extension in `packages/url4`: parser validation, lowering, both panels, code binding, builder and renderer, and the cross-version test on the `455166b0d` reader (C19) | Fresh main only |
| 7 Router in Fusion | One-Router and three-Router Fusion; Model-equivalent placements with each position's outcome (C18); `router-placement-v1` (C12) | 6; url4 leaf |
| 8A fixed-label reference | Isolated DistilBERT serving bundle and model-free conformance through the existing scalar contract | Existing scalar path; approval of the C7 reference fragment |
| 8B fixed-label Router | Standalone Router integration with the 8A fixture | 6 and 8A |
| 9 Qualification | Integrated, live and hosted evidence on Linux/NATS/JetStream | 5-8 and an owner-approved window |

Readers ship before writers in every Unit: `no_selection`, Router IR and decision readers,
frozen-copy `classify` and `routers` provenance readers and report readers, `router_definitions`
included, and the url4 at-most-one reader (C19) deploy before the SDK can emit Router work. Hosted
readiness is not claimed until Unit 9 passes on the real hosted path.

## 4. Pilot reconciliation

The pilot lives in `.claude/worktrees/byom-routing-pilot`, branch `OME-1822-byom-routing-pilot`,
HEAD `89e6acfeb`, with 38 uncommitted status entries. `31c1158e8` is 415 commits ahead of that base.
The pilot's own spec, plan and ledger (`docs/{spec,plan,work}/2026-11-04-byom-routing-pilot.md` in
that worktree) remain authoritative for its slice and are not rewritten by this extension.

Paths changed by both the pilot and `89e6acfeb..31c1158e8`, with a three-way merge simulated
against `31c1158e8`:

| Path | Merge | Keep |
|---|---|---|
| `apps/screamingface-engine/src/screamingface_engine/error_text.py` | conflict | Main's `PUBLIC_UNVOUCHED_CODES`/codes plus the pilot `ROUTING_CODES` in `ENGINE_RESERVED_CODES` |
| `apps/screamingface-engine/src/screamingface_engine/world/factory.py` | clean | Main's E4c runtime install plus the pilot routing mount |
| `apps/screamingface-engine/tests/unit/test_url4_executor.py` | conflict | Main's allowlist plus the pilot's `gateway_endpoints.py` entry |
| `packages/screamingface/CHANGELOG.md` | conflict | Both entries |
| `packages/screamingface/src/screamingface/__init__.py` | conflict | Main's E4c exports plus `RoutedAnswer` |
| `packages/screamingface/src/screamingface/client.py` | clean | Main's client plus `route_answer(profile, input)` |
| `packages/screamingface/tests/public_surface_snapshot.json` | conflict | Regenerated from the merged surface |

No pilot-only new path collides with a path added on main.

Both pilot test-transition manifests are stale. They remain evidence for their original base only:

| Manifest | Path | Pilot base blob | Main blob at `31c1158e8` |
|---|---|---|---|
| `.claude/test-change-approvals/OME-1822.json` | `apps/screamingface-engine/tests/unit/test_url4_executor.py` | `ffccfdce3c99` | `4a2ba578bf28` |
| `.claude/test-change-approvals/OME-1823.json` | `packages/screamingface/tests/public_surface_snapshot.json` | `b72408d416e7` | `c6a68a3ccc4b` |

Landing the pilot needs, in order and each with its own authorization: checkpoint the dirty
worktree, rebase or integrate onto fresh origin/main, resolve the five conflicts as above, obtain new
exact owner approvals for both paths against main's blobs, run the full Engine and SDK gates on the
integrated diff, then open the pilot PR under OME-1822/1823. None of these steps is performed by this
spec. Unit 5.2 and later Engine/SDK work start from fresh origin/main after the pilot lands. Unit 5.1
does not touch pilot paths and may start from fresh origin/main at any time.

Behavior retained from the pilot without change: the `/route-answer` mount and its 8 KiB direct
target (`job_env.py:229`, `rest/mounts.py:329`), the `routed-answer-v1` envelope, the legacy
profile revision bytes (pilot `world/routing_config.py:175-187`), `unique-argmax-v1` with
`routing_ambiguous` on a tie, the pilot `routing_*` codes, and its policy and failure checks.

## 5. Ownership

| Owner | Responsibility |
|---|---|
| SDK | Authored values, freezing, whole-Recipe preflight, compilation, capability check before `POST /runs`, inline result and report decoding |
| Engine | IR validation per occurrence, metadata preflight, classification through the Gateway port, pure policy, conditional dispatch, evidence, failure completion and origin, run-boundary replay check |
| Gateway | Classifier wire formats, input capability and limits metadata, credentials, grants, upstream-attempt counts, classify capture and replay, seal provenance |
| E4c substrate | Lazy branch opening, skip members, quorum, budget ledger, Cascade lines |

Selection never moves into the Gateway. The SDK never runs a classify-then-chat loop. The core
never imports plugins; the SystemOne codec is a Gateway remote-endpoint plugin module selected by
the target's declared contract.

## 6. Contract index

| Contract | What it pins | File |
|---|---|---|
| C1 | `sf.Router`, `sf.ScoringClassifier`, `sf.RoutingPolicy` signatures and the complete runtime refusal matrix | [contracts.md](contracts.md) |
| C2 | `screamingface.router-spec.v1`: closed per-source, per-mode variants | contracts.md |
| C3 | `router-definition-v1` preimage and golden vectors V1-V5 | contracts.md |
| C4 | url4 block, step inputs, ADMIT preflight roles, failure completion | contracts.md |
| C5 | `screamingface.router-decision.v1` (completed only) and the internal draft | contracts.md |
| C6 | Policy table, version 1 | contracts.md |
| C7 | Gateway choice input, `input_contracts`, `classifier-limits-v1`, `X-AIGW-Upstream-Attempts` | [contracts-replay.md](contracts-replay.md) |
| C8 | Engine classification port, seeds, attempt facts | contracts-replay.md |
| C9 | `classify` frozen-copy entry, run definition set and run manifest | contracts-replay.md |
| C10 | `no_selection` readers before writers | contracts.md |
| C11 | Phases, codes, reservation, presentation | contracts.md |
| C12 | Capability IDs and discovery document | contracts.md |
| C13 | Inline entry, `router-answer.v1`, `sf.RouterAnswer`, SDK failure mapping | [contracts-entry.md](contracts-entry.md) |
| C14 | Prepared inputs | contracts.md |
| C15 | Kinds, stored results, definition snapshot, reports | contracts.md |
| C16 | Bounds | contracts.md |
| C17 | Engine classifier catalog | contracts-entry.md |
| C18 | Router outcome as Gate branch, Pipeline stage, Fusion member or synthesizer and Cascade tier | [contracts-placement.md](contracts-placement.md) |
| C19 | url4 at-most-one source: a named expansion bound to zero sources with no failure, or one source under its own name | contracts-placement.md |

## 7. Relation to the governing design

**PR #35 changes required: none.** Every contract above either fills a detail PR #35 assigns to the
implementation spec or wires a behavior PR #35 states. If a Unit finds that a design statement
cannot be met as written, it stops and the change goes to PR #35 before any code.

| PR #35 assigns to the implementation spec | Source | Pinned in |
|---|---|---|
| Public constructor, serialized IR, capability negotiation, inline result and error, prepared inputs, report revisions and read-back | `client/router-recipes.md:401-403` | C1, C2, C12, C13, C14, C15 |
| Validated size, count and token bounds | `client/router-recipes.md:147`; `classification-capabilities.md:23-25`, `:70-72` | Size and count: C16 and C7 `limits`; the token-aware bound stays inside the target (C7), pinned in Units 5.1 and 8 |
| Exact Router schema IDs | `engine/router-execution.md:139-141` | C2, C5, C13 |
| Capability identifiers and discovery payloads | `engine/router-execution.md:152-154` | C12 |
| Classify capture and lookup routes, payload and error shapes, attempt encoding | `engine/router-execution.md:379-382` | C9 |
| SystemOne declaration and bounded canonical request schema | `classification-capabilities.md:96` | C7 |
| Preparation signatures, source-reference shapes, reader paths and codecs | `client/router-recipes.md:228-229`; `engine/routing-inputs.md:61`, `:89` | C14 and the Unit 6 input spec |

Behaviors PR #35 states that this spec wires without changing them:

| Design statement | Source | Wiring |
|---|---|---|
| Replay validates the definition revision once at the run boundary; policy and revision are not per-call identity | `engine/router-execution.md:383-385` | C9 run manifest; classify entry keyed without revision |
| Every physical attempt is recorded; logical calls and attempts are distinct | `engine/router-execution.md:248`, `:367` | C7 header on chat and classification; C8 attempt facts; C5 `Attempts` |
| Fixed IR omits instructions and descriptions | `client/router-recipes.md:154-158` | C2 `FixedScoring` and `Plain` variants; V4 |
| `select="all"` keeps recognized labels in classifier order; unknown labels remain in evidence | `engine/router-execution.md:235`, `:238` | C5 selector evidence and the Router reply parser |
| A Model synthesizer reads the original input and completed member responses | `engine/router-execution.md:327` | C4 step inputs |
| Quorum and partial failure use E4c skip-member semantics | `client/router-recipes.md:113-117` | C4 panel |
| Terminal paths keep their record; a stored result keeps the decision | `engine/router-execution.md:334-343`; `engine/routing-inputs.md:113-117` | C4 failure completion; C15 |
| Each occurrence retains its selected label and Model set | `engine/router-execution.md:335-338`; `engine/routing-inputs.md:119-121` | C5 `selected` and `branches` carry `model`; C13 decodes from the envelope alone |
| Prepared data is read, verified and frozen before that Router's model I/O | `engine/routing-inputs.md:35`, `:90-91` | C9 run definition set; C14 |
| A retained result keeps the used definition snapshot and reads back without the source | `engine/routing-inputs.md:113-117` | C15: inline `url4`, prepared `router_definitions` |
| A Router abstention keeps each position's outcome rules; a required Router failure prevents synthesis | `engine/router-execution.md:105-110`, `:203-217`, `:322-325` | C10 vocabulary; C15 root Case outcome and attribution; C18 per position; C19 member slot |
| Entry adapters stay separate where envelopes differ | `engine/router-execution.md:36` | C13 |

Contracts added because the design requires an outcome but names no mechanism: the Engine
classifier catalog (C17, for the required SDK metadata preflight), the upstream-attempts header and
attempt facts (C7, C8, for recorded physical attempts), the seal-provenance `routers` field, its
read route and the run definition set (C9, for the run-boundary check and the frozen prepared
definition), `router_definitions` (C15, for the retained snapshot of a prepared definition),
`router_unsupported` outside a recorder scope (C4, for the retained decision), and the url4
at-most-one source with `router-placement-v1` (C19, C12, for a Fusion member abstention that is
neither an answer nor a failure). C19 uses Spec B's existing extensible `exec-key=value` as the exact
package extension `expand.at_most_one=true`; it changes neither the grammar nor a PR #35 rule. The
"existing URL4 syntax" constraint in `engine/routing-inputs.md:13-15` governs C14 input delivery,
not C18 placement.

## 8. Issue coverage

| Item | Issue | State on 2026-11-17 |
|---|---|---|
| Epic | OME-1306 | Open |
| Pilot Engine and SDK | OME-1822, OME-1823 | Open; landing needs separate authorization |
| E4c capability advertised by the Engine | OME-1921 (parent OME-1291) | Backlog, assigned outside this work |
| SDK refusal before the first paid call on an Engine without E4c | OME-1922 (parent OME-1291) | Backlog, `blocked` |

OME-1921 and OME-1922 define the capability path C12 extends. Unit 6 SDK writers cannot emit Router
IR before that path exists; coordinate with their owner before Unit 6. New leaves are filed at
PR-open, one per landing (`app/aigateway`, `app/screamingface-engine`, `pkg/client-sf`, and
`pkg/url4-sdk` for the url4 leaf), under OME-1306, after user confirmation. This spec files nothing.

## 9. Left to Units

This spec and the plan are normative for every Unit. A Unit gets its own ledger, fresh worktree,
RED-first tests and gates, not its own spec or plan. Each item below is pinned before code on the
affected interface by amending this spec in the section that owns it, and the owner re-approves only
the changed fragment: Unit 5.1 amends C7 (`contracts-replay.md`), the url4 leaf amends C19
(`contracts-placement.md`). A short Unit addendum is written only when a new implementation-changing
decision appears before code that neither this spec nor the plan covers, or when a Unit 6, 7 or 8
storage, API, IR or serving decision cannot be stated unambiguously here.

- Unit 5.1: pinned in C7, the question ID `choice`, the common Laya and Jev request, the native
  response checks, the target config keys for `limits` and the refusal code `classifier_limit_exceeded`.
- Unit 5.2 (**amendment pending owner approval**): C2/C3 pin dynamic-profile configuration and
  revision identity; C4/C6 pin the shared Engine boundary and the shipped fixed-profile error
  split; C4/C5 pin JOIN's input, the strict draft and early-failure identity; C8 pins direct-entry
  attempt observation; C16/C17 pin classifier discovery freshness, membership and read bounds.
  Approve these clauses and complete the Unit 5.1 SDK runtime proof before implementing Unit 5.2.
- Unit 6: url4 text of the panel body; the inline adapter's case key and occurrence numbering;
  inline error class names; the measured root GET limit and question bound; the prepared-input API,
  storage, retention, cleanup, multi-definition layout and reader codecs; the capability endpoint if
  OME-1921 has settled a different one.
- url4 leaf: pinned in C19, the `url4.src` keyword `at_most_one=` and the two-plus failure code
  `x.expansion_too_many`.
- Unit 7: placement refusal messages; the forms C18 leaves open (the member read, its route and the
  marked member slot, the Pipeline gate, a Router as a panel Gate's decision call in the IR, the
  report view of that Gate).
- Unit 8A (**amendment pending owner approval**): the checkpoint, artifact and serving boundary,
  native scalar wire, labels, token budget and refusal are pinned in the
  [C7 fixed-label reference](contracts-replay.md#fixed-label-reference-unit-8a). The isolated
  lock and consumed-file inventory are verified before implementation against the selected runtime.
  Checkpoint provisioning and real model qualification require separate approval.
- Unit 9: the hosted window, intermediary URL limits and mixed App/worker characterization.

## 10. Documents

1. `00-overview.md` — this file.
2. `contracts.md` — C1-C6, C10-C12, C14-C16.
3. `contracts-replay.md` — C7-C9: classification input, physical attempts, replay.
4. `contracts-entry.md` — C13 inline entry and result, C17 Engine classifier catalog.
5. `contracts-placement.md` — C18 Router outcome inside compositions, C19 url4 at-most-one source.
6. `test-plan.md` — first failing tests, acceptance per Unit, test-transition approvals.
