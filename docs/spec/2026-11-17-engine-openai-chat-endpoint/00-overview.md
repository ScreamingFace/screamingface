# OpenAI-compatible chat endpoint on the Engine — overview

**Status:** draft, written from the owner interview of 2026-11-17 (Q1–Q17). The owner approved
P1–P20 and OQ-1 as written on 2026-11-17 (ans:Q17). Design review round 1 (two independent
reviewers, 2026-11-17: one APPROVE_WITH_FIXES, one ESCALATE; 2 blockers and 15 major points) is
fixed in this text; see §11. P21–P30 came from that review, and the owner approved them on
2026-11-17 (ans:Q18–Q20). Design review round 2 (broad, two reviewers, both APPROVE_WITH_FIXES:
1 blocker and 11 major points) is fixed in this text; see §11. P31–P40 came from that review.
The owner decided three of its points (ans:Q25–Q27). Design review round 3 (targeted, one
reviewer: APPROVE_WITH_FIXES, no blocker, 2 major points) is fixed in this text; see §11. The
owner approved P31–P40 and P42 on 2026-11-17 (ans:Q31) and replaced P33 and P41 by a different
rule for web search (ans:Q30). Design review round 4 (targeted: APPROVE_WITH_FIXES, no blocker,
2 major points) is fixed in this text; see §11. The plan is written and waits for approval. **Epic:** not set (the owner names it at PR-open). **Leaves:** filed at PR-open.
**Base:** branch `engine-openai-chat-endpoint`, worktree
`.claude/worktrees/engine-openai-chat-endpoint`, on origin/main `8530a9d75`.

## 1. Summary

Users ask to use their url4 ensembles from tools that speak the OpenAI API. The Engine gets one
new route, `POST /v1/chat/completions`. The `model` field holds a Candidate URL4 or a gateway
model id. The Engine runs that recipe as the user built it and answers in the OpenAI shape.

The feature has three dedicated parts and one move:

- **The route** (control plane). It validates the request, checks the recipe, stores the
  conversation as a run-scoped blob, schedules a run with the new shape `chat` and holds the
  connection for the result. It answers as JSON or as a buffered event stream.
- **The chat handler** (an internal endpoint in the world, run as one observed node). It gives
  each step that is not final a text view of the conversation, and it calls the existing recipe
  evaluation with no change. Reducers, signals, Gates, Cascades and budgets work as measured.
- **The final-step endpoint** (world). When the request has tools, the last model step of the
  recipe runs here: one request to the gateway with the native conversation and the client
  tools. Its tool calls go back to the client. The Engine never runs a tool.
