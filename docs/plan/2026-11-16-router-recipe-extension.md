# Router Recipe extension — implementation plan

**Status:** approved by the owner, 2026-11-19.
**Epic:** OME-1306. **Issues:** one leaf per landing, filed at PR-open after owner confirmation.
**Base:** origin/main `31c1158e8`.
**Governing design:** screamingface-design PR #35 at approved head `3e903bd`.
**Normative spec:** `docs/spec/2026-11-16-router-recipe-extension/`, contracts C1-C19.
**Preserved pilot:** `.claude/worktrees/byom-routing-pilot`, `89e6acfeb`, OME-1822/1823.

This plan orders implementation of the approved design and the approved spec. It does not approve
source edits, Git publication, Linear changes or live inference. The spec (C1-C19) and this plan are
normative for every Unit. Each delivery Unit gets its own ledger, fresh worktree, RED-first tests and
gates, and explicit implementation approval before code. Items the spec leaves open
(`00-overview.md` §9) are pinned by amending the spec before code; the owner re-approves only the
changed fragment. A separate Unit addendum is written only when a new implementation-changing
decision appears before code that neither the spec nor this plan covers. Each Unit's Linear issue
and `docs/tasks/` mirror are created at PR-open, after owner confirmation, then the branch is
renamed to `OME-N-<description>`.

## 1. Goal and completion boundary

Deliver one first-class immutable `sf.Router` that:

- evaluates a benchmark as one Candidate;
- answers one question through `client.route_answer(router, question)`;
- supports single selection, subset selection, authored default and `no_selection`;
- preserves routing evidence, attempts, costs, capture/replay and stored-result read-back;
- occupies the selected Model-equivalent Gate/Pipeline/Fusion/Cascade positions;
- composes as one or three Router members in Fusion;
- uses dynamic Laya/Jev choices and a fixed-label BERT reference through the shared classifier path.

The extension is complete only after Unit 9 proves the integrated hosted path. Local fake/live checks
do not establish production or hosted readiness.

## 2. Protected invariants

Every Unit preserves these contracts:

1. PR #35 is the behavior/architecture authority; C1-C19 are the implementation-contract authority.
2. Existing chat, scalar `client.classify`, profile-ID `route_answer`, reports and frozen copies remain
   compatible unless the spec names an approved additive transition.
3. Selection stays in Engine. SDK never orchestrates classify-then-chat; Gateway never selects a Model.
4. Unselected candidates make zero model calls. Classifier failure never invokes `default=`.
5. An abstained Router is a non-answer, not `""` as an answer and not a failure.
6. Unknown cost/attempt outcome remains unknown; no path fabricates zero spend or a safe retry.
7. Definitions, labels, candidates, order, Model policy and revisions are immutable and versioned.
8. Credentials remain in Gateway Connections; no key enters Router IR, URL4, queue payload, result,
   cache key, capture or diagnostics.
9. Readers deploy before writers. Capability IDs describe every eligible current/queued worker, not
   App metadata alone.
10. No live, paid or production action occurs before an owner-approved qualification window.

## 3. Dependency graph

```text
approved spec + approved plan
        |-----------+-----------+----------------+----------------|
        v           v           v                v                v
named-profile   Unit 5.1    C19 URL4 leaf   capability infra   Unit 8A model-free
   pilot        Gateway                         OME-1921/1922    BERT conformance
        |           |
        +-----+-----+
                   v
             Unit 5.2 Engine routing core
                   |---------------------|
                   v                     v
             Unit 6 readers/runtime   capability readers/refusal
                   |---------------------|
                              v
                  activate Unit 6 capability IDs
                              v
                    Unit 6 Client writers
                   |----------------------|
                   v                      v
         Unit 7 placements         Unit 8 BERT reference
         (also needs C19)          (does not need Unit 7)
                   |----------------------|
                              v
                    Unit 9 final qualification
```

Unit 5.1, C19, capability infrastructure and model-free Unit 8A may proceed in parallel after plan
approval. Pilot landing is separately authorized. Unit 5.2 and Units 6-9 require the pilot landed on
fresh main. Unit 6 reader/runtime work requires Unit 5.2 plus the capability discovery contract, but
its IDs activate only after their behavior/readers are deployed. Unit 7 requires Unit 6 plus C19.
Unit 8 Router integration requires Unit 6 but not Unit 7.

