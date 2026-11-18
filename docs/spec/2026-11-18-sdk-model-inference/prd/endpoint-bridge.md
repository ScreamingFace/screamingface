# PRD — `endpoint()`: the bridge to other libraries

Tags as in `00-overview.md` §2.

## 1. User story

As a user of the OpenAI SDK, LangChain or LiteLLM, I get the base URL, the model text and the
auth headers of my ensemble from the SDK, and I give them to my library
`[stated ans:Q1]` `[stated ans:Q2]`.

## 2. Current behaviour

- `Client.engine_url` is public `[existing S/client.py:169]`.
- The auth object of the client gives the auth headers, but only through private attributes, and
  only after a sign-in named the audience of the token `[existing S/_access/base.py:23]`
  `[existing S/_access/auth.py:338]`.
- The docs of PR #1937 tell a user to run an evaluation first and to extract the Candidate URL4
  from its report `[existing public-docs/src/pages/sf-client/guides/OpenAiApiPage.vue:154]`.

## 3. Scenarios

**EB-S1 The values.** `[proposed P7]`
- Given `llm = sf.ModelInference(ensemble)`
- When `e = llm.endpoint()`
- Then `e.base_url` is the Engine URL of the client with `/v1`; `e.model` is the Candidate URL4
  text (or the model id); `e.headers` has the auth headers that the client sends now.

**EB-S2 A local Engine.** `e.headers` is empty `[implied]`.

**EB-S3 A hosted Engine.** `endpoint()` calls `Client.login()` first. With a usable token (for
example from `SCREAMINGFACE_ACCESS_TOKEN`) that call returns at once; with none it does the
sign-in of the client. Then the headers have the token `[proposed P7]`
`[existing S/client.py:204]`.

**EB-S4 The token is not shown.** `repr(e)` and `str(e)` show the header names and hide each
value. The token is in no log line and in no error text `[proposed P7]`.

**EB-S5 A recipe with a reducer.** `endpoint()` loads the operator catalogue (as MI-S7).

**EB-S6 A token that expired.** The values are a snapshot. A later call of `endpoint()` gives new
headers. The docs say this next to the example `[proposed P7]`.

**EB-S7 Async.** With an `AsyncClient`, `endpoint()` returns an awaitable `[stated ans:Q7]`.

**EB-S8 Failure.** A sign-in that fails gives `AuthenticationError`; a catalogue that cannot load
gives the error of the loader. No partial value is returned.

## 4. Out of scope

An `openai` dependency of the SDK at run time; a ready client object; adapters for LangChain or LiteLLM; a refresh
callback for the token `[proposed]`.

## 5. TDD plan

| # | Test | Level | Scenario | Risk | Note |
|---|---|---|---|---|---|
| EB-1 | `endpoint_text_form_hides_header_values` | unit | EB-S4 | M×H | first: a credential must not leak |
| EB-2 | `endpoint_values_for_a_local_and_a_hosted_client` | unit | EB-S1, EB-S2, EB-S3 | M×M | a token from `SCREAMINGFACE_ACCESS_TOKEN`; the mock answers the discovery request of `login()` |
| EB-3 | `endpoint_values_work_with_a_plain_http_post` | unit | EB-S1 | M×M | a POST made only from the three values reaches the mock Engine with the right path, model and headers |
| EB-4 | `endpoint_loads_the_catalogue_for_a_reducer_recipe` | unit | EB-S5 | L×M | |
| EB-5 | `endpoint_is_awaitable_with_an_async_client` | unit (asyncio), typing | EB-S7 | L×M | |
| EB-6 | `endpoint_failure_gives_no_partial_value` | unit | EB-S8 | L×M | |
| EB-7 | `docs_example_with_the_openai_client_runs` | SDK docs test | EB-S1 | L×M | needs P16 (`openai==2.54.0` as a dev dependency); the snippet file of the docs page, with the mock Engine as the HTTP client of the OpenAI client. Without P16 this test is not written, and the docs page says that the example is not run |

## 6. Open questions

None.
