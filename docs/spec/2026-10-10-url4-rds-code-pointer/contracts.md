# Contracts — code-pointer intents (url4 2.0.0)

Abbreviations: `G` = `packages/url4/src/url4/`, `T` = `packages/url4/tests/`. Spec
references are to URL4 Spec A/B/C. "Lean: X" names the theorem in `formal/` that states
the rule. Code anchors refer to branch `url4-audit-fixes`.

## C1 — Intent classification (R1)

**Owner:** `G/core/intent.py` (new). Pure function, no I/O:

```python
class IntentForm(StrEnum):
    QUOTED = "quoted"                    # B §5.2 rule 4
    RELATIVE_URI = "relative_uri"        # rule 2.3
    URL4_REFERENCE = "url4_reference"    # rule 3.3
    ABSOLUTE_URI = "absolute_uri"        # rule 5
    BARE_TOKEN = "bare_token"            # rule 10
    EXPRESSION = "expression"            # rules 1, 2.1, 2.2, 3.1, 3.2, iteration
    VARIABLE_REF = "variable_ref"        # rule 8.1
    SELF_REF = "self_ref"                # rule 7.1
    IDENTITY_REF = "identity_ref"        # rule 7.2
    STRUCT_OBJECT = "struct_object"      # rule 6
    PROSE = "prose"                      # unquoted text that is not a bare-value (url4 leniency)

class IntentMode(StrEnum):
    LLM = "llm"; RDS = "rds"; COMPUTED = "computed"

def classify_intent(text: str) -> IntentForm: ...
def intent_mode(form: IntentForm) -> IntentMode: ...     # the B §6 table, total
```

**Detection order** is B §5.2, tested in this order on the raw intent text (before any
`;expr-params`, which the parser already splits off):

| Test on the text | Form |
|---|---|
| starts `'` | `QUOTED` |
| starts `(` | `EXPRESSION` (local or iteration) |
| starts `/`; `(` at depth 0 before any `?` or stop char | `EXPRESSION` (relative sugar, rule 2.2) |
| starts `/`; a `?` comes first and its query holds a parameter `q=(` at depth 0, after `?` or after an `&` (protocol params may come first: `/claude?t=90&q=(c)!x`) | `EXPRESSION` (relative canonical, rule 2.1; §8 parse rules 7a, 16) |
| starts `/`; otherwise | `RELATIVE_URI` |
| starts `url4://`; the same two tests after authority/path | `EXPRESSION` (remote, rules 3.1, 3.2) |
| starts `url4://`; otherwise | `URL4_REFERENCE` |
| starts `{` | `STRUCT_OBJECT` |
| `@` alone / `@` + name | `SELF_REF` / `IDENTITY_REF` |
| `$` + name or digit | `VARIABLE_REF` (or `EXPRESSION` when `*(` follows: iteration) |
| contains `://` | `ABSOLUTE_URI` |
| otherwise, one `bare-value` token (B §8: no space, no control character) | `BARE_TOKEN` (or `EXPRESSION` when `*(` follows) |
| otherwise (unquoted text with a space or a control character) | `PROSE` — not ABNF; url4 keeps it a prompt for compatibility |

The canonical test reuses the parser's own scan (`find_expression_param`, used by
`_parse_expr_canonical`), so the classifier and the parser cannot disagree.

`intent_atom` (`G/core/grammar.py:675`) uses this function instead of its prefix rules
("`/` → `RelUrl`, `scheme://` → `Url`"). So a relative or remote **expression** in
intent position gets an expression node and lowers as a computed intent. Today it lowers
as a data read. `G/core/render.py` keeps its lockstep invariant with `intent_atom`, so it
changes in the same commit; the round-trip tests stay green.

**Mode table** (Lean: `IntentForm.specMode`):

| Form | Mode | 2.0 action (Lean: `v1`) |
|---|---|---|
| `QUOTED` | LLM | prompt (unchanged) |
| `RELATIVE_URI` | RDS | **invoke the code mount** (C2–C5) |
| `URL4_REFERENCE`, `ABSOLUTE_URI` | RDS | **fetch, use the content as the prompt** (the 1.5.1 path, unchanged): **deviation D2**, owner decision Q1 |
| `BARE_TOKEN` | RDS | **invoke the named job** (the code mount with that name key, Q6; P3) |
| `PROSE` | LLM | prompt (unchanged; outside the ABNF) |
| `EXPRESSION`, `VARIABLE_REF`, `SELF_REF`, `IDENTITY_REF`, `STRUCT_OBJECT` | computed | evaluate; the result text is the prompt (Q3) |