## 4. Preparation and issue slicing

Before the first implementation edit:

1. Land or pin the exact approved spec/plan commit; do not implement from this uncommitted worktree.
2. Confirm design PR #35's approved head/merge state and merged E4c `baedbd4` ancestry. Kevin's
   approval at `3e903bd` assumes the Nov 12 Router decisions remained aligned with Ionesio; before
   capability implementation, confirm with the OME-1921/1922 owner whether their shared lane lands
   first or Unit 6 uses the C12 fallback.
3. Re-read current `CLAUDE.md`, `.claude/sdlc.local.md` and the active stack card.
4. For the current spec/plan publication PR, after owner confirmation, file the
   `cross-unit/repo-dev-processes` OME-1306 leaf, self-assign it, apply the required actor/who-acts
   labels, create its `docs/tasks/` mirror and rename this branch to `OME-N-<description>`.
5. At each later implementation PR-open, repeat that workflow with one leaf per affected landing.
   Expected components are `app/aigateway`, `app/screamingface-engine`, `pkg/client-sf` and
   `pkg/url4-sdk`; close both Linear and mirror only after merge/acceptance.
6. Create a fresh worktree from then-current `origin/main` and that Unit's ledger; pin that Unit's
   open items by amending the spec (`00-overview.md` §9) and get the changed fragment approved.
7. Before source probes or RED tests, run `uv lock --check`, then `uv sync --frozen --python <v>` in
   every touched project for every interpreter `<v>` in that stack's workflow matrix: Python 3.12 and
   3.13 for AIGateway, Engine and Client; Python 3.12, 3.13 and 3.14 for URL4. Record
   `uv run --frozen --python <v> python -V` and resolved direct versions for each environment. Never
   use an inherited `.venv` as dependency evidence.
8. Enumerate every prior test/snapshot change reported by the append-only gate and obtain exact approval.

Do not enlarge OME-1822/1823 with new Router Recipe work. Do not restart Units 0-3. Unit 4 remains a
separately authorized qualification lane.

## 5. Pilot landing — fixed named-profile baseline

**Landing:** Engine + Client, OME-1822/1823. **Separate Git authorization required.**

1. Checkpoint only the 36 explicitly allowlisted source/test/docs/approval paths from the dirty pilot;
   exclude every other untracked generated index directory from every checkpoint/commit.
2. Integrate `89e6acfeb` with fresh main. The current reconciliation predicts seven overlapping paths
   and five conflicts: `error_text.py`, `test_url4_executor.py`, `CHANGELOG.md`, SDK `__init__.py` and
   `public_surface_snapshot.json`; `world/factory.py` and SDK `client.py` merge cleanly.
3. Keep main's E4c/logprobs/public-intent-error behavior plus pilot `ROUTING_CODES`, profile wire,
   `unique-argmax-v1`, legacy revision bytes and direct-helper semantics.
4. Obtain fresh exact approvals for `test_url4_executor.py` and `public_surface_snapshot.json` against
   their actual integration-base blobs; old OME-1822/1823 manifests remain historical evidence only.
5. Run Engine and Client gates and open the pilot PR only after diff review.

**Exit:** fixed named profiles and profile-ID `route_answer` are landed and green. No `sf.Router` claim.

## 6. Unit 5.1 — Gateway dynamic-choice adapter

**Landings:** `app/aigateway` implementation plus a `pkg/client-sf` runtime-compatibility test leaf.
**Depends on:** approved plan only; may run parallel with pilot/C19.

1. RED: add C7 fake-HTTP tests for text/choice contract discrimination, strict limits, exact native
   Laya/Jev bodies, response identity/order, malformed probabilities and concurrent isolation.
2. Add `ClassifierEntry.input_contracts` and versioned `classifier-limits-v1`; preserve scalar catalog
   and classification body bytes.
