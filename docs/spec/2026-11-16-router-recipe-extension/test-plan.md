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
| 5.2 | Any test asserting a world without benchmarks serves no runtime routes | Router, branch and combine runtimes install with the Gateway world (C4) | Listed in the Unit 5.2 ledger at its base |
| 5.2 | Engine tests pinning `_post_completion`'s return shape, if any | It also returns the Engine attempt count (C8) | Listed in the Unit 5.2 ledger at its base |
| 6, readers | `apps/screamingface-engine/tests/unit/test_combine_pick_output.py` (`:358`, `:368`) | Vocabulary gains `no_selection` | At 6 base |
| 6, readers | `apps/screamingface-engine/tests/unit/test_combine_band.py` (`:682-694`) | Same | At 6 base |
| 6, readers | `apps/screamingface-engine/tests/unit/test_combine_gate_words.py` (`:776`, `:782`) | Same | At 6 base |
| 6, readers | `apps/screamingface-engine/tests/unit/test_combine_evidence_words.py` (`:323`) | Same | At 6 base |
| 6, readers | `apps/screamingface-engine/tests/unit/test_combine_evidence_contract_fixture.py` (`:488-490`) | `AbstainReason` minus writers' reasons must also exclude `no_selection` | At 6 base |
| 6, readers | `apps/screamingface-engine/tests/unit/test_e4c_decision_cases.py` (`:167-169`) | Gate results never write `no_selection`; exclude it like `cut_not_met` | At 6 base |
| 6, readers | `packages/screamingface/tests/test_gate_words.py` (`:591` and the lists at `:531`, `:598`) | Vocabulary gains `no_selection` | At 6 base |
| 6, readers | `packages/screamingface/tests/test_band_words.py` | Same | At 6 base |
| 6, readers | `packages/screamingface/tests/test_evidence_words.py` (`:460-475`) | Pinned `answer.v1` lists | At 6 base |
| 6, readers | `packages/screamingface/tests/test_pick_output.py` (`:214-228`) | Pinned `answer.v1` lists | At 6 base |
| 6, readers | `packages/screamingface/tests/data/schemas/screamingface.answer.v1.json` | Schema lists gain `no_selection` | At 6 base |
| 6, readers | `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` | Same | At 6 base |
| 6, readers | `apps/screamingface-engine/tests/unit/data/combine_contract/binding_names.json` | Pattern adds `router`; accepts `router_7`, rejects `router_7_admit`, `router_7_decide`, `router_7_block` (C15) | At 6 base |
| 6, readers | Tests pinning the exact `candidate-result.v1` key set or the SDK `CandidateResult` fields, if any | `router_definitions` (C15) | Enumerated in the 6 spec |
| 6, readers | Tests pinning the exact wire Case Operation key set, if any | `router` joins `combine` and `decision` as an optional key (C15) | Enumerated in the 6 spec |
| 6 | `apps/aigateway/tests/unit/test_frozen_copy_support.py` (`:26`) | Entry kind gains `"classify"` | At 6 base |
| 6 | `packages/screamingface/tests/public_surface_snapshot.json` | `Router`, `ScoringClassifier`, `RoutingPolicy`, `RouterAnswer`, the `route_answer` overloads | At 6 base |
| 6, inputs | `packages/screamingface/tests/public_surface_snapshot.json` | The new `CandidateResult` field and constructor parameter `router_definitions` (C15) | At that PR's base |
| 6 | `packages/screamingface/tests/data/surface_parity.json` | If parity covers the new exports | At 6 base |
| url4 leaf | url4 tests pinning the exact source-annotation key set or the builder's parameters, if any | `expand.at_most_one=true` uses the extensible execution-key form; the §8.1.3 exclusive source-key set stays unchanged (C19) | Enumerated in the url4 leaf ledger |

