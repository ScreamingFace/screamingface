# Contracts: Router Recipe extension

Base `31c1158e8`. Paths are relative to `packages/screamingface/src/screamingface/` (SDK),
`apps/screamingface-engine/src/screamingface_engine/` (Engine) and `apps/aigateway/src/aigateway/`
(Gateway) unless written in full. Design citations are to screamingface-design PR #35 at `3e903bd`,
under `solutions/screamingface/product/`; where this file and the design differ, the design wins and
this file is wrong (overview §7). C7-C9 are in [contracts-replay.md](contracts-replay.md), C13 and
C17 in [contracts-entry.md](contracts-entry.md), C18 and C19 in
[contracts-placement.md](contracts-placement.md).

**Strict records.** Every new record is a closed union. A value matches exactly one variant; every
key that variant lists is present, a key typed `| null` carries `null` for "none", and a key the
variant does not list is absent. A missing or unknown key, a wrong type, a value outside its variant
or a broken invariant is a compatibility error, never an ignored extension.

The implementation cannot delegate those rules to a lax/default decoder. Gateway and Engine
Pydantic boundaries use explicit strict fields, `extra="forbid"`, finite-number validation
(`allow_inf_nan=False` or an equivalent field validator), and discriminator/explicit variant dispatch
that proves exactly one match. Raw JSON readers reject non-standard `NaN`/`Infinity` constants and
every value that becomes non-finite after parsing, including `1e999` and `-1e999`. No numeric contract
field is typed or decoded as `Any` before the finite/type check.
The base SDK has no Pydantic runtime dependency, so its existing dependency-free readers enforce the
same closed/finite rules manually; this extension does not add Pydantic to the base SDK.

## C1 — SDK authored values (Unit 6)

```python
class _RouterCandidate(TypedDict):      # private, not exported; annotation only
    model: Required[str | sf.Model]
    description: NotRequired[str]

sf.ScoringClassifier(classifier: str, *, instructions: str | None = None)
sf.RoutingPolicy(*, match: Literal["best", "exact"])
sf.Router(
    *,
    classifier: sf.ScoringClassifier | sf.LLMClassifier | sf.RegexClassifier,
    policy: sf.RoutingPolicy,
    select: Literal["one", "all"],
    candidates: Mapping[str, _RouterCandidate],
    synthesizer: str | sf.Model | sf.Vote | None = None,
    quorum: int | Literal["all"] | None = None,
    default: str | sf.Model | None = None,
    name: str | None = None,
)
```

Construction makes no I/O, deep-copies and freezes every input, and stores candidates as an ordered
tuple in author order (`client/router-recipes.md:129-133`). Equality, the IR and the revision follow
that order. The TypedDict is static only. The matrix below is the complete runtime check, in this
order: each argument in signature order, then the cross-field rules. Messages follow the SDK form
`"sf.Router quorum= ..."` (`_surface/selectors.py:46-53`). Every row is a Unit 6 test.

| Argument | `TypeError` | `ValueError` |
|---|---|---|
| `ScoringClassifier(classifier)` | Not `str` | Empty after the route validation `sf.Model` applies (`recipe._model_route`, `recipe.py:78`), or a control character |
| `ScoringClassifier(instructions=)` | Not `str` or `None` | Empty, whitespace only, or outside C16 |
| `RoutingPolicy(match=)` | Not `str` | Not `"best"` or `"exact"` |
| `Router(classifier=)` | Not `sf.ScoringClassifier`, `sf.LLMClassifier` or `sf.RegexClassifier` | none |
| `Router(policy=)` | Not `sf.RoutingPolicy` | none |
| `Router(select=)` | Not `str` | Not `"one"` or `"all"` |
| `Router(candidates=)` | Not a `Mapping` | Count outside C16 |
| A candidate key | Not `str` | ScoringClassifier: empty or outside C16, never trimmed, case-folded or normalized; selector source: see cross-field rules |
| A candidate record | Not a `Mapping`; `model` not `str` or `sf.Model` (a Recipe, Router or Fusion included); `description` present and not `str` | Missing `model`; a key other than `model` and `description`; `description` empty or outside C16 |
| `Router(synthesizer=)` | Not `None`, `str`, `sf.Model` or `sf.Vote`; every other step (`Median`, `Mean`, `Rank`, `Filter`, `Concat`, `ArgMax`, `ArgMin`, `First`, `Merge`, `JudgePick`, `Judge`, `Gate`, `Synthesize`), Recipe, Pipeline or Fusion included | `sf.Vote` with `weights=` or `over="benchmark"` |
| `Router(quorum=)` | Not `None`, `str` or `int`; a `bool` (`quorum=True`) | A `str` other than `"all"`; an `int` outside `1..len(candidates)` |
| `Router(default=)` | Not `None`, `str` or `sf.Model` | none |
| A candidate, default or synthesizer Model | none | `optional=True` or an explicit `name=`: the label or role is the identity, and neither field has Router meaning |
| `Router(name=)` | As `sf.Fusion(name=)` | As `sf.Fusion(name=)` |

A `str` candidate, default or synthesizer becomes `sf.Model(str)`, and `sf.Model`'s own errors
propagate unchanged; equal inputs give equal IR.

Cross-field rules, all `ValueError`:

| Rule | Refused |
|---|---|
| Dynamic choice (`ScoringClassifier` with `instructions`) | A candidate without `description` (`client/router-recipes.md:151-153`) |
| Fixed labels (`ScoringClassifier` without `instructions`) | A candidate with a `description` key, any value (`client/router-recipes.md:154-158`) |
| Selector source (`LLMClassifier`, `RegexClassifier`) | Candidate keys unequal to the selector's declared label set. `description` is optional per candidate, as the candidate record allows (`client/router-recipes.md:124-125`); it is kept in the definition and report and not sent to the classifier |
| Policy and source | `match="best"` without `ScoringClassifier`; `match="exact"` with `ScoringClassifier`; `match="best", select="all"` (deferred, `engine/router-execution.md:236`) |
| Select shape | `select="one"` with `synthesizer` or `quorum`; `select="all"` without both |