3. Add the bounded SystemOne choice codec under the remote-endpoint plugin; no arbitrary JSON,
   fallback, redirects, cookies or request-side model binding. C7 pins its native request and
   response checks, the target `limits` config and the limit refusal code before code.
4. Add the outer pure-ASGI attempt-header middleware and count physical sends in transport request
   hooks, below overload policy and LiteLLM's hidden resend. Inventory and instrument every current
   inference transport family, not only LiteLLM and remote endpoints. The middleware sits immediately
   inside `CallIdMiddleware`, strips `root_path`, shares one mutable counter across
   `BaseHTTPMiddleware` tasks and counts independently of the accounting collector. Preserve
   status/body; test handled early refusals and unhandled-error absence. Compare complete accounting
   with `sum(1 + redirect_hop_count)`; omitted/partial evidence cannot falsify the header. Prove the
   source-confirmed HuggingFace/Ollama generic LiteLLM client seam under both locks or stop C7 rather
   than emit a false zero.
5. Add the optional frozen-copy `routers` provenance reader and sealed provenance read route. Do not
   add the C9 `classify` frozen-copy entry/replay writer in this Unit.
6. Run AIGateway gates, no-Enterprise guard and append-only review.
7. The existing `screamingface-e2e-replay.yml` lane runs the new model-free runtime attempt test under
   Python 3.12 with LiteLLM `1.104.5`. In `packages/screamingface`, also run the same command locally
   under Python 3.13 and record `python -V`: `uv sync --frozen --python 3.13 --extra runtime && uv run
   --frozen --python 3.13 --extra runtime python -V && SCREAMINGFACE_TEST_E2E=1 uv run --frozen
   --python 3.13 --extra runtime pytest tests/e2e/test_runtime_router_transport_attempts.py -q`.

**Exit:** Unit 5.1 fake-HTTP matrix passes; old scalar classification remains byte-compatible.

## 7. C19 URL4 leaf — named at-most-one expansion

**Landing:** `pkg/url4-sdk`. **Depends on:** approved plan only; prerequisite of Unit 7.

1. Pin `expand.at_most_one=true` as a public package extension using Spec B's existing extensible
   `exec-key=value` and Spec C's unknown-key fallback; no grammar or design-repo amendment. C19 pins its
   builder surface (`at_most_one=`) and two-plus failure code (`x.expansion_too_many`) before code.
2. RED: text, broadcast and code-binding tests for zero, one, empty-string, two-plus, non-collection,
   unnamed, missing-expand and annotation-order cases under required/optional and quorum.
3. Implement C19 in parser, AST/lowering, gather/broadcast/code binding, builder and renderer. The mark
   refines ordinary expansion; unmarked and ordinary `;expand` bytes/behavior remain unchanged.
4. Cross-version-test the final bytes in an isolated `455166b0d` URL4 environment:
   zero remains absent; one degrades to bare/`name[0]`; two remain two old-reader sources. The new reader
   restores `name` and refuses two with the pinned code.
5. Run the project URL4 gate, including its current 95% coverage floor, and every prior URL4 suite.
6. Build the URL4 wheel and install its base dependency set only: with Pydantic absent, exercise C19
   parse/render plus text, broadcast and code-binding execution. Release/deploy readers before any
   Unit 7 compiler emits the mark.

**Exit:** C19 matrix and old-reader fallback are green; no Router code is part of this landing.

## 8. Unit 5.2 — shared Engine routing core

**Landing:** `app/screamingface-engine`. **Depends on:** pilot landed + Unit 5.1.

1. RED: C2/C3 strict records and vectors V1-V5, every C6 policy row, named-profile tie/error parity,
   source-specific seed behavior and C11 spoof matrix.
2. Extract one Engine-owned routing application boundary used by dynamic named profiles and compiled
   Router definitions. It owns metadata/access preflight, evidence validation, the pure policy core,
   selected-route dispatch ports, attempt facts and failure normalization. Keep the profile and Recipe
   entry adapters/presenters separate; do not build a second orchestration policy behind either one.
3. Add Router runtime foundations, failure-as-data completion through JOIN, attempt facts and the Engine
   classifier catalog C17. Install Router/branch/combine runtime for Gateway worlds without benchmarks.
