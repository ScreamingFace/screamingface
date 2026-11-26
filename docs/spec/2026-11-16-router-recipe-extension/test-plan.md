# Test plan: Router Recipe extension

Base `31c1158e8`. Each Unit's ledger turns this into exact test names; this file fixes what every
Unit must prove, the first failing tests and the prior-test transitions that need owner approval.

## 1. Ground rules

1. TDD in every Unit: the first commit of a behavior is a failing test.
2. Prior tests are append-only. A modified, deleted, renamed or retyped prior test, snapshot or
   fixture under `tests/` needs an exact approval manifest `.claude/test-change-approvals/OME-N.json`
   (base and approved blob per path), checked by the append-only gate (`.claude/scripts/run_gates.py:382`).
   An approval for one base blob never carries to another.
3. Model-free: fake HTTP upstreams and fake Gateway responses only. No live key, paid call,
   download or production action in any Unit before Unit 9's owner-approved window.
4. Historical results are not evidence for new code: every Unit reruns its full gates on its own diff.
5. Local substitutes do not prove Linux/NATS/JetStream, hosted auth or intermediary URL limits.
   Hosted readiness stays unclaimed until Unit 9 passes on the hosted path.
6. Every scenario that names a public call uses the real public Client entry
   (`client.route_answer`, `client.evaluate`, `client.classify`), cold and warm worlds.

## 2. Expected prior-test transitions

| PR | Path | Reason | Base blob |
|---|---|---|---|
| Pilot landing | `apps/screamingface-engine/tests/unit/test_url4_executor.py` | Pilot allowlist entry for `world/gateway_endpoints.py` | `4a2ba578bf28` |
| Pilot landing | `packages/screamingface/tests/public_surface_snapshot.json` | `RoutedAnswer`, `route_answer(profile, input)` | `c6a68a3ccc4b` |
| 5.1 | `apps/aigateway/tests/unit/remote_endpoint/test_app_classifier_catalog.py` | Catalog rows gain `input_contracts` and `limits` (`null` for its HF targets) | `d71d7abcbe95` |
| 5.1 | `apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json`, written by `tests/unit/test_cache_hit_contract_fixture.py` | The chat cache hit carries `x-aigw-upstream-attempts: 0` (C7) | `f935a58399c7` |
| 5.2 | `apps/screamingface-engine/tests/unit/test_url4_executor.py` | Allowlist for the Router runtime module | At 5.2 base |
| 5.2 | Engine tests pinning the exact `ENGINE_RESERVED_CODES` set, if any | `ROUTER_CODES` joins it | Listed in the Unit 5.2 ledger at its base |
| 5.2 | Engine tests pinning the Gateway world's exact runtime routes, if any | The Router runtime joins the existing branch and combine runtimes, including without benchmarks (C4) | Listed in the Unit 5.2 ledger at its base |
| 6, C10 readers | `apps/screamingface-engine/tests/unit/test_combine_pick_output.py` | Vocabulary gains `no_selection`; returned answers unchanged | `e8ecd83c4a8f334fad7b5325f77254767cbc9d92` |
| 6, C10 readers | `apps/screamingface-engine/tests/unit/test_combine_band.py` | Same vocabulary delta | `2a79e58a72c011b51efc6702da631448ce5dcd94` |
| 6, C10 readers | `apps/screamingface-engine/tests/unit/test_combine_gate_words.py` | Same vocabulary delta | `561939bc784df3d00466feb37d5d6189b7fc75ec` |
| 6, C10 readers | `apps/screamingface-engine/tests/unit/test_combine_evidence_words.py` | Same vocabulary delta | `059dc827432f5fde8f0ae8c7e1c864f7fe1909e1` |
| 6, C10 readers | `apps/screamingface-engine/tests/unit/test_combine_evidence_contract_fixture.py` | Exclude the new Router-only reason from prior writer samples | `d9df5ec0a67a119815ad597135b0b0d4c92f05b3` |
| 6, C10 readers | `apps/screamingface-engine/tests/unit/test_e4c_decision_cases.py` | Gate still does not write `no_selection` | `cfab822320ca0a140c79a93c80d12feb12af0a07` |
| 6, C10 readers | `packages/screamingface/tests/test_gate_words.py` | Reader/schema lists gain `no_selection` | `fe473507796a4ec18ce239f1a1fcd642d057cc97` |
| 6, C10 readers | `packages/screamingface/tests/test_band_words.py` | Same reader/schema delta | `e82b4fa46ffe9f62cfe4221532efb8a59b6074c5` |
| 6, C10 readers | `packages/screamingface/tests/test_evidence_words.py` | Same reader/schema delta | `01d9ea3400a7415e4747b3f8876d0fded2f1ffe7` |
| 6, C10 readers | `packages/screamingface/tests/test_pick_output.py` | Same reader/schema delta | `49408f2520950463f91a5823d0d942956e1087ec` |
| 6, C10 readers | `packages/screamingface/tests/data/schemas/screamingface.answer.v1.json` | Extend reason enums only | `f2275ecb6cb7a3174f14d7cb728d24f44ce31102` |
| 6, C10 readers | `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` | Extend reason enums only | `db067f2be462652c44a3d4212340fa0d21608158` |
| 6, C15 readers | `apps/screamingface-engine/tests/unit/data/combine_contract/binding_names.json` | Accept `router_7`, reject `router_7_admit`, `router_7_decide`, `router_7_block` | `226c5a61e17332f57a6c38fc182864e04e499fbd` |
| 6, Gateway | `apps/aigateway/tests/unit/test_frozen_copy_support.py` | Entry kind gains `"classify"` | `e297e0c3e1363c7c42c1284702f2f69f5343fb00` |
| 6, C15 readers or input snapshot | `packages/screamingface/tests/public_surface_snapshot.json` | `CandidateResult.router_definitions` and its constructor; approve when first exposed | `fd6ccf9f7f09e912842fe5a261144fdd35f7f2e4` |
| 6, SDK writers | `packages/screamingface/tests/public_surface_snapshot.json` | New Router types, errors, preparation and `route_answer` overloads; separately approve the writer delta | Snapshot blob above is the inventory baseline, not the writer's base |
| 6, SDK writers | `packages/screamingface/tests/data/surface_parity.json` | Only if the exact public diff changes parity | `6236801c8f7075182120e7c6d5c3d2068b4b35a5` |
| url4 leaf | url4 tests pinning the exact source-annotation key set or the builder's parameters, if any | `expand.at_most_one=true` uses the extensible execution-key form; the §8.1.3 exclusive source-key set stays unchanged (C19) | Enumerated in the url4 leaf ledger |