Whether a hosted target accepts text or choice input is decided by classifier metadata, read by the
SDK through the Engine catalog (C17) during preflight and again by Engine ADMIT, never by authored
data. `sf.ScoringClassifier` and `sf.RoutingPolicy` are not Recipes; `sf.Router` is. No
`sf.RouterCandidate` export and no `sf.Classifier` name.

## C2 — Router IR `screamingface.router-spec.v1` (Units 5.2 and 6)

The intent of the Router ADMIT step (C4). The Engine owns validation; the SDK writer is only an author.

```text
router-spec.v1 = {"schema": "screamingface.router-spec.v1", "router": <binding>,
                  "revision": "sha256:<64 hex>", "revision_scheme": "router-definition-v1",
                  "calls": Calls, "definition": D}
Calls          = {"classifier": <binding> | null, "candidates": [<binding>, ...],
                  "default": <binding> | null, "synthesizer": <binding> | null}

D              = {"classifier": Classifier, "policy": Policy, "candidates": [Candidate, ...],
                  "default": Model | null, "synthesizer": Synthesizer | null,
                  "quorum": "all" | int | null}
Classifier     = FixedScoring | ChoiceScoring | LlmSelector | RegexSelector
FixedScoring   = {"source": "scoring", "model": <Gateway classifier id>,
                  "contract": "classification-scores-v1", "input": "text"}
ChoiceScoring  = {"source": "scoring", "model": <Gateway classifier id>,
                  "contract": "classification-scores-v1", "input": "choice", "instructions": str}
LlmSelector    = {"source": "llm", "model": Model, "labels": [str, ...], "prompt": str | null,
                  "multi": bool}
RegexSelector  = {"source": "regex", "rules": <RegexClassifier._spec()["rules"]>, "multi": bool}
Candidate      = Plain | Described
Plain          = {"label": str, "model": Model}
Described      = {"label": str, "model": Model, "description": str}
Model          = {"model": <sf.Model.model>, "prompt": str | null, "params": {<name>: str}}
Policy         = {"type": "router-policy", "version": 1, "match": "best" | "exact",
                  "select": "one" | "all"}
               | {"type": "unique-argmax-v1"}
Synthesizer    = {"kind": "model", "model": Model}
               | {"kind": "vote", "extract": <as combine-spec>, "normalize": str | null}
```

| Classifier variant | Candidate variant | Design |
|---|---|---|
| `FixedScoring` | every candidate `Plain`; a `FixedScoring` with an `instructions` key, even `null` or `""`, matches no variant | `client/router-recipes.md:154-158` ("fixed IR omits them") |
| `ChoiceScoring` | every candidate `Described`; `instructions` and every `description` non-empty | `client/router-recipes.md:151-153` |
| `LlmSelector`, `RegexSelector` | each candidate `Plain` or `Described`, as authored | `client/router-recipes.md:124-125` |

- `Model.params` is exactly the compiled call's parameters: `dict(resolved_params(model.params))`
  (`_evaluation/policy.py:18-29`), so every value is the string the call sends (`True` gives
  `"true"`, `0.2` gives `"0.2"`). Two authored values that compile to the same call share a revision.
  The `llm` source's `Model` is `LLMClassifier.model`, including its merged `max_tokens`. The `vote`
  record's `extract` and `normalize` are the values `combine_spec_text` (`_evaluation/combine_spec.py`)
  writes for that `sf.Vote`. No record carries a URL, header, credential, code, `optional`, `name` or
  transport option.
- Policy is a closed union with `type` as its discriminator. `router-spec.v1` accepts only
  `router-policy`; a named-profile definition (Unit 5.2) accepts only `unique-argmax-v1`, with
  `default`, `synthesizer` and `quorum` all `null`. Both decode into one internal policy value that
  the pure core (C6) evaluates.
- `router` and every `Calls` value are compiler bindings, never derived from a raw label. `router` is
  `router_N`, numbered like E4c's `gate_N`; `Calls` names the binding each role's model call carries:
  the LLMClassifier call's `selector_N` (`null` for `scoring` and `regex`; a scoring classify call is
  keyed by `router` itself, C8), each candidate's `model_N` in candidate order, the default's
  `model_N`, and the synthesizer's `synthesis_N` (`null` without one). `router` and `Calls` are not
  in `D`, so they do not change the revision; compile, rebuild and both input carriers keep them
  (`engine/router-execution.md:385`).
- Engine ADMIT checks, before any I/O of the occurrence: schema, the variant of every record, C16
  bounds, unique labels, the policy variant and its compatibility with the source, the
  select/default/synthesizer/quorum shape, unique `Calls` bindings, and that `revision` recomputes
  from `definition` (C3). The metadata preflight is in C4.

## C3 — Definition revision `router-definition-v1` (Units 5.2 and 6)

```text
revision = "sha256:" + hex(sha256(canonical(
               {"scheme": "router-definition-v1", "definition": D})))
canonical(v) = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode()
```

- `D` is the C2 definition. Candidates are a list, so author order is part of the revision; `D`
  holds no object keyed by a label, so key sorting never reorders candidates.
- The preimage is independent of transport. The IR rides in a url4 intent through the SDK's
  `canonical_json` (`ensure_ascii=False`, `$` escaped), and the Engine recomputes the revision from
  the decoded values.
- The author `name`, `router`, `Calls`, the question and the input carrier are not in `D`.
  Classifier, instructions, descriptions, order, every Model's prompt and parameters, policy variant,
  default, synthesizer and quorum are (`engine/routing-inputs.md:109-111`).
- The pilot's legacy profile revision (pilot `world/routing_config.py:175-187`) and
  `RoutedAnswer.revision` bytes do not change. A dynamic-choice named profile uses this scheme with
  `{"type": "unique-argmax-v1"}`; its config states `revision_scheme = "router-definition-v1"`, the
  Engine's routing evidence records it, and the `routed-answer-v1` wire is unchanged, so a v1 reader
  sees only the `sha256:<64 hex>` string.

Golden vectors, shared by Unit 5.2 and Unit 6 tests. `D` (dynamic choice):