4. Generalize dynamic named-profile config without changing legacy fixed-profile bytes.
5. Keep every Router model call in the C4 block as a literal url4 call inside a gated iterate, so the
   existing `run_model_routes` scan reads it without a definition-derived route enumerator. Test on a
   C4 block fixture that it exposes every LLMClassifier, candidate, default and Model-synthesizer route
   while preserving private-route non-disclosure. Through the same shared world-level admission entry
   used by `_ModelEndpoint`, make ADMIT await the run's check before scoring CLASSIFY.
6. Run Engine gates, layering and append-only review.

**Exit:** dynamic choices execute through the shared core with one selected generation; legacy profile
and scalar classification behavior remain unchanged.

## 9. Capability infrastructure and per-ID activation — OME-1921/1922

**Preferred shared landings:** OME-1921 Engine discovery document, then OME-1922 Client
reader/refusal. They remain OME-1291-owned work, not ordinary OME-1306 leaves, and may proceed after
plan approval. They are not hard Unit 6 blockers: if their owner does not land the shared path first,
Unit 6 ships the exact C12 endpoint and Client reader under its own OME-1306 Engine/Client leaves.

1. Land the strict discovery document and open-ID Client reader through OME-1921/1922 when available;
   otherwise deliver the same contract in Unit 6. Missing discovery means unsupported.
2. Client whole-Recipe preflight can compute required IDs before Unit 6, but no Router ID is advertised
   merely because the discovery endpoint exists.
3. Unit 6 deploys its Gateway/Engine/report readers and dormant runtime first. Only then activate
   `router-v1`, `classify-frozen-copy-v1` and `router-input-ref-v1` for the eligible worker fleet.
4. Release/enable Unit 6 Client writers only after those IDs are observable and mixed workers refuse
   unsupported work with zero I/O.
5. Unit 7 repeats the same activation sequence for `router-placement-v1` after C18/C19 readers.
6. Before rollback/reintroduction, withdraw the affected ID, stop new submissions and drain accepted work.

**Exit:** discovery/refusal infrastructure exists independently; each ID activates only after the
behavior it certifies is deployed. Unsupported Recipes fail before submission/paid I/O.

## 10. Unit 6 — first-class Router Recipe

**Landings, reader-first:** Gateway C9 lookup/digest/replay readers; Gateway C9 capture writer; Engine/vocabulary/
report readers and runtime; capability-ID activation; Client public writer/compiler. **Depends on:**
Unit 5.2 + the C12 discovery/refusal contract, supplied by OME-1921/1922 when already landed or by
Unit 6's own OME-1306 Engine/Client leaves otherwise.

1. Readers PRs: add `no_selection`, strict Router definition/decision/result/report readers,
   `router_definitions`, operation bindings, the binding/attempt-aware classify digest, Gateway
   `EntryKind="classify"` lookup and the `/v1/frozen-copies/{id}/classifications` replay
   response/header behavior, plus Engine/Client decoders before writers.
2. Gateway writer PR: add capture insertion. Keep it disabled until the reader release is deployed.
3. Engine PR: add C1-C6/C9-C17 runtime, run definition set, run-boundary replay manifest, classifier
   capture/replay, inline answer adapter and prepared definition/question reader/storage contracts.
4. Prove the prepared carrier moves only `D` and keeps the same literal URL4 bodies and admitted route
   set as the inline carrier, with zero classify/chat calls and no Router C5 record on run-file refusal.
5. Activate `router-v1`, `classify-frozen-copy-v1` and `router-input-ref-v1` only after all required
   Gateway/Engine/report readers and eligible workers are deployed.
6. Client PR: add immutable `ScoringClassifier`, `RoutingPolicy`, `Router`, compiler/rebuild/topology,
   standalone evaluation, strict dependency-free reports/decoders and the overload
   `route_answer(router, question)`; do not add Pydantic to the base SDK. Before releasing this writer,
   build the exact wheel, export the exact base lock with `uv export --frozen --no-dev
   --no-emit-project`, populate a clean environment, install the wheel with `--no-deps`, assert
   Pydantic/Tortoise are absent, and run Router/decode/report smoke.
