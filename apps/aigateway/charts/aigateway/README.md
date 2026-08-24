# aigateway

Helm chart for ScreamingFace AI Gateway.

Install the demo database chart first, then install this app chart:

```bash
helm install aigw-db apps/aigateway/charts/db \
  --namespace aigw \
  --create-namespace \
  --wait \
  --values apps/aigateway/charts/db-aigateway.values.yaml
helm install aigw apps/aigateway/charts/aigateway --namespace aigw --wait
```

The app chart is database-agnostic. It consumes `AIGATEWAY_DATABASE_URL` from `database.existingSecret`, which defaults to the `aigw-db` Secret created by `charts/db`.

## Public URL

Set `publicUrl` to the externally reachable gateway origin when using hosted OAuth callbacks:

```bash
helm upgrade --install aigw apps/aigateway/charts/aigateway \
  --namespace aigw \
  --set publicUrl=https://aigateway.example.com \
  --set "ingress.hosts[0].host=aigateway.example.com" \
  --set "ingress.hosts[0].paths[0].path=/" \
  --set "ingress.hosts[0].paths[0].pathType=Prefix"
```

Quote indexed `--set` keys in shells such as zsh. If you override a list item, set the full `host` and `paths` structure.

For temporary k3s smoke tests without real DNS, a host such as `aigateway.40.76.107.241.nip.io` resolves to `40.76.107.241` and works with host-based Ingress rules.

## The admin surface

`/v1/admin` — the tenant and API-key management the `aigateway-ui` console drives — is gated on an
allowlist of email addresses, checked against the `X-User-Email` the mesh injects. It is a **second**
gate: header identity establishes *who* a caller is, `config.adminEmails` establishes whether they
may administer.

**It ships empty, and empty is not a no-op.** With no entries the admin API answers `503 Admin API
is disabled` to everyone, so a stock install has the surface switched off rather than open. Turn it
on deliberately:

```bash
helm upgrade --install aigw apps/aigateway/charts/aigateway \
  --namespace aigw \
  --set-string 'config.adminEmails[0]=you@example.com' \
  --set-string 'config.adminEmails[1]=colleague@example.com'
```

Matching is case-insensitive. The list is *not* stored in a Secret — these are identities, not
credentials, and they appear in the ConfigMap by design so that who may administer is auditable
from the rendered manifest.

## The global response cache

`config.requestCache.enabled` turns on a response cache that is **global**: one row per exact
request, shared by every caller. Two callers who send the identical request get the identical stored
response, and the second one's provider credential is never touched. The chart ships `true`; set
`config.requestCache.enabled=false` to opt out.

**Hugging Face caveat.** Hugging Face participates only for ids pinned to a known partner provider
(`…:novita`, `…:groq`, …). Unsuffixed ids and the routing policies `:fastest` / `:cheapest` /
`:preferred` always dispatch, because the backend is chosen per request and `:preferred` follows the
requesting account's own preference order. For the ids that do cache, gated-repository responses
replay across accounts before any credential is resolved — see consequence 6 on
`config.requestCache` in `values.yaml`.

`true` makes the cache available immediately. Reading and writing the response row has no
secret-provider, encryption-key or canary dependency. Effective-key construction may still read the
caller's encrypted profile-default index; it never resolves the selected provider credential on a hit.

Three more things to know before enabling it anywhere else:

- **`config.authMode: disabled` removes the boundary entirely.** Every peer who can reach the port is
  the same anonymous principal, so the corpus is common to everyone with network access. The gateway
  does **not** refuse the cache for this — understand it before enabling the cache with auth off.
- **Responses are plaintext in the database.** The compact provider-response JSON is stored in
  `response_json`. Database readers, replicas, snapshots and backups can read the entire response
  corpus. Provider credentials remain encrypted separately.
- **Rows never expire.** There is no TTL and no eviction, so `request_cache_entries` grows with the
  number of distinct requests ever answered. Monitor it and prune deliberately.

Callers opt a single request out with `{"cache": {"use-cache": false}}`. Full runbook — including
destructive rollback and pruning queries:
`apps/aigateway/DEPLOYMENT.md`.

## Who may connect

`networkPolicy.clientPodNames` defaults to `url4-cloud`, `url4-runner` and `aigateway-ui`. In
`cloudflare_headers` mode that list is not hardening — it **is** the authentication boundary, which
is why the template refuses to render an ingress rule with no peers rather than emitting one that
admits everything.

`aigateway-ui` is the admin console. It is a Backend-for-Frontend, so it is the console's *Pod* that
connects here, not a browser. If you override this list and drop the entry, the console does not
degrade — it is denied at the CNI, and the symptom is a connect timeout in the console with nothing
in this gateway's logs, because the packet never arrives. Drop it only if you do not deploy the
console.

## Production

`values-prod.yaml` expects externally managed Secrets and production ingress settings:

```bash
helm template apps/aigateway/charts/aigateway \
  --values apps/aigateway/charts/aigateway/values-prod.yaml
```

Production database infrastructure should be managed separately, for example CloudNativePG or managed Postgres.

Published releases include the app chart in GHCR:

```bash
helm install aigw oci://ghcr.io/screamingface/screamingface/charts/aigateway \
  --version 0.2.0 \
  --namespace aigw
```