```json
{"candidates":[{"description":"Programming questions.","label":"code","model":{"model":"openrouter/openai/gpt-4o-mini","params":{},"prompt":null}},{"description":"Everything else.","label":"general","model":{"model":"openrouter/meta-llama/llama-3.1-70b-instruct","params":{},"prompt":null}}],"classifier":{"contract":"classification-scores-v1","input":"choice","instructions":"Pick the expert for the question.","model":"laya/router","source":"scoring"},"default":null,"policy":{"match":"best","select":"one","type":"router-policy","version":1},"quorum":null,"synthesizer":null}
```

`F` (fixed labels; no `instructions` or `description` key anywhere):

```json
{"candidates":[{"label":"LABEL_0","model":{"model":"openrouter/openai/gpt-4o-mini","params":{},"prompt":null}},{"label":"LABEL_1","model":{"model":"openrouter/meta-llama/llama-3.1-70b-instruct","params":{},"prompt":null}}],"classifier":{"contract":"classification-scores-v1","input":"text","model":"bert/router","source":"scoring"},"default":null,"policy":{"match":"best","select":"one","type":"router-policy","version":1},"quorum":null,"synthesizer":null}
```

| Vector | Definition | Revision |
|---|---|---|
| V1 | `D` | `sha256:25d95f844082f8802647d75bbfcc0cb4452528990df72d92a640ead3b4e98930` |
| V2 | `D`, candidates reversed | `sha256:61273d67ca5ac7ad6711072150f20d21f36662690d2cdfcc8a7d81db870477eb` |
| V3 | `D`, `"policy": {"type": "unique-argmax-v1"}` | `sha256:4817721933b6f2fe964f8fc6f856fe71fc3a211bc48b0b02ded1bc7188a2b208` |
| V4 | `F` | `sha256:c75782a7999e73e1ba8bad72ae16b2083daba323c2d385c9ce9e5f1e357985ae` |
| V5 | `D`, candidate `code` authored as `sf.Model(..., params={"temperature": 0.2, "max_tokens": 256, "logprobs": True, "stop": "END"})`, so its `params` is `{"logprobs":"true","max_tokens":"256","stop":"END","temperature":"0.2"}` | `sha256:71feeae5684881461a5c4b70513cfd1841f471d54666df3d56ffbacb1f5a2a9f` |

## C4 — Compiled Router block on the E4c substrate (Units 5.2 and 6)

The design keeps the E4c branch runtime as substrate while Router keeps its own definition, evidence
and one-answer semantics (`engine/router-execution.md:93-96`), and the compiler emits inert routing
data plus one lazy routing operation (`client/router-recipes.md:393-394`). In url4 that operation is
one named block per Router occurrence, as E4c compiles one `gate_N_block` (`world/branch.py:1-20`).

The input adapter supplies one strict internal document: `{"input": str}` for the exact question, or
`{"failed": {"code": str, "permanent": bool}}` when a prepared-question read was missing, denied,
expired, malformed or digest-mismatched. Control-plane deadline/cancellation still propagates. `Q` is
the successful document's input: the value the compiler already gives a Model in the same position
(`input_context`, `_evaluation/candidate.py:444`): `$input` at the top of a Case, the previous stage in
a Pipeline, `$_sf_recipe_input` in a nested invocation, and the entry-bound input for C13.

```text
router_N_input   = <C14 input adapter: {"input": str} | {"failed": {"code": str, "permanent": bool}}>
router_N_admit   = /ensemble/router/v1/admit($router_N_input)!'<router-spec.v1>'
router_N_scores  = /ensemble/router/v1/classify($router_N_admit)                           scoring
router_N_open_s  = /ensemble/router/v1/open($router_N_admit)!'classify'                    llm, regex
router_N_sel     = $router_N_open_s*(<LLMClassifier call over Q>);iteration.on_error=collect          llm
router_N_sel     = $router_N_open_s*(<KEYWORDS over Q>);iteration.on_error=collect                    regex
router_N_decide  = /ensemble/router/v1/decide({admit: $router_N_admit,
                                               evidence: $router_N_scores | $router_N_sel})
router_N_open_cK = /ensemble/router/v1/open($router_N_decide)!'cK'          select="one", per candidate
router_N_cK      = $router_N_open_cK*(<candidate K Model call over Q>);iteration.on_error=collect
router_N_open_d  = /ensemble/router/v1/open($router_N_decide)!'default'     only with default=
router_N_d       = $router_N_open_d*(<default Model call over Q>);iteration.on_error=collect
router_N_open_p  = /ensemble/router/v1/open($router_N_decide)!'panel'       select="all"
router_N_panel   = $router_N_open_p*(<panel body>);iteration.on_error=collect                         select="all"
router_N         = /ensemble/router/v1/join({decision: $router_N_decide, cK?, d?, panel?})?binding=router_N
```

An accepted ADMIT document carries the exact `input` string beside the normalized definition. The
scoring route receives only that whole document, validates the accepted variant and then extracts its
input inside the route before dispatching; caller-side URL4 traversal never reads an absent field.
For LLMClassifier, RegexClassifier and every model body, OPEN is the success gate and `Q` means the
accepted `$router_N_admit.input` resolved only inside the opened iterate. An input failure therefore
reaches DECIDE/JOIN without URL4 substituting `""` and without any classifier call.

When the scoring route receives a non-accepted ADMIT document, it returns exactly
`{"not_run": true}` without calling the classification port. DECIDE accepts that document only beside
the same non-accepted ADMIT result and ignores it as evidence; `{"not_run": true}` beside accepted
ADMIT is `router_evidence_invalid`. Unit 5.2 pins this route document before code.

Inputs of each step:

| Step | Reads |
|---|---|
| ADMIT | The strict `router_N_input` document; it carries an input failure forward before metadata preflight |
| Scoring classify, LLMClassifier call, KEYWORDS, every candidate, the default | `Q` |
| Model synthesizer | `{input: Q, panel}`: the original input and the completed selected answers (`engine/router-execution.md:327`) |
| `sf.Vote` synthesizer | The panel of completed selected answers only |
| Panel | Selected candidates' answers only; an unselected or failed candidate's output never enters it |