7. Prepared inputs: explicit publication, scoped worker read, digest/schema verification, retention,
   expiry/cleanup and stored-result read-back after source expiry; a prepared-question domain failure
   enters C4 as data so JOIN remains the one C5 publisher. Tortoise/asyncpg/aiosqlite stay confined to
   the Engine `runs/` control-plane boundary; worker/world code reads through a framework-free port and
   worker-visible adapter. Reusing blob infrastructure requires a bounded text/JSON media policy,
   authority and lifetime contract. If persistence adds a `runs/` table or field, the Unit includes
   the migration plus SQLite/Postgres migration tests before its reader; no silent upload or
   post-refusal rerun. Qualify request-target ceilings for every supported Uvicorn parser/protocol with
   one-write and fragmented delivery plus the largest real Authorization/identity/trace header set.
   h11's ceiling applies to the whole incomplete request head, while httptools' target behavior differs;
   set the Engine limit below the smallest observed envelope. Only requests reaching the App are
   promised post-auth 414, while outer parser refusal may be 400.
8. Replay: changed definition/source misses before live I/O; captured classifier cost remains a
   `cache.reference`; classify lost-reply ambiguity uses the existing partial-capture rule; every
   complete terminal path preserves phase/attempts/spend evidence.
9. Run affected Gateway, Engine and Client gates plus all exact transition approvals.

**Exit:** root Router single/subset, inline/prepared parity, report read-back and zero-live-I/O replay pass.

## 11. Unit 7 — Router inside compositions

**Landings, reader-first:** Engine C18 readers/runtime, then Client compiler/writer. **Depends on:** Unit
6 + landed C19 URL4 leaf.

1. Engine reads Router C5 outcomes in Gate/Pipeline/Fusion/Cascade positions; abstention is a non-answer,
   failure keeps required/optional semantics and no alternate branch opens implicitly.
2. Client compiles Fusion Router members through named expanded C19 slots and pins exact text,
   broadcast and code-binding bytes. An answered empty string remains an answer.
3. Add `router-placement-v1` preflight and activate only after all eligible workers have C18/C19.
4. Test Gate branch, Pipeline stop, Cascade escalation/last tier, Fusion member under all/numeric quorum,
   Router synthesizer, one Router + Model and three Routers/overlapping pools. Under `sf.WithBudget`,
   prove pre-start `budget_refused` with zero calls, started Router spend reaching later decisions and
   equal live/replay decisions. Capture/replay three identical sibling classifier bodies without
   exchanging binding/occurrence evidence or costs.
5. Test C19-marked new-App/old-worker refusal and withdraw/drain rollback with zero paid calls.
6. Run Engine and Client gates and exact public-surface approvals.

**Exit:** every C18 position has the same answer/abstain/failure semantics as an ordinary completed Model.

## 12. Unit 8 — BERT fixed-label reference

Split the work so model-free conformance is not serialized behind Unit 6.

1. **Unit 8A, after plan approval:** pin the reference-server scalar request/result contract,
   checkpoint/artifact revision, tokenizer/serving versions, label meanings and token-aware bound;
   build the isolated fake/reference-server conformance fixtures through existing scalar classify.
2. Give the reference server its own project lock and build artifact, with explicit CPU/GPU target and
   platform wheels. Keep serving dependencies out of AIGateway, Engine, SDK base/runtime and URL4
   manifests; use the shared scalar classifier contract and an isolated reference bundle/server.
3. **Unit 8B, after Unit 6:** add fixed-label Router V4 integration and actual Client -> Engine ->
   Gateway -> fake target tests, including denied account, exact text, complete label vector,
   malformed scores and at/over-bound no-truncation refusal.
4. Fixed-label Router tests use no instructions/descriptions and invent no arbitrary labels.
5. Real endpoint/weights qualification only in an approved Unit 9 window.

**Exit:** shared classifier + fixed Router contract passes; no quality claim beyond the qualified labels.

## 13. Unit 9 — integrated/live/hosted qualification

**Depends on:** Units 5-8 and authorized infrastructure/endpoints/window.