Lean: `v1_not_conforms_iff` (D2 is the only deviation), `v1_act_eq_invokeLocal_iff`
(only a relative URI or a named job runs code, on this node), `target_conformant` (the
full B §6 profile, for when D2 closes).

**Named jobs (P3, Q6).** A `BARE_TOKEN` intent is a code pointer whose `pointer` is the
token itself, with no params. The parser builds a `NamedJob` node for it (not `Text`), so
`render` writes it back bare and the round trip keeps the mode.

Traps for the tests (TDD row 1): `/p(c)!x`, `/p?q=(c)!x`, `/p?t=1&q=(c)!x`,
`url4://n/p(c)!x`, `url4://n/p?t=1&q=(c)!x` → `EXPRESSION`; `/api?q=hi`, `/p?x=1&y=2`
→ `RELATIVE_URI`; `rows*()!x` → `EXPRESSION`.

**The code-pointer text.** For `RELATIVE_URI`, split once at the first `?`:

- `pointer` = the path (`"/" path-segment *( "/" path-segment )`). It may hold `$name`
  or `$N` (B §8.2.3). These refer to **the group's own sources** (B §6.2), not to the
  outer scope, and they are interpolated strictly (C6).
- `params` = the `query-tail`, read by C7.

## C2 — Code mounts and the handler API (R4)

**Owner:** `G/core/code.py` (new) for the types (plain data, so `io`, `dag` and `peer` can
all import them); `G/peer/server.py` for registration.

```python
CodeValue = str | int | float | bool | None | list["CodeValue"] | dict[str, "CodeValue"]
CodeWeight = float | Mapping[str, float]              # B §4.1.1 scalar or structured

@dataclass(frozen=True, slots=True)
class CodeInput:
    position: int                 # $N: 1-based, after expansion (B §6.2, §5.3.12.4)
    name: str | None              # `name`, `name[i]` or `src[i]` (B §5.3.12.5); None if unnamed
    value: CodeValue              # C3
    weight: CodeWeight | None     # None = no weight given; 0.0 is a weight (B §5.3.10.3)

@dataclass(frozen=True, slots=True)
class CodeCall:
    pointer: str                          # the path after $-interpolation
    params: Mapping[str, str]             # C7
    inputs: tuple[CodeInput, ...]         # source order; strictly increasing positions

    def input(self, ref: int | str) -> CodeInput:
        """`2`, `"$2"` → by position; `"member_1"` → by name.
        KeyError if absent (a failed source); ValueError if the name is not unique (Q4)."""

CodeHandler = Callable[[CodeCall], str | Awaitable[str]]
```

```python
@node.code("/ensemble/combine/v1")
def combine(call: CodeCall) -> str: ...
```

Rules:

| Rule | Why |
|---|---|
| `Url4Node.code(key)` takes a path (`/score/v1`) or a name (`score_v1`, one `bare-value` token without `$`). One table, own keys (Q6): `!score_v1` finds only the name key, `!/score/v1` only the path key. A name is never routable. |
| `Url4Node.code(path)` registers in a **separate** table. A path is an endpoint, a data route or a code mount, never two of them; registration raises `ValueError` on overlap. A code mount may not be at or under the eval path (as data routes today). The endpoint rule is unchanged (only the exact eval path is refused). | A code mount has an input contract (A §1.1). An endpoint is a model route and `processor_routes()` returns all endpoints (`G/peer/server.py:192`), so a code handler registered as an endpoint would become a processor candidate. |
| A code mount is **not** reachable as an HTTP endpoint. `GET /ensemble/combine/v1?…` → 404 `endpoint_not_found`, as today. | Code runs only as an intent. R5: no new wire. |
| Lookup is by exact path, after `$`-interpolation. | Same rule as endpoints. |
| The handler returns `str`. Any other return value → `intent_error`. | C §13.6 rule 3 |

**Port.** The DAG does I/O only through `ctx.io`. A new optional protocol beside
`SupportsProcessorRoutes` (`G/io/layer.py`):

```python
@runtime_checkable
class SupportsCode(Protocol):
    def has_code(self, pointer: str) -> bool: ...                 # sync; used by preflight
    async def invoke_code(self, call: CodeCall) -> str: ...
```

