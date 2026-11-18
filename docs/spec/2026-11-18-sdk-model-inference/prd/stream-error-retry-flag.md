# PRD — Engine: a retry flag in the stream error event, and one reply shape

Tags as in `00-overview.md` §2. This is a change to the route of PR #1937, in
`apps/screamingface-engine`.

## 1. User story

As a client that reads the stream, I know from the error event if a retry is safe, as I know it
from the `x-should-retry` header of a plain answer `[stated ans:Q5]`.

## 2. Current behaviour

- A failure after the stream started is one event, `data: {"error": {"message", "type", "code"}}`,
  with no retry hint `[existing E/chat/sse.py:44]` `[existing E/rest/chat_stream.py:104]`.
- For the same failure, the plain route sends `x-should-retry` and, for some codes,
  `Retry-After` `[existing E/rest/chat_answer.py:62]`.
- The Engine already holds the retry flag and the seconds for each failure
  `[existing E/rest/chat_errors.py:66]`; the stream does not send them.
- A reply with tool calls and no text has `"content": ""` on the plain route and no `content` key
  in the stream `[existing E/rest/chat_answer.py:178]` `[existing E/chat/sse.py:101]`.
- One code can have two answers: `run_failed` is retryable for a killed worker and not retryable
  for a memory budget `[existing E/rest/chat_answer.py:66]`. So a client cannot derive the flag
  from the code.

## 3. Scenarios

**SE-S1 A retryable failure.** `[proposed P10]`
- Given a streamed request whose run ends with `worker_draining`
- Then the error event has `"should_retry": true` and `"retry_after": 5`.

**SE-S2 A failure that is not retryable.** For `timeout` (504) the event has
`"should_retry": false` and no `retry_after`.

**SE-S3 The drain of the App.** The event `server_restarting` has `"should_retry": true` and
`"retry_after": 5`.

**SE-S4 Same values as the plain route.** For each terminal case of the answer table, the flag
and the seconds of the event are equal to the header values of the plain answer
`[proposed P10]`. One function gives both.

**SE-S5 An unexpected error after the start.** The event `internal_error` has
`"should_retry": false`.

**SE-S6 Old clients.** The three keys of today stay; the new keys are added. An OpenAI client
that reads the event ignores them `[implied]`.

**SE-S7 One shape for a tool-call reply with no text.** `[proposed P13]`
- Given a run whose result has tool calls and no text
- Then the plain reply has `"content": null`, as OpenAI sends it
- And a reply with text, a refusal, or no tool call does not change.

## 4. Out of scope

Each other change of the plain route; a new HTTP header on the stream; a change of the chunk
frames.

## 5. TDD plan

| # | Test | Level | Scenario | Risk | Note |
|---|---|---|---|---|---|
| SE-1 | `stream_error_event_has_the_retry_values_of_the_plain_answer` (each terminal case, table) | unit | SE-S4 | H×M | RED: the event has no flag |
| SE-2 | `drain_event_is_retryable_with_retry_after` | unit | SE-S3 | M×M | extends the drain test of the stream |
| SE-3 | `unexpected_error_event_is_not_retryable` | unit | SE-S5 | L×M | |
| SE-4 | `error_event_keeps_message_type_code` | unit | SE-S6 | L×M | |
| SE-5 | `reply_built_from_the_frames_equals_the_plain_reply` (text, refusal, tool calls with text, tool calls with no text, abstained, no cost record) | unit | contracts C2.3 | H×H | a small reference builder in the test; compares `choices`, `usage` and `screamingface`; RED today for tool calls with no text (risk R4) |
| SE-7 | `plain_reply_with_tool_calls_and_no_text_has_null_content` | unit | SE-S7 | M×M | RED: the reply has `""` |
| SE-6 | docs page: the stream section names `should_retry` (DOC-2 list) | unit | — | L×L | |

The tests of the stream in the branch of PR #1937 are not on `main`, so a change to them is
not a change to a prior test of `main`. The approval record of PR #1937 does not change.

## 6. Open questions

None.