**Failure completion.** Every Router outcome, including failures, ends in exactly one publication of
the completed C5 record, by JOIN, before the occurrence fails or answers. The mechanism has four
parts, and the inline entry (C13) uses it rather than its own:

1. **Failures travel as data until JOIN.** ADMIT does not raise for a refused definition; it returns
   a refusal document `{"refused": {"code": str}}`. It also carries the input adapter's strict
   failure document forward without metadata or provider I/O. The Router's own classify route catches the
   classification port's failure and returns `{"failed": {"code": str, "permanent": bool}}`. Every
   model call of the occurrence sits in an OPEN-gated iterate with `iteration.on_error=collect`, so
   its failure becomes one error row `{"error": {"kind", "message", "code"?, "retryable"?}}`
   (`packages/url4/src/url4/dag/nodes/_shared.py:162-182`). This differs from E4c on purpose: E4c
   bodies use `iteration.on_error=fail` (`_evaluation/branch.py:608`), and E4c JOIN accepts only
   text rows (`world/branch.py:788-794`).
2. **The subset path is one row.** For `select="all"`, the selected candidates' calls, the E4c
   skip-member combine and the synthesizer are all inside the one `router_N_panel` body. A selected
   member's own failure under `quorum="all"`, `quorum_not_met` and a synthesizer failure therefore
   all become that iterate's error row. The panel keeps E4c skip-member semantics (selection from
   DECIDE; `quorum="all"` makes every selected member required; a number `q` makes them optional with
   floor `min(q, selected)`), as `client/router-recipes.md:113-117` requires.
3. **DECIDE never raises for a Router outcome.** It returns the internal draft (C5): failed at phase
   `input` for an input failure document, failed at phase `admit` for a definition refusal document,
   failed at phase `classify` for a classifier failure document or an error row,
   failed at phase `decide` with `router_evidence_invalid` for invalid evidence, else the C6 result.
   It raises only an Engine contract error for a malformed context, a defect that ends the run like
   any E4c contract error.
4. **JOIN is the single publisher.** It reads the draft, the iterate rows and the attempt facts
   (C8) of every `Calls` binding, builds the completed C5, publishes it under its own fingerprint
   (`?binding=router_N`) as `record_gate_call` does (`operation_calls.py:258`), and only then either
   returns the answer text, returns `""` for an abstention, or raises a `ResolutionError` with the
   failing operation's code and permanence, built like `fail_closed`
   (`benchmarks/failure_classes.py:102`). An error row's `message` is dropped: the record keeps
   bounded codes only. To callers the occurrence stays atomic: one answer, one abstention or one
   failure, never a partial success.

`record_operation_call` publishes only while an identity is bound and a recorder scope is active
(`operation_calls.py:191-210`). ADMIT therefore refuses `router_unsupported` when no recorder scope
is active, so a Router never runs model I/O where its record would be lost. A benchmark Case and the
inline entry (C13) always provide one. Control-plane endings (deadline, cancellation) are not
Router failures; they propagate unchanged through `collect` and end the run.

Step contracts:

- **ADMIT** validates C2 and runs the per-occurrence metadata preflight, with no inference, for every
  model-bearing role: the scoring classifier's visibility, input capability and limits (the C17
  source); the LLMClassifier Model; every candidate; the default; a Model synthesizer. For each Model
  it checks the canonical route, its Connection, the parameter contract and an executable route in
  this world, as the E4c preflight does for a Gate member. Every step that can reach a provider
  depends on ADMIT in the url4 graph, so a refusal runs nothing of this Router. It is not a whole-plan
  pre-pass: Fusion siblings may already have spent.
- **Run-file admission.** On base `31c1158e8`, OME-1809's `run_model_routes`
  (`benchmarks/picture_admission.py:416-443`) checks every model route a file-carrying url4 run can
  reach before its first provider call. Every Router model call is a literal url4 call in the block's
  gated iterate bodies for both input carriers. A prepared definition moves only `D`; the same block
  remains url4 and is never hidden inside non-expression text, which the scan does not read. Private
  routes the caller cannot list keep the admission code's existing non-disclosure behavior. Failure
  refuses the run with zero Router, sibling or synthesizer provider calls; a Gateway content-part
  refusal remains the backstop for a dynamically unreachable route. When the run carries files,
  ADMIT awaits this run's shared OME-1809 admission check before returning an accepted document. The
  scoring CLASSIFY step therefore cannot reach `/v1/classifications` before file admission succeeds;
  an LLMClassifier's existing chat call and every selected branch await the same shared result. A
  failed shared check is a run refusal, not a Router outcome: ADMIT re-raises it unchanged and
  publishes no C5 record.
- **CLASSIFY.** A scoring source calls the Engine classification port (C8) once with `Q`. An
  LLMClassifier call is the E4c selector call (`_evaluation/candidate.py:363-381`) with three
  changes: it reads `Q` instead of the fixed `$input`, it sits behind `router_N_open_s` instead of
  `;optional`, and its failure is a Router failure, never a default (`client/router-recipes.md:170-173`).
  A RegexClassifier runs the E4c KEYWORDS route (`_evaluation/branch.py:89`) over `Q` and makes no
  model call.
- **DECIDE** is pure: it applies C6 to the evidence and returns the draft.
- **OPEN** returns `[{}]` only for the branch the draft chose (`classify` when ADMIT accepted; a
  selected `cK` for `select="one"`; `default` when the policy chose it; `panel` for a selected
  subset), else `[]`, as E4c OPEN does (`world/branch.py:660`). Unselected bodies make zero calls.
- **Bodies** are the candidates' ordinary compiled Model calls on the existing chat path
  (`world/connector.py:415`), with chat capture, cache, connector retries and attribution unchanged.
- **JOIN** returns the Router answer text as the node value. A Fusion, Pipeline, Gate or Cascade
  reads only that text and the outcome on the recorded call, as it reads a Gate's
  (`_call_result`, `world/branch.py:777`), never a serialized envelope. C18 pins each position.
