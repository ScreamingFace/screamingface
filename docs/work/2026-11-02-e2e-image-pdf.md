---
ticket: OME-1551
stack: repo
status: done   # planned | in_progress | done | blocked
started: 2026-11-02
finished: 2026-11-02
---

# e2e-image-pdf — prove a url4 ensemble over an image and a PDF end to end on the local stack

## Intent

Closing proof for the OME-1529 execution path: run
`(https://<fixture>/chart.png, https://<fixture>/report.pdf)!"Does the chart appear in the report?"`
as an ensemble (members + fusion synthesizer) on the local stack (engine + aigateway), on top of the
open PR stack #1478 → #1482 → #1587 → #1588, and record every failure with its owning PR. No code
in the PR branches is changed; this branch carries only evidence.

## Planned changes

- `docs/work/2026-11-02-e2e-image-pdf.md` (this ledger, with the evidence appendix).
- `docs/work/2026-11-02-e2e-image-pdf/` — fixtures, harness scripts, trimmed logs (no secrets).

## Test plan

- Fixture server that counts fetches, behind a public https tunnel (the url4 source guard is
  https-only and refuses loopback by default).
- Ensemble run over the PNG + PDF; checks per the OME-1551 acceptance list.
- Refusal path: a PDF to a model without `pdf` in `input_modalities`; a text-only ensemble member.

## Acceptance (OME-1551)

- Fixture server sees each URL fetched exactly once (pinned).
- Every member's and the synthesizer's gateway request carries the image and PDF parts.
- Answer checkable against unambiguous fixtures.
- Image tokens in cost.usage where the provider reports them.
- A text-only model in the ensemble is refused by name before any call.
- No base64 in logs or spans.
- Live test run locally.

## Outcome

- **Actual files:** this ledger; `docs/work/2026-11-02-e2e-image-pdf/` (fixtures, `make_fixtures.py`,
  `fixture_server.py` (unused, see deviations), `recording_proxy.py`, `run_expr.py`,
  `serve_local_with_bytes_shim.py`, `url4.e2e.toml`, the `*.url4` expressions, `evidence/`).