Unit 6 inventory blobs above are from `99072d273706f5ac673d49f5cd605a763e66c220` and are not
approvals. At each leaf's exact base, obtain the owner's approval of each old/new blob pair in
its own manifest before editing a prior test. If a changed base or newly discovered key-set test
requires a different transition, stop and obtain its own approval. One Engine/SDK owner integrates
the C10 ten prior tests and two schema fixtures, and C15's binding parity. Audit both workflow
path lists and the Engine foreign-fixture inventory for any new cross-stack fixture dependency.
`packages/screamingface/tests/test_frozen_record_fields.py`
derives its lists from `ABSTAIN_REASONS` and the schema (`:104`): it is rerun, not changed.
`apps/aigateway/tests/unit/test_frozen_copy_routes.py:188-198` keeps refusing an unknown provenance
field such as `build`: `routers` becomes a known field, so the test stays unchanged. The pilot's
existing manifests (`OME-1822.json`, `OME-1823.json`) were approved against `ffccfdce3c99` and
`b72408d416e7`; they are not relabeled or rewritten. Each Unit reruns the append-only check on
its real diff and lists every path it reports in its ledger, including any missing above.
`apps/screamingface-engine/tests/unit/test_classification_frozen_copy.py` keeps asserting that the
direct classification mount refuses capture and replay; Router capture is tested in new files.
Prior `_post_completion` tests keep their two-value unpacking and are rerun unchanged. The optional
observer has separate tests (C8).
The three pinned `report.v1` exports (`packages/screamingface/tests/data/report_v1_combine_report.json`,
`report_v1_gate_report.json`, `report_v1_vote_median_report.json`) stay byte-identical, because
`router_definitions` and `router` are written only when present (C15): their tests are rerun, not
changed. The url4 leaf changes no other prior test: unmarked and `;expand` sources keep their
behavior and rendered bytes (C19).

## 3. First failing tests

| Unit | First failing test |
|---|---|
| Pilot landing | The pilot's own routing tests on the integrated diff, unchanged, plus main's full suites |
| 5.1 | A choice target receives a native SystemOne body whose criteria follow `options` order, and the response projects to `classification-scores-v1` in returned order |
| 5.2 | The C3 golden vectors V1-V5 recomputed from their definitions, then the shared pure policy table (C6) as parametrized cases, with the named-profile adapter still mapping a tie to `routing_ambiguous` |
| 5.2 | A dynamic named profile sends choices in branch order and hashes its bound parameters. A mixed configuration fails at startup; metadata refusal, tie and a missing or extra label make no branch call. The fixed-profile TOML, digest, scalar body and distinct refusal codes stay unchanged. |
| 5.2 | Pure C6 `select="all"` yields the ordered selected indices and unknown evidence in the strict C5-compatible draft; include default and no-selection outcomes and malformed records. No subset execution or combine codec change. |
| 6, readers | `screamingface.answer.v1` decoders in SDK and Engine accept `no_selection`; nothing writes it yet |
| 6 | `sf.Router` construction: author order kept, `str` and `sf.Model` normalize to equal IR and the C3 vectors, input mutation cannot change it, every C1 matrix row |
| 6 | `client.evaluate(router, benchmark=...)` against fake upstreams calls the classifier once and exactly one selected Model per Case |
| 6 | `client.route_answer(router, question)` returns `RouterAnswer` decoded from a strict `router-answer.v1` envelope, with no benchmark and no outer Fusion |
| 6, subset | Approved positive/failing rendered panel goldens drive Router-to-combine selection and inline subset execution; unselected calls are absent, quorum failure prevents synthesis and JOIN publishes one C5 record |
| 6 | Capture then pinned replay of a Router run reproduces the decision and answer with zero live classifier or model I/O |
| 6 | A classify capture whose possibly sent first reply is lost records an `ambiguous` classify outcome and a `partial` capture, even when a later Engine attempt answers; a connect-phase failure that sent nothing is not ambiguous |
| 6, inputs | An oversize inline request is refused before capability mint, and the prepared carrier gives the same revision and selection |
| url4 leaf | A text panel of two plain sources and one marked `;expand` source with an empty body packs two entries, counts two for `quorum` and records no failure; holding `["x"]`, the marked source packs `name: x` where the unmarked expansion packs bare `x` |
| 7 | A Fusion of three single-select Routers over nine candidates runs three classifications, three selected generations and one synthesis |
| 8 | The BERT reference fixture passes the scalar decoder and a two-label fixed Router; text one token over the reference server's token-aware bound, special tokens counted, is refused untruncated |

## 4. Unit 5.1 fake-HTTP acceptance (gate before Engine integration)

All against a fake HTTP upstream; it must pass before Unit 5.2 depends on the contract.

1. Native Jev fixture: required `model`, `state`, `questions`; Laya fixture: model omitted or a checkpoint
   pin, no Jev-only fields sent. One question with the ID `choice` and `state` `{"body": text}`; no
   other field is sent; its identity is checked on the response.
2. Three-, four- and five-option questions from different definitions reach one service; criteria
   order equals `options` order; labels such as `LABEL_0` stay exact.