- **Prepared question** (C14): the input adapter resolves the reference once into the strict input
  document. ADMIT/DECIDE/JOIN consume a failed document and publish one C5 record at phase `input`;
  otherwise the block reads its `input` as `Q`. No later step reads the reference itself.

The Router runtime installs `/ensemble/router/v1/{admit,classify,decide,open,join}` and the inline
entry `/ensemble/router/v1/answer` (C13). The Router runtime, the branch runtime
(`install_branch_runtime`, `world/branch.py:219`, which also serves KEYWORDS) and the combine runtime
(`install_combine_runtime`, `world/combine.py:51`) install whenever the Gateway world is composed,
after the direct-mount snapshot (`world/factory.py:252`), so none becomes a direct mount; today they
install only beside benchmarks (`world/factory.py:171-185`, `:253`). Candidate invocation and the
corrective runtime stay benchmark-only. The named-profile mount keeps
`node.fetch(encode_subrequest(...))` for its selected call; both paths end in the connector's
`_ModelEndpoint` (`world/connector.py:415`). They are adapters over one Engine-owned routing
application boundary, not merely consumers of common record types: metadata/access preflight,
evidence validation, C6 policy, selected-route dispatch ports, attempt facts and C11 normalization
have one implementation. The shared connector endpoint is the selected-route dispatch port; the
profile adapter may reach it through `node.fetch` while the Router DAG reaches it through its compiled
call. The profile wire/presenter and Router DAG/JOIN remain separate adapters.
Unit 6 pins the exact url4 text of the panel body here, within these rules, before code.

## C5 — Decision record `screamingface.router-decision.v1` (Units 5.2 and 6)

Only the completed record exists outside the Engine. DECIDE's draft
`screamingface.router-decision-draft.v1` is internal: it carries `router`, `revision`,
`revision_scheme`, `policy`, `evidence`, `outcome`, `reason`, `selected`, `unknown_labels` and, for
`outcome` `failed`, `{"phase", "code", "permanent"}`; Unit 5.2 pins its strict shape here before
code. No stored result, report reader or envelope accepts a draft. Like E4c records, the completed
record holds labels, numbers, ids and bounded codes only, never question, answer, description or
error message text.

| Key | Value |
|---|---|
| `schema` | `"screamingface.router-decision.v1"` |
| `router` | As C2 |
| `revision`, `revision_scheme`, `policy` | As C2; `null` iff `failure.phase` is `admit`, because a refused definition is not echoed |
| `evidence` | `null` when no valid evidence exists; else one of the forms below |
| `outcome` | `selected` \| `default` \| `no_selection` \| `failed` (no policy result: phases `admit` to `decide`) |
| `reason` | `null` iff `outcome` is `failed`; else `unique_max` or `exact` for `selected`, and `tie`, `empty`, `unknown_only`, `unknown_selected` or `multiple_selected` for `default` and `no_selection` |
| `selected` | `[{"index": int, "label": str, "model": str}]` in classifier order (returned order for scores, reply order for llm, KEYWORDS order for regex); `model` is that candidate's canonical Model ID (C2 `Model.model`); `[]` unless `outcome` is `selected` |
| `unknown_labels` | Every returned label with no candidate, in classifier order: all of them for scores, the selector's `unknown` list for a selector |
| `classifier_call` | `null` for regex or when the classifier did not run; else `{"binding": str, "cost": number \| null}` plus `Attempts` |
| `branches` | `[{"role": "candidate" \| "default", "index": int \| null, "label": str \| null, "model": str, "status": "answered" \| "failed", "code": str \| null}` plus `Attempts]` for every branch call that ran, from the attempt facts of its `Calls` binding; `index` and `label` are `null` for the default; `model` is the branch's canonical Model ID |
| `quorum` | Subset after selection: `{"floor": int, "selected": int, "answered": int}`; else `null` |
| `synthesis` | Subset after quorum was met: `{"kind": "model", "status", "reason", "code"}` plus `Attempts`, or `{"kind": "vote", "status", "reason", "code"}`; `status` is `answered` \| `abstained` \| `failed`, `reason` an `answer.v1` abstain reason or `null`; else `null` |
| `status` | `answered` \| `abstained` \| `failed` |
| `failure` | `null` unless `status` is `failed`; then `{"phase": <C11 phase>, "code": str}` |

`Attempts` = `{"engine_attempts": int ≥ 1, "upstream_attempts": int ≥ 0 | null, "possibly_billed":
bool}`: every Engine request of that logical call and the Gateway's upstream count, defined in C8.

Evidence forms:

- Scoring: `{"source": "scoring", "model": str, "contract": "classification-scores-v1",
  "scores": [{"label": str, "score": number}]}` in returned order.
- Selector: `{"source": "llm" | "regex", "labels": [str], "unknown": [str], "parse": "ok" |
  "no_match" | "unrecognized" | "unparsed"}`. `labels` are the recognized labels in classifier order,
  each once. For llm the Router's reply parser keeps E4c's tokenization, trimming, case-insensitive
  match, single-token read for `multi=False` and reply-size bound (`combine/ports.py:694-715`), but
  orders recognized labels by first occurrence in the reply and keeps every distinct unknown token
  in reply order, each cut at 64 characters, at most 32; a reply naming more distinct unknown tokens
  is `unparsed`. This follows "keeps every recognized label in classifier order" and "Unknown labels
  remain in evidence" (`engine/router-execution.md:235`, `:238`); E4c's own parser, which returns
  declared order and only the first unknown, stays unchanged for Gates. For regex, `labels` is the
  KEYWORDS output and no matching rule gives `no_match` (`world/branch.py:455`). `no_match` occurs
  only for regex, `unrecognized` and `unparsed` only for llm.

The record therefore carries the selected label and Model set (`engine/router-execution.md:335-338`)
on its own: a reader needs no definition to name the Models that answered.

