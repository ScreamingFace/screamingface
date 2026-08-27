# scoreboard

Helm chart for the ScreamingFace benchmark scoreboard.

Install the demo database chart first, then install this app chart:

```bash
helm upgrade --install scoreboard-db apps/scoreboard/charts/db \
  --namespace scoreboard \
  --create-namespace \
  --wait \
  --values apps/scoreboard/charts/db-scoreboard.values.yaml

helm upgrade --install scoreboard apps/scoreboard/charts/scoreboard \
  --namespace scoreboard \
  --wait
```

The app chart is database-agnostic. It consumes `SCOREBOARD_DATABASE_URL` from `database.existingSecret`, which defaults to the `scoreboard-db` Secret created by `charts/db`.

## Benchmarks

The post-install/post-upgrade seed Job runs `python -m scoreboard.seed`. Re-running the Job is safe because benchmark registration is idempotent.

Each benchmark's text — display name, description, focus line, dataset link — is read at deploy from the Engine named by `.Values.seedBenchmarks.engineUrl`, over its public `GET /v1/benchmarks` catalog. That Engine definition is the only place the text is written, so `revision` cannot drift from the Engine's computed value and a values override cannot blank the prose (OME-904). Set `engineUrl` per deployment; leaving it empty seeds only the configured entries.

`.Values.seedBenchmarks.benchmarks` is passed as JSON alongside it and is **empty by default** — the legacy demo entries it used to carry were retired in OME-986. Use it only for a benchmark the Engine does not publish, such as a local smoke target. An entry whose id the Engine also publishes is ignored, and the Job names it in its output.

Seeding never deletes: removing an entry stops it being recreated but leaves any existing row in place. Remove one with `python -m scoreboard.retire_benchmark --benchmark <id> --yes`.

Disable seeding with:

```bash
helm upgrade --install scoreboard apps/scoreboard/charts/scoreboard \
  --namespace scoreboard \
  --set seedBenchmarks.enabled=false
```

## CORS

Production CORS should include the portal origin:

```yaml
cors:
  origins:
    - https://screamingface.ai
```

## Production

`values-prod.yaml` expects externally managed Postgres through a Secret with a `database-url` key, three app replicas, nginx ingress, TLS, and NetworkPolicy enabled:

```bash
helm template scoreboard apps/scoreboard/charts/scoreboard \
  --values apps/scoreboard/charts/scoreboard/values-prod.yaml
```