3. A scalar-only target refuses an object `input`, and a choice-only target refuses a string, with
   400 `unsupported_input`, zero upstream requests and `X-AIGW-Upstream-Attempts: 0`.
4. Malformed, empty, duplicate, non-finite, boolean or out-of-range probabilities, a repeated JSON key,
   a wrong answer type, a wrong question identity, reported truncation or colliding options
   (`usage.truncated`, `state_tokens_dropped`, `truncated_questions`, `usage.options`), a non-null
   `error` on the body and a non-null `error` on the `choice` answer (each beside valid
   probabilities), an upstream 413 or 422 and oversize bodies fail as `provider_error`, and the same
   answers fail readiness; an `error` of `null` in either place decodes normally, and a well-formed
   label outside the options is returned unchanged.
5. Every declared `classifier-limits-v1` key refuses with 400
   `{"detail": {"code": "classifier_limit_exceeded", "limit": "<key>", ...}}` before the credential is
   read. Startup refuses a choice value outside its C7 range and an HF value outside
   `1..2147483647`. An HF target without `limits` shows `limits: null` and accepts what it accepts
   today.
6. Two concurrent requests with different option sets and different keys never mix bodies or headers.
7. `/v1/classifiers` and `/v1/classifiers/details` show `input_contracts` and strict `limits` (text
   and choice variants, and `null` for an HF target without limits); the scalar path, its response
   body bytes, grants, managed key attach/replace/readiness, denied callers and no-fallback tests stay
   green unchanged.
8. Header origin matrix, on both chat and classification and for every C7 row: status and body are
   unchanged, and the header is `0` before upstream I/O (auth or dependency refusal, malformed body,
   unknown model or provider, missing Connection, grant refusal, own shedding, chat cache hit,
   frozen-copy replay hit, miss and unavailable), `n` after `n` physical send admissions. Cover one
   LiteLLM dispatch with a hidden connection-error resend (`2`), an outer 529 retry (`2`), a codec
   refusal before send (`0`) and a transport failure (`1`) under both shipped LiteLLM locks. At the
   Unit base, inventory and fake-test one send through every chat/classification transport family:
   shared/default LiteLLM, remote endpoint, local, OpenAI, Gemini, Codex and Antigravity. The
   production remote-endpoint transport has retries `0`. Source for both locks shows HuggingFace/
   Ollama pass the dispatched client to their base handler; the real Gateway test must prove its hooks
   for both, with accounting enabled and disabled (one send `1`, a hidden resend `2`; Ollama through
   a fake model listing and the fake transport, never a live host), and inability to observe them is a
   C7 stop condition.
9. The pure-ASGI middleware sits immediately inside outer `CallIdMiddleware` and outside every other
   user middleware: handled auth/body-cap/validation/error responses carry the header, while an
   unhandled ServerError response does not. Test `root_path="/gw"`, `auth_mode=disabled`, accounting
   collector absent and two hook increments across the auth middleware task boundary. Any Starlette
   outer body limit stays disabled on these routes or its pre-user-middleware 413 is explicitly outside
   the header promise. On a complete chat success with no omitted attempts, the header equals
   `sum(1 + redirect_hop_count)` over accounting attempts; test a folded redirect and a size-bounded
   response with omitted attempts. Partial/omitted accounting does not invalidate an otherwise observed
   physical-send header. A chat replay hit, a replayed error, a miss and an unavailable copy carry `0`,
   including the replay of a call that sent twice; the matcher already counts the classification replay
   path, whose hit, miss and unavailable cases the Unit 6 C9 row in §5 adds with the route.
10. Seal provenance accepts `routers` (1-256 strict entries) and still refuses every case of
    `apps/aigateway/tests/unit/test_frozen_copy_routes.py:188-198`;
    `GET /v1/frozen-copies/{id}/provenance` returns the stored value for a sealed copy, `[]` without
    `routers`, and `frozen_copy_unavailable` for unknown, open and malformed ids alike; any
    authenticated caller holding a sealed copy's id reads its provenance, as it may replay that copy.
    A stored row the seal would refuse today, written straight to the database (a list, a string or
    a number; a non-string, empty or over-long `engine_version`; `routers` null, an object, empty,
    over 256 entries or with one invalid entry; an extra key), reads `200` with exactly
    `{engine_version, routers}`, `null` and `[]` for the invalid parts and no extra key; the OpenAPI
    schema of the route is that strict response, a closed record (`additionalProperties: false`
    for the read and its entries), and the read model refuses an unknown key.
11. `screamingface-e2e-replay.yml` runs the model-free runtime transport test on Python 3.12. Run the
    same frozen-lock command locally under Python 3.13 and retain its output in the Unit evidence.
12. Shutdown, through the real app for the accounting handler and the attempt handler alike: a
    shutdown cancelled while the handler closes lets that close end, still runs the later steps, then
    raises the cancellation. On its own, the close helper logs a failed close without raising,
    logs it too when one cancellation is waiting, keeps waiting through repeated cancellations and
    raises only after the close ends, and a close cancelled twice under `asyncio.run` has ended, not
    been cancelled, when the loop stops. The prior cancelled-step shutdown test stays unchanged.

## 5. Contract tests each Unit must include