Invariants: `answered` has `outcome` `selected` or `default` and no failed required branch;
`abstained` has `outcome` `no_selection`, or a subset whose synthesis abstained; `failed` has a
`failure`, and its `outcome` is `failed` for phases `admit` to `decide`, else the decision it was
executing. A `phase` is fixed by which binding failed (C11), never by a code. Unselected candidates
appear as declared alternatives only; no record invents an operation, usage or a zero cost for them.
Unknown classifier cost stays `null` in the Router and in enclosing totals.

## C6 — Pure policy, version 1 (Unit 5.2)

| Policy | Evidence | Result |
|---|---|---|
| any | Classifier failure document or error row (an LLMClassifier call failure included) | `failed`, phase `classify`, the failing call's code; no default |
| `best/one` | Not a complete finite non-boolean vector in `[0,1]`, duplicate label, or a candidate label missing | `failed`, phase `decide`, `router_evidence_invalid` |
| `best/one` | Unique maximum on a candidate label | `selected` that candidate / `unique_max` |
| `best/one` | Unique maximum on an unknown label | `default`, else `no_selection` / `unknown_selected` |
| `best/one` | Tie at the maximum | `default`, else `no_selection` / `tie` |
| `exact/one` | `ok`, one recognized label | `selected` / `exact` |
| `exact/one` | `unrecognized`, one recognized label and unknown tokens | `selected` / `exact`; unknown kept |
| `exact/one` | More than one recognized label (`multi=True` selector) | `default`, else `no_selection` / `multiple_selected` |
| `exact/all` | `ok` or `unrecognized`, one or more recognized labels | `selected` all recognized, in classifier order / `exact`; unknown kept and skipped |
| `exact/one` | `unrecognized`, no recognized label | `default`, else `no_selection` / `unknown_selected` |
| `exact/all` | `unrecognized`, no recognized label | `default`, else `no_selection` / `unknown_only` |
| `exact/*` | `no_match` (regex) or `unparsed` (llm) | `default`, else `no_selection` / `empty` |
| `unique-argmax-v1` | Unique maximum on a profile label | The selected profile route |
| `unique-argmax-v1` | Tie; missing or extra label | `routing_ambiguous`; the pilot's existing error, unchanged |

The policy never sorts, normalizes or invents scores, never promotes a runner-up and claims no
calibration (`engine/router-execution.md:229-251`). With a selector source, every recognized label
has a candidate (C1). No Router-policy retry: the policy never re-runs a classifier or a selected
Model, and a classifier failure never runs the default. Retries below the policy stay as on main
and are recorded (C8).

## C10 — `no_selection` in `screamingface.answer.v1` (Unit 6, first PR)

Readers accept the value before any writer exists, as E4c did for `budget_refused`. One PR adds it to
all of:

- Engine `AbstainReason` (`combine/ports.py:58`), `AnswerReason` (`:61`) and the explicit
  `ABSTAIN_REASONS` tuple (`:77`).
- SDK `AbstainReason` (`answer.py:29`) and `AnswerReason` (`:33`); the derived `ANSWER_REASONS` and
  `ABSTAIN_REASONS` (`:59-60`) follow and feed `_evaluation/gate_decision.py:418` and the
  combine-evidence reader. Unit 6 adds here any display word it needs.
- Both pinned schemas: `packages/screamingface/tests/data/schemas/screamingface.answer.v1.json` and
  `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`.

A Router abstention is a non-answer for Fusion quorum, makes a Cascade Case abstain unless a
`sf.escalate_if(sf.unanswered())` line follows, stops a Pipeline and stays the taken Gate branch's result.
C18 wires each of these positions.

## C11 — Failure origin and presentation (Units 5.2 and 6)

- The shared use case classifies every Gateway refusal after a classifier or branch POST as execution
  origin, `aigateway_http_<status>`, with a bounded cause. It never consults a mount table; the
  pilot's mount mapping (pilot `world/gateway_endpoints.py:95`) becomes the direct presenter only.
- Phases, fixed by where the failure was observed: `admit` (a refusal document from
  `router_N_admit`), `input` (the prepared-question reader), `classify` (`router_N_scores` or
  `router_N_sel`), `decide` (`router_N_decide`), `generate` (a selected `router_N_cK`), `default`
  (`router_N_d`), `synthesize` (`router_N_panel`, including a selected member's failure under
  `quorum="all"` and `quorum_not_met`).
- New Engine codes: `router_definition_invalid` and `router_unsupported` at ADMIT,
  `router_evidence_invalid` at DECIDE. Router failures otherwise keep the failing operation's code
  and permanence; the three new codes are permanent.
- The new codes form `ROUTER_CODES`, and `ENGINE_RESERVED_CODES` (`error_text.py:112`, today
  `ENGINE_ERROR_CODES | CONTROL_PLANE_TERMINAL_CODES`) adds it, as the pilot did for its
  `ROUTING_CODES`. `connector._upstream_code` (`world/connector.py:2005-2010`) relays any upstream code
  that is not reserved; without this a branch chat failure could carry `router_definition_invalid` and
  read as an ADMIT refusal with no model I/O.
- Per case: declared codes stay themselves (`benchmarks/contract.py:60`, including `quorum_not_met`);
  undeclared Router and pilot routing codes become `upstream_error` with `source_code`
  (`benchmarks/aggregation.py:176-183`). No Router code joins `ENGINE_ERROR_CODES` (`error_text.py:64`).
- Terminal run HTTP keeps `_sanitized_error` (`rest/routes.py:90`): a Router code there becomes
  `internal_error` with only `permanent` kept. Phase and spend reach a caller through records, never
  through that code: the C5 record in stored results (C15), and the C13 envelope for the inline entry.
- Recipe retry advice is conservative when siblings may have spent; a "no model I/O" statement is
  scoped to one Router occurrence. The direct helper keeps its retry table.

## C12 — Capability gate (Units 6 and 7, with OME-1921/1922)

```json
{"object": "engine_capabilities", "contract": "engine-capabilities-v1",
 "capabilities": ["e4c-branch-v1", "router-v1", "classify-frozen-copy-v1", "router-input-ref-v1",
                  "router-placement-v1"]}
```

