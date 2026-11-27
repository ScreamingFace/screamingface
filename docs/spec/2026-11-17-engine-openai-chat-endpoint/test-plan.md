# OpenAI-compatible chat endpoint: test plan

## 1. Strategy

- **Pyramid.** Most tests are unit tests on pure functions: the wire models, the recipe check,
  the two conversation views, the result translation and the SSE frames. Each connection in
  [contracts](contracts.md) has one integration test or more. Three E2E tests cover the spine.
- **No money.** No test calls a provider. Unit and integration tests use a stub gateway. The
  tests marked E2E run on the local in-process App with a fake gateway and the `openai` SDK as
  the client (plan decision D1). They do not use the SDK replay lane, because a new scenario
  there needs a paid recording first
  `[existing packages/screamingface/tests/e2e/README.md:1]`.
- **RED first.** Each delta test fails for the right reason before the code exists. The
  characterization tests (`CHAR`) of the transport move pass on the code of today by design.
- **Existing tests are append-only.** A change to an existing test needs an approval record
  `[existing .claude/scripts/run_gates.py:382]`. Unit U1 needs one: 26 existing test files
  refer to `connector` names that the move relocates, and their patch targets must change
  ([gateway-transport](prd/gateway-transport.md) §2.2). Unit U3 needs two more: the test that
  pins the Engine error code set by hand gets the three new codes, and the test that pins "no
  combine route in a world with no Benchmarks" is replaced by CR-25. The plan lists the files. No
  other unit changes an existing test.
- **New dev dependency.** The `openai` package is not an Engine dependency today. ST-4, CC-22,
  TC-21 and DOC-1 need it as a dev dependency `[proposed — review 1]`.
- **Gates.** `uv run .claude/scripts/run_gates.py screamingface-engine` for each unit, and the
  `repo` stack for the layering gate.

## 2. Techniques

| Technique | Where |
|---|---|
| Boundary values | body size at 8,000,000 and 8,000,001 bytes; `model` at 32,000 and 32,001 characters; `tools` empty, one, many; result at the inline cap |
| Decision table | final position × tools present (tool-calls §3.1); failure code × status (chat-completion §3.2) |
| State transitions | request: accepted → scheduled → answered / failed / timed out / disconnected; each exit stops the run and deletes the blob |
| Property-based | each text view parses as a valid envelope (TC-5); rendering is deterministic (TC-6); CHAT_INPUT round trip (CR-1) |
| Golden bytes | transport headers and body digest before and after the move (GT-1, GT-2) |
| Client conformance | the `openai` SDK types parse each response and each frame sequence (ST-4, CC-22) |

## 3. Unit order and test counts

The order is risk-first and follows the dependencies. The plan document will turn it into units.

| Unit | PRD | Tests | Count |
|---|---|---|---|
| U1 shared gateway round trip | [gateway-transport](prd/gateway-transport.md) | GT-1 … GT-8 | 8 |
| U2 chat leaf: records, recipe check, re-point, views | [chat-run](prd/chat-run.md), [tool-calls](prd/tool-calls.md) | CR-1, CR-2, TC-1 … TC-8, TC-29, TC-31 … TC-34 | 15 |
| U3 run shape, chat-input store and handler | [chat-run](prd/chat-run.md) | CR-3 … CR-29 | 27 |
| U4 REST route, non-streamed | [chat-completion](prd/chat-completion.md) | CC-1 … CC-48 | 48 |
| U5 streamed response | [streaming](prd/streaming.md) | ST-1 … ST-9, ST-11 … ST-13 | 12 |
| U6 final-step endpoint and tools | [tool-calls](prd/tool-calls.md), [streaming](prd/streaming.md) | TC-9 … TC-28, TC-30, TC-35, TC-36, ST-10 | 24 |
| U7 docs | [docs](prd/docs.md) | DOC-1, DOC-2 | 2 |
| **Total** | | | **136** |

The build is one pull request `[stated ans:Q22]`. Each unit is one commit or more in this order,
so the move of U1 can be read alone.

## 4. Constraints of the owner and the tests that pin them

| Constraint | Test |
|---|---|
| Same authentication as today (ans:Q2) | CC-1, CC-2 |
| A dedicated path that does not adapt the existing endpoint (ans:Q6) | CR-7, GT-1, GT-2, GT-7, TC-10 |
| Each ensemble runs as built (ans:Q8) | CR-7, CR-8, CR-28, TC-14, TC-15 |
| The last model step decides tool calls (ans:Q8) | TC-14, TC-16 |
| No reducer at the final step with tools (ans:Q9) | TC-2, TC-3, TC-33 |
| Abstain is an empty answer with a status; fail is an HTTP error (ans:Q10) | CR-10, CR-11, CC-13, CC-14 |
| The transport is moved, not copied (ans:Q11) | GT-6 |
| `usage` is the whole ensemble sum (ans:Q13); a cached call counts 0 (ans:Q26) | CR-9, CR-18, CC-12, CC-45 |
| Sampling fields are ignored (ans:Q14) | CC-15, TC-9 |
| Cache on by default (ans:Q15) | CC-20 |
| Web search follows the model route (ans:Q30) | CR-22, TC-22 |
| `model` is a URL4 or a model id (ans:Q16) | CC-5, CC-6, CC-7, CC-40 |
| The input is deleted when the request ends (ans:Q17) | CC-19, CC-39, CC-41, CR-26, ST-8 |
| A Cascade with tools is refused; `cascade >> model` runs as built (ans:Q18, ans:Q27) | TC-33, TC-36 |

## 5. What is not tested here

- Live providers and real agents. A manual check with pi and opencode against a local stack is a
  step of the plan, not a gate.
- Load. The capacity numbers in the PRDs are targets to measure on kind before the hosted
  release.