| Unit | Contract | Test |
|---|---|---|
| 5.2 | C2, C3 | Strict IR per variant: a missing key, an unknown key, a wrong type; a `FixedScoring` with `instructions` present as a string, `null` or `""`; a `Plain` candidate under `ChoiceScoring`; a `Described` candidate under `FixedScoring`, even with `""`; a `unique-argmax-v1` policy inside `router-spec.v1`; a `router-policy` in a named profile; duplicate `Calls` bindings; a revision that does not recompute; each refused at ADMIT before any I/O |
| 5.2 | C3 | Golden vectors V1-V5 byte-exact in the Engine core; V5 equals the SDK's compiled call parameters |
| 5.2 | C4 | In the lower-level single-select/default fixture, each classifier source and the branch that runs receive the injected `Q`; unselected branches make no calls. |
| 6 | C4 | In the subset panel fixture, each selected Model receives `Q`, the Model synthesizer receives `{input: Q, panel}`, and `sf.Vote` receives the panel only. Unselected or failed candidate output never enters the panel. |
| 5.2 | C4 | ADMIT preflight per role: an invisible classifier, a missing input capability, `limits: null`, and for each of the LLMClassifier Model, a candidate, the default and a Model synthesizer an unknown route, a missing Connection, a refused parameter and a non-executable route, each refused at ADMIT with zero classifier and zero chat requests |
| 5.2 | C4 | File admission sees literal calls for the supported standalone single-select/default runtime. One blind route yields public `intent_error` and zero model/classify sends or C5 records; do not disclose a private route. |
| 5.2 | C4 | Keep the static C4 route-enumeration fixture including a literal Model-synthesizer route as plan §8 requires; this checks scanning, not a compiled or executed subset panel. |
| 6 | C4, C9, C14 | Extend the admission proof to literal calls in the inline and prepared carriers, including the subset Model synthesizer. No provider, sibling or synthesizer runs after a run-level file admission refusal; do not leak private routes. |
| 5.2 | C4, C5 | Input-failure document, ADMIT refusal, classifier refusal, invalid evidence, selected/default failure, answered/default/no-selection: check one record, bounded code/permanence and no raw message. Test the input document independently of the prepared-question transport. Preserve strict C2/C3/C5 and pure C6 subset decisions. |
| 6 | C4, C5, C13 | Subset selection reader checks occurrence and indices, preserves selected order and never executes an unselected member. Test `quorum="all"` required-member failure, numeric floor, `quorum_not_met`, synthesizer failure and success through the panel and inline entry. The panel emits one collected row, and JOIN publishes once. |
| 5.2 | C4 | A Router outside a recorder scope is refused `router_unsupported` with zero model requests |
| 5.2 | C5 | The draft is never accepted by the stored-result, report or envelope readers |
| 5.2 | C4/C5 | The selected default's admitted Model and `Calls` supply the JOIN roles and attempt evidence. Malformed draft or mismatched occurrence/slots are contract errors. An input refusal takes precedence, performs no metadata or provider read and publishes exactly one `input` record with null definition fields; an `admit` refusal also has null fields. No valid binding means no invented record. |
| 5.2 | C5, C6 | Llm reply parser: classifier order, duplicates once, every distinct unknown kept in reply order and cut at 64 characters, 33 distinct unknowns give `unparsed`; E4c Gate parsing unchanged |
| 5.2 | C6 | Every table row, including regex `no_match` and llm `unparsed` giving `empty`, and llm `unrecognized` with and without a recognized label |
| 5.2 | C8 | Attempt facts for scoring classify, LLMClassifier, single-select candidate and default, on success and failure: an Engine transport retry gives `engine_attempts: 2`; OME-1872 retries count for chat; sum the headers across attempts; a missing header or lost reply makes the sum `null`; a cached attempt contributes `0`; `possibly_billed` follows its table. No policy retry or default run after classifier failure. |
| 6 | C8, C9 | Apply the same attempt assertions to the executed subset's selected members and Model synthesizer, for success and failure. Replay contributes zero upstream attempts without erasing earlier counts or unknowns. |
| 5.2 | C8 | Drive the direct named-profile entry through classifier and selected branch. Show internal role facts for success, refusal and failure, no fact for an unstarted role, no cross-invocation or late-cancellation write, no Candidate record, and identical public body and retry semantics. Test the optional observer through transport/queue and existing Candidate retries and on a final exception; no change to the two-value return. |
| 5.2 | C8 | Seeds by source in a seeded run: scoring sends no seed and does not refuse; an LLMClassifier call carries the seed as the E4c selector call does; regex makes no call; direct `GET /classify` still refuses |
| 5.2 | C11 | Spoof matrix: upstream branch or classifier responses carrying each Router code cannot emit Engine-authored Router codes in Case evidence or terminal HTTP. |
| 6 | C11, C13 | Repeat the spoof cases through the inline adapter; the envelope preserves the actual failure phase and a bounded code, never the spoofed Router code. |
| 5.2 | C17 | `GET /v1/classifiers` projects rows strictly with both `limits` variants and `null`, omits a row with an unknown limit key or contract, applies the caller identity of `/v1/models`, and makes no inference |
| 5.2 | C16/C17 | Fresh reads for two concurrent callers and a changed grant; no stale response on failure. Include a visible classifier outside the declared chat routes and profiles. Drop invalid or duplicate rows without changing valid order. Exercise inclusive byte bound, one byte more across chunks, unsupported encoding, malformed envelope and correctly empty list. Check private headers and zero inference. |
| 5.2 | C4 | A classifier-only world without benchmarks serves the Router, branch and combine routes, none as a direct mount; single-select/default/no-selection execution only. |
| 6 | C4, C13 | Execute the inline subset Router in that world after the panel goldens and reader are approved. |
| 6 | C1 | Every constructor matrix row with its exception class: `quorum=True` is `TypeError`; `quorum=0` and `quorum=len+1` are `ValueError`; a non-`str` classifier ID, an empty one; `instructions` of the wrong type, empty, over the bound; a non-mapping `candidates`; a non-`str` key; a wrong classifier or policy object; a wrong `match` or `select` value and type; a non-mapping record, an extra key, a non-`str` description, a Recipe model; `optional=True` and explicit `name=` on candidate, default and synthesizer Models; selector label set unequal to candidate keys; every cross-field rule |
| 6 | C1 | Closed synthesizer: `str`, `sf.Model` and `sf.Vote()` accepted; `sf.Vote(weights=...)`, `sf.Vote(over="benchmark")`, every other step, a Recipe, Pipeline and Fusion refused |
| 6 | C9 | Run manifest: the same function at capture and replay; a capture seals `routers`; replay after changing any part of any Router's `D` (each source, policy, default, quorum) fails `frozen_copy_miss` before any replayed or live request; a copy sealed without `routers` fails the same way; an unknown copy fails `frozen_copy_unavailable`; a replay run without a Router sends no provenance request |
| 6, inputs | C9, C14 | Prepared drift: capture with a prepared definition, change the source bytes behind a new reference while the expression still declares the captured revision, then replay the standalone Router: `frozen_copy_miss` before any request. A source changed after the run starts never reaches ADMIT, which reads the frozen `D` only |
| 6, inputs | C4, C14 | A missing, denied, expired, malformed, partially published or digest-mismatched prepared question becomes the strict input failure document; scoring CLASSIFY receives only the whole failed ADMIT document, returns exactly `{"not_run": true}` and never sees an empty substituted input or calls its port; JOIN publishes exactly one C5 record at phase `input`, with zero classifier/chat calls. The same `not_run` document beside accepted ADMIT is `router_evidence_invalid`. Deadline and cancellation remain control-plane endings without a Router record. The worker/world reader passes the database-layer gate with no Tortoise/asyncpg/aiosqlite import |
| 6 | C9, C16 | Run definition set refusals before `url4_run`, with zero requests and no Router record: 257 Routers in a raw expression, one `router` binding used twice, an unreadable or undecodable prepared source; the SDK refuses 257 Routers before submission; 256 run |
| 6 | C9 | Classify entry key: binding, occurrence and attempt separate identical requests; no revision header exists. The replay result preserves the recorded fields and status and carries `X-AIGW-Upstream-Attempts: 0`, as do a miss and an unavailable copy. |
| 6 | C9 | Capture owner vs. replay caller authority; original fields/status, replay-only `_aigw`, `request_economics.direct_cost_status="not_applicable"`. Successful replay: missing/malformed, measured zero and positive price reference. Recorded error: `usage_accounting.cache.reference: null`, original `detail` and supported headers. No provider/credential lookup or replay direct spend. Recheck chat/tool copies at the coordinated Gateway base. |
| 6 | C12 | Dormant App replies `[]`; valid future IDs ignored by older readers; malformed or missing required claims refuse before mint or start. Legacy HTTP sequences stay fixed. Recheck withdrawal across replicas, including a stale-positive/racing start, and prove accepted work drains on compatible readers. |
| 6, inputs | C14, C16 | Same digest under two principals does not cross authority. Interrupted upload never becomes visible; accepted inputs survive queue delay and worker replacement or admission refuses. Exercise expiry/sweep, revoked access, corrupt bytes, mixed carriers and C15 read-back with input/Gateway unavailable. Verify `L−1/L/L+1`, post-auth-only 414 and pre-parser refusal on the qualified profile. |
| 6 | C13 | Overloads: pyright reveals `RoutedAnswer` for `str` and `RouterAnswer` for `sf.Router`; `profile=`/`input=` keywords work for both; `router=`/`question=` raise `TypeError` |
| 6 | C13 | Strict `RouterAnswer`: every status row of the envelope table, a missing or unknown key, a `status` unequal to `decision.status` and a broken invariant are decode errors with no rerun |
| 6 | C5, C13 | `selected` and `selected_model` decode from the envelope alone, with no Router object in scope, for `selected`, `default`, subset and `no_selection` outcomes; a `selected` entry or a `branches` entry without `model` is a decode error |
| 6 | C13 | Failure mapping: each phase gives the Router execution error with its phase and code; `may_have_billed` is false only when every `Attempts` record is unbilled or no call ran; terminal frames give `True` |
| 6 | C15 | Stored results: a Router Case keeps the completed C5 under `router` on its operation; the Router record is not a provider call (`is_provider` false, so the accounting index and budget fold skip it); a result without a Router is byte-identical; the stored `url4` decodes the used definition |
| 6 | C15 | Attribution: the JOIN record and every Router model call that ran (classifier selector, selected candidate, default, synthesizer) appear as operations; an unselected candidate appears in none; Gate attribution unchanged |
| 6 | C10, C15 | Root outcome only: a standalone Router with `no_selection` stores the Case as abstained with the empty answer and `abstained` set; an answered Router stays answered; no Gate/Pipeline/Fusion/Cascade placement is admitted before Unit 7 |
| 6, inputs | C15 | Snapshot: `router_definitions` appears only with a prepared Router and holds its `D`; the saved-run rebuild and a Recipe rebuild read back after the source expired with zero source reads; a stored `D` whose recomputed revision differs from the stored one or from its C5 records is refused |
| 6, inputs | C15 | Persistence round trip: a prepared Router result saved through `sf.reports`, its source then unreadable behind a reader double that counts reads, comes back from `sf.reports.get` with an equal `router_definitions` and zero source reads; a copied saved run keeps it; its `report.v1` export carries the same list; a result body and a saved run without the key decode as before |
| 6 | C15 | `report.v1` shape: an export without a prepared Router has no `router_definitions` key and the three pinned exports stay byte-identical; a Case Operation without a Router has no `router` key; with one, `router` passes the strict wire decoder and `CaseOperation.to_dict` unchanged |
| 7 | C18 | Gate branch: a Router branch with `no_selection` gives the outer Gate result `abstain` with reason `no_selection`, the other branch makes zero calls and the Case is abstained; an answered Router branch stays answered; a failed one fails the Gate |
| 7 | C18 | Cascade: a Router tier with `no_selection` followed by `sf.escalate_if(sf.unanswered())` runs the next tier once, and a failed Router tier does the same; a Router last tier with `no_selection` makes the Case abstain; a bare Router tier before a signal line is refused before submission |
| 7 | C18 | Pipeline: a Router stage with `no_selection` before a Model stage makes zero downstream calls and stores the Case abstained with reason `no_selection`; a failed Router stage makes zero downstream calls and fails with its code; an answered Router stage passes its answer to the next stage, which runs once; a combine abstention inside a Pipeline still hands `""` on (AB-D2) |
| url4 leaf | C19 | Text panel: zero elements give no position, no `$name` binding, no entry and no failure, under `;required` and under `;optional`; one element packs `name: element` and binds `$name` to the raw element, `""` included; `quorum` counts zero and one |
| url4 leaf | C19 | Broadcast panel: zero elements give no part; one element gives `source_name: name`, never `name[0]`; the quorum gate counts as the text panel does |
| url4 leaf | C19 | Code binding: one element binds as `name` with the declared weight, never `name[0]` with a divided weight; zero elements bind nothing |
| url4 leaf | C19 | Failures: two elements fail the source with `x.expansion_too_many`, and a non-collection value with `expansion_not_iterable`; each is guarded by `;required` and `;optional` as any failure |
| url4 leaf | C19 | Refusals: a mark without `;expand` is refused at parse and by `url4.src`; an unnamed source, a named `;expand;<mark>` source without `;required`/`;optional`, a source with both guards, a guard with a value and a marked source whose `;expand` carries a value (`;expand=false`, which an unmarked source still reads as `;expand`) are refused at parse, by `url4.src` and on the tree path (`run(tree)`), with no fetch and no call, and so is a marked tree source whose name is empty, `src` or not an identifier; the mark as an expression parameter is refused wherever params are read: a group or iteration envelope, the inner tail of a reduce over iteration, the canonical call form `/p?<mark>&q=(a)!'i'`, both render paths, a node's HTTP query (HTTP 400, like any invalid param) and the params of any expression, relative call or remote call in a tree, an inline collection's included; a refused tree fetches no file, as its text fetches none; a C19 form inside an iteration's body, intent or reducer (the reducer's own `;` chain included), a relative call's context, a deferred group or a Form-3 `processor=` expression is refused by `compile_expression` and `run` before any fetch or call, while a prose or quoted context still ships verbatim and a row that fails on another rule is still skipped; a C19 form in a structured intent (a group's, a row's, a relative one or a Form-3 processor's) is refused at parse or before any fetch or call, never sent to a model as prose or read as a code pointer, and the intent classifier raises it, while an intent that only looks like url4 stays prose; an `@` in quoted text, in a URL's user or in a nested sibling never makes a context with a broken mark the receiver's, while a real holdings ref still ships it verbatim; a context group the text path defers is read as lowering reads it, so one that fails on another rule hides no C19 error beside or inside it, and with none such a call still compiles; in a skipped or collected row a member, an intent call or an intent param that breaks another rule never hides a C19 error, in either order and in a nested group, and without one a group still reports its first error; a text too deep for the eager parser is refused when it names the mark, a well-formed mark, a Form-3 processor and a relative call's context included, and a node answers it with HTTP 400, not 500, and compiles as before when it does not; the public eager readers (`parse`, `parse_value`, `build`, `classify_intent`) and the client front door refuse it too, and so do the builders and the client helpers given it as an intent or a reducer, `is_named_job` (a named job `render` checks, a code name `Url4Node.code` mounts) and `render` reading a structured intent back, before any fetch, and keep their `RecursionError` when it names no mark, each reading a text from as deep a caller as at base; a remote call's context, a relative reducer's context and a holdings context are forwarded byte for byte, and a receiving node of this version refuses the mark in them at its entry with no fetch; on an expression-valued member the raw parser refuses `;<mark>;required` and `;<mark>` alone, and parses `;required;<mark>` with the mark as a source annotation; the renderer refuses a mark ahead of every source-level key |
| url4 leaf | C19 | Bytes: `url4.src(..., at_most_one=True)` writes exactly one `expand.at_most_one=true` after `;required` or `;optional`, and parse then render keeps its bytes; another value, a duplicate and placement before every source-level key are refused; unmarked and `;expand` sources keep theirs; every prior url4 test passes unchanged |
| url4 leaf | C19 | Cross-version: a url4 install from `455166b0d`, in its own environment, runs the leaf's final rendered bytes of a text and a broadcast panel with two plain members and one marked member, under quorum 3 and quorum 2, with a process double that counts calls and records its sources. Zero elements: no source from the marked member; quorum 3 ends in `quorum_not_met` with zero process calls, and quorum 2 makes one call whose sources hold only the two plain members. One element: one source, bare in the text panel and `name[0]` in the broadcast collection. Two elements: two sources. The new reader, on the same bytes, gives no source, `name: element` and `source_name: name`, and the pinned code |
| 6 | C12 | A Recipe with a Router anywhere but its root is refused before submission, with zero requests |
| 7 | C12, C19 | Without `router-placement-v1`, the same Recipe is refused before `POST /runs` with zero requests and no marked source written; with it, the Router member slot is `member_i` with `;expand` and the mark |
| 7 | C18 | Fusion member: a Router with `no_selection` beside two Models is absent from the answered panel, from the Model synthesizer's context and from the url4 resolved count, in the text and the broadcast panel, with no member failure recorded; an answered Router keeps its `member_i` label in both panels (C19), an answered `""` included; the member read follows the C5 status, never the text |
| 7 | C18 | Quorum with one abstained Router of three members: default quorum `"all"` ends in `quorum_not_met` with no synthesis call; `quorum=2` synthesizes over the two that answered; `quorum=3` ends in `quorum_not_met`; an optional abstained Router under a numeric quorum is dropped the same way; a required Router failure still fails the Fusion; with skip members, the floor counts the abstained Router as selected and unanswered |
| 7 | C18 | Synthesizer: a Router synthesizer with `no_selection` stores the root Candidate's Case abstained with reason `no_selection`; the same Fusion as a Gate branch gives an abstained Gate result |
| 7 | C18 | Budget: a Router branch refused by `sf.WithBudget` records `budget_refused` with zero classifier/model calls; after a Router starts, its classifier/selected/default/synthesis charges reach later decisions; captured classifier price reaches replay through `cache.reference`, so live and replay make the same budget decisions |
| 7 | C9, C18 | Three sibling Routers with identical classifier request bodies retain distinct binding/occurrence evidence: capture then replay reproduces all three decisions and costs without exchanging entries or making live calls |

