# OME-1394 — AIGateway rejects explicit X-Profile

## Outcome

Activate the accepted Stage D AIGateway selector sunset after Engine producer-off: selector-less
requests retain their behavior, while every explicit `X-Profile` is rejected without disclosing its
value.

## Scope

- Chat completions, model parameters, model admission, and provider-access availability.
- Value-free `x_profile_unsupported` HTTP 400 rendering.
- Selector-free `connection_ambiguous` guidance.
- Retire `X-Profile` from response `Vary` where it no longer selects behavior.

## Gate

Offline implementation and verification may proceed. Merge and deployment activation remain
blocked on the approved quick alpha drain proof after Engine build `df6e9b92`.

## Implementation Status

Ready for implementation review. The Stage D route suite passes, all approved legacy-contract
tests were re-pinned without skips or deletions, and the complete AIGateway gate runner is green.
No deployment or production access was performed.

## Out Of Scope

- Production/deployment access and the drain proof itself.
- URL4, Engine, SDK, D18, Stage E, schemas, migrations, and dependencies.
