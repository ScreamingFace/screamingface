# OME-1195 — execution access in model details

Approved direction: minimal Gateway discovery extension for OME-1042 (owner conversation, 2026-09-14).

`GET /v1/model-parameters?model=...` gains `context.execution_access`, with values `configured` and `missing`. It refers to the same authenticated account and X-Profile as execution. A resolved profile/connection is configured; with neither, a provider supporting profileless execution is configured when its existing profileless auth selector reports a mode, or when it declares only no-auth execution. Otherwise access is missing.

This is configuration discovery, not credential validation: configured does not guarantee upstream acceptance, balance, reachability, or future access. Do not read/decrypt secrets, refresh tokens or make inference requests. Existing credential-target resolution errors (named missing target, pending/error profile, ambiguous connection) remain typed errors. Default credential-free datasheets continue to return 200 with missing access.

The new field is per-request context, outside parameter-contract identity: changing access does not itself change model parameter semantics. Existing private/no-store and Vary policy applies. Consumers must treat an absent field from older Gateways as unknown, never as missing.

Use the existing route and resolver; no new endpoint, provider-name switches or new dependency. Engine already relays the full response bytes and permits unknown fields; its existing proxy tests assert unchanged forwarding. No Engine implementation is needed (planned OME-1196 canceled). Client OME-1042 checks all required models before dispatch. This PR only implements Gateway OME-1195 under coordinating OME-1194.