## 6. Acceptance per Unit

| Unit | Must prove | Design acceptance (`engine/router-execution.md`) |
|---|---|---|
| 5.2 | Dynamic choices run through the generalized named-profile path with one selected generation; legacy profile bytes and errors unchanged; C8 matrix through the direct entry | 4, 8, 10 |
| 6 | C1-C6, C9-C13, C15, C17: standalone evaluation, inline answers, subset with quorum and synthesis, `no_selection`, capability refusal before `POST /runs`, raw malformed IR refused at ADMIT, a completed record for every standalone/root terminal path in stored results, capture and replay of every complete terminal path, partial classification capture on lost-reply ambiguity, binding/attempt-aware classify keys, report read-back; the exact built base wheel repeats Router/decode/report smoke in an exact-lock clean environment where Pydantic/Tortoise are absent before any Client writer release | 1, 5, 6, 7, 10, 11, 13 |
| 6, inputs | C14 and C16: carrier parity, missing/denied/expired/mismatched/partial sources including queued worker reads, size extremes, unknown outcomes with no rerun, prepared drift refused at the replay boundary, read-back after input expiry from `router_definitions`; qualify each supported Uvicorn parser/protocol with one-write and fragmented delivery using the largest real Authorization/identity/trace header set, choose the Engine limit below the smallest whole-request envelope, assert in-envelope over-limit gives post-auth 414 and outer parser refusal may give pre-App 400 | 12 |
| url4 leaf | C19 in both panels and the code binding; the refusals (no `;expand`, no name, the mark before every source-level key on an expression-valued source); the cross-version run on the `455166b0d` reader; parse, render and builder round trip; clean base-wheel execution with Pydantic absent; prior url4 suites unchanged | None; C19 is a url4 form, not a design rule |
| 7 | C18: one-Router and three-Router Fusion; every C18 row in §5 (Gate branch, Cascade tier and last tier, Pipeline stage, Fusion member under each quorum, synthesizer, budget); three-Router capture/replay preserves sibling identities and costs; a failed Router member keeps its C5 record; recursive candidates are refused; the `router-placement-v1` check (C12) | 2, 3, 9, 13, 14 |
| 8A | Model-free [fixed-label reference](contracts-replay.md#fixed-label-reference-unit-8a) matrix below, including actual Client → Engine → Gateway → loopback fixture through existing scalar classify; isolated build, lock and artifact verification | Scalar portion of 4 |
| 8B | After 6 and 8A, standalone fixed-label Router in the V4 form; complete label coverage, tie and unknown-winner handling, and over-bound native refusal reaching the Router as a classifier failure with no generation or default call | Router portion of 4 |
| 9 | The rebuilt SDK wheel repeats the Unit 6 clean-base proof; an exact exported `[runtime]` lock environment installs it with `--no-deps`, asserts material versions, boots its vendored Gateway and separate Engine environment and passes strict records, attempt headers and fake capture/replay; live BERT, Laya and Jev use separate approved endpoints; hosted Linux/NATS/JetStream run covers intermediary URL limits; a new App with an old eligible worker refuses standalone and composed Router plans, a C19-marked Fusion included, before any source, classifier, model, sibling or synthesizer I/O, with zero paid calls; withdrawing `router-placement-v1` stops new marked submissions while accepted ones drain (C12) | 8, 12, 13 |

Across Units, every Router test also checks: unselected candidates make zero calls, every Engine
attempt and every Gateway upstream attempt of every Router call is recorded or explicitly unknown,
unknown cost stays unknown, and no failure triggers an implicit fallback, a lowered quorum or a
claimed free retry. Every strict numeric boundary rejects `NaN`, positive/negative infinity,
`1e999`/`-1e999` after parsing and a boolean used as a number; every closed union rejects missing/extra keys and any input matching zero or
multiple variants. Run the same vectors through Gateway/Engine Pydantic models, raw JSON/stored-result
readers, the C13 envelope and the dependency-free SDK decoder.

### Unit 8A model-free first RED

Start with the real reference HTTP boundary and fake tokenizer/head ports with call counters.
Give the fixture synthetic token IDs and two logits, with output labels from the approved contract.
First pin exact text delivery and the token cliff: 511 and 512 IDs including special tokens are
accepted and passed unchanged to the head once; 513 returns the exact native 422 body and runs
the head zero times. Include a case where special tokens alone push it over and a fixture that
would pass if the server truncated at 512. This proves the adapter's control flow, not real counts
for any text under the selected checkpoint.

| Boundary | Required deterministic witness |
|---|---|
| Request codec | A text with leading/trailing whitespace, mixed case and Unicode reaches the tokenizer unchanged. Duplicate, missing and unknown keys, a batch, null or numeric input, and invalid UTF-8 or a lone surrogate refuse before tokenization. At the inclusive wire bound a valid body reaches JSON validation; one byte more, including fragmented delivery, refuses with zero tokenizer/head calls. |
| Media and precedence | Use the header/combined-failure vectors below. Check status, exact closed error body, uncompressed `application/json`, and body-reader/tokenizer/head counts at each rejected boundary. |
| Output codec | Equal logits give ordered `NEGATIVE`, `POSITIVE` at 0.5 each; another pair proves full-vector softmax rather than sorting, thresholding or taking a maximum. Test large finite logits and refuse wrong arity, NaN, infinities and booleans without emitting scores. |
| Offline provisioning | Use the exact fixture manifest below; verify when each malformed input fails before loader entry and while external networking is denied. |
| Scalar composition and readiness | Use separate pinned Gateway and Engine processes and the SDK over loopback. Gateway uses multi-account auth with synthetic identities and grants/Connections, not the single anonymous principal of disabled auth. Test one granted caller plus denied and missing-Connection callers (zero upstream calls). Verify the original text and ordered normalized scores, and readiness `ping` through the same codec. A native over-token 422 makes one upstream send with no overload resend and maps to sanitized 502 `provider_error` at Gateway. A C7 character limit refuses before any send; keep existing scalar top-k coverage unchanged. |
| Isolation | From the isolated project, use `uv lock --check --offline`, `uv run --frozen --offline pytest -q` and its pinned lint, type and build checks. Inspect the Linux x86_64 CPU / Python 3.12 wheel resolution and built reference artifact; exclude weights, fetched tokenizer/config files and caches. Check the product manifests, locks and SDK base/runtime inclusion paths did not acquire any serving dependency. |

**Native header and precedence vectors.** Unless noted, use body `{"inputs":"ping"}` and a
valid fake encoding and head. Treat each listed disallowed form as a separate case.

| Headers or body | Response and boundary |
|---|---|
| `application/json` with no `Content-Encoding`; `application/json; charset=utf-8` with `identity`; `Application/JSON ; CHARSET="UTF-8"` with `Identity` and surrounding spaces/tabs | Each returns 200 and one head call. |
| Missing or duplicate `Content-Type` (even identical), comma list, `application/problem+json`, wrong charset, extra or repeated charset parameter, whitespace around `=` | 415 `unsupported_media_type`; no body read. |
| Valid `Content-Type`, but empty, duplicate or comma-list `Content-Encoding`, or `gzip` | 415 `unsupported_media_type`; no body read. |
| Refused header and a body of 65,537 bytes that is also invalid JSON | 415 wins; no body read. |
| Valid headers and 65,537 bytes of invalid JSON in two chunks | 413 `request_too_large` wins; never call tokenizer/head. |
| Valid headers, at most 65,536 bytes, but `{"inputs":"ping","extra":0}` with a tokenizer double that would emit 513 IDs | 400 `invalid_request` wins; no tokenizer or head call. |
| Valid request, 513 IDs including specials, and a head double that would raise | 422 `input_token_limit_exceeded` wins; exactly one tokenizer call and no head call. At 512 IDs with the same failing head, return 500 `classifier_failed`. |

**Offline fixture.** Put only the manifest below and these four fake regular files at the test
artifact root: `config.json` and `tokenizer_config.json` contain the two bytes `{}`;
`model.safetensors` contains the four bytes `head`; `vocab.txt` contains the three bytes `abc`.
None has a newline. These bytes are for fake loaders only, not a model checkpoint. For the
manifest use the exact UTF-8 bytes of the fenced JSON below, with LF line endings and one final LF.
Set `SF_BERT_REFERENCE_MANIFEST_SHA256` outside that root to
`9f94a3b04de4138225dc013b8cb2d858f99279ea87eb658b184d127e64b699a7`.

```json
{
  "schema": "screamingface.bert-reference-artifacts.v1",
  "model": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
  "revision": "714eb0fa89d2f80546fda750413ed43d93601a13",
  "license": "Apache-2.0",
  "files": [
    {
      "path": "config.json",
      "size_bytes": 2,
      "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    },
    {
      "path": "model.safetensors",
      "size_bytes": 4,
      "sha256": "9f2e6d33a3717ee826353a404ba4618d1aeeb6879ad7936bce8ed5f46814924d"
    },
    {
      "path": "tokenizer_config.json",
      "size_bytes": 2,
      "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    },
    {
      "path": "vocab.txt",
      "size_bytes": 3,
      "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    }
  ]
}
```

The valid snapshot reaches the fake loaders. Each invalid variant fails startup with zero loads:

- Keep the expected digest fixed and remove only the final LF; also test missing, malformed or
  mismatched external digest and an in-tree digest file in place of the external setting.
- Separately supply the matching digest of each malformed manifest from the test harness, so schema
  checks cannot pass merely by failing the digest check. Try wrong version/identity, missing,
  extra and duplicate keys at both record levels, empty files, repeated or reversed paths, `true`
  or `2e0` as a size, and uppercase hex. Try `/vocab.txt`, `../vocab.txt`, `./vocab.txt`, a nested or
  backslash path, a non-ASCII or uppercase alias, and the reserved `manifest.json` as file paths.
- Keep the manifest fixed and change one file's length, or change one byte without changing its length.
  Remove a listed file, add a hidden file or nested directory, or replace a listed file with a
  directory or FIFO. Reject a symlink replacing the root, manifest or a listed file, even if it points
  to the exact bytes inside or outside the root. Assert refusal without opening a non-regular
  payload for hashing, following a symlink, or making a fallback download.

Record exact base, interpreter, platform, lock/fixture digests, commands, outcomes, counters and
any skips. Keep the harness and fixtures in the isolated project so the product test suites do not
read them. A skipped or stubbed public path does not establish scalar composition. Preserve existing
product tests. Unit 8B tests the V4 fixed-score form with the qualified labels, exact matching and
no dynamic instructions/descriptions (reject even null or empty fields). Keep the existing C3 V4
hash vector unchanged. Neither the fixture result nor a sentiment score establishes real inference,
hosted readiness or Router quality; Unit 9 requires a separately approved window.

## 7. Not proven before Unit 9

| Item | Why | Detection |
|---|---|---|
| Live classifier behavior (BERT, Laya, Jev) | Needs approved endpoints, keys and a window | Unit 9 qualification |
| Hosted transport and auth | Local substitutes are not the hosted path | Unit 9 hosted run |
| Proxy and ingress URL limits | Not measurable locally | Unit 9, before enabling the hosted path |
| Mixed App/worker and App/Gateway rollout | Needs deployed old components | Characterization before hosted activation with a C19-marked Fusion and zero paid calls; withdraw and drain before an older worker takes work again (C12) |
| Classifier token budgets and truncation reporting | Provider-specific | Unit 5.1 fixtures, Unit 8 reference server, then Unit 9 live check |