- **The transport move.** The full gateway round trip (all the code below the tool loop) leaves
  `connector.py` for a shared module, with no behaviour change. This is larger than the three
  parts named in the interview; see P24.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`, `G/` =
`apps/aigateway/src/aigateway/`. Line numbers are on origin/main `8530a9d75`.

## 2. Subsystems and ownership

| Part | Module (proposed) | Half | Document |
|---|---|---|---|
| Route | `E/rest/chat_completions.py` | control plane | [chat-completion](prd/chat-completion.md), [streaming](prd/streaming.md) |
| Chat leaf | `E/chat/` | shared leaf | [erd](erd.md), [tool-calls](prd/tool-calls.md) §3 |
| Chat handler | `E/world/chat_turn.py` | world | [chat-run](prd/chat-run.md) |
| Final-step endpoint | `E/world/chat_final.py` | world | [tool-calls](prd/tool-calls.md) |
| Shared transport | `E/world/gateway_transport.py` | world | [gateway-transport](prd/gateway-transport.md) |
| Docs | `public-docs`, Engine README | — | [docs](prd/docs.md) |

Existing code that changes:
- the `RunShape` type, and one new branch in the executor for the `chat` shape;
- one new keyword (`chat_input`) on the schedule port, on `_schedule`, on the queue codec, on the
  in-process adapter and on the test fakes; the 5 s grace and the run deadline for `chat`;
- the registration of two internal routes in `E/world/factory.py`;
- the blob store: a `delete` operation, and a second store instance with its own policy;
- a filesystem blob store in the local stack;
- a small wrapper around the App server that sets a drain event on the stop signal;
- the world installs the combine and branch routes also when it has no Benchmarks;
- three new codes in the Engine error code set, and the existing test that pins that set;
- the existing test that pins "no combine route in a world with no Benchmarks"
  (`test_combine_wiring.py`), replaced by CR-25;
- the App mount table: a filter by the direct-mount set (`E/world/serving.py`);
- `E/world/classification.py`: its imports of six moved names;
- the layering gate lists;
- `connector.py`: about half of it moves to the shared module, and 26 existing test files change
  their patch targets (approval record needed). Existing code that does not change: the model endpoint and its loop, the
envelope schemas, the Candidate Invocation envelope, the combine and branch routes, the gateway.

## 3. Reading order

1. This overview.
2. [erd.md](erd.md): the three records.
3. [prd/gateway-transport.md](prd/gateway-transport.md): the first unit.
4. [prd/chat-run.md](prd/chat-run.md): the run side.
5. [prd/chat-completion.md](prd/chat-completion.md): the HTTP side with no tools.
6. [prd/streaming.md](prd/streaming.md).
7. [prd/tool-calls.md](prd/tool-calls.md): the final step and the tools.
8. [prd/docs.md](prd/docs.md).
9. [contracts.md](contracts.md) and [test-plan.md](test-plan.md).

## 4. Interview ledger

Answers are quoted as the owner wrote them. "NR" = the owner picked an option that was not the
recommended one.

| Q | Subject | Answer |
|---|---|---|
| Q1 | target and clients | "both (doesn`t matter their tools, we`re aiming for compatibility with agents like opencode, claude code, pi, etc) and well known sdks that expect this type of api from an LLM platform" |
| Q2 | hosted authentication | "Same auth mechanism we use nowadays"; later: "it must use the same auth workflow we already have." |
| Q3 | raw url4 text in `model` | "yup" |
| Q4 | buffered stream is acceptable | "yup" |
| Q5 | tools | "tools are important to support (for agentic workflows)." |
| Q6 | a dedicated endpoint | "instead of adapting the existing engine runner endpoint logic, what if we copy/create our own new endpoint in the runner and then make it specifically for this feature? … i`d prefer to have a second and lean / opnionated endpoint specifically for this feature." |
| Q7 | path | "Instead of /openai/v1/chat/completions, why not just v1/chat/completions (if it`s already in use, try sf/v1/chat/completions)?" |
| Q8 | ensemble scope and tool decision | "consider that the fusion/ensemble logic and workflow can be a bit more complex (look at e4a, e4b and e4c workflows + the regular Fusion on). Ideally, the user must be able to build their own ensemble in whatever way they decide to, and then the last LLM inference step of that ensemble might be able to make the required decisions." |
| Q9 | reducer at the final step with tools | "deterministic reducers at the final step shouldn`t be supported in `with tools` scenarios." |
| Q10 | abstain = empty answer with a status; fail = HTTP error | "yeah, agreed" |
| Q11 | transport: move or copy | "move" |
| Q12 | Claude Code and Codex formats as later adapters | "yup" |
| Q13 | `usage` counts | "Whole ensemble sum" (NR) |
| Q14 | request fields such as temperature, max_tokens, stop, response_format, tool_choice | "Ignore all of them" (NR) |
| Q15 | shared cache | "On by default (Recommended)" |
| Q16 | content of `model` | "URL4 or model id (Recommended)" |
| Q17 | proposed decisions P1–P20, OQ-1 (delete the input at request end) and a design review before the plan | "Let`s go all with your suggestion/answers" |
| Q18 | meaning of ans:Q9, and P30 (a Cascade with tools) | "When I mean `no reducer at the final step with tools` I mean, no static/algorithm reducer (like vote). If it`s a model type (synthetizer, etc). It can do it"; then for P30: "Let`s go with A" (refuse, with the `>> model` way) |
| Q19 | P24 (move size), P25 (rollout), P21–P23 and P26–P29 | "Full round trip (Recommended)"; "Shutdown hook (Recommended)"; "Approve all seven (Recommended)" |
| Q20 | a second review before the plan | "yeah, a new broad review" |
| Q21 | an on/off setting for the endpoint | "Always on" (NR) |
| Q22 | pull requests for the build | "One PR" (NR) |
| Q23 | commit of the spec | "Leave it uncommitted" |
| Q24 | parent epic | "At PR-open (Recommended)" |
| Q25 | the limit of 24 runs in flight, shared by evaluations and chat requests | "Share the limit (Recommended)" |
| Q26 | a cached call counts 0 tokens in `usage` | "Yes, document it (Recommended)" |
| Q27 | `cascade >> model` when the Cascade abstains | "Run as built (Recommended)" |
| Q28 | a third review | "Yes, targeted (Recommended)" |
| Q29 | P41, web search when a step does not set it | "Follow the model route" (NR) |
| Q30 | the same question again, after I found that each model route has web search on by default | "On by default (route rule)" (NR) |
| Q31 | P31–P40 and P42 | "Approve all (Recommended)" |
| Q32 | next step | "One more targeted review" |
| Q33 | chat answers and the community cache, after the final review stated that each signed-in account can read the stored answers | "community cache must be on by default". Reason of the owner: the product is for benchmarks and evaluations, and for these a shared cache is good for cost and for reproducibility (NR) |
| Q34 | the server subclass in `cli.py` and the edits to three CLI tests | "make the edits" |
| Q35 | the time limit for a slow large body (408) | "1 min instead of 30 secs" (replaced by Q36) |
| Q36 | the same limit, after I reported that 60 s does not fit in the shutdown grace of the App pod | "let`s keep the 30s instead of 60s limit" |
| Q37 | the edit to `tests/unit/test_mount_routes.py` | "edit in the tests approved" |
| Q38 | the parent epic, after a search of Linear found no ticket and two epics that fit (E8, E9) | "OME-1297, E8 (Recommended)" |

