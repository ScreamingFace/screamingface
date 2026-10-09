# Contracts — node → RDS code pointer

**Status:** proposed. Part G §26 (code-pointer execution) is not published, so every shape here is
`[proposed]` and waits for Kevin McDonough to confirm it (K1–K9 in
[00-overview.md](00-overview.md#6-open-items-for-kevin-mcdonough)). The user decided the rules
behind them (ans:Q1–Q3).

Abbreviations: `G` = `packages/url4/src/url4/`, `T` = `packages/url4/tests/`. Test numbers are the
rows of [prd/rds-code-pointer.md §7](prd/rds-code-pointer.md#7-tdd-plan-red--green--refactor).

## C1 — The RDS input document v1 (the payload of every code-pointer call)

One JSON object. The node builds it after the group's sources reach a terminal state and quorum
passes.

```json
{"v": 1,
 "inputs": {
   "member_1": "A says 4",
   "member_2": "B says 5",
   "extract_pattern": "ANSWER: \\d+",
   "$4": "free text",
   "rows": ["R r1", {"k": 1}],
   "cfg": {"k": "v", "n": 3}}}
```

| Field | Rule | Source |
|---|---|---|
| `v` | Integer `1`. A new field beside `inputs` is a minor change; a change to `inputs` is `v: 2`. | `[proposed]` (P3) |
| `inputs` | One key per resolved source. The key order is the source order after expansion. Serialize with `ensure_ascii=False` and no whitespace (`separators=(",", ":")`). | `[stated ans:Q2]` |
| key, named source | the source's name (`name-part`, from `name:` or `name=`), whatever its weight | `[stated ans:Q2]` |
| key, unnamed source | `$k`, where `k` is the 1-based position after expansion, the same `k` that `$k` names in a template. `$` is not a `name-part` character, so a `$k` key never meets a name. | `[proposed]` (P4) |
| weight-`0.0` source | present, like any other source | `[stated ans:Q2]` |
| failed `;optional` source | absent (no key, no `null`) | `[stated ans:Q2]` |
| value, default | a JSON string that holds the source's resolved text exactly | `[proposed]` (P5) |
| value, collection | a JSON array, when the source is an iteration expression, a broadcast group, an inline parenthesized collection, or a **named** `;expand` source. Rows are typed as `_rows_to_json` types them `[existing G/dag/nodes/_shared.py:118-127]`. | `[stated prompt]` (Spec B §5.3.8), `[proposed]` (P5) |
| value, unnamed `;expand` source | each element is its own input, with its own `$k` key | `[proposed]` (P4) |
| value, `struct-object` source | a JSON object (the canonical JSON that `StructNode` makes `[existing G/dag/nodes/fetch.py:217-231]`) | `[proposed]` (P5) |
| weights, budgets, content types, call identity | not in v1 | `[proposed]` (P6) |

**Why strings by default.** A string keeps the bytes exact: no number re-typing (`"007"` stays
`"007"`), no key re-ordering, no float re-printing, and no guess about what "looks like" JSON. The
E4a combine needs each member's output "byte for byte". A code pointer that wants structure parses
the string itself; that is its input contract (Spec B §6.3). `[proposed]`

**Why structure only from the expression.** Spec B §5.3.8 binds a *collection* as a JSON array. The
expression says which sources are collections (iteration, broadcast, inline collection, expansion)
and which are objects (struct-object). The node reads that from the compiled graph, never from the
content. A fetched body that holds JSON array text is a string. `[proposed]`

**Why a named expansion is one array.** Spec B §5.3.12.5 names the elements `name[0]` …
`name[N-1]`. One array under `name` gives the same addressing (`$name[0]` is element 0, which is
how `_gather_expanded` already binds it `[existing G/dag/nodes/_shared.py:240-250]`), and it avoids
the `src[i]` clash that two unnamed expansions would have. Kevin confirms (K5). `[proposed]`

**Why no metadata.** Weight is attribution metadata, not delivery (ans:Q2). Attribution belongs to
the envelope (Part D §17) and the attribution model (Part E §22). The `v` field leaves room for
`weights` or a call identity (U4) later, as sibling fields. `[proposed]`

Contract tests: rows 6, 7, 8.

## C2 — Node → relative code pointer, in-process, synchronous call

The caller is `CodePointerNode` (new, `G/dag/nodes/`). The callee is a handler registered with the
existing `@node.endpoint(path)` `[existing G/peer/server.py:103-112]`. No new decorator.

**Target string** (built by the new codec in `G/wire/`, beside `encode_subrequest`):

```
<path>?<query-tail as written>&q=(<escaped document>)
<path>?q=(<escaped document>)                         # no query-tail
```

- `<path>` and `<query-tail as written>` are the author's bytes (after `$name` path
  substitution, §2.5 of the PRD). The node does not re-encode them. `[proposed]`
- `q=` is the last parameter, as the grammar requires
  `[existing G/wire/subrequest.py:207-217]`. `[implied]`
- **No `!` tail.** The missing tail plus a valid v1 document is the RDS marker. Kevin confirms
  (K2). `[proposed]` (P8). Correction (code review, 2026-10-09): not every LLM-mode call has a
  `!intent` tail. `encode_subrequest(path, ctx, None)` sends a context-only `q=(ctx)`
  `[existing G/wire/subrequest.py:58-75]`, and the Engine judge uses it
  (`judge_provider.py:196`). Such a call is read as RDS only when its context is itself a valid
  v1 document; the Engine judge's envelope (`schema`, `messages`) is not. Also, a 1.x node that
  receives a 2.0 RDS target runs it as an LLM call (context = the document, intent `""`) and
  answers 200. Both facts are input for K2.
- **Escaping.** Percent-encode the UTF-8 document, keeping raw only RFC 3986 unreserved characters
  and `! $ * , ; : @ / ? =`. So `( ) ' % & # + " { } [ ] \`, space, control characters and
  non-ASCII are escaped. `+` is escaped because a fully-encoded decode reads a raw `+` as a space.
  `[proposed]` (P8)

Worked example (from `(member_1:/a(…)!'P', member_2:/b(…)!'P', extract_pattern:0.0:'ANSWER: \\d+')`):

```
/ensemble/combine/v1?reducer=vote&extract=last_number@1&q=(%7B%22v%22:1,%22inputs%22:%7B%22member_1%22:%22A%20says%204%22,%22member_2%22:%22B:%205%20%28final%29%5Cnok%22,%22extract_pattern%22:%22ANSWER:%20%5C%5Cd%2B%22%7D%7D)
```

**Receiver (dispatch).** `_dispatch.dispatch` `[existing G/peer/_dispatch.py:137-152]` changes in
this order:

1. Split the query at depth 0 and find the raw `q` value. Today's splitter
   `[existing G/wire/subrequest.py:184-242]` also validates every value with `param-value`, so
   the split moves into its own function (`split_expression_query`) that does not validate.
2. Decode the `q` payload. Raw convention (a raw `(` is present): it must be `(` + body + `)`; one
   `unquote` of the body. Fully-encoded convention (`_fully_encoded`,
   `[existing G/wire/subrequest.py:159-171]`): one `unquote_plus`, then strip the outer parens. Do
   **not** run the balanced-paren scan; JSON strings may hold unbalanced parens. `[proposed]`
3. If the payload has no `!` tail and the body is a JSON object with `v == 1` and an object
   `inputs`, the call is RDS. Else it is an LLM call and today's path runs unchanged. `[proposed]`
4. For an RDS call, read the params with the query-tail rule (C6). For an LLM call, keep
   `validate_param` (`param-value`). `[stated ans:Q3]`
5. Match the endpoint by exact path, as today `[existing G/peer/_dispatch.py:164]`.

**Handler shape.** `Request` `[existing G/peer/_dispatch.py:51-62]` gains two fields with defaults,
so every 1.x handler keeps working:

```python
RdsValue = str | list[object] | dict[str, object]

@dataclass(frozen=True)
class Request:
    path: str
    context: str                 # RDS: the decoded document JSON text, exactly as received
    intent: str                  # RDS: "" (the code pointer is the path itself)
    params: Mapping[str, str]    # RDS: query-tail params (C6); LLM: param-value params
    mode: Literal["llm", "rds"] = "llm"
    inputs: Mapping[str, RdsValue] | None = None   # set iff mode == "rds" (C1 "inputs")
```

`[proposed]` (P7). Kevin confirms the field names (K1).

**Result.** The handler returns `str` (or an awaitable of `str`), as today
`[existing G/peer/_dispatch.py:185-188]`. The node returns it unchanged as the group's value.

**Policies.** Timeout: none of its own; the run's deadlines and cancellation apply. Retries: none
(the call is not a source, so `;retry=` does not apply). Idempotency: the call is a GET (doctrine
N1, `[existing G/peer/_dispatch.py:27-28]`); the same expression and the same source values give
the same URL. Ordering: the call starts after every source is terminal.

**Failure behavior.** See C7.

Contract tests: rows 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 22.

## C3 — Node → relative code pointer over HTTP

The same target string as C2, sent as `GET` to the node's HTTP surface. The ASGI app already
dispatches through the same `fetch` port `[existing G/peer/_http.py:69-83]`, so C2's receiver
rules are the HTTP rules too.

```
GET /ensemble/combine/v1?reducer=vote&extract=last_number@1&q=(%7B%22v%22:1,…%7D) HTTP/1.1
200 OK
content-type: text/plain; charset=utf-8

<handler result>
```

- Error body: the existing `{"error": {"code", "message"}}` `[existing G/peer/_asgi.py:48-61]`.
- Status: add `intent_error` → 422 and `unsupported_mode` → 400 to `_STATUS_BY_CODE`
  `[existing G/peer/_http.py:30-39]`. Other codes keep today's mapping. `[proposed]`
- Size: the document is in the request line. The server's request-line limit applies, as it does
  to today's reducer input. `[proposed]`

Contract tests: row 24.

## C4 — Node → remote url4 code pointer

Intent `url4://<authority>/<path>[?<query-tail>]` with no expression form (Spec B §5.2 rule 3.3).

- Target: `url4://<authority><C2 target string>`, sent through `ctx.io` as
  `FetchRequest(target, relative=False, kind="url4")`, like `RemoteFetchNode` does
  `[existing G/dag/nodes/fetch.py:176-178]`. The adapter maps `url4://` to `https://` (Spec B §3.5).
- The remote node applies C2's receiver rules.
- Error code (Should, row 26): for kind `url4`, the outbound adapter reads `{"error": {"code"}}`
  from a non-2xx body and raises with that code and its permanence. Today every non-2xx answer
  becomes a transient `ResolutionError` `[existing G/io/http.py:79-84]`, so a remote `intent_error`
  would be retried. `[proposed]` (P18)

Contract tests: rows 23, 26.

## C5 — Broadcast and iteration-reducer variants

| Form | Calls | Document `inputs` | Result | Source |
|---|---|---|---|---|
| `(a, b, c)!*<code pointer>` | one per **resolved** source, in source order | `{"current": <value>}` (value typed by C1) | the Spec B §6.1.4 array: `{"source_position", "source_name", "result"}` per resolved source, as `BroadcastCollectNode` builds it `[existing G/dag/nodes/group.py:206-216]` | `[proposed]` (P10), K4 |
| `(<collection>*(<body>)[!<per-row>])!<code pointer>` (iteration reducer) | one | `{"$1": [<rows>]}` (the rows as `_rows_to_json` builds them) | the handler result | `[proposed]` (P15) |
| `(<collection>*(<body>))!/reduce(all)!'agg'` (relative-expression reducer) | unchanged | unchanged | unchanged `[existing G/dag/nodes/iteration.py:213-224]` | `[implied]` |

`$current` is the Spec B §6.1.2 name for "the current source being processed", and in RDS mode a
variable reference is the input contract (Spec B §6.3). So the per-source key is `current`.
`[proposed]`

Contract tests: rows 20, 21.

## C6 — The query-tail param reader (U3a)

Owner: `G/core/_annotations.py`, beside `validate_param`. One function, two callers: the
classifier at compile time (the author's intent text) and dispatch at call time (the received
query).

```
query-tail = *( ALPHA / DIGIT / unreserved / ":" / "@" / "/" / "?" / "+" / "&" / "=" )
```

| Step | Rule | Source |
|---|---|---|
| split | on `&`; each segment splits at its first `=` | `[implied]` (ABNF has no key/value structure inside `query-tail`) |
| decode | `unquote` (percent only). **Not** `unquote_plus`: `+` is a literal `query-tail` character. | `[proposed]` (P9) |
| validate | every decoded character of key and value is in the `query-tail` set minus `&`; a key also has no `=` | `[stated ans:Q3]`, OME-507 "validate the decoded value" `[existing G/wire/subrequest.py:225-229]` |
| flag | a segment with no `=` is a flag with value `""` | `[existing G/wire/subrequest.py:219-224]` (same convention) |
| reserved | a key `q` is refused (`q=` belongs to the transport) | `[proposed]` (P9) |
| duplicates | a key that appears twice is refused | `[proposed]` (P9) |
| error | `malformed_source`, permanent | `[existing G/core/_annotations.py:131-135]` (same code) |

Not affected: the protocol params of a url4 URI's own query string (eval path, relative and remote
*expression* calls) keep `param-value` `[stated ans:Q3]`. The transport-only strip
(`rid`, `resume`, `[existing G/wire/subrequest.py:43-50]`) does not apply to a code pointer's
query-tail; those are author params of the code. `[proposed]`

Contract tests: rows 2, 4, 5, 27.

## C7 — Error contract

| Case | When detected | Code (Spec C §13.5.2) | Class | Sources | Code pointer called? |
|---|---|---|---|---|---|
| `https://`, `http://`, other non-url4 scheme as intent | compile | `unsupported_mode` | permanent | none resolved | no |
| code pointer query outside `query-tail`, key `q`, duplicate key | compile (and again at dispatch) | `malformed_source` | permanent | none resolved | no |
| two sources with the same name in an RDS group | compile | `malformed_source` | permanent | none resolved | no |
| required source fails | source resolution | the source's own code | the source's own | the failed one `failed` | no |
| quorum not met | after sources are terminal | `quorum_not_met` (package code; Spec C §13.6 rule 2 names no code) | permanent | as resolved | no |
| no endpoint at the path (incl. a data-route-only path) | call | `intent_error` (K6) | permanent | stay `resolved` | attempted |
| handler raises a `Url4Error` | call | the handler's code | the handler's | stay `resolved` | yes |
| handler raises anything else, or returns a non-`str` | call | `intent_error` | permanent | stay `resolved` | yes |
| a source body is an error page or `{"error": …}` with HTTP 200 | never by the node | — (the code pointer may raise `intent_error`) | — | `resolved` | yes |
| remote node unreachable / transport error | call | today's adapter code (`resolution_failed`, transient) | transient | stay `resolved` | attempted |

`intent_error` and `unsupported_mode` are new `ErrorCode` members
`[existing G/core/errors.py:29-57]`. Source states follow Spec C §13.6: an intent failure leaves
resolved sources `resolved`. `[stated prompt]`

## C8 — Dependency rule

- `url4.core` (classifier, query-tail validator, `ErrorCode`) imports nothing from `url4.dag`,
  `url4.peer`, `url4.wire` or `url4.io`. `[stated prompt]` (hexagonal; core defines, adapters
  implement)
- `url4.wire` (document codec, target builder) imports only `url4.core`.
- `url4.dag` (`CodePointerNode`, wiring) does I/O only through `ctx.io`.
- `url4.peer` (dispatch, `Request`) decodes with `url4.wire` and validates with `url4.core`.
- Enforcement: the existing layering test already checks this direction for every module under
  these prefixes `[existing T/unit/test_layering.py:1-21]`, so new modules are covered when they
  land in the right package. No new arch test is needed.