The `no_selection` reader PR changes 10 prior test files and 2 schema fixtures; the stored-result
reader PR changes `binding_names.json`. `packages/screamingface/tests/test_frozen_record_fields.py`
derives its lists from `ABSTAIN_REASONS` and the schema (`:104`): it is rerun, not changed.
`apps/aigateway/tests/unit/test_frozen_copy_routes.py:188-198` keeps refusing an unknown provenance
field such as `build`: `routers` becomes a known field, so the test stays unchanged. The pilot's
existing manifests (`OME-1822.json`, `OME-1823.json`) were approved against `ffccfdce3c99` and
`b72408d416e7`; they are not relabeled or rewritten. Each Unit reruns the append-only check on
its real diff and lists every path it reports in its ledger, including any missing above.
`apps/screamingface-engine/tests/unit/test_classification_frozen_copy.py` keeps asserting that the
direct classification mount refuses capture and replay; Router capture is tested in new files. The
three pinned `report.v1` exports (`packages/screamingface/tests/data/report_v1_combine_report.json`,
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
| 6, readers | `screamingface.answer.v1` decoders in SDK and Engine accept `no_selection`; nothing writes it yet |
| 6 | `sf.Router` construction: author order kept, `str` and `sf.Model` normalize to equal IR and the C3 vectors, input mutation cannot change it, every C1 matrix row |
| 6 | `client.evaluate(router, benchmark=...)` against fake upstreams calls the classifier once and exactly one selected Model per Case |
| 6 | `client.route_answer(router, question)` returns `RouterAnswer` decoded from a strict `router-answer.v1` envelope, with no benchmark and no outer Fusion |
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
| 5.2 | C4 | Lower-level C4 block fixture, not public placement: for each source (scoring, llm, regex), the classifier, every selected candidate and the default receive the injected `Q`; a Model synthesizer receives `{input: Q, panel}`; `sf.Vote` receives the panel only; an unselected or failed candidate's output never enters the panel |
| 5.2 | C4 | ADMIT preflight per role: an invisible classifier, a missing input capability, `limits: null`, and for each of the LLMClassifier Model, a candidate, the default and a Model synthesizer an unknown route, a missing Connection, a refused parameter and a non-executable route, each refused at ADMIT with zero classifier and zero chat requests |
| 5.2 / 6 | C4, C9 | OME-1809 run-file admission: with image/PDF attachments, `run_model_routes` sees the LLMClassifier, every candidate, default and Model synthesizer for the inline and prepared carriers; one blind route ends the run with `intent_error`, zero Router C5 records and zero Router, sibling or synthesizer provider calls, while a private route absent from caller-visible metadata is not named. With a ScoringClassifier, classification upstream calls are also exactly zero: CLASSIFY cannot run before the shared admission check succeeds |
| 5.2 / 6 | C4, C5 | Failure completion, one test per terminal path with the C5 record read from the Case recorder and the failure re-raised with its code and permanence: prepared-question input failure, per-occurrence metadata ADMIT refusal, scoring classify failure, LLMClassifier failure, invalid evidence, selected candidate failure, default failure, `quorum="all"` member failure, `quorum_not_met`, synthesizer failure; plus answered, default and `no_selection` paths. Each publishes exactly one record, and no record holds a message; the separate run-file admission refusal above publishes none |
| 5.2 | C4 | A Router outside a recorder scope is refused `router_unsupported` with zero model requests |
| 5.2 | C5 | The draft is never accepted by the stored-result, report or envelope readers |
| 5.2 | C5, C6 | Llm reply parser: classifier order, duplicates once, every distinct unknown kept in reply order and cut at 64 characters, 33 distinct unknowns give `unparsed`; E4c Gate parsing unchanged |
| 5.2 | C6 | Every table row, including regex `no_match` and llm `unparsed` giving `empty`, and llm `unrecognized` with and without a recognized label |
| 5.2 | C8 | Attempt facts for scoring classify, LLMClassifier, candidate, default and Model synthesizer calls, on success and failure: an Engine transport retry gives `engine_attempts: 2`; OME-1872 retries count for chat; the header sums across Engine attempts; a missing header or a lost reply gives `null`; a replayed or cached call gives `0`; `possibly_billed` follows its table; no policy retry after a classifier failure and no default run |
| 5.2 | C8 | Seeds by source in a seeded run: scoring sends no seed and does not refuse; an LLMClassifier call carries the seed as the E4c selector call does; regex makes no call; direct `GET /classify` still refuses |
| 5.2 | C11 | Spoof matrix: an upstream branch or classifier response carrying each Router code is not relayed as that code (reserved), per case, at terminal HTTP and in the C13 envelope |
| 5.2 | C17 | `GET /v1/classifiers` projects rows strictly with both `limits` variants and `null`, refuses an unknown limit key or contract, applies the caller identity of `/v1/models`, and makes no inference |
| 5.2 | C4 | A classifier-only world without benchmarks serves the Router, branch and combine routes, none as a direct mount, and runs an inline subset Router there |
| 6 | C1 | Every constructor matrix row with its exception class: `quorum=True` is `TypeError`; `quorum=0` and `quorum=len+1` are `ValueError`; a non-`str` classifier ID, an empty one; `instructions` of the wrong type, empty, over the bound; a non-mapping `candidates`; a non-`str` key; a wrong classifier or policy object; a wrong `match` or `select` value and type; a non-mapping record, an extra key, a non-`str` description, a Recipe model; `optional=True` and explicit `name=` on candidate, default and synthesizer Models; selector label set unequal to candidate keys; every cross-field rule |
| 6 | C1 | Closed synthesizer: `str`, `sf.Model` and `sf.Vote()` accepted; `sf.Vote(weights=...)`, `sf.Vote(over="benchmark")`, every other step, a Recipe, Pipeline and Fusion refused |
| 6 | C9 | Run manifest: the same function at capture and replay; a capture seals `routers`; replay after changing any part of any Router's `D` (each source, policy, default, quorum) fails `frozen_copy_miss` before any replayed or live request; a copy sealed without `routers` fails the same way; an unknown copy fails `frozen_copy_unavailable`; a replay run without a Router sends no provenance request |
| 6, inputs | C9, C14 | Prepared drift: capture with a prepared definition, change the source bytes behind a new reference while the expression still declares the captured revision, then replay the standalone Router: `frozen_copy_miss` before any request. A source changed after the run starts never reaches ADMIT, which reads the frozen `D` only |
| 6, inputs | C4, C14 | A missing, denied, expired, malformed, partially published or digest-mismatched prepared question becomes the strict input failure document; scoring CLASSIFY receives only the whole failed ADMIT document, returns exactly `{"not_run": true}` and never sees an empty substituted input or calls its port; JOIN publishes exactly one C5 record at phase `input`, with zero classifier/chat calls. The same `not_run` document beside accepted ADMIT is `router_evidence_invalid`. Deadline and cancellation remain control-plane endings without a Router record. The worker/world reader passes the database-layer gate with no Tortoise/asyncpg/aiosqlite import |
| 6 | C9, C16 | Run definition set refusals before `url4_run`, with zero requests and no Router record: 257 Routers in a raw expression, one `router` binding used twice, an unreadable or undecodable prepared source; the SDK refuses 257 Routers before submission; 256 run |
| 6 | C9 | Classify entry key: binding, occurrence and attempt separate identical requests; no revision header exists; replay returns the recorded body with `X-AIGW-Upstream-Attempts: 0`, and a miss and an unavailable copy also carry `0`; a known captured price returns through the chat replay mapping as `cache.reference`, while today's `null` stays unknown |
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
| url4 leaf | C19 | Failures: two elements fail the source with the pinned code, and a non-collection value with `expansion_not_iterable`; each is guarded by `;required` and `;optional` as any failure |
| url4 leaf | C19 | Refusals: a mark without `;expand` is refused at parse and by `url4.src`; an unnamed source, a named `;expand;<mark>` source without `;required`/`;optional`, and a source with both guards are refused at parse and by `url4.src`; on an expression-valued member the raw parser refuses `;<mark>;required` and `;<mark>` alone, and parses `;required;<mark>` with the mark as a source annotation; the renderer refuses a mark ahead of every source-level key |
| url4 leaf | C19 | Bytes: `url4.src` writes exactly one `expand.at_most_one=true` after `;required` or `;optional`, and parse then render keeps its bytes; another value, a duplicate and placement before every source-level key are refused; unmarked and `;expand` sources keep theirs; every prior url4 test passes unchanged |
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
| 8 | BERT scalar fixture and fixed-label Router (V4 form), complete label coverage, tie and unknown-winner handling, token-aware refusal at and over the bound reaching the Router as a classifier failure (C7); serving stack has its own lock/artifact and leaks no dependency into shared manifests | 4 |
| 9 | The rebuilt SDK wheel repeats the Unit 6 clean-base proof; an exact exported `[runtime]` lock environment installs it with `--no-deps`, asserts material versions, boots its vendored Gateway and separate Engine environment and passes strict records, attempt headers and fake capture/replay; live BERT, Laya and Jev use separate approved endpoints; hosted Linux/NATS/JetStream run covers intermediary URL limits; a new App with an old eligible worker refuses standalone and composed Router plans, a C19-marked Fusion included, before any source, classifier, model, sibling or synthesizer I/O, with zero paid calls; withdrawing `router-placement-v1` stops new marked submissions while accepted ones drain (C12) | 8, 12, 13 |

Across Units, every Router test also checks: unselected candidates make zero calls, every Engine
attempt and every Gateway upstream attempt of every Router call is recorded or explicitly unknown,
unknown cost stays unknown, and no failure triggers an implicit fallback, a lowered quorum or a
claimed free retry. Every strict numeric boundary rejects `NaN`, positive/negative infinity,
`1e999`/`-1e999` after parsing and a boolean used as a number; every closed union rejects missing/extra keys and any input matching zero or
multiple variants. Run the same vectors through Gateway/Engine Pydantic models, raw JSON/stored-result
readers, the C13 envelope and the dependency-free SDK decoder.

## 7. Not proven before Unit 9

| Item | Why | Detection |
|---|---|---|
| Live classifier behavior (BERT, Laya, Jev) | Needs approved endpoints, keys and a window | Unit 9 qualification |
| Hosted transport and auth | Local substitutes are not the hosted path | Unit 9 hosted run |
| Proxy and ingress URL limits | Not measurable locally | Unit 9, before enabling the hosted path |
| Mixed App/worker and App/Gateway rollout | Needs deployed old components | Characterization before hosted activation with a C19-marked Fusion and zero paid calls; withdraw and drain before an older worker takes work again (C12) |
| Classifier token budgets and truncation reporting | Provider-specific | Unit 5.1 fixtures, Unit 8 reference server, then Unit 9 live check |