**Effects of the two NR answers, recorded and not reopened.**
- Q13: an agent that reads `usage.prompt_tokens` as the context size reads a value that is too
  high for an ensemble. The response gives the real value in `screamingface.final_step.usage`,
  and the docs say so.
- Q14: the output limit of the final step is the value in the recipe, or the default of the
  provider. The docs tell users to set `max_tokens` in the recipe for agent use.
- Q30: each step of a chat request searches the web when its model route can search, unless the
  recipe sets `web_search=false`. The conversation text of that step goes to the search
  provider, and the turn costs more. A recipe can search here when it did not search in a
  Benchmark that forbids it. No shared code changes for this. With tools, the final step cannot
  use the Engine web tools, so P13 now refuses only a final step that asks for them explicitly
  (tool-calls §3.2).
- Q21: the route has no setting. It is reachable in each environment as soon as the code is
  deployed. Because of Q22, the full feature arrives in one deploy, so no half-built route is
  reachable.
- Q22: one pull request holds the transport move and the new code. The plan keeps the units as
  separate commits in order (U1 first), so a reviewer can read the move alone and a revert of
  one unit stays possible before the merge. The deploy order (workers before the App) still
  applies.

## 5. Scope map

| In this spec | Later (not in this spec) |
|---|---|
| `POST /v1/chat/completions`, JSON and buffered stream | token-by-token streaming |
| `model` = Candidate URL4 or gateway model id | named aliases; recipes in `/v1/models` |
| each recipe kind with no tools, but not corrective loops | corrective loops outside a Benchmark |
| tools, when each final position is a model step or an outcome | tool calls from reducers; a Cascade or a step Gate with tools (add `>> model` to use them today) |
| hosted access with the Access token header; local with no credential | API keys; Bearer tokens |
| OpenAI Chat Completions format | Anthropic Messages (Claude Code); OpenAI Responses (Codex) |
| one shared queue and worker pool | a separate lane or lighter workers for chat runs |