- `GET /v1/capabilities` on the Engine App, under the same caller auth as `/v1/operators`, returning
  the document above. If OME-1921 settles a different endpoint or E4c ID before Unit 6, the Unit 6
  spec moves the Router IDs into it unchanged; otherwise Unit 6 ships this one. The object keys are
  strict; the ID list is open, and readers ignore IDs they do not know.
- `router-v1` covers C2-C6, C10, the run definition set (C9), the inline entry and envelope (C13), the
  stored-result changes (C15) and the classifier catalog (C17);
  `classify-frozen-copy-v1` covers C9, its run manifest included; `router-input-ref-v1` covers C14;
  `router-placement-v1` covers C18 and the url4 reader of C19. A Recipe with a Router anywhere but
  its root needs `router-placement-v1`. Unit 7 adds it; until then the SDK refuses such a Recipe
  before submission.
- The SDK checks the IDs a Recipe needs before `POST /runs` and the first `GET /?q=`, and before
  minting a capability, and refuses with no run started. A missing document means no capability.
  Endpoint success elsewhere is not evidence.
- An ID states what the whole fleet can run. The App advertises it only when every worker that can
  take a current or queued run, and the Gateway, have its readers. App metadata alone is not
  evidence (`engine/router-execution.md:147-154`).
- While any eligible worker lacks the readers, the ID is not advertised. Before an older worker
  takes work again, by rollback or by reintroduction, the App withdraws the ID: the SDK then refuses
  new submissions that need it, and accepted runs that need it drain first (`:427-430`).
- Before hosted activation, characterize a new App with an old eligible worker for standalone and
  composed Router plans, a Fusion whose Router member carries the C19 mark included. It passes only
  when the work is refused before any source, classifier, selected-model, sibling or synthesizer
  I/O, with zero paid calls. A paid call falsifies the simple rollout; the operations mechanism
  (homogeneous pool, drain or capability-aware queue) then follows that evidence (`:155-158`).

## C14 — Prepared inputs (Unit 6, last PR)

Fixed here: two carriers, inline and prepared reference, chosen by the final encoded size and
capabilities before the first run-start; plain strings stay literal; no silent upload, transport
switch, profile registration or rerun after a refusal or uncertain outcome; definition and question
can each be prepared; the input adapter resolves a question into C4's strict success/failure document,
so the same normalized definition and exact successful `Q` reach the classifier either way, while a
domain read failure reaches JOIN as phase `input` with no provider call; the
source digest, the definition revision and the run identity stay distinct; stored results read back
after the source expires without the source, a frozen copy or a rerun (C15). A prepared definition
keeps `router`, `revision` and `Calls` inline beside its reference. The executor reads every
prepared definition once, before `url4_run`, into the run definition set (C9); only `D` moves to
that set, while the Router block and all of its literal model calls remain url4. The manifest uses the
revision recomputed from the decoded `D`, and ADMIT validates the frozen `D` from that set, never
the source, and refuses a declared `revision` that does not recompute with
`router_definition_invalid`. A prepared-definition read failure fails the run before `url4_run`; a
prepared-question read failure is phase `input` of its occurrence (C11).

Left to the Unit 6 input spec, before its code: SDK method names and the typed reference shape;
the backing store, evaluated first against existing run-file admission and attachment blob references
(neither is assumed sufficient); write and read authority independent of the digest; complete-upload
visibility; availability to actual workers; retention through the queue, run and recovery horizon;
quotas, expiry, cleanup and the failure for missing, denied, expired or mismatched data; the layout for
several prepared definitions in one run; the Router-input reader's resource paths and codecs; and the
supported question bound. The existing Engine database boundary remains fixed: only `runs/` may import
Tortoise, asyncpg or aiosqlite. World/runner code consumes a framework-free input port backed by a
worker-visible adapter. Existing blob infrastructure is reusable only after its image/PDF-only media
policy is extended by an explicit bounded text/JSON, authority and retention contract.

## C15 — Kinds, topology, stored results and reports (Units 6 and 7)

- `router` joins every closed-kind consumer the E4c `gate` kind touches: `recipe.py:113-163`,
  `_surface/lowering.py:525-532`, `_surface/rebuild.py:286-293`, `_surface/render.py`,
  `_evaluation/candidate.py`, `_evaluation/model.py:392-399`, `_evaluation/topology.py`,
  `_evaluation/url4.py`, `url4.py`, `report.py:61` and `:865-872`, `accounting.py:335`, `_ui/cards.py`
  and `_ui/branch_view.py`. Cascade tier normalization admits a Router wherever it admits `sf.Model`.
  A signal line directly after a Router is refused before submission (Router v1 publishes no signals).
- Stored results carry the completed C5 the way they carry the E4c Gate record. The in-process
  `OperationCall` (`operation_calls.py:30`, `decision` at `:66`) gains `router: RouterDecision | None`,
  and `is_provider` (`:69-72`) is false when it is set, so the record is never counted as a provider
  call. The wire `OperationOutput` (`benchmarks/contract.py:370`, `decision` at `:397`) gains `router`,
  excluded when `None` like `decision`, so a result without a Router stays byte-identical; the
  projection copies it where it copies `decision` (`benchmarks/operation_outputs.py:135`, `:201`,
  `:214`). The operation projection admits the JOIN binding: `_BINDING`
  (`benchmarks/operation_outputs.py:60`) and the SDK pattern (`_operation_bindings.py`) add `router`,
  and the shared fixture `apps/screamingface-engine/tests/unit/data/combine_contract/binding_names.json`
  accepts `router_7` and rejects `router_7_admit`, `router_7_decide` and `router_7_block`, read by
  `apps/screamingface-engine/tests/unit/test_binding_names_fixture.py` and
  `packages/screamingface/tests/unit/test_binding_pattern_conformance.py`.