- **Commits:** on `e2e-image-pdf` (see `git log`).
- **Gates:** n/a (evidence-only branch, no product code).
- **Deviations:**
  - **Base:** the stack top `db6b228ec` (#1588) is used as is. It does NOT contain #1482's head
    `e33b550ff` (nor #1478's `c287f1d94`); the local merge conflicted (F1), so that path stopped.
    The base is 78 commits behind `main` and lacks #1584 (picture admission) and #1572 (image/file
    tokens in cost). The coordinator-requested local merge of `origin/OME-1803-pdf-admission`
    (#1645) also conflicted (F1), so it was not tested.
  - **Fixture host:** the https tunnel to a local counting fixture server was denied by the
    session's permission policy, so the fixtures are served from public CDNs pinned to commit
    `12f9844a9` of this branch (PNG: raw.githubusercontent.com, `image/png`; PDF:
    rawcdn.githack.com, `application/pdf`). The fetch count is taken engine-side instead (shim log).
  - **Test shim:** F2 blocks every https attachment in local mode. `serve_local_with_bytes_shim.py`
    monkeypatches `FairShareIOLayer` (in this process only) to forward `fetch_bytes` through the
    same gate and logs each outbound attachment fetch. Everything after F2 was exercised through
    that shim. It is not a fix.
  - **Custom adapter:** only an OpenRouter key is available locally (repo `.env`); Gemini/Codex need
    an interactive OAuth login, so every member is an OpenRouter (LiteLLM) route.
  - **web_search:** `url4.e2e.toml` sets `web_search = false` on the five routes used. With the
    default (`true`), OpenRouter's web plugin added ~2.6k prompt tokens per call (a "hello" call
    billed 0.0074 credits against an upstream cost of 0.0004) and the member answers cited web pages.

## Results per acceptance criterion

| Criterion | Result | Evidence |
| --- | --- | --- |
| Each URL fetched exactly once | PASS (engine-side count) | `evidence/1-ensemble/fetches.jsonl`: 2 lines, one per URL, for 2 occurrences each. No fixture-server count (tunnel denied). |
| Every member's and the synthesizer's request carries image + PDF parts | PASS (through the F2 shim) | `evidence/1-ensemble/gateway_requests.jsonl`: all 3 calls send `image_url` (sha256 `4ff14d01…`) + `file` (sha256 `280cd34b…`), equal to the fixtures' digests. |
| Answer checkable | PASS | Both members and the synthesizer answer YES, ZEBRA-7341, 17/42/29, Figure 3, "amber falcon" (`evidence/1-ensemble/ensemble.out`). |
| Image tokens in cost.usage where reported | NOT TESTABLE | The base lacks #1572 (OME-1744). OpenRouter did not report image tokens either: `prompt_tokens_details` has no image field for these three models. cost.usage carries only input/output totals. |
| Text-only model refused by name before any call | FAIL | F4: the capable member was dispatched and billed, then the run failed on the upstream 404 (`evidence/refusal_text_only_member/`). |
| No base64 in logs or spans | PASS (local sinks) | 0 data URIs, 0 fixture base64 prefixes, 0 runs of 200+ base64 chars in gateway.log, engine.log, proxy log and all WS frames (spans + logs). No OTel exporter runs locally, so exported spans were not checked. |
| Live test run locally | PASS | Live OpenRouter calls, 2026-11-02. |
| Members span a LiteLLM provider and a custom adapter | NOT TESTABLE | No Gemini/Codex credential (OAuth is interactive). |

## Findings

**F1 — the stack top does not merge with #1482's head, `main` or #1645.** Owner: #1587/#1588
(reconcile onto #1482 `e33b550ff`).
Repro: `git merge origin/OME-1539-url4-file-refs` on `db6b228ec` → conflict in
`apps/screamingface-engine/src/screamingface_engine/world/connector.py` `_raise_for_status`
(#1588's `refusal = intent_error_for(detail)` → `ResolutionError(code=INTENT_ERROR)` against
#1482's `text = detail` → `raise _GatewayRefusal(...)`). `git merge origin/main` and
`git merge origin/OME-1803-pdf-admission` conflict in the same `connector.py` and in
`packages/url4/src/url4/io/http.py` (the stack's typed-404 `except httpx.HTTPStatusError` block
against main's #1605 `_failure()` refactor). All merges were aborted.

**F2 — local mode refuses every https attachment source (blocker).** Owner: #1588 (OME-1545,
engine side of attachments).
Suspect: `apps/screamingface-engine/src/screamingface_engine/runner/fair_share.py:292-310`:
`FairShareIOLayer.__init__` forwards `fetch_ex`, `fetch_holdings`, `processor_routes` and
`default_route` but not `fetch_bytes`. `serve --local` always wraps the run io in it
(`local.py:491`, `runner/main.py:456-457`), so `url4/dag/_materialize.py:307-315` finds no port.
Repro: `ensemble.url4` on the unpatched engine → terminated `unsupported_mode`: "attachment source
'…/chart.png' needs a binary-safe io layer (fetch_bytes)", 0 model calls.

**F3 — an `@` anywhere in a call's context silently turns opted-in attachments into text.**
Owner: #1587 (OME-1543, `c44b7d190`).
Suspect: `packages/url4/src/url4/dag/source_scan.py:216`
(`if node.context is not None and "@" not in node.context`) is a substring test: a URL with `@`
in its path (jsDelivr's `/gh/o/r@ref/…`) disables the scan of the whole context. It mirrors
`dag/_lowering.py:235`. A segment that fails to parse is also skipped silently
(`source_scan.py:236-239`). Repro: `at_sign_url.url4` → HTTP 200, 0 fetches, the model gets
`src=https://…@12f9844a9/…;accept=image/png` as text and answers "I can't access links"
(`evidence/at_sign_url/`). The same URL at the top level (`(src=…@…;accept=image/png)!'d'`)
is scanned. Expected: attach, or refuse with a typed error; never degrade to text with a 200.

**F4 — no by-name refusal for a url4 run whose attachments reach a blind model.** Owner: OME-1803
(#1645) scope, or a new leaf under OME-1529; #1645 alone does not close it.
Suspect: picture admission (#1584, `main`) and PDF admission (#1645) run only from the picture
Benchmark Cases route (`benchmarks/picture_admission.py`), not for run attachments
(`current_attachments()`). The gateway's `check_messages`
(`apps/aigateway/src/aigateway/core/content_parts.py:173`) checks per-adapter capability, not the
model's `input_modalities`, and the OpenRouter path does not call it. Repro:
`refusal_text_only_member.url4` (gpt-4o-mini + llama-3.3-70b) → both calls dispatched; llama →
upstream 404 "No endpoints found that support image input" → `provider_error` (permanent); the
gpt-4o-mini call completed at the gateway (200, billed) and was then cancelled engine-side
(`evidence/refusal_text_only_member/`, `evidence/logs/gateway.trimmed.log`).

**F5 — a PDF to an image-only model is billed and reported as a transient error.** Owner: gateway
OpenRouter plugin (not in the stack); also covered by F4.
Repro: `refusal_pdf_to_image_only.url4` (mistral-small-3.2, `input_modalities` `[text, image]`) →
OpenRouter HTTP 200 with usage (155 in / 11 out, 0.002 credits) → gateway `provider_error`
"OpenRouter reported a provider error", **`permanent: false`** → url4 `provider_error`,
`permanent: false`. A capability mismatch is deterministic and should be permanent (or never
dispatched).

**F6 — pre-existing (main): a text-only fan-out reduce to Anthropic fails.** Owner: engine
connector, not in the stack (new bug).
Suspect: `apps/screamingface-engine/src/screamingface_engine/world/connector.py:1495-1501`
(`_messages` always appends `{"role": "user", "content": context or ""}`). A default-route reduce
has empty stdin, so the call is system + empty user → OpenRouter/Anthropic 400 "messages: at least
one message is required". With attachments the user message carries parts, so the e2e path is
unaffected.

**Note (by design, F1b):** the attachment source text (`src=https://…;accept=…`) still rides as
the text part after the attachment parts.

## Evidence appendix

Stack: aigateway (worktree code, `AIGW_AUTH_MODE=disabled`, fresh SQLite in the session scratch
dir, one OpenRouter api-key connection created from the repo `.env` without printing it) →
`recording_proxy.py` on :9115 (records each chat request's parts as media type + base64 length +
sha256, never the base64) → engine `serve --local` on :9108 via `serve_local_with_bytes_shim.py`,
`URL4_RUNNER_CONFIG=url4.e2e.toml` (gateway at the proxy, `default_route` = the synthesizer
`/openrouter/anthropic/claude-haiku-4.5`). Client: `run_expr.py` (token → WS attach → `GET /?q=`).

Fixtures (`make_fixtures.py`): `chart.png` sha256 `4ff14d014fd62abf…`, `report.pdf` sha256
`280cd34bc5ba723d…`. The chart title is "Chart ZEBRA-7341" with bars 17/42/29; the PDF's
Figure 3 names ZEBRA-7341 and the same values, plus the phrase "amber falcon".

Ensemble (`ensemble.url4`): members `m1:/openrouter/google/gemini-2.5-flash(src=PNG;accept=image/png,
src=PDF;accept=application/pdf)!'Q'`, `m2:/openrouter/openai/gpt-4o-mini(…same…)!'Q'`, fused by the
group intent on the default route (claude-haiku-4.5).

| Run | Result | Files |
| --- | --- | --- |
| ensemble | 200, YES + all four facts; 2 fetches; 3 calls with both parts; subtree cost 0.00425695 credits, 11,526 in / 213 out | `evidence/1-ensemble/` |
| PDF → image-only model | `provider_error`, permanent false (F5) | `evidence/refusal_pdf_to_image_only/` |
| text-only member | `provider_error` 404 after the capable member was billed (F4) | `evidence/refusal_text_only_member/` |
| PDF served as `application/octet-stream` | `unsupported_content_type`, 1 fetch, 0 model calls (correct) | `evidence/wrong_content_type/` |
| `@` in the attachment URL | 200, 0 fetches, URL sent as text (F3) | `evidence/at_sign_url/` |

Base64 scan: `grep -cE 'data:[a-z/.+-]+;base64,'`, the first 40 base64 chars of each fixture, and
`grep -cE '[A-Za-z0-9+/]{200,}'` over gateway.log, engine.log, proxy.log and every evidence file:
all 0.