Known limit of the scope: Claude Code and Codex do not speak the Chat Completions format, so
they cannot use this endpoint `[stated ans:Q12]`. opencode, pi and the OpenAI-style SDKs can.
Hosted use needs a client that can send a custom header `[stated ans:Q2]`.

## 6. Proposed decisions that need sign-off

These were my engineering defaults. The owner approved all of them as written on 2026-11-17
`[stated ans:Q17]`. They are in scope. Their `[proposed]` tags in the other files stay, so a
reader can see which lines came from this table.

| P | Decision | Where |
|---|---|---|
| P1 | Records `chat-input.v1` and `chat-result.v1`; run env key `URL4_CLOUD_CHAT_INPUT`; run shape `chat` | erd §2 |
| P2 | The conversation travels as a run-scoped blob; body cap 8,000,000 bytes; `model` cap 32,000 characters | erd §2.1, chat-completion CC-S17 |
| P3 | The OpenAI error envelope and the status table (401, 400, 404, 413, 422, 429, 502, 503, 504) | chat-completion §3.2 |
| P4 | `n` > 1, `logprobs` and audio are refused with 400 (they change the shape of the answer) | chat-completion CC-S16 |
| P5 | Time limit 600 s (`chat_max_wait_s`); keep-alive 15 s (`chat_keepalive_s`) | chat-completion §4, streaming §4 |
| P6 | The in-flight cap answers 429, not 503 | chat-completion CC-S19 |
| P7 | The `screamingface` object in the response; the topic is never returned | contracts C1 |
| P8 | No Run registry row, no capture, no replay for chat requests | erd §1.3 |
| P9 | The text view rules | tool-calls §3.4 |
| P10 | The native message layout of the final step | tool-calls §3.5 |
| P11 | The internal route `/ensemble/chat/v1/final/<model id>` and the re-point by expression change | tool-calls §3.2 |
| P12 | With tools, a Gate with a reducer branch is refused; an unknown final form is refused | tool-calls §3.1 |
| P13 | A final step that needs the Engine web-tool loop is refused when the request has tools | tool-calls TC-S11 |
| P14 | A model with no tool support is refused before the run, from the catalogue | tool-calls TC-S10 |
| P15 | An error after the stream starts is one error event and no `[DONE]` | streaming ST-S6 |
| P16 | `stream_options.include_usage` has an effect, although other option fields are ignored | streaming ST-S3 |
| P17 | A provider refusal is a 200 with `message.refusal` | chat-completion CC-S25 |
| P18 | A benchmark-linked expression in `model` is refused with a hint | chat-completion CC-S15 |
| P19 | Deploy order: workers before the App | erd §2.2 |
| P20 | A one-model recipe with an empty instruction for a gateway model id; the plan confirms the exact URL4 form | chat-completion CC-S1 |

### 6.1 Decisions from design review 1 (approved by the owner on 2026-11-17, ans:Q18–Q19)

