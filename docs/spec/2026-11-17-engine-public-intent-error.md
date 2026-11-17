# Engine — report `intent_error` on the synchronous url4 answer

Status: draft for owner review · 2026-11-17 · follows OME-941 (`_sanitized_error`) and the
image-input matrix proof (`2026-11-17-e2e-image-input-matrix.md`).

## 1. Problem

A url4 run that the gateway refuses (for example an image sent to a text-only model) ends with
`intent_error`, permanent, after zero provider calls. The synchronous `GET /?q=` answer reports it
as `502 internal_error`: `rest/routes.py::_sanitized_error` scrubs every code outside
`ENGINE_ERROR_CODES` and `CONTROL_PLANE_TERMINAL_CODES`. A caller cannot tell "this model can't
read your file" from an Engine crash. Seen live on 2026-11-17 (image-input matrix, mistral control)
and noted earlier in the OME-1809 ledger.

`intent_error` cannot join `ENGINE_ERROR_CODES`: `world/connector.py` mints it from the gateway's
422 body (`intent_error_for(detail)`), so its message is upstream text, and reserving the code
would forbid exactly that mapping.

## 2. Decision (owner, 2026-11-17)

**Code only.** A new set `PUBLIC_UNVOUCHED_CODES = {"intent_error"}` in `error_text.py`:

- the code is reported as itself; the message is withheld (the fixed table detail is used), like
  `CONTROL_PLANE_TERMINAL_CODES`;
- it is **not** part of `ENGINE_RESERVED_CODES`: an upstream may still produce it, and it vouches
  for nothing;
- disjoint from both existing sets ("a code has one policy, not two").

## 3. Shape

- `error_text.py`: the set, its WHY docstring, exported.
- `rest/routes.py::_sanitized_error`: `code = error.code if error.code in
  (CONTROL_PLANE_TERMINAL_CODES | PUBLIC_UNVOUCHED_CODES) else _SCRUBBED_CODE`; docstring updated.
- HTTP status stays 502 and `permanent` passes through unchanged (already public).

## 4. Out of scope

- A 4xx status for refusals; showing the refusal reason text.
- The benchmark result contract (it already reports run-level `intent_error` via admission).
- OME-1809 (#1853), which adds url4 admission and raises the same code; this change covers it.

## 5. Landing

`app/screamingface-engine`, one leaf under epic OME-1529 (image input), filed at PR-open.
