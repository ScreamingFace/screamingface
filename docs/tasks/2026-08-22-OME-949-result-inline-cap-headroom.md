---
id: OME-949
linear_url: https://linear.app/openmined/issue/OME-949/cut-runner-default-result-inline-cap-to-512-kib-for-nats-envelope
status: done
type: bug
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-22
closed:
---

# Cut runner default result inline cap to 512 KiB for NATS envelope headroom

Runs whose aggregated result lands in roughly (0.94 MiB, 1.00 MiB] fail deterministically at
the run's FINAL frame with `nats: maximum payload exceeded` — after every model call has
been paid for. The runner's inline gate compares the RAW result against a default cap that
equals the broker's 1 MiB `max_payload` default, but the published frame is the CloudEvent
envelope wrapping it (~+6% measured: a 619,026-byte result became a 657,732-byte frame), so
that window passes the gate and is then rejected by the broker at publish time.

Fix: `DEFAULT_RESULT_INLINE_CAP_BYTES` 1 MiB → 512 KiB — double the measured envelope cost
as margin. Results in (512 KiB, hard cap] spill to the artifact store; the SDK redeems
artifacts transparently, so no caller or protocol change.

Canonical artifacts:

- Ledger: `docs/work/2026-08-22-OME-949-result-inline-cap-headroom.md`
- Full diagnosis: `issue.md` (test branch, debug session 2026-08-22)