| P | Decision | Where |
|---|---|---|
| P21 | A second blob store instance (the chat-input store) with its own policy; the local stack sets a filesystem blob store | erd §1.1 |
| P22 | The handler runs as one observed node on the internal route `/ensemble/chat/v1/turn`; the App computes `usage` and `cost_usd` from the cost-usage frames (details: see P32) | chat-run §2, chat-completion CC-S3 |
| P23 | Re-point by binding name, with Gate bodies parsed and rendered again; a client recipe that names the internal route prefix is refused | tool-calls §3.2 |
| P24 | The moved set is the full round trip (about half of `connector.py`), and existing test files change their patch targets (21 files; see P36) | gateway-transport §2.2 |
| P25 | The App stops in-flight chat runs when it shuts down; clients get 503 `server_restarting` (mechanism: see P31) | chat-completion CC-S37 |
| P26 | `x-should-retry: false` on a 504 and on permanent failures | chat-completion §3.2 |
| P27 | 415 for a content type that is not JSON; a running body cap; a limit on request bodies in memory (rule: see P38) | chat-completion CC-S34, CC-S35 |
| P28 | A chat run carries the run deadline. (The web search part is replaced by ans:Q30) | chat-run CR-S15 |
| P29 | A `model` value is a URL4 if and only if it starts with `(`; each other value is looked up as a model id | chat-completion CC-S1 |
| P30 | With tools, each `sf.Cascade` and each step Gate is refused (the effect of ans:Q9); the docs give the `>> model` way | tool-calls §3.1 |

### 6.2 Decisions from design reviews 2 and 3 (approved by the owner on 2026-11-17, ans:Q31; P33 and P41 withdrawn)

| P | Decision | Where |
|---|---|---|
| P31 | The drain starts at the stop signal, through a wrapper around the App server; this replaces the hook of P25 | chat-completion CC-S37 |
| P32 | `usage` and the cost come from the root cost-usage frame; `cost_usd` is null for an unpriced run; the `calls` field of P7 is removed, because a run gives one usage record for the whole ensemble | chat-run CR-S3, chat-completion CC-S3 |
| P33 | Withdrawn. Replaced by ans:Q30: web search follows the model route | chat-run CR-S16 |
| P34 | The chat routes have their own installer with the gateway world; the combine, branch and chat routes are installed also in a world with no Benchmarks | tool-calls §3.2, chat-run CR-S19 |
| P35 | The executor calls the turn route in the shape of a Candidate route call; the turn route and the final route fail closed outside a chat run | erd §2.2, chat-run CR-S18 |
| P36 | `connector.py` imports the transport module, not its names, so a stale test patch fails; 26 test files and `classification.py` change their targets | gateway-transport §2.2 |
| P37 | One terminal table for each end state of a run, with status, body code and retry header | chat-completion §3.2 |
| P38 | At most 4 large bodies are parsed at one time; this replaces the 64 MB rule of P27. The content-type check ignores parameters | chat-completion CC-S34, CC-S35 |
| P39 | `finish_reason` is the value of the provider; the "if and only if" rule is removed | erd §2.4 |
| P40 | The model lookup is kept for 60 s; a failed lookup is 503 | chat-completion CC-S1 |
| P41 | Withdrawn. Replaced by ans:Q30: no new policy mode and no shared code change. The recipe text is still never changed | chat-run CR-S16 |
| P42 | (review 3) The App filters its mount table by the direct-mount set, so the internal routes are never public | chat-run CR-S19 |

## 7. Global assumptions

- The hosted Engine is behind Cloudflare, which closes a response with no bytes after about
  100 s. The keep-alive lines of the stream prevent this. A long request with no stream can fail
  at the edge `[proposed]`. The plan verifies this with infra.
- The local stack has a blob store. If `screamingface up` does not set one, the plan adds the
  setting `[proposed]`.
- The gateway accepts the native message layout of the final step for each provider (two system
  messages; a `user` message after a `tool` message). Review 1 did not verify this for
  Anthropic. The plan tests it on the replay lane before unit U6 `[proposed — review 1]`.
- A call served from the cache reports 0 tokens `[existing E/world/connector.py:853]`. The owner
  accepted this for `usage` `[stated ans:Q26]`.
- Measured overhead of a queued run: about 350 ms typical, 1.6 s at p95, about 2 s with no idle
  warm child `[existing apps/screamingface-engine/docs/plans/uniform-executor/measurements/parity-gate.md:200]`.

## 8. Risks and the condition to look at each again

