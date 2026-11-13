---
id: OME-1834
linear_url: https://linear.app/openmined/issue/OME-1834/url4-pass-in-process-subrequests-to-the-endpoint-directly-without-url
status: done
type: improvement
priority: none
labels: [url4-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-05
closed: 2026-11-07
---

# url4: pass in-process subrequests to the endpoint directly, without URL encode/decode

An in-process url4 call hands its endpoint the structured request instead of percent-encoding the
context into a URL and decoding it back. Remote calls keep today's wire format. On the full
12,032-Case MMLU-Pro run, the peak RSS drops from 3,011 MiB to 1,426 MiB.

Spec: `docs/spec/2026-11-05-url4-inprocess-dispatch.md`. Ledger: `docs/work/2026-11-05-url4-inprocess-dispatch.md`.
