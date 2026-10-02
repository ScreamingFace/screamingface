---
id: OME-1050
linear_url: https://linear.app/openmined/issue/OME-1050/redact-prompt-bearing-records-at-the-runtime-log-sink
status: in_review
type: bug
priority: medium
labels: [client-sf, agentic, autonomous]
created: 2026-08-31
---

# Redact prompt-bearing records at the runtime log sink

Follow-up to OME-990. Owner decision on 2026-10-01: option A. The fix covers three structural
carriers only:

- url4 `q=` query values;
- litellm's `Messages:` exception suffix;
- litellm's debug curl `-d` body.

These are redacted at two points: a wrapping log-record factory, and every line `RuntimeLog`
writes. In addition, `litellm.redact_messages_in_exceptions = True` is pinned and
`LITELLM_LOG` is forced to `WARNING`. Unmarked free text is out of scope.

- 2026-10-01: first pass blocked on a spec contradiction, because the factory cannot see
  `print`, warnings or tracebacks. The owner chose option A. Implemented on branch
  `bershadsky/ome-1050-redact-prompt-bearing-records-at-the-runtime-log-sink`; ledger
  `docs/work/2026-10-01-runtime-log-sink-redaction.md`. PR opened, In Review.