| Risk | Look again when |
|---|---|
| Cost: each agent turn runs the full ensemble on the full context | users report turn cost; then add provider prompt-cache support |
| Capacity: a chat run holds a worker slot. A caller with 24 runs in flight (for example a large evaluation) gets 429 on each agent turn, and the SDK fails after its retries `[stated ans:Q25]` | users report refused agent turns; then give chat requests their own limit or lane |
| Text view quality: non-final steps see tool history as text | members propose wrong tool arguments often; then give members a native view |
| Two model-call paths | a gateway contract change needs edits in both; the shared transport must then grow |
| Token expiry for hosted agents | users report daily failures; then decide again on a long-lived credential |

## 9. Deferred questions

None is open.

**OQ-1 Input blob retention (closed).** The blob store has a sweep and no delete. The
conversation of an agent can hold source code. The owner approved the default
`[stated ans:Q17]`: add a delete operation, delete the blob when the request ends, and keep the
sweep as the safety net (erd §1.1).

## 10. Next steps

1. Done: four design review rounds (§11).
2. Done: the plan is `docs/plan/2026-11-17-engine-openai-chat-endpoint.md`, with units U1–U7 as
   ordered commits of one pull request. It waits for the owner.
3. Code starts only after the owner approves the plan in plain words.

## 11. Design review record

**Round 1, 2026-11-17.** Two independent reviewers read the spec against the code. Lane A (run
side and tools): ESCALATE. Lane B (HTTP side and consistency): APPROVE_WITH_FIXES.

| Finding | Severity | Fix in this spec |
|---|---|---|
| The blob store refuses the chat input on both sides (signature rule, default policy on the Runner, no store in local mode) | blocker | P21 |
| A run started with `Url4Node.evaluate` has no observer, so it reports no cost and no usage; the result body is built before the cost fold | blocker | P22 |
| Gate branch bodies are text, and a member and a synthesizer can share a route, so a re-point by path is wrong | major | P23 |
| Each Cascade with tools is refused, and the spec did not say so | major | P30 |
| Five moved functions do not give the final step the cache policy, the retries and the reports | major | P24 |
| The move breaks about ten existing tests that patch `connector` globals | major | P24 |
| The usage sum from operation attribution undercounts two bindings on one route | major | P22 |
| A client recipe can name the internal final route | major | P23 |
| The text view did not cover content part lists | major | tool-calls §3.4 rule 0 |
| An App rollout leaves chat runs that pay until their deadline | major | P25 |
| A stream disconnect cancels its own cleanup | major | streaming ST-S8 |
| Large bodies can exhaust App memory before admission | major | P27 |
| SDK retries multiply the ensemble cost | major | P26 |
| Raw failure codes and problem+json bodies can leave the route | major | chat-completion §3.2, CC-S36 |
| A cross-site simple POST can start a paid ensemble on a local stack | major | P27 |
| The schedule port cannot carry the input ref | major | erd §2.2, contracts C5 |
| Minor: read path of a large result; model classification rule; unit order of ST-10; hosted 401 comes from the edge; `openai` dev dependency; default-cache assertion; wrong guard citation; run deadline; web search policy; refusal path | minor | fixed in place |

Not verified by the reviewers: how the gateway shapes two system messages and a user message
after a tool message for Anthropic (§7).

**Round 2, 2026-11-17 (broad).** Two independent reviewers checked the round-1 fixes and read the
whole spec again. Both: APPROVE_WITH_FIXES.

