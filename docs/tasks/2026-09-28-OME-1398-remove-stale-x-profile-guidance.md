---
id: OME-1398
linear_url: https://linear.app/openmined/issue/OME-1398/aigateway-uidocs-remove-stale-x-profile-selection-guidance
status: completed
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-09-28
closed: 2026-10-01
---

# OME-1398 — Remove stale X-Profile selection guidance

## Outcome

Align the Admin UI, generated AIGateway types and gateway identity diagrams with the active Stage D
contract: requests do not select a credential by profile name, every nonblank `X-Profile` is refused,
and selector-less requests resolve the account/provider pair's effective credential or return 409
when the pair is ambiguous.

## Scope

- Regenerate the committed declaration from the already-correct local provider-access OpenAPI.
- Replace the Admin UI hint that instructs operators to select a credential through `X-Profile`.
- Regenerate the committed AIGateway schema declaration from the corrected local OpenAPI.
- Update the Markdown and Mermaid gateway identity flow and its rendered assets.

## Out Of Scope

- D18 pair-addressed admin successor routes or Admin UI CRUD migration.
- Engine/URL4 selector-carrier cleanup.
- Stage E Profile route, runtime or storage retirement.

## Implementation Status

Merged in PR #1210 as `57e78d71a9582b238ac4fe7cf0f682cb012c06a2`. The form keeps the
legacy `default` name required by the current admin route but no longer presents it as a request
selector. The generated schema says nonblank `X-Profile` is rejected, and the identity flow shows
selector-less pair resolution with explicit 409 ambiguity.
