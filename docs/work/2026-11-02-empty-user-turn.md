---
ticket: OME-1808
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# empty-user-turn — never send an empty user turn

## Intent

`_messages` in `world/connector.py` always appended `{"role": "user", "content": context or ""}`.
A default-route reduce with no attachments has an empty context, and its intent carries the
members' answers plus the fusion prompt, so the call was `system=<intent>` + `user=""`. Anthropic
(via OpenRouter) drops the empty turn, lifts the system message out, and answers 400 "messages:
at least one message is required" (OME-1551 e2e, branch `e2e-image-pdf`, ledger F6). Other
providers tolerate the empty turn.

Mapping: when the context is empty (`None` or `""`) and an intent exists, the intent travels as
the one user turn and no system message is sent. Leaving the user turn out is not an option:
Anthropic's 400 is exactly "no messages" once the system message is lifted out. A non-empty
context, and every candidate-input envelope, sends byte-identical messages to before.

Cache and identity: `request_identity.model_request_key` hashes `(path, params, context, intent)`,
not the messages, so no request key changes. The aigateway response cache keys on the chat body,
so only the empty-context calls (which already failed on Anthropic) get a new gateway key.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/connector.py` — `_messages`.
- `apps/screamingface-engine/tests/unit/test_empty_user_turn.py` — new tests.

## Test plan

- Empty context (`""`, `None`) with an intent → exactly `[{"role": "user", "content": intent}]`.
- Through the connector handler: the gateway receives one non-empty user message.
- Non-empty context → `[system intent, user context]`, byte-identical to before.
- A candidate-input envelope with a picture → system + native messages, unchanged.
- No intent and no context → unchanged (`[user ""]`): nothing exists to carry; out of scope.

## Acceptance

- No call with an intent sends an empty user turn; every other message list is unchanged.
- `run_gates.py screamingface-engine --base origin/main` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `world/connector.py` (`_messages` early return for an empty
  context with an intent) and the new `tests/unit/test_empty_user_turn.py` (7 tests: RED 3 failing
  before the fix, all 7 green after).
- **Commits:** this commit — `fix(screamingface-engine): never send an empty user turn`.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN (append-only,
  ruff, ruff format, pyright, layering, pytest + coverage).
- **Deviations:** none. Not covered: a whitespace-only context still goes out as written (a
  non-empty context keeps today's bytes by rule); no intent and no context still sends `user=""`.