| Adapter | `SupportsCode` |
|---|---|
| The node's in-process IO (the one that serves its relative fetches) | yes: looks up the code table, runs the handler |
| `StaticIOLayer` | yes, through a new `code: Mapping[str, CodeHandler] = {}` argument (tests) |
| `HttpIOLayer`, client-side runs | no → a relative code pointer fails with `unsupported_mode` |

## C3 — Input binding (R3)

`inputs = bind(expand(sources))` after every source is terminal.

1. **Expand.** An expansion source (`*src` / `;expand`) becomes one source per element,
   at its own position. Positions are renumbered (B §5.3.12.4). Names: `name[i]`, or
   `src[i]` when unnamed (§5.3.12.5). Weight per element: `declared / N` (§5.3.12.6).
   A failed expansion source stays one failed source. Lean: `resolvedCount_expandWith_expand`.
2. **Bind.** The position of source `k` (1-based) is `k`. A resolved source gives
   `CodeInput(k, name, value, weight)`. A failed source gives nothing: no key, no
   `None`, no placeholder. Lean: `find?_pos_bind`, `length_bind`, `pairwise_pos_bind`.
3. **Weight.** It is copied, never used to filter. A weight-`0.0` source is delivered.
   Lean: `payload_bind_reweigh`.

**Value typing comes from the expression, never from the content:**

| Source form | `CodeInput.value` | Basis |
|---|---|---|
| quoted text, fetched URI, relative data read, expression result, scalar `$ref` | `str`, the exact resolved text | — |
| `struct-object` | `dict`; a bare-token field that is a number becomes a number | B §5.3.11.3 |
| iteration expression | `list` of the per-element results | B §5.3.8 last line |
| broadcast group `(…)!*…` | `list` of `{"source_position", "source_name", "result"}` | B §6.1.4 |
| expansion element | the element as parsed from the collection (B §5.3.7): `str`, number, `dict`, … | B §5.3.12.4 |
| `$ref` bound to a collection or struct | that value's type | B §6.2 |

A fetched body that holds JSON text stays a `str`. The code parses it if its contract
says so (B §6.3).

## C4 — Gate and call count (R2)

```
required_ok = every ;required source resolved
quorum_ok   = all      → true                        (C §12.2: "all required sources")
              N        → resolved ≥ N
              majority → resolved ≥ floor(T/2) + 1    (T = post-expansion total)
gate        = required_ok and quorum_ok
```

The counts are after expansion and include weight-`0.0` sources. Lean: `gate_mono`,
`gate_eq_false_of_required_failed`, `gate_all_of_all_optional`.

| Intent op | Gate open | Gate closed |
|---|---|---|
| `!` | one call with all inputs (Lean: `calls_aggregate`) | no call; `required_source_failed` → the failed source's own error; quorum → `quorum_not_met` |
| `!*` | one call per resolved source. Its inputs: that source first (`$current`, B §6.1.2 rule 3), then every other resolved source that a `$`-reference in the pointer names (rule 4), each at its original position. Result = the B §6.1.4 array in source order (Lean: `length_calls_broadcast`, `head?_inputs_of_mem_calls_broadcast`, `length_inputs_of_mem_calls_broadcast`) | same |

All-optional, all-failed, `quorum=all`: the gate is open and the code runs with
`inputs=()`. That is C §12.2 read literally. An author who needs a floor writes
`;quorum=1`.

Triggers: url4 has no trigger delivery. The one call happens when every source is
terminal (C §12.5 sync).

## C5 — Lowering and group sites

**Owner:** `G/dag/_wiring.py` (`_reduce_graph`), new `G/dag/nodes/code.py`
(`CodeCallNode`).

For a group `(S)!I` or `(S)!*I` where `classify_intent(I) == RELATIVE_URI`:

```
lower(group) =
  if not isinstance(ctx.io, SupportsCode):       → FailNode(unsupported_mode)   # no source subgraph
  elif pointer is static and not io.has_code(p): → FailNode(intent_error)       # no source subgraph
  else:
      sources → GuardNodes (required/optional, as today)
      !  → CodeCallNode(pointer, params, slots, quorum)
      !* → per-source CodeCallNode + BroadcastCollectNode
```

