# Contracts: Router entries — inline result and classifier catalog

Base `31c1158e8`. Path conventions, design citations and the strict-record rule are those of
[contracts.md](contracts.md).

## C13 — Inline entry, `router-answer.v1` and `sf.RouterAnswer` (Unit 6)

### Why an entry adapter

The design keeps entry adapters separate where their envelopes differ
(`engine/router-execution.md:36`) and requires the inline entry to return one typed answer or
terminal outcome with its routing evidence (`engine/routing-inputs.md:119-121`). A raw `GET /?q=`
run cannot: it has no recorder scope, so ADMIT refuses a Router there (C4), and its terminal error is
scrubbed: `_sanitized_error` (`rest/routes.py:90-131`) keeps only `permanent` for a Router code. The
inline entry is therefore one Engine adapter shaped like Candidate Invocation
(`world/candidate_adapter.py`).

### Engine entry

```text
/ensemble/router/v1/answer({input: <question>})!'<compiled router_N_block>'
```

- The plan of `client.route_answer(router, question)` is this one call on the existing `POST /runs`
  and `GET /?q=` lifecycle. The intent is the C4 block; the adapter binds `input` (or, with C14, the
  prepared-question reader result) as C4's strict input document. The block alone turns success into
  `Q` or publishes a failed C5 record at phase `input`.
- The adapter opens one recorder scope, evaluates the block in the same world, and reads the one C5
  record JOIN published. It adds no completion logic of its own: every Router outcome, failures
  included, is completed by C4's failure-completion mechanism. When JOIN raised, the adapter catches
  that one `ResolutionError` and returns the envelope with `status: "failed"`; the record JOIN
  published is its only source.
- The adapter returns one `router-answer.v1` JSON document as the run's result text, for answered,
  abstained and Router-failed outcomes alike. Only failures outside the Router occurrence end the run
  with a terminal frame: a run definition set refusal before `url4_run` (C9); a run-file admission
  refusal re-raised unchanged by ADMIT (C4); an adapter contract error; a published record missing;
  deadline, cancellation and other control-plane endings. Their code/message projection and preserved
  permanence continue through `_sanitized_error`; the blind-route refusal keeps public `intent_error`.
- Unit 6 pins the adapter's case key and occurrence numbering for capture and replay here before code,
  within the existing Gateway call-key rules (`core/frozen_copy/headers.py:45-57`).

### Envelope `router-answer.v1`

```text
{"contract": "router-answer.v1",
 "status": "answered" | "abstained" | "failed",
 "answer": str | null,
 "abstain_reason": str | null,
 "failure": {"phase": <C11 phase>, "code": str, "may_have_billed": bool} | null,
 "decision": <completed screamingface.router-decision.v1, C5>}
```

| `status` | `answer` | `abstain_reason` | `failure` |
|---|---|---|---|
| `answered` | `str` | `null` | `null` |
| `abstained` | `null` | `"no_selection"` iff `decision.outcome` is `no_selection`, else `decision.synthesis.reason` | `null` |
| `failed` | `null` | `null` | `decision.failure` plus `may_have_billed` |

- `status` always equals `decision.status`; every other combination is a decode error.
- `failure.code` is the failing operation's bounded code (a Router code, `aigateway_http_<status>`,
  `quorum_not_met`, `frozen_copy_miss`, ...) as data in an Engine-authored record. It is never a
  message, and `phase` never derives from it. A relayed upstream code cannot be a Router code (C11).
- `may_have_billed` is `false` only when every `Attempts` record in `decision`
  (`classifier_call`, each of `branches`, `synthesis`) has `possibly_billed` `false`, or no model call
  ran (phase `admit` or `input`, or a regex classifier with no branch). Otherwise it is `true`.

### SDK surface

```python
@overload
def route_answer(self, profile: str, input: str) -> RoutedAnswer: ...
@overload
def route_answer(self, profile: sf.Router, input: str) -> sf.RouterAnswer: ...
```