- A Router abstention marks its Case abstained. `final_operation_abstained`
  (`benchmarks/operation_outputs.py:118-138`, called at `benchmarks/invocation.py:92`) reads only
  `combine` and the Gate `decision` today; it also returns true for an operation whose
  `router.status` is `abstained`. `_final_reference` (`benchmarks/operation_outputs.py:143-158`)
  follows a root `$gate_N_block` to its JOIN only through `_GATE_BLOCK` (`:62`, checked in
  `_gate_block` at `:161-175`); that pattern also admits `router_N_block`. A Router whose abstention
  is the Candidate's result, standalone or in every position where a Gate's abstention marks the
  Case today, then stores the Case as abstained with the empty answer (`abstained` on
  `CandidateInvocation`, `benchmarks/contract.py:437`), never as an answered empty string (C10).
  Positions inside a composition follow C18.
- Router operations are attributed like a Gate's. `_operation_bindings`
  (`benchmarks/operation_outputs.py:238`) enters a Gate block through `_GATE_BLOCK` in
  `_scope_sources` (`:313-333`) and parses gated iterate bodies named by `_GATE_ITERATE` (`:63`,
  `gate_N_then|else`) in `_gated_scopes` (`:279-299`). The block pattern admits `router_N_block` and
  the iterate pattern admits the Router's gated iterates (`router_N_sel`, `router_N_cK`, `router_N_d`,
  `router_N_panel`), so the JOIN record and every Router model call that ran become operations, and an
  unselected candidate, gated and never called, becomes none.
- The used definition snapshot stays with the result (`engine/routing-inputs.md:113-117`). An inline
  Router's `D` is the `router-spec.v1` intent inside the stored candidate `url4` (`report.py:328`,
  `:484`). A prepared Router's `D` is not in that `url4`, so the Engine `candidate-result.v1`
  (`benchmarks/contract.py:582`) gains `router_definitions`: the prepared part of the run definition
  set (C9) as `[{"binding", "revision", "definition": D}]` sorted by binding, attached once per result
  outside the Benchmark aggregates and excluded when the run has no prepared Router, so every other
  result stays byte-identical. The SDK `CandidateResult` (`report.py:314`) keeps it beside `url4`.
  The saved-run rebuild and the Recipe rebuild take each Router's `D` from its inline intent or from
  `router_definitions` by binding, and refuse a `D` whose recomputed revision differs from the stored
  one or from its C5 records. Reading a stored result never fetches an input source, reads a frozen
  copy or reruns classification. Rebuilding from a bare `url4` with no stored result needs the
  prepared source, as any execution does.
- Persistence. Every path that keeps a result keeps `router` and `router_definitions`. Each reader
  ships before any writer, and no stored report is migrated.
  - Saved run: `sf.reports` keeps the Engine result body as `result.json` beside the
    `screamingface.saved-run.v1` manifest (`_results/store.py:100-105`, `:209-213`) and rebuilds the
    `CandidateResult` from it (`reports.py:302-315`), so the snapshot needs no manifest field. The
    strict `_candidate_payload` (`_evaluation/results.py:254-292`) admits `router_definitions` as an
    optional key, as it admits `scores`, and `_candidate_result` (`:157-225`) passes it on. A result
    body without it decodes as before.
  - Case operations: `router` follows E4c's `decision`. It is an optional key of the wire Case
    Operation (`_evaluation/results.py:501-511`), a field of `CaseOperation`
    (`case_result.py:335-336`) and exported only when set (`:377-380`). No record version changes.
  - `screamingface.report.v1`: `CandidateResult._export_fields` (`report.py:577-635`) writes
    `router_definitions` exactly when it is not empty. Every report without a prepared Router stays
    byte-identical, the pinned exports included
    (`packages/screamingface/tests/test_report_v1_identity.py:93`,
    `packages/screamingface/tests/test_e4c_report.py:225`, `:333`,
    `packages/screamingface/tests/test_report_v1_vote_identity.py:77`). The format stays
    `screamingface.report.v1`, additive as for `scores`
    (`docs/spec/2026-10-05-OME-1268-multi-score-benchmarks.md:194-199`). Unlike the candidate keys
    emitted always (`report.py:599-600`), absence has one meaning here: no prepared Router. The SDK
    has no `report.v1` decoder (`report.py` only writes it; `_inspect_log/payload.py:106-111` is a
    one-way export), so its readers are the saved-run path above and external consumers, for whom an
    absent key means an empty list.

## C16 — Bounds (Units 5.1, 5.2 and 6)

The design requires validated bounds and rules out unbounded "configurable" values
(`client/router-recipes.md:147`). These are the bounds:

| Item | Bound | Basis |
|---|---|---|
| Candidates per Router | 1-32 | Equal to E4c `MAX_SELECTOR_LABELS = 32` (`_surface/selectors.py:29`) for one authoring limit; a choice target's own `limits` may be lower |
| Raw `ScoringClassifier` label | 1-64 UTF-8 bytes, no control characters | Target metadata may be stricter |
| Candidate description | 1-1,024 characters | |
| Classifier instructions | 1-4,096 characters | Below E4c `MAX_LABEL_PROMPT_CHARS = 16_384` (`_surface/selectors.py:30`) |
| Serialized `router-spec.v1` | 64 KiB | Checked by ADMIT and the SDK |
| Router members in one Fusion | 1 and 3 qualified | Design; more needs its own limit and test |
| Routers in one run | At most 256, each `router` binding once | The seal provenance bound (C9); the SDK refuses before submission, the run definition set before `url4_run` (`router_definition_invalid`) |
| Router nesting | Candidates are Models only | Design |
| Inline question | Up to the measured GET limit; larger needs C14 | Unit 6 measures |
| Engine root request target | Unit 6 chooses an application limit below the smallest qualified server/parser envelope; SDK refuses before mint, Engine after auth with 414 only inside that envelope. At or above an outer parser ceiling, 400 may occur before the App/auth and is not an Engine 414 | `_require_q` (`rest/routes.py:257`) has no bound today; qualify Uvicorn protocol/parser choices with one-write and fragmented delivery plus the largest real Authorization/identity/trace headers. h11 bounds the whole incomplete request head, not the target alone; httptools differs. The mount's 8 KiB is not this contract |

None of these bounds is a token count; token-aware limits are enforced inside each target (C7). A
Unit 6 measurement may lower a bound; raising one is a contract change.