- The RDS branch runs **before** the fan-out gate, the base merge and the broadcast
  merge in `_reduce_graph`. No RDS group reaches `ctx.processor` or the `process` hook.
- **Preflight** is the `FailNode` branch: the sources of a group that cannot run are
  never built, so they never run (Lean: `evalGroup_unsupported`, `evalGroup_unmounted`).
  A `FailNode` inside an `;optional` source fails only that source (C §10.1).
- The same rule applies in an iteration body (`coll*(S)!/code`: one call per element)
  and when the group's only source is an iteration (`(rows*(…)!'R')!/code`: one input
  whose value is the row `list`). The 1.5.1 "iteration reducer" path does not see RDS
  intents.
- A pointer with `$` is checked at call time (C2 lookup), not at preflight.
- `CodeCallNode` builds `CodeCall`, calls `await ctx.io.invoke_code(call)`, and maps
  errors by C8. `NodeStarted.node_kind == "CodeCallNode"` is the RDS signal.

## C6 — Strict field paths in RDS scopes

B §5.3.4.1: in RDS mode, a missing field, a type error or an out-of-bounds index MUST
fail with `malformed_source`. LLM mode substitutes `null` or empty.

- A `$`-reference is interpolated **strictly** when the node runs the nearest enclosing
  group's intent as code (action `invokeLocal`: a relative code pointer or a named job).
  This covers the group's source values and the pointer path. A prompt group nested
  inside a code group's sources is lenient again (the nearest group decides). Lean:
  `v1_strictFields_iff`, `specMode_eq_rds_of_strictFields`.
- In a strict scope a reference with no binding is `unbound_reference` (B §6.3:
  references are mechanically required); in an LLM scope it stays verbatim.
- The run option `strict_fields` stays. It forces strictness in LLM scopes too, and it
  never relaxes an RDS scope.

## C7 — The `query-tail` reader

**Owner:** `G/core/_annotations.py`, beside `validate_param`.

```
query-tail = *( ALPHA / DIGIT / unreserved / ":" / "@" / "/" / "?" / "+" / "&" / "=" )
```

| Step | Rule |
|---|---|
| validate | the raw text matches `query-tail`. **No percent-decoding:** the expression text is already decoded (B §7.4), and `%` is not in `query-tail`. |
| split | on `&`; each segment at its first `=`; a segment with no `=` is a flag with value `""` |
| duplicates | a key that appears twice → `malformed_source` (Q8) |
| when | at compile time; the parsed `params` travel in `CodeCall` |

No key is reserved. `q`, `t` and `rid` are ordinary author params here, because nothing
goes on the wire (R5). Protocol params of a URL4 request (eval path, relative and remote
expressions) keep `param-value`, unchanged.

## C8 — Errors

| Case | When | Code | Class | HTTP (eval path) |
|---|---|---|---|---|
| relative code pointer, IO has no `SupportsCode` | lowering (group-level) | `unsupported_mode` | permanent | 501 |
| static code pointer not mounted (incl. a path that is only an endpoint or data route) | lowering (group-level) | `intent_error` | permanent | 422 |
| `$` pointer not mounted | call | `intent_error` | permanent | 422 |
| query outside `query-tail`, or a duplicate key | compile | `malformed_source` | permanent | 400 |
| RDS field-path error | interpolation | `malformed_source` | permanent | 400 |
| unbound `$name` / `$N` | interpolation | `unbound_reference` (existing) | permanent | 400 |
| required source failed | gate | that source's code | that source's class | by class |
| quorum not met | gate | `quorum_not_met` (existing; A2) | permanent | 422 |
| handler raises anything (a `Url4Error` too), or returns a non-`str` | call | `intent_error`; a `Url4Error`'s code goes in `detail` | permanent | 422 |