The design names the arguments `router` and `question` (`client/router-recipes.md`); the exact
Python signature keeps the pilot's parameter names (`profile`, `input`, pilot `client.py:517`), as
`classify(model, input)` (`client.py:543`) already does for `classifier_id, text`, so pilot keyword
calls keep working. `router=` and `question=` are not keywords and raise `TypeError`. A `str` keeps
the pilot mount and `RoutedAnswer` unchanged.

`sf.RouterAnswer` is the strict decoding of an `answered` or `abstained` envelope, and of nothing
else: every field comes from the envelope, which carries the selected Model IDs in its C5 record, so
the decoder needs neither the authored Router nor a stored definition.

| Field | Type | Source |
|---|---|---|
| `status` | `Literal["answered", "abstained"]` | envelope |
| `answer` | `str \| None` | envelope |
| `abstain_reason` | `str \| None` | envelope |
| `route` | `Literal["selected", "default", "none"]` | `decision.outcome` (`no_selection` gives `"none"`) |
| `selected` | `tuple[tuple[str, str], ...]` | `(label, model)` per `decision.selected` entry; `()` when it is empty |
| `selected_model` | `str \| None` | for `select="one"` and `status` `answered`: `decision.selected[0].model` when `outcome` is `selected`, the `model` of the `branches` entry with `role` `default` when `outcome` is `default`; else `None` |
| `evidence` | typed C5 evidence | `decision.evidence` |
| `policy`, `reason` | typed | `decision` |
| `quorum`, `synthesis` | typed or `None` | `decision`, subset only |
| `revision`, `revision_scheme` | `str` | `decision` |
| `run_id` | `str` | run lifecycle |

Failure mapping; Unit 6 names the classes inside the existing SDK error hierarchy:

| Case | Result | `may_have_billed` |
|---|---|---|
| Capability, shape, size or catalog refusal before `POST /runs` | Planning-time error, no run | `False` |
| Envelope `failed` | Router execution error with `phase`, `code`, `run_id` | envelope value |
| Terminal run failure without an envelope | Existing run error with the `_sanitized_error` code and `permanent` | `True` |
| Lost start acknowledgment or interrupted stream | Same-run recovery where supported, else the run error | `True` |
| Completed result fetch failure, or an envelope that fails strict decoding | Result decode error; no rerun | `True` |

The direct mount's status and retry table is not reused.

## C17 — Engine classifier catalog `GET /v1/classifiers` (Unit 5.2)

The design requires SDK whole-Recipe metadata preflight before submission
(`client/router-recipes.md:395-396`) and lets classifier metadata decide which input contract can
execute (`client/router-recipes.md:160-161`), but names no transport. The SDK talks only to the
Engine, and classifier metadata lives in the Gateway; the Engine serves model discovery
(`rest/catalog.py:116`) but no classifier catalog today. This is the transport:

```text
{"object": "list", "data": [{"id": str, "input_contracts": <C7 input_contracts>,
                             "limits": <C7 TextLimits | ChoiceLimits>}]}
```

- Same caller identity, credential handling and RFC 9457 problem mapping as `GET /v1/models`; it
  lists the caller-visible Gateway classifiers (C7 rows) projected to `id`, `input_contracts` and
  `limits`, copied without change, and makes no inference. Unit 5.2 pins here, before code, whether
  it caches per caller and whether the Engine world bounds the list.
- Rows are strict under C7: an unknown `input_contracts` value, a `limits.contract` other than
  `classifier-limits-v1`, a missing or unknown limit key, or a value outside `1..2147483647` makes that
  row unusable, and the SDK refuses a Router that needs it. A missing row means the classifier is
  not usable.
- ADMIT reads the same Gateway metadata on its own; the SDK preflight never replaces it.
- Covered by `router-v1` (C12); the SDK reads it only after the capability check.