| Finding | Severity | Fix in this spec |
|---|---|---|
| The shutdown hook of the framework runs after the open requests end, so it cannot stop a waiting chat request | blocker | P31 |
| A run gives one usage frame for the whole ensemble, not one for each call; the call count has no source | major | P32 |
| `usage` and the cost were not defined for unpriced calls and for cache hits | major | P32, ans:Q26 |
| "Web search off unless the step turns it on" cannot be said with the existing policy | major | P33 (withdrawn later; replaced by ans:Q30) |
| The final route needs gateway state that its registration point does not have; a world with no Benchmarks has no ensemble routes | major | P34 |
| The way the executor calls the turn route, and its concurrency, were not specified | major | P35, chat-run CR-S20 |
| 21 test files (not ten) patch the moved names, and a name import would make the patches silent | major | P36 |
| `cascade >> model` changes an abstain into a model answer | major | ans:Q27 (run as built), docs |
| The `finish_reason` invariant contradicted a scenario | major | P39 |
| The terminal table was incomplete (worker drain, kills, no result frame) | major | P37 |
| The 64 MB limit counted raw bytes, not parsed size | major | P38 |
| Minor: charset in the content type; permanent 503 without `Retry-After`; lookup failure; docs limits; capacity wording; size boundaries; a test that could not fail; pictures to a model that cannot read them | minor | fixed in place |

Confirmed as correct by round 2: the chat-input store (P21), selection by binding name (P23), the
shielded cleanup on a stream disconnect, the model classification rule (P29), the refusal of
Cascades with tools (P30), and the OpenAI error envelope.

**Round 3, 2026-11-17 (targeted).** One independent reviewer checked only what round 2 changed.
Verdict: APPROVE_WITH_FIXES, no blocker.

| Finding | Severity | Fix in this spec |
|---|---|---|
| A `web_search=false` written into the recipe text breaks the way Gates and combine steps find the records of their members (a Budget Gate would count no spend) | major | the recipe text is never changed; the owner then chose the route rule (ans:Q30) |
| The App would publish the internal routes as public mounts, because it lists each endpoint of a world with no Benchmarks | major | P42 |
| 26 test files (not 21) and one source file refer to the moved names | minor | P36, gateway-transport §2.1 |
| Terminal table: the time-out row, a catch-all row for `stopped`, and one existing test that pins the code set | minor | chat-completion §3.2 |
| Drain: thread-safe set of the event, a request after the event, a subprocess test | minor | chat-completion CC-S37 |
| The usage field mapping was not written down | minor | contracts C9 |
| Body places with no length header; `finish_reason` with no provider value; a "not known" lookup is not kept | minor | fixed in place |
| Old text left over | minor | fixed in place |

Confirmed as correct and buildable by round 3: the drain at the stop signal (P31), the usage chain
from each model call to the root frame (P32), the call of the turn route with a recipe of 32,000
characters (P35), the import rule (P36), and P38–P40.

Not verified: whether an existing test pins the route set or the OpenAPI document of a world with
no Benchmarks. The plan checks this before unit U3.

**Round 4, 2026-11-17 (targeted, small).** One independent reviewer checked the web search rule
of ans:Q30, the App mount filter (P42) and the consistency of the last edits. Verdict:
APPROVE_WITH_FIXES, no blocker.

| Finding | Severity | Fix in this spec |
|---|---|---|
| An existing test pins "no combine route in a world with no Benchmarks" | major | chat-run CR-S19, test-plan §1 |
| The default search result depends on the search key of the Engine, and the spec did not say so | major | chat-run CR-S16 (table), CR-22, docs |
| The final-step endpoint must derive its search flag itself and not reuse the request builder | minor | tool-calls §3.2 |
| A step that is not final can try to call a client tool that it sees as text | minor | chat-run CR-S16, docs |
| The place of the always-on installer; "never public" needs the App filter | minor | chat-run CR-S19, tool-calls §3.2 |
| Old history row; two line numbers | minor | fixed in place |

Confirmed by round 4: with no policy bound, no step raises in the default case; no code needs a
Benchmark scope when a call searches; the App mount filter keeps the public mounts and
`/openapi.json` the same; the final positions do not change; the test counts match (136).

Not verified (needs a live provider): provider search together with client function tools on
one request. The plan tests it on the replay lane before unit U6.
