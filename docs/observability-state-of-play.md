# Debugging & Traceability — State of Play

> **What this is.** A team-facing brief on whether our traces and logs actually correlate,
> what we found when we checked, and what still needs a decision. Written to be readable by
> anyone on the team, including people who haven't touched the observability work.
>
> **As of 2026-08-25.** A snapshot, not a living spec. The detailed artifact — every claim
> with file-level evidence, the full roadmap, and the recorded decisions — is
> [`docs/spec/2026-08-22-observability-traceability-review.md`](spec/2026-08-22-observability-traceability-review.md).
> Where the two disagree, the spec wins.
>
> **Also pasteable as a Slack canvas.** The capability matrix below is deliberately a
> monospace block rather than a Markdown table, because Slack canvases don't render tables.
> Open problems raised here belong in [`ISSUES.md`](ISSUES.md); the work items are in Linear
> under epic `OME-935`.

## TL;DR

- We checked whether traces and logs actually correlate across our services. **They don't.** The chain is severed at the engine → aigateway boundary, and no log line in any service carries a trace id.
- This was an **empirical** audit, not a code read — we ran the real code paths and captured real output. It found several things a code reading got wrong in the optimistic direction.
- The fix is mostly cheap, and most of the plumbing already exists. One keystone item unblocks the rest.
- Two security defects turned up along the way. One has a one-line fix and should land before anything else.

## What we found

The engine's trace machinery is genuinely **correct inside one process** — one trace id per run tree, real parent edges, no crosstalk even under concurrent load. Credit where it's due.

It just never leaves that process:

- **Engine → aigateway carries no trace context.** During a run whose frames all carried the same trace id, the complete header set observed on the wire was `Host, Accept, Accept-Encoding, Connection, User-Agent, X-User-Email, X-Profile, Content-Length, Content-Type`. No `traceparent`.
- **aigateway never reads the header anyway.** Instrumenting the request object showed the entire chat path looks up exactly two headers: `Authorization` and `X-Profile`. There's no half-built ingestion to finish — there's nothing.
- **No log record anywhere carries a trace id.** The scoreboard emits *zero* application log lines at all; its log-level knob is inert by construction.
- **Run evidence is deleted 60 seconds after a run ends.** The Job pod goes at 120s. A failed deployed run is unreconstructable after roughly two minutes — so a bug report filed the next morning points at nothing.
- **A mapped provider failure returns a 500 and logs nothing.** Zero WARNING or ERROR records. Anyone alerting on WARNING+ sees silence while the gateway is failing.
- **A successful stream is entirely anonymous** — no id in logs, body, or headers.

## Decisions already locked

- **Backend: SigNoz**, self-hosted, behind Cloudflare Access.
- **Retention: 30 days, full bodies** in that gated sink.
- **Tracebacks: split posture** — full tracebacks on non-dispatch paths (auth, admin, DB, config), class-name-only on the dispatch path where provider text can leak.
- **Error reports go to private Linear only.** No public issues.

## Open — needs a call

1. **Rule 9** (`OME-976`). As written it forbids product code from calling Linear's API, which blocks the report-intake service. Either amend it explicitly, or fall back to an agent filing via MCP during triage (async, no ticket id back to the reporter).
2. **Anonymous vs authenticated reporting** (`OME-973`). This decides whether we take on an abuse surface at all. Note the stakes went up when we chose private Linear: spam now lands in the workspace we work in, not a public tracker we could moderate at arm's length.
3. **The `topic` invariant** (`OME-966`). It's documented across the engine as a bearer capability that must never be shared — and it's already published for every submitted score on an unauthenticated endpoint. Not exploitable today, but it becomes so the moment anything authorises on it. Fix client-side, scoreboard-side, or re-document.

## Fix these first

- **`OME-990` — `runtime.log` records user prompts in cleartext.** Runs start as `GET /?q=<url4 expression>`, the expression is prompt-bearing by construction, and uvicorn's access log is left on, writing the query string into a `0644` file. One-line fix (`access_log=False`). This must land *before* any "attach your logs" feature exists, or a local exposure becomes an exfiltration path.
- **`OME-967` — the client should mint the trace id.** Today it's minted inside the Runner Job and never returned, so every failure *before the first frame* (capability mint, run start, WS handshake) has no id at all and is unjoinable forever. The engine already accepts an inbound trace id, so this is client-side only. **It's the keystone — most other work is worth less without it.**
- **`OME-991` — the runtime owner token is passed on argv**, so it's visible in `ps`. Everywhere else that value is handled as a secret.

## What a report can actually carry today

Legend: `today` / `967` = needs OME-967 / `—` = not available.

```
                             Python     Studio     aigateway-ui   Portal
                           (Jupyter)                              (web)
  IDENTITY
  verified user email          —          —           today         —
  self-asserted author         —          —             —         today
  CORRELATION
  run id                      967     mock only         —           —
  trace id                    967         —             —           —
  server request id            —          —             —           —
  timestamp                  today      today         today       today
  ERROR FACTS
  error code / kind          today        —           today       today
  full traceback             today        —             —           —
  failing cell source        today        —             —           —
  WS close code              today        —             —           —
  ENVIRONMENT
  SDK / app version          today      today           —           —
  OS / python                today      coarse        today         —
  browser + frontend         widget       —           today       today
```

Two things to read off that:

- **Only aigateway-ui knows who its user is.** The Python client holds a Cloudflare Access token but parses exactly one claim from it — the expiry — so it has no email and nowhere to put one. It can send a rich, well-typed error report that **nobody can reply to**.
- **The biggest gap is correlation, not identity.** No client can produce a run or trace id when a failure surfaces. Today the only join key we have is *(endpoint, approximate timestamp)*.

## Also worth knowing

- **Studio is a click-through prototype**, not a client — no network code at all beyond the auto-updater. Every run, provider discovery and OAuth flow is a timer over fake data. Error reporting there is moot until a real transport is wired, though it *does* hold provider API keys locally, so it'll be our highest-sensitivity client the day it becomes real.
- **The scoreboard hands a caller another run's id** when content-hash dedup collapses two distinct runs (`OME-970`) — so any trace context in that metadata names the wrong execution.
- **Score submission metadata is unbounded** on the public write path (`OME-969`): a 64 KB blob returns 201.

## Where the work lives

- **Epic `OME-935`** — Phase 0, "make existing signals consumable". Eleven sub-issues, no new infrastructure, all independently shippable.
- **Phase 1** — one trace, end to end. Payoff: a single trace id greppable across every pod's logs, still with zero new infrastructure.
- **Phase 2** — SigNoz plus a frame-to-OTLP exporter. That exporter *is* the durable evidence store, which supersedes the design-only "Enclave" store we'd sketched.
- **Phase 3** — the report button and intake service, in parallel with Phase 2.