1. Run all affected stack gates and append-only/public-surface approvals on the integrated diff.
2. Rebuild the exact SDK wheel and repeat the Unit 6 clean-base smoke. Export the exact `[runtime]`
   lock set with `uv export --frozen --no-dev --extra runtime --no-emit-project` into a second clean
   environment, assert every material version, install that wheel with `--no-deps`, boot its vendored
   Gateway plus separately built Engine environment, and run the strict-record/attempt-header matrix
   and one fake Router capture/replay round trip. Separately run one unconstrained public
   `pip install <wheel>[runtime]` smoke and record its resolved versions; it is distribution-range
   compatibility evidence, never lock evidence.
3. Local integrated fake HTTP: real Gateway auth/Connections plus cold/warm Engine worlds under the
   app locks and the SDK runtime lock.
4. Live BERT/Laya/Jev: exact versions, keys via Connections, bounded inputs/outputs/time/spend and
   separate evidence per target; no inference from one target's fixture to another.
5. Hosted Linux/NATS/JetStream: queue -> real cold/warm worker -> Gateway under real auth, applied
   capability/config revisions, result/replay/read-back and intermediary URL limits.
6. Mixed rollout: new App/old worker and App/Gateway combinations, including C19-marked Fusion. Any
   paid call on unsupported work fails activation. Prove capability withdrawal and drain before rollback.
7. Publish a final evidence report separating deterministic, local-live, hosted, quality and accounting
   facts. Keep old Unit 2/3 pending gates separate unless their own acceptance is actually met.

**Exit:** all design acceptance is evidenced; only then claim Router extension and hosted readiness.

## 14. Per-Unit verification and reporting

Each Unit ledger must list exact new tests and exact prior files requiring approval from
`test-plan.md`. Minimum project gates:

| Landing | Gate |
|---|---|
| `app/aigateway` | `uv run .claude/scripts/run_gates.py aigateway` |
| Unit 5.1 SDK-runtime compatibility | CI `screamingface-e2e-replay.yml` runs Python 3.12. Also run locally under Python 3.13 and record `python -V`: `cd packages/screamingface && uv sync --frozen --python 3.13 --extra runtime && uv run --frozen --python 3.13 --extra runtime python -V && SCREAMINGFACE_TEST_E2E=1 uv run --frozen --python 3.13 --extra runtime pytest tests/e2e/test_runtime_router_transport_attempts.py -q` |
| `app/screamingface-engine` | `uv run .claude/scripts/run_gates.py screamingface-engine` |
| `pkg/client-sf` | `uv run .claude/scripts/run_gates.py screamingface` |
| `pkg/url4-sdk` | `uv run .claude/scripts/run_gates.py url4` |
| Repo-only docs/process | repo card checks plus Markdown links/tables/`git diff --check` |

Every report names changed files, commands actually run, exact base/head, prior-test approvals,
deterministic versus live evidence, residual risks and blocked hosted checks. Historical pass counts are
not evidence for a new diff.

## 15. Rollout and rollback order

1. Gateway/Engine/URL4/report readers and capability discovery.
2. Engine runtime writers.
3. Homogeneous/capability-aware worker activation and mixed-version characterization.
4. Client compiler/public writers.
5. Live cohort enablement only after zero-I/O unsupported-work checks.

Rollback reverses writers first: withdraw capability IDs, stop new submissions, drain accepted work,
then roll back workers/readers. Preserve chat/classify/profile calls, stable IDs, Connections, shared
cache behavior, stored reports and frozen copies; do not revoke unrelated keys or lower the Unit 3
capability floor (`engine/router-execution.md:427-430`).

## 16. Immediate next action after plan approval

After explicit owner approval of this plan:

1. Prepare/file the landing issues only when opening each PR, after owner confirmation.
2. Start Unit 5.1 Gateway and the C19 URL4 leaf in separate fresh worktrees; no live calls.
3. Pursue pilot landing only under separate checkpoint/commit/push/PR authorization.
4. Do not start Unit 5.2, Unit 6 or Unit 7 before their dependencies land and their open items
   (`00-overview.md` §9) are pinned in the spec and approved.
