# url4 RDS code pointer — Implementation Plan

> **For agentic workers:** steps use checkbox (`- [ ]`) syntax. One branch, one PR, one commit
> per task. Do the tasks in order: each task uses the one before it.

**Goal:** a relative-URI or `url4://` intent runs as one RDS code-pointer call with the group's
sources as a JSON input document (url4 2.0.0).

**Spec:** `docs/spec/2026-10-09-url4-rds-code-pointer/` (overview, PRD, contracts C1–C8, test
plan). The user approved it on 2026-10-09 ("plan + code on defaults"). The code follows the K1–K9
recommended defaults. Kevin McDonough confirms K1–K9 in parallel; a change from him touches only
the codec (Task 2) and its tests.

**Tech stack:** Python 3.12, uv, pytest (asyncio), httpx ASGI transport. No new dependency.

**Abbreviations:** `G` = `packages/url4/src/url4/`, `T` = `packages/url4/tests/`. Row numbers
(`CH1`–`CH11`, `1`–`29`) are the rows of PRD §7.

## What the code changed in the spec

| # | Spec said | Code says | Plan does |
|---|---|---|---|
| A1 | release 1.5.1 → 2.0.0 | `main` already has a breaking url4 change (#1085). Release PR #852 already proposes 2.0.0 | the user decided (2026-10-09): join 2.0.0. This PR merges before #852. The overview §10 says so |
| A2 | C2 step 1: "today's splitter, without validating values yet" | `extract_expression_params` validates every param with `param-value` before dispatch knows the mode `[G/wire/subrequest.py:222,237]` | Task 3 splits it: `split_expression_query` (no validation) + the old function, which stays as split + validate |
| A3 | D4: "an inline parenthesized collection" source is a JSON array | a bare `(a, b)` in source position fails with `missing_intent` `[G/dag/_lowering.py:447-462]`, so an inline collection is never a direct source | no work; the row-7 case uses an iteration over an inline collection |
| A4 | the classifier reads the ABNF production | the grammar's `parse_value` already makes the decision (path charset, §8 rule 16, host and port checks); a second set of rules disagreed with it (design review, 2026-10-09: `/p?a=(b)`, `url4://:80/p`, `/rows*()!'R'`) | the classifier runs `parse_value` on the atom text (L7) |
| A5 | an `https://` intent fails "before any source resolves" | a lazy nested group compiles at spawn time `[G/dag/executor.py:261-287]` | top-level and AST groups fail at compile. A group inside a lazy fragment fails when the fragment compiles (still before its own sources resolve). `Graph.validate()` finds both |

## Decisions taken in this plan (the owner can change any of them before the PR)

| # | Decision | Why |
|---|---|---|
| L1 | **One marker type, `JsonText(str)`**, in `G/dag/nodes/_shared.py`. `CollectNode`, `BroadcastCollectNode` and `StructNode` return it. The RDS gather parses a `JsonText` with `json.loads`; every other `str` stays a string | the PRD row-7 note ("mark by type, like `FetchedText`"). One type for arrays and objects, because the JSON already says which one it is |
| L2 | **The classifier is `classify_intent(atom) -> IntentClass`** in a new module `G/core/intent.py`. `IntentClass(mode: IntentMode, pointer: CodePointer \| None)` | pure, in the core, testable per ABNF row (row 1) |
| L3 | **`_Intent` gets a third field, `pointer: CodePointer \| None`.** `_compile_group` routes on it before broadcast, the fan-out gate and the fold | one routing point for the AST path and the text path (both reach `_intent_from_ast`) |
| L4 | **A new node, `CodePointerNode`, in a new module `G/dag/nodes/code_pointer.py`.** Broadcast uses one `CodePointerNode` per source (in single-source mode) under the existing `BroadcastCollectNode` | no RDS branch inside `MergeNode`; the §6.1.4 rows come from the existing collector |
| L5 | **The receiver decides RDS in `call_endpoint`**, so `dispatch` and `dispatch_direct` share it. An RDS request whose path has no endpoint fails with `intent_error` and never falls through to the eval path or a data route | E2: a data route is never code |
| L7 | **The classifier runs the grammar's `parse_value` on the `RelUrl`/`Url` atom text.** `RelUrl` → RDS (then `read_query_tail`); `RelExpr`, `RemoteExpr`, or a `missing_intent` error (`/reduce()`) → LEGACY; `Iteration` → COMPUTED; a non-url4 scheme → UNSUPPORTED (not parsed); any other `ParseError` propagates (`malformed_source`); a `url4://` reference with no path (`url4://n`) → `malformed_source`, because it names a node, not code | one owner for the production rules: the grammar. The no-path refusal is our choice; the owner can change it to RDS on `/` |
| L6 | **`ReduceNode` classifies its reducer text with `classify_intent(intent_atom(...))`.** RDS → one call with `{"$1": [rows]}` | D8 |

## Review round (2026-10-09, after Task 6)

`design-reviewer` (Tasks 3–6) and `sf-code-review` (whole branch) found no structural problem.
The fix round changes these plan points:

| # | Was | Now |
|---|---|---|
| R1 | Task 4 step 5: the reducer is classified at resolve time | at lowering (contracts C7 "compile"): no per-row call runs before the refusal. The per-row intent of an iteration is checked at lowering too, unless it holds a `$` reference |
| R2 | (not stated) a code-pointer reducer with a `!` tail | `malformed_source`; the tail is never dropped |
| R3 | Task 4 step 2: map `endpoint_not_found` from the fetch to `intent_error` | removed: a `Url4Node` already answers an RDS miss with `intent_error`, and the mapping corrupted a handler's own error |
| R4 | Task 5: adopt any known code; permanent iff 4xx | adopt only `intent_error`, `unsupported_mode`, `malformed_source`, `quorum_not_met` (the Engine reserves some codes); permanent for 4xx and 500 (url4's server sends 500 for a permanent unmapped code) |
| R5 | Task 4 step 2: RDS quorum error as `_check_quorum` | permanent (C7), through one shared helper; LLM groups unchanged |
| R6 | — | a call's own folded intent on the AST path is not classified (P16); the substituted code-pointer path is re-checked; the handler's exception text stays off the wire; duplicate names are allowed in a broadcast |

## Global constraints

- **Worktree:** this one (`.claude/worktrees/url4-rds-code-pointer`, branch `url4-rds-code-pointer`).
  Rebase on `origin/main` before the PR. Open PR #1340 also edits `G/dag/_lowering.py`; rebase
  after it if it merges first.
- **Tests:** from `packages/url4`, `uv run pytest -q`. Free and offline. HTTP rows use the ASGI
  app with `httpx.ASGITransport`, never the network.
- **Gates** at the end of each task: `uv run .claude/scripts/run_gates.py url4` (from the repo
  root): ruff check, ruff format --check, pyright, pytest with `--cov-fail-under=95`.
- **Append-only gate during Task 4.** `run_gates.py` compares with `HEAD` by default; the
  pre-push hook compares with the merge base on `origin/main`. Task 4 runs
  `run_gates.py url4 --base $(git merge-base origin/main HEAD)`. Its append-only check then
  names only `T/unit/test_dag.py` and `T/unit/test_characterization.py` (CH8–CH10) until the
  manifest exists at PR-open; confirm that list, then run the other gates with
  `--skip-append-only`. Report it in the ledger.
- **Tests are append-only.** The only prior tests that change are CH8, CH9 and CH10
  (`T/unit/test_dag.py:440-469`, `T/unit/test_dag.py:472-483`,
  `T/unit/test_characterization.py:53-61`). They change in the task that removes their behavior.
  At PR-open, the owner approval manifest `.claude/test-change-approvals/OME-N.json` pins the
  two changed files (`approved_test_changes.py`); the PR body names them.
- **Layering:** `T/unit/test_layering.py` already enforces C8. `core` imports nothing new;
  `wire` imports only `core`.
- **Comments:** only the anchors `WHY:`, `INVARIANT:`, `AIDEV-NOTE:`, `FEATURE:`, `STORY:`.
  `FEATURE: RDS code pointer (url4 2.0)` on each new module.
- **Commits:** conventional, no `Co-Authored-By`, no ticket. The squash title at merge is
  `feat(url4)!: run URI intents as RDS code-pointer calls` with the `BREAKING CHANGE:` footer
  from overview §10.

## Task 0 — Characterization first (CH7, CH11)

**Files:** create `T/spec/test_rds_code_pointer.py`; append to `T/spec/test_param_conformance.py`.

- [ ] CH7: an eval-path request `GET /v1?tone=a@b&q=(x='1')!'go'` fails with
  `malformed_source` (through `Url4Node` dispatch).
- [ ] CH11: one test per row of the PRD §2.3 probe table, run on today's code. Use a `Url4Node`
  with endpoints `/a` → `"A says 4"`, `/b` → `"B says 5"`, `/ensemble/combine/v1`, a data route
  `/instr` → `"INSTRUCTION TEXT"`, a recording `process` hook, and a recording default route.
  Name the tests `test_char_1_5_1_<what>`. Put the comment `# AIDEV-NOTE: flips in Task 4` on
  rows 1, 2, 4 and 6. Rows 3 and 5 also flip (a data route is not code, E2), as the design
  review found; Task 4 flips rows 1–6.
- [ ] All green on today's code. Commit `test(url4): pin the 1.5.1 URI-intent behavior`.

## Task 1 — Core: error codes, query-tail reader, intent classifier (rows 1, 2, 4, 5, 27)

**Files:** `G/core/errors.py`, `G/core/_annotations.py`, new `G/core/intent.py`,
`G/core/__init__.py` (export only if the core exports its siblings; follow the file). Tests:
new `T/unit/test_intent_classifier.py`; append to `T/spec/test_param_conformance.py`.

1. `ErrorCode` gains `INTENT_ERROR = "intent_error"` and `UNSUPPORTED_MODE = "unsupported_mode"`.
2. In `_annotations.py`, beside `validate_param`:

   ```python
   # query-tail = *( ALPHA / DIGIT / unreserved / ":" / "@" / "/" / "?" / "+" / "&" / "=" )
   _QUERY_TAIL_CHAR_RE = re.compile(r"[A-Za-z0-9\-._~:@/?+=]*", re.ASCII)  # no "&" inside a part

   def read_query_tail(query: str) -> dict[str, str]:
       """A code pointer's ``?query-tail`` as params (U3a, contracts C6). Raise ParseError."""
   ```

   Rules, in this order: empty `query` → `{}`. Split on `&`; skip empty segments. Split each
   segment at its first `=`; no `=` → flag, value `""`. Decode key and value with
   `urllib.parse.unquote` (never `unquote_plus`). The decoded key must be non-empty, match
   `_QUERY_TAIL_CHAR_RE` and hold no `=`; the decoded value must match `_QUERY_TAIL_CHAR_RE`.
   Key `q` → error. A key seen twice → error. Every error is
   `ParseError(..., code=ErrorCode.MALFORMED_SOURCE)` (permanent by default) and names the key.
   Return the dict in query order.
3. New `G/core/intent.py`:

   ```python
   class IntentMode(StrEnum):
       LLM = "llm"                # Text atom (quoted text, bare token)
       COMPUTED = "computed"      # Expression, Iteration
       VALUE = "value"            # VarRef, StructObject, SelfRef, IdentityRef
       RDS = "rds"                # relative-uri, or url4:// reference
       UNSUPPORTED = "unsupported"  # any other scheme://
       LEGACY = "legacy"          # relative/remote expression text, /path(...) text

   @dataclass(frozen=True)
   class CodePointer:
       path: str                  # as written; may hold $name (substituted at run time)
       query: str                 # the query-tail as written, "" when absent
       params: Mapping[str, str]  # read_query_tail(query)
       authority: str | None = None  # set iff url4://

   @dataclass(frozen=True)
   class IntentClass:
       mode: IntentMode
       pointer: CodePointer | None = None   # set iff mode is RDS

   def classify_intent(atom: Node) -> IntentClass: ...
   ```

   - `Text` → LLM. `Expression`, `Iteration` → COMPUTED. `VarRef`, `StructObject`, `SelfRef`,
     `IdentityRef` → VALUE. Any other node type → LEGACY.
   - `RelUrl(value)`: `path, sep, query = value.partition("?")`. If `_DATA_PATH_RE` (import it
     from `url4.core.grammar`) does not fullmatch `path`, or `"(" in query` → LEGACY (an
     expression form, PRD §2.5 last row). Else RDS with
     `CodePointer(path, query, read_query_tail(query))`. So `/p?x=1,2`, `/p?q=hello` and
     `/p?a=1&a=2` raise `malformed_source` here (row 2, E8).
   - `Url(value)`: `url4://` head → strip it; `authority, slash, rest = remainder.partition("/")`;
     the same path and `(` checks on `"/" + rest` → LEGACY or RDS with `authority`. Any other
     scheme → UNSUPPORTED.
   - `INVARIANT:` comment: never trust the node type alone, because `intent_atom` puts
     expressions in `RelUrl`/`Url` `[G/core/grammar.py:916-925]`.
4. Tests (RED first): row 1 parametrized over the PRD §2.5 table, through
   `classify_intent(intent_atom(text))`, including the traps `/p(c)!x`, `/p?q=(c)!x`,
   `url4://n/p(c)!x`, `/reduce()` → LEGACY; `https://x/y`, `http://x`, `s3://b/k` → UNSUPPORTED;
   `/ensemble/combine/v1?reducer=vote&extract=last_number@1` → RDS with those params. Row 4: the
   reader cases (`@` kept, `+` literal, `%40` → `@`, flag → `""`, `q` refused, duplicate
   refused, `,` refused). Row 5 and 27: `validate_param("tone", "a@b")` still raises.
- [ ] RED → GREEN → gates. Commit `feat(url4): classify intents and read code-pointer query tails`.

## Task 2 — Wire: the RDS document codec (rows 6-codec, 8)

**Files:** new `G/wire/rds.py`; `G/wire/__init__.py` exports. Test: new
`T/unit/test_rds_document.py`.

```python
RdsValue = str | list[object] | dict[str, object]
RDS_VERSION = 1

def encode_rds_document(inputs: Mapping[str, RdsValue]) -> str:
    """json.dumps({"v": 1, "inputs": dict(inputs)}, ensure_ascii=False, separators=(",", ":"))"""

def decode_rds_document(text: str) -> dict[str, RdsValue] | None:
    """The ``inputs`` of a valid v1 document, else None (never raises on bad JSON)."""
    # valid = a JSON object, "v" == 1 (int, not bool), "inputs" a JSON object

def encode_rds_target(path: str, query: str, document: str) -> str:
    """``<path>?<query>&q=(<escaped>)`` or ``<path>?q=(<escaped>)`` (contracts C2)."""

def decode_q_payload(raw_q: str) -> str | None:
    """The body of ``(<body>)`` with no ``!`` tail, decoded, or None (contracts C2 step 2)."""
```

- Escape: `urllib.parse.quote(document, safe="!$*,;:@/?=")`. `quote` keeps the RFC 3986
  unreserved set raw and escapes everything else, including `+`, `&`, `%`, `(`, `)`, `'` and
  non-ASCII (UTF-8). `INVARIANT:` `+` is escaped because a fully-encoded decode reads `+` as a
  space.
- `decode_q_payload`: raw convention (`"(" in raw_q`): it must start with `(` and end with `)`
  and the body (between them) must hold no raw `(` or `)` → `unquote(body)`; else None. A raw
  `)` followed by `!` means an LLM call → None. Fully-encoded convention (no raw `(`, has `%`):
  `unquote_plus(raw_q)`, then it must start with `(` and end with `)` → the inside; else None.
  Do not run the balanced-paren scan.
- Tests: row 6 codec part (key order kept, `ensure_ascii=False`, no spaces); row 8 seeded
  `random.Random(20261009)` corpus of 200 documents over the alphabet: newline, `'`, `"`, `%`,
  `&`, `(`, `)`, `#`, `+`, space, `\\`, `é`, `日`, emoji, empty string → target →
  `decode_q_payload` (both conventions: the raw target, and `quote(full_q, safe="")` as a
  standard client sends it) → `decode_rds_document` → equal. `decode_rds_document` returns None
  for `{"v": 2, ...}`, `{"v": true, ...}`, a list, `inputs` not an object, and bad JSON.
- [ ] RED → GREEN → gates. Commit `feat(url4): add the RDS input document codec`.

## Task 3 — Peer: `Request.mode`/`inputs`, RDS dispatch, HTTP status (rows 10, 11, E9)

**Files:** `G/wire/subrequest.py`, `G/peer/_dispatch.py`, `G/peer/direct.py` (only if it
builds a `Request` or validates params itself), `G/peer/_http.py`. Tests: append to
`T/unit/test_server.py` or a new `T/unit/test_rds_dispatch.py` (prefer new).

1. `subrequest.py`: extract the loop of `extract_expression_params` into
   `split_expression_query(query_string) -> tuple[list[tuple[str, str | None]], str | None]`:
   same depth-0 split and same "`q=` closes the query" error, raw values, `None` for a flag, no
   validation. `extract_expression_params` becomes split + today's validation, with the same
   behavior (all its tests stay green unchanged).
2. `Request` gains `mode: Literal["llm", "rds"] = "llm"` and
   `inputs: Mapping[str, RdsValue] | None = None`, with the C2 comments.
3. `dispatch`: split with `split_expression_query`. If a raw `q` is present and
   `decode_q_payload(q)` gives text that `decode_rds_document` accepts → RDS call:
   params = `read_query_tail(<raw query before q=, without the trailing &>)`; if `path` is an
   endpoint → `Request(path, context=<document text>, intent="", params, mode="rds",
   inputs=<inputs>)`; else raise `ResolutionError(f"no code pointer at {path!r} on node ...",
   code=ErrorCode.INTENT_ERROR, permanent=True)`. Never fall through to the eval path or data
   routes. Else → today's path, with params validated exactly as today.
4. `call_endpoint`: a handler that raises a `Url4Error` → re-raise unchanged. In RDS mode only,
   any other `Exception`, or a result that is not `str` → `ResolutionError(...,
   code=ErrorCode.INTENT_ERROR, permanent=True)` chained `from exc`. LLM mode keeps today's
   behavior.
5. `dispatch_direct`: give it the same RDS branch by reusing the helper from step 3 (one owner).
6. `_http.py` `_STATUS_BY_CODE`: `INTENT_ERROR: 422`, `UNSUPPORTED_MODE: 400`.
- Tests: row 10 (all `Request` fields for an RDS target built by `encode_rds_target`, both
  conventions); row 11 (every LLM shape: `q=(ctx)!intent`, `q=()!x`, context-only `q=(ctx)`
  whose ctx is not a v1 document, a fully-encoded LLM call → `mode == "llm"`, `inputs is None`);
  `@` param kept for RDS and refused for LLM (E9); RDS to a data-route-only path →
  `intent_error`; RDS to a missing path → `intent_error`; handler `ValueError` →
  `intent_error`; handler `Url4Error(code="x.custom", permanent=False)` kept; HTTP status 422.
- [ ] RED → GREEN → gates. Commit `feat(url4): dispatch RDS code-pointer calls to endpoints`.

## Task 4 — DAG: code-pointer groups (rows 3, 6-gather, 7, 9, 12–23, 25, 28; flips CH8–CH10)

**Files:** `G/dag/nodes/_shared.py`, `G/dag/nodes/group.py`, `G/dag/nodes/fetch.py`
(`StructNode` only), new `G/dag/nodes/code_pointer.py`, `G/dag/nodes/__init__.py`,
`G/dag/__init__.py` (export like its siblings), `G/dag/_wiring.py`, `G/dag/_lowering.py`
(`_intent_from_ast` only), `G/dag/nodes/iteration.py` (`ReduceNode`). Tests: the delta rows go
in `T/spec/test_rds_code_pointer.py`; the CH11 rows marked "flips in Task 4" change there;
CH8, CH9, CH10 change in place.

1. `_shared.py`: `class JsonText(str)` (L1) with a `WHY:` docstring. `CollectNode`,
   `BroadcastCollectNode` and `StructNode` return `JsonText(...)`. Add

   ```python
   def _gather_rds(inputs: Mapping[str, Payload], slots: tuple[SlotSpec, ...]) -> dict[str, RdsValue]:
   ```

   It walks the slots like `_gather`, with a running 1-based position `k` over resolved values
   after expansion: `SourceFailure` → skip (no key, `k` not advanced); `list` + name → one key,
   value `[_row_value(e) for e in elements]`, `k += len(elements)`; `list` + no name → one
   `$k` key per element, string value; `JsonText` → `json.loads`; other `str` → `str(value)`.
   Key = name, else `f"${k}"`. Instrumental slots are **included**. `_row_value` is the row rule
   of `_rows_to_json` (`_maybe_json(r) if r[:1] in "[{" else r`); refactor `_rows_to_json` to
   use it.
2. New `code_pointer.py`:

   ```python
   @dataclass(eq=False)
   class CodePointerNode:
       pointer: CodePointer
       slots: tuple[SlotSpec, ...] = ()
       quorum: int | None = None
       single: bool = False   # broadcast part: inputs == {"current": <value>}
       deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": node} or {"source": node}

       async def resolve(self, inputs, ctx) -> Payload: ...
   ```

   - Group mode: `values = _gather_rds(inputs, self.slots)`. Quorum: count of resolved slots
     after expansion, instrumental **included** (P11): raise `quorum_not_met` like
     `_check_quorum` when `quorum is not None and count < quorum`. `quorum=None` with nothing
     resolved → call with `{}` (D9).
   - Single mode: `inputs["source"]` → `{"current": <typed value>}` (same typing as
     `_gather_rds`).
   - Path: `_substitute(self.pointer.path, ctx.scope, ctx)` (outer scope, PRD §2.5).
   - Target: `encode_rds_target(path, self.pointer.query, encode_rds_document(values))`.
     Relative → `await ctx.io.fetch(target, relative=True)`. Remote → `await _fetch(ctx,
     FetchRequest(f"url4://{authority}{target}", relative=False, kind="url4"))`.
   - Never read `ctx.processor`, never call `ctx.process` (`INVARIANT:` comment, rows 12, 22).
   - A non-`Url4Error` exception from the fetch propagates unchanged; the receiver maps errors
     (Task 3).
   - In-process mapping: an `endpoint_not_found` from the fetch of an RDS target → re-raise as
     `ResolutionError(code=INTENT_ERROR, permanent=True)` (E1 against an IO layer that is not a
     `Url4Node`, for example `StaticIOLayer`).
3. `_wiring.py`: `_Intent` gains `pointer: CodePointer | None = None`. In `_compile_group`,
   first: if `intent is not None and intent.pointer is not None`:
   - duplicate slot names → `ParseError(..., code=MALFORMED_SOURCE)` (D12);
   - `broadcast` → `BroadcastCollectNode(names, deps={f"part:{i}": CodePointerNode(pointer,
     single=True, deps={"source": slot.make({})})})`;
   - else → `CodePointerNode(pointer, _slot_specs(slots), quorum, deps={f"src:{i}": node for
     ... in enumerate(_build_slots(slots))})`.
   No other branch changes.
4. `_lowering.py` `_intent_from_ast`: classify a `RelUrl`/`Url` atom. RDS → `_Intent(make=<as
   today>, pointer=cls.pointer)`. UNSUPPORTED → `ParseError(f"... {atom.value!r} ...",
   code=ErrorCode.UNSUPPORTED_MODE, permanent=True)`. Every other mode → as today.
5. `ReduceNode.resolve`: before `grammar_parse`, if `classify_intent(intent_atom(reducer_src))`
   is RDS → one fetch through the same target builder with `{"$1": json.loads(array_json)}`;
   UNSUPPORTED → `unsupported_mode`. A relative-expression reducer keeps `_dispatch`. Put the
   target-building in one helper in `code_pointer.py` that both nodes call (no copy).
- Tests (RED first, one behavior each; use a `Url4Node` with endpoints, a recording `process`
  hook and a recording default route): rows 3, 6 (gather part), 7, 9, 12–23, 25, 28 as PRD §7.2
  states them. Row 7 also pins that a lazy group source (`r=(/rows*()!'R $item')`) keeps the
  `JsonText` marker through `ctx.spawn`. Flip CH8 and CH10 to `unsupported_mode` and CH9 to
  "lowers to `CodePointerNode`". Flip the CH11 rows marked in Task 0.
- [ ] RED → GREEN → gates. Commit `feat(url4)!: run URI intents as RDS code-pointer calls`
  with the `BREAKING CHANGE:` footer.

## Task 5 — Outbound adapter keeps the remote error code (row 26, Should)

**Files:** `G/io/http.py`. Test: new `T/unit/test_http_remote_errors.py`.

- In `HttpIOLayer._get`, on `httpx.HTTPStatusError` for a target that was `url4://` (pass a
  flag from `_transport_url`'s caller), read the body as JSON `{"error": {"code": str}}`. When
  the code is a known spec code, raise `ResolutionError(message, code=<code>, permanent=<from
  the status: 4xx → True, 5xx → False>)`. Otherwise keep today's transient error. Non-url4
  targets keep today's behavior exactly.
- Test: an ASGI peer whose code pointer raises `ValueError`, reached through `HttpIOLayer` with
  `httpx.ASGITransport` → the caller gets `intent_error`, `permanent is True`.
- [ ] RED → GREEN → gates. Commit `feat(url4): keep a remote url4 node's error code`.

## Task 6 — HTTP and E2E rows, docs (rows 24, 29; release checks)

**Files:** `T/spec/test_rds_code_pointer.py`; `packages/url4/README.md`;
`docs/spec/2026-07-11-url4-package-v1-spec.md`; the spec folder of this unit; the ledger.

- Row 24: an ASGI `Url4Node` app + `httpx.ASGITransport`; the caller node's outbound IO is
  `HttpIOLayer` on that transport; a `url4://` code pointer gets byte-exact inputs (the Task 2
  alphabet) and the `@` params.
- Row 29: the E4a three-model vote: three members `member_1..3:/m1..3($input)!'P'`, a weight-0.0
  `extract_pattern`, intent
  `/ensemble/combine/v1?reducer=vote&extract=last_number@1&normalize=numeric@1&tie=first&min_votes=2`
  against a stub combine that records its `Request`; assert the three texts byte-exact and the
  five params.
- README: a "Migrating to 2.0" section with the four steps of overview §10.
- v1 spec: a 2.0 note on the `FanoutReduceNode` and `BarrierNode` rows.
- Spec fixes from the anchor check: `connector.py:464` → `:465` (overview §8, PRD §2.3);
  test-plan §2 anchor `pyproject.toml:92-94` → `T/unit/test_characterization.py:177-192`;
  contracts C2 step 1 wording ("split only; `split_expression_query`"); PRD §4 observability
  ("`node_kind == "CodePointerNode"` is the signal this package gives; no `intent_mode` field
  exists"); overview §10 version text (A1).
- Run the Engine and SDK suites against this url4 (no test edits allowed; a red test is a
  finding): `apps/screamingface-engine`: `uv run pytest -n auto -q tests/unit`;
  `packages/screamingface`: `uv run pytest -n auto -q`.
- [ ] Gates for url4, then the two regression suites. Commit
  `test(url4): HTTP and E4a spine rows for RDS code pointers` and
  `docs(url4): migration note for 2.0 RDS code pointers`.

## After Task 6 (stop here; the owner decides)

- Design review against this plan and the spec (`design-reviewer`), then `sf-code-review`.
- The PR is **not** opened in this session. At PR-open: confirm the issue text with the user,
  file one issue under OME-500, rename the branch to `OME-N-url4-rds-code-pointer`, write the
  approval manifest for CH8–CH10, mirror in `docs/tasks/`, and say in the PR body that #852
  must merge after this PR.

## Follow-ups in this PR (ans:Q7, ans:Q8 — 2026-10-09)

Three units, built in parallel in three worktrees branched from `bd20bea3d`, each committed
there and then cherry-picked onto this branch. **File ownership is disjoint** (below); a unit
never edits a file another unit owns. Gates per unit: `run_gates.py url4` (the card now also
runs `scripts/check_module_size.py`, which `url4-tests.yml` already ran in CI) with the same
append-only rule as Task 4 (only the CH8–CH10 files may be named).

Found while planning: `check_module_size.py` fails on this branch for four modules
(`dag/_lowering.py` 805/747, `dag/nodes/_shared.py` 326/267, `dag/nodes/iteration.py` 231/228,
`peer/_dispatch.py` 293/214). The script's rule: split by reason to change; never raise a
baseline; lower a baseline when its module shrinks for good. U2 and U3 fix all four.

### U1 — O6: a failed optional source in an LLM broadcast makes no call and no row

- **Owns:** `G/dag/nodes/group.py` (`MergeNode` only); new `T/spec/test_broadcast_optional.py`.
- **Change:** `MergeNode.resolve` returns `inputs["source"]` unchanged when it is a
  `SourceFailure`, before any substitution or `ctx.process` call. `BroadcastCollectNode`
  already drops a `SourceFailure` part (`group.py:215`). This mirrors the code-pointer
  broadcast (`CodePointerNode(broadcast_part=True)`). Spec B §6.1.3: broadcast applies across
  resolved sources.
- **Tests (RED first):** `(a='1', b=/nope;optional, c='3')!*'T $current'` → `process` called
  twice (not with `""`), result rows for positions 1 and 3 only; a required failure still fails
  the run; a fetch/computed broadcast intent (`!*($x)` or a var-ref intent — whichever form
  still uses `MergeNode`) behaves the same. No existing test pins the old behavior (scout,
  2026-10-09); no production code builds `!*` with `;optional`.

### U2 — O7: endpoints opt in to code-pointer calls

- **Owns:** `G/peer/server.py`, `G/peer/_dispatch.py`, new `G/peer/_code_pointer.py`,
  `G/peer/direct.py`, `G/peer/_http.py` (only if needed); tests `T/unit/test_rds_dispatch.py`,
  `T/spec/test_rds_code_pointer.py`, `T/spec/test_rds_code_pointer_sites.py`,
  `T/spec/test_rds_code_pointer_http.py`, `T/unit/test_http_remote_errors.py`, and new
  `T/unit/test_rds_opt_in.py`; `packages/url4/README.md` ("Migrating to 2.0" step 3 and the
  example).
- **Change:** `Url4Node.endpoint(path, *, rds: bool = False)` (and any registration sugar that
  forwards to it — read `server.py`); the node keeps the set of opted-in paths beside
  `_endpoints`. The code-pointer branch of dispatch (`rds_call`, `call_rds`, `_raw_query_tail`)
  moves to `G/peer/_code_pointer.py` (one owner; `_dispatch.py` and `direct.py` import it), and
  refuses a path that is an endpoint without `rds=True` with
  `ResolutionError("endpoint {path!r} does not take code-pointer calls", code=INTENT_ERROR,
  permanent=True)` before the handler runs. An LLM call to an `rds=True` endpoint is still
  delivered. `_dispatch.py` must end ≤ its cap (214); lower its `BASELINE` entry only if U3 has
  not touched the file — U3 owns `scripts/check_module_size.py`, so U2 reports the new line
  count instead and the main loop updates the entry at merge.
- **Tests:** every test on this branch that registers a code-pointer endpoint adds
  `rds=True`; new tests: a model-like endpoint registered without the flag receives no call and
  the caller gets `intent_error` permanent (in-process, `dispatch_direct`, and HTTP 422); an
  LLM call to an `rds=True` endpoint still works with `mode="llm"`.
- **Engine:** no code change; its suite must stay green (no Engine handler sends or serves
  code-pointer calls — scout, 2026-10-09).

### U3 — module-size splits (behavior unchanged)

- **Owns:** `G/dag/_lowering.py` and new `G/dag/_lowering_*.py` modules, `G/dag/compiler.py`,
  `G/dag/nodes/_shared.py` and a new `G/dag/nodes/` module for the code-pointer gather,
  `G/dag/nodes/iteration.py`, `G/dag/nodes/code_pointer.py`, `scripts/check_module_size.py`.
  Must NOT edit `group.py`, `fetch.py` or any test (if a test imports a moved private name,
  keep a re-export and report it).
- **`_lowering.py` split** (scout proposal, by reason to change; the facade keeps the import
  path `url4.dag._lowering`, which only `compiler.py` imports):
  facade (`Lowerer`, `LoweringRegistry` — or a leaf `_lowering_registry.py` to avoid a cycle —
  `default_registry`, `Graph`, `compile_expression`, `_lower_top_level`);
  `_lowering_nodes.py` (default lowerers, context-slot wiring, iteration, collection/source);
  `_lowering_text.py` (the text path); `_lowering_intent.py` (intent, reducer and row-intent
  classification, `_slot_identity`, `_refs_of_ast`). Every module ≤ 450 lines; no import
  cycle; module docstrings in the `_wiring.py` style ("split out of …, one-directional").
- **`_shared.py` / `iteration.py`:** move the code-pointer responsibilities out (`JsonText`
  may stay if `group.py`/`fetch.py` import it from `_shared`; `_gather_rds` and its helpers move
  to a new `G/dag/nodes/_rds_gather.py` or into `code_pointer.py`); move the reducer's
  code-pointer call into a helper in `code_pointer.py`. Both end within their caps.
- **Baselines:** lower `dag/_lowering.py`, `dag/nodes/_shared.py`, `dag/nodes/iteration.py`
  entries to their new counts (they shrank for good); add entries for the new modules only if
  the script's convention lists comparable modules (read it); never raise one.
- **Tests:** none new (pure move); the full suite, pyright and the layering test prove it.
