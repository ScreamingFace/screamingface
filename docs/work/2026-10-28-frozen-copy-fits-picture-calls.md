---
ticket: OME-1756
stack: aigateway
status: done
started: 2026-10-28
finished: 2026-10-28
---

# frozen-copy-fits-picture-calls — a capture run records every call the gateway accepts

## Intent

A capture run records each model call into the AI Gateway's frozen copy, so the run can be
replayed later without calling a model. The gateway accepts a request of up to 8 MiB
(`max_request_bytes`), but one frozen-copy entry was capped at 2,000,000 B. Picture Cases carry
their pictures inline (MMMU: 17 of 847 multiple-choice Cases over 2,000,000 B; LAB-Bench FigQA and
TableQA too), so their calls were answered but never recorded, and a replay failed with
`frozen_copy_miss`. The entry cap now follows the request cap plus room for the recorded response.

## What one entry stores (measured from the code)

- Chat lane: the request body after the `cache` control is popped, plus the response body the
  caller received. Both are re-serialised as compact JSON with `ensure_ascii=False`, so a base64
  data URI counts once, byte for byte: no second base64 and no extra escaping (base64 has no
  character JSON escapes). The request is never larger than the wire body, except for rewritten
  floats: Python writes `1e9` as `1000000000.0` (+9 B) and `1E2` as `100.0` (+2 B). A chat body
  carries a handful of numbers (`temperature`, `top_p`, `max_tokens`), so that adds bytes. Only a
  crafted body of about 230,000 exponent literals (2 MiB / 9 B) could use up the headroom, and
  then only its capture fails, never the call.
- Tool lane: description plus `{"result": ...}`, both from ONE request body, so it is already
  under `max_request_bytes`.
- Storage: `request_json` / `response_json` are Tortoise `JSONField`s (TEXT on SQLite, JSONB on
  Postgres, which holds values far above 10 MiB). No schema change and no migration.
- The Helm chart does not set either variable; no chart or env doc states the entry cap.

## Planned changes

- `apps/aigateway/src/aigateway/config.py`: `FROZEN_COPY_RESPONSE_HEADROOM_BYTES = 2 MiB`;
  `frozen_copy_max_entry_bytes` defaults to `max_request_bytes + FROZEN_COPY_RESPONSE_HEADROOM_BYTES`
  (a `default_factory` over the validated request cap, so an operator who raises the request cap
  raises the entry cap with it). An explicit `AIGW_FROZEN_COPY_MAX_ENTRY_BYTES` still wins.
- `apps/aigateway/pyproject.toml` + `uv.lock`: pydantic floor `>=2.10` (the first release whose
  `default_factory` receives the validated fields).
- `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` F3: the default.
- New test file `apps/aigateway/tests/unit/test_frozen_copy_entry_cap.py`.

## Test plan

- The default entry cap is the request cap plus the response headroom, and above the request cap
  (fails if the default is lowered back to a fixed number).
- Raising `AIGW_MAX_REQUEST_BYTES` raises the entry cap with it; an explicit entry cap wins.
- Store: an entry whose request is just under the request cap, plus a response, is captured and
  read back unchanged; one byte over the derived cap is refused.
- Route: a picture chat call just under the request cap is answered, stored (`X-AIGW-Capture:
  stored`) and replays with the same answer.
- The existing refusal tests (`test_frozen_copy_capture.py` size-cap section) are unchanged and
  still run with their explicit small caps.

## Acceptance

- Every call the gateway accepts in a capture run fits one entry under the default settings.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `docs/tasks/2026-10-28-OME-1756-frozen-copy-fits-picture-calls.md`.
- **Commits:** `fix(aigateway): size the frozen-copy entry cap from the request cap (OME-1756)`.
- **Gates:** only the touched lanes. `test_frozen_copy_entry_cap.py` (6), the five other
  `test_frozen_copy_*.py` files and `test_body_cap_route.py`: 156 passed. The Engine's
  `test_picture_case_limits_fit_the_gateway.py` (reads `config.py` source with `ast`): 1 passed.
  ruff check + ruff format + pyright on `config.py` and the new test: clean. Mutation: with the old
  fixed `default=2_000_000`, 4 of the 6 new tests fail, the route test with the live symptom
  (`X-AIGW-Capture: failed`, `FrozenCopyEntryTooLarge` in the log).
- **Deviations:** pydantic floor raised to `>=2.10` (the release whose `default_factory` receives
  the validated fields); the lock already resolved 2.13.5, so only the specifier line moved.
  No prior test was edited.
- **Owner-verify:** after deploy, a capture run over MMMU multiple-choice should report every Case
  `stored` (none `failed`), and its replay should have no `frozen_copy_miss`. Not run here (paid).
  Frozen copies captured before this change keep their gaps: the oversized picture Cases were
  never stored, a sealed copy accepts no insert, and nothing re-captures them. A submission whose
  copy predates the deploy must be captured again to replay those Cases.