Every execution failure is `intent_error` (C §13.6: "When intent execution fails, the
error code is `intent_error` (permanent)"). A handler that wants its caller to retry
cannot ask for it; the caller sees a permanent failure. Lean:
`exists_intentError_of_toOutcome_eq_failed`.

Sources that resolved stay resolved after an intent failure (C §13.6).

**Status choice** (Lean: `cls_inbound_statusOf`, `inbound_statusOf`): a caller that
applies C §13.2.1 to our status recovers the class of our code, and the exact code when
§13.2.1 has one. `status_for_code` (`G/peer/_http.py`) keeps its explicit rows and gets
a class default: an unlisted **permanent** code → 422, an unlisted transient code → 502.
`internal_error` keeps an explicit 500 row, and a failure with no code (an internal bug)
stays 500.
Today an unlisted permanent code (for example `quorum_not_met`,
`expansion_not_iterable`) gets 500, which a conformant caller reads as transient and
retries. 501 ↔ `unsupported_mode` is exact. `intent_error` has no status in
§13.2.1; 422 keeps the class (permanent), and the JSON body carries the code
(§13.2.1 "response body inspection"). 400 would lose `unsupported_mode`
(`inbound_400_ne_unsupported_mode`). 500 would make `intent_error` transient
(`cls_inbound_500_ne_cls_intentError`).

`G/core/errors.py` gains `INTENT_ERROR` and `UNSUPPORTED_MODE`. Both are Spec C registry
codes, so they have no `x.` prefix.

## C9 — Forwarded calls keep a code-pointer intent verbatim

C §11.6.2 rule 3: a nested expression passes through **verbatim** inside the child's
`q=`. Today, for both a relative call (`/p(ctx)!/code`) and a remote call
(`url4://n/v1(ctx)!/code`), the caller lowers the call's intent as its own dependency
(`deps["intent"]` in `G/dag/_lowering.py`), fetches `/code`, and sends the fetched text.

2.0 rule: when the form of a forwarded call's intent is `RELATIVE_URI`, the caller builds
no intent dependency and sends the pointer text unchanged: `/p?q=(ctx)!/code`. The node
at `/p` decides what `/code` means. An absolute-URI intent of a forwarded call keeps
today's path (the caller fetches it; D2).

A named-job intent (`/p(ctx)!score_v1`) travels the same way: verbatim, unquoted.

**Prompt intents (A5 fix, owner decision Q10).** A quoted or computed intent of a
forwarded call is resolved by the caller, as before, and is then sent as a
`quoted-text` literal: `'` + the text with `\` → `\\` and `'` → `\'` + `'`
(`q=(ctx)!'Answer the question'`). So an eval-path receiver reads a prompt, never a
named job or a code pointer. `decode_subrequest` (endpoint dispatch, `StaticIOLayer`
routes) unquotes a quoted-text intent, so an endpoint handler's `Request.intent` is the
same text as in 1.5.1. Limit: `quoted-char` is `%x20-7E` and url4 refuses a raw control
character in quoted text, so a resolved prompt that holds one (a newline) is sent
unquoted, as in 1.5.1; such a text is never a `bare-value`, so a receiver still reads it
as `PROSE`, unless it starts with a value head (`/`, `(`, `{`, `@`, a scheme).

## C10 — Remote code pointers (deferred; design for Part G)

In 2.0 no intent form names code on another node: absolute URIs are prompt sources (Q1,
D2). This section records what blocks remote code, for the day an absolute URI becomes a
code pointer. The owner's rule for that day is Q2: refuse with `unsupported_mode` until
Part G defines the input transport.

A conformant remote call must be a URL4 request whose `q=` is an expression. The natural
form is to **delegate the group**: send `url4://n/v1?q=(S')!/code?…`, where `S'` is `S`
with outer `$`-references substituted. The node `n` then runs its own relative code
pointer. Two spec gaps block it (Q2):

1. A substituted value with a newline or non-ASCII text cannot be a `quoted-text`
   (the ABNF `quoted-char` is `%x20-7E`; url4's parser refuses control characters such
   as a newline, and accepts non-ASCII beyond the ABNF).
2. A resolved collection cannot be a literal source (a parenthesized collection exists
   only before `*(`; a `struct-object` cannot hold arrays, B §5.3.11.3).

Until then, authors send the whole expression to the owning node.

## C10a — Layering

- `url4.core`: `IntentForm`, `classify_intent`, the `query-tail` reader, `ErrorCode`,
  and the plain data types `CodeCall`, `CodeInput`, `CodeHandler` (re-exported from
  `url4`). It imports nothing from `dag`, `peer`, `io`, `wire`.
- `url4.io.layer`: `SupportsCode`; imports the types from `url4.core`.
- `url4.dag`: `CodeCallNode` and wiring; I/O only through `ctx.io`.
- `url4.peer`: `Url4Node.code` and the in-process `SupportsCode` adapter.
- The existing `T/unit/test_layering.py` covers the new modules; no new arch test.
