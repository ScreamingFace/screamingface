# Scoreboard Deployment

This runbook deploys `apps/scoreboard` as a containerized FastAPI service on Kubernetes. The app chart is database-agnostic: it reads `SCOREBOARD_DATABASE_URL` from a Secret, runs Tortoise migrations as a Helm pre-install/pre-upgrade Job, and seeds configured benchmarks as a post-install/post-upgrade Job.

## Artifacts

- Container image: `ghcr.io/screamingface/screamingface-scoreboard:<version>`.
- App chart: `oci://ghcr.io/screamingface/screamingface/charts/scoreboard`.
- Demo database chart in this repo: `apps/scoreboard/charts/db`.

The demo database chart is a single `postgres:16-alpine` Deployment with a PVC. It is useful for k3s smoke tests and demos, but it has no HA, backups, PITR, or managed upgrade policy.

## Local k3s Smoke Image

Build an amd64 image for a single-node Linux k3s server:

```bash
docker buildx build \
  --platform linux/amd64 \
  -f apps/scoreboard/Dockerfile \
  -t ghcr.io/screamingface/screamingface-scoreboard:sf188-local \
  --load \
  .
```

Check the image size target from the SCORE-007 acceptance criteria:

```bash
SIZE_BYTES=$(docker image inspect ghcr.io/screamingface/screamingface-scoreboard:sf188-local --format '{{.Size}}')
test "$SIZE_BYTES" -lt 209715200
```

Import the local image into k3s containerd when you do not want to push a temporary tag:

```bash
docker save ghcr.io/screamingface/screamingface-scoreboard:sf188-local \
  | ssh adminuser@40.76.107.241 \
      "sudo k3s ctr -n k8s.io images import --platform linux/amd64 -"
```

Verify it is available to pods:

```bash
ssh adminuser@40.76.107.241 \
  "sudo k3s ctr -n k8s.io images ls | grep screamingface-scoreboard"
```

## Demo Database

Install the generic Postgres chart with the scoreboard values overlay:

```bash
helm upgrade --install scoreboard-db apps/scoreboard/charts/db \
  --namespace scoreboard \
  --create-namespace \
  --values apps/scoreboard/charts/db-scoreboard.values.yaml \
  --wait
```

The chart creates `Secret/scoreboard-db` with `username`, `password`, `database`, and `database-url`. The app chart consumes only the `database-url` key.

For production, replace this chart with managed Postgres or a Postgres operator. Create a Secret with a `database-url` key and point `database.existingSecret` at it.

## App Install

Use a real HTTPS hostname in production. For a temporary k3s smoke test, `nip.io` can map a hostname to an IP without creating DNS records. For example, `scoreboard.40.76.107.241.nip.io` resolves to `40.76.107.241` and works with Traefik host-based Ingress.

```bash
helm upgrade --install scoreboard apps/scoreboard/charts/scoreboard \
  --namespace scoreboard \
  --set image.tag=sf188-local \
  --set ingress.className=traefik \
  --set "ingress.hosts[0].host=scoreboard.40.76.107.241.nip.io" \
  --set "ingress.hosts[0].paths[0].path=/" \
  --set "ingress.hosts[0].paths[0].pathType=Prefix" \
  --set 'cors.origins[0]=*' \
  --wait
```

Quote indexed `--set` keys in shells such as zsh. If you override a list item, set the full `host` and `paths` structure.

## Production Install

For production, use managed Postgres and a Secret with a `database-url` key:

```bash
kubectl -n scoreboard create secret generic scoreboard-db \
  --from-literal=database-url='postgres://scoreboard:<password>@<host>:5432/scoreboard'

helm upgrade --install scoreboard oci://ghcr.io/screamingface/screamingface/charts/scoreboard \
  --version 0.1.0 \
  --namespace scoreboard \
  --values apps/scoreboard/charts/scoreboard/values-prod.yaml \
  --set database.existingSecret=scoreboard-db \
  --set database.existingSecretKey=database-url \
  --wait
```

`values-prod.yaml` sets three app replicas, Traefik ingress, TLS annotations, production CORS for `https://screamingface.ai`, and NetworkPolicy enabled. The chart also sets `FORWARDED_ALLOW_IPS="*"` so uvicorn honors Traefik's forwarded HTTPS scheme for redirects. Adjust `ingress.className` if the production cluster uses a different ingress controller.

Set `config.authMode: cloudflare_headers` (default: `disabled`) to require the mesh-verified `X-User-Email` identity header on `POST /v1/scores` instead of trusting the client-supplied `submitted_by` free text (OME-404, following OME-326). This is sound ONLY while the service is reachable exclusively through the chain that injects that header — set `config.allowedNetworks` (comma-separated CIDRs) to the peers permitted to present it:

```bash
helm upgrade scoreboard oci://ghcr.io/screamingface/screamingface/charts/scoreboard \
  --namespace scoreboard \
  --reuse-values \
  --set config.authMode=cloudflare_headers \
  --set config.allowedNetworks="10.0.0.0/8" \
  --set config.forwardedAllowIps="127.0.0.1" \
  --wait
```

Leaving `config.authMode` at its default (`disabled`) keeps today's behavior — the write path stays open, `submitted_by` is whatever the client sends. This is the current setting for `values-prod.yaml`'s Traefik-fronted, directly internet-exposed deployment: that ingress path does not run behind the Cloudflare Access + Envoy mesh, so `cloudflare_headers` mode would make `X-User-Email` trivially forgeable there — only enable it for a deployment actually sitting behind that mesh.

**`FORWARDED_ALLOW_IPS` must be *disjoint* from `allowedNetworks` — not merely non-`"*"`.** `values.yaml`'s default `config.forwardedAllowIps: "*"` (see above, needed for Traefik's HTTPS-redirect scheme) tells uvicorn's `ProxyHeadersMiddleware` to trust a client-supplied `X-Forwarded-For` from *any* peer, overwriting `request.client.host` — the same value `peer_in_networks()` reads to decide whether to trust `X-User-Email`. An earlier version of this doc recommended "fixing" that by scoping `forwardedAllowIps` to the real reverse proxy's address — **don't do that.** `ProxyHeadersMiddleware` overwrites `request.client.host` from `X-Forwarded-For` whenever the real peer falls inside `forwardedAllowIps`, *even a single narrow address*, not just `"*"`. If that address also falls inside `allowedNetworks`, the exact peers the check exists to authenticate are the ones it can no longer see correctly — the same bypass, just scoped smaller instead of eliminated. The mesh-fronted deployment has no Traefik-style hop that needs `ProxyHeadersMiddleware`'s trust at all, so the correct value here is uvicorn's own plain loopback default (`127.0.0.1`, as in the example above), not something scoped to the mesh's CIDR. `create_app` now refuses to start whenever `SCOREBOARD_AUTH_MODE=cloudflare_headers` and `FORWARDED_ALLOW_IPS` overlaps `SCOREBOARD_ALLOWED_NETWORKS` at all — not just the literal `"*"` case — so a misconfiguration here fails loudly at startup rather than silently reopening the bypass.

## Benchmark Seeding

The app chart runs `python -m scoreboard.seed` after install and upgrade. Seed data comes from `.Values.seedBenchmarks.benchmarks` and is passed through `SCOREBOARD_SEED_BENCHMARKS_JSON`.

**The default seeds nothing.** `benchmarks` is `[]` and `engineUrl` is empty, so a fresh install registers no benchmark at all and `GET /v1/benchmarks` returns an empty list. The legacy `hle` / `livetruth` / `livetruth-latest` demo entries were removed in OME-986; they were leftovers from the previous SF project.

A real deployment gets its benchmarks from the Engine, by pointing `engineUrl` at the Engine's **in-cluster** address:

```yaml
seedBenchmarks:
  enabled: true
  engineUrl: http://screamingface-engine.screamingface.svc.cluster.local:8000
  benchmarks: []
```

To register a benchmark the Engine does not publish — a local smoke target, say — list it explicitly:

```yaml
seedBenchmarks:
  enabled: true
  benchmarks:
    - id: smoke
      display_name: Smoke
      description: Local smoke target, not an Engine benchmark
```

An entry whose id the Engine also publishes is ignored and named in the Job's output; the Engine is the only place a published benchmark's text is written (OME-904).

Re-running the Job is safe because benchmark registration is an upsert.

**Seeding never deletes.** Removing an entry from this list stops it being recreated; it does not remove a row that already exists, which stays and is still served. To remove one:

```bash
python -m scoreboard.retire_benchmark --benchmark <id> --yes
```

It refuses while any score or baseline references the benchmark, and refuses an Engine-published one unless you also pass `--include-engine-owned` — which is only correct once the Engine has stopped publishing it, since otherwise the next seed recreates it.

Disable seeding with `--set seedBenchmarks.enabled=false`.

## Smoke Checks

Run the Helm test and check public health:

```bash
helm test scoreboard --namespace scoreboard --timeout 3m
curl -fsS http://scoreboard.40.76.107.241.nip.io/healthz
curl -fsS http://scoreboard.40.76.107.241.nip.io/v1/benchmarks
```

Submit a smoke score with an idempotency key. **`benchmark_id` must name a benchmark this deployment actually registered** — the default seed list is empty, so pick one from the `/v1/benchmarks` call above or seed a `smoke` entry as shown under Benchmark Seeding. Submitting to an unregistered id returns 404. If `config.authMode=cloudflare_headers` is set, add `-H "X-User-Email: <email>"` (and submit from an allowed peer) or this 401s:

```bash
curl -fsS -X POST http://scoreboard.40.76.107.241.nip.io/v1/scores \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: score-007-smoke-1" \
  -d '{"version":1,"benchmark_id":"smoke","spec_id":"score-007-smoke","url4_expression":"url4://smoke","submitted_by":"score-007","score":0.5,"total_questions":2,"ran_with_providers":["smoke"],"client":{"name":"curl","version":"0.1.0","platform":"k3s"}}'

curl -fsS http://scoreboard.40.76.107.241.nip.io/v1/leaderboard/smoke
```

The SCORE-007 initial task mentions POSTing from SF desktop, but current D-SCORE-006 in this repo is AIGateway desktop login, not scoreboard score publishing. Use the public API smoke above until a desktop submission task exists.

## Portal And Public Artifacts

The scoreboard service owns the public portal at `https://scoreboard.screamingface.ai/`. The portal calls `/v1/*` same-origin, so CORS is not needed for the portal itself.

The service also exposes exact public JSONL routes as inline text:

```bash
curl -fsS https://scoreboard.screamingface.ai/livetruth-latest.jsonl
curl -fsS https://scoreboard.screamingface.ai/livetruth-latest.eval.jsonl
curl -fsS https://scoreboard.screamingface.ai/livetruth-masking.dataset.jsonl
```

`livetruth-latest.jsonl` intentionally contains answers/context for the current demo, and `livetruth-latest.eval.jsonl` intentionally exposes direct-eval rows including `expected_answer`. Do not expose `livetruth-latest.answer-key.jsonl` or broad generated-artifact globs.

After deploy, open `https://scoreboard.screamingface.ai/` and verify the browser console has no failed `http://localhost:9106` requests and no CORS failures.

## Migrations

The app chart runs:

```bash
python -m tortoise -c scoreboard.db.TORTOISE_CONFIG migrate
```

This runs in a Helm hook Job before app Deployment rollout. Do not run `Tortoise.generate_schemas()` in production and do not run migrations in app startup.

## Upgrade And Rollback

Upgrade:

```bash
helm upgrade scoreboard apps/scoreboard/charts/scoreboard \
  --namespace scoreboard \
  --reuse-values \
  --set image.tag=<new-tag> \
  --wait
```

Rollback:

```bash
helm history scoreboard --namespace scoreboard
helm rollback scoreboard <revision> --namespace scoreboard --wait
```

> **Run `python -m scoreboard.check_rollback_safety` first.** Rolling back below the release that
> introduced private boards publishes every private submission — see
> [Private boards and rollback](#private-boards-and-rollback--run-the-preflight-first).

Helm rollback does not roll back database schema migrations. Keep migrations forward-compatible where possible.

### Breaking migrations and multi-replica rollouts

`values-prod.yaml` sets `replicaCount: 3`, and the migration Job is a `pre-upgrade` hook — it
finishes **before** the Deployment rolls. So during a production upgrade the old pods keep serving
against the **new** schema until the rollout completes. A migration that renames or drops a column
those pods still query makes them fail for that window, and `/healthz` does not touch the database,
so readiness stays green and Kubernetes keeps them in the Service. Combined with the line above —
rollback does not revert the schema — a breaking migration is not recoverable by `helm rollback`.

**Before cutting a `scoreboard-v*` tag, check whether any unreleased migration renames or drops a
column.** If one does, pick one:

- **maintenance window** — scale to 0, migrate, scale back up. Simplest, and fine while the service
  has no users.
- **expand/contract** — add the new column, dual-write, backfill, switch reads, drop the old column
  in a later release. Three deploys, no downtime. Use this once the board has real users.

`0005_auto_20260817_1520` (OME-865, renaming `verified_by_openmined` to
`verified_by_screamingface`) is the first migration in this category. It is safe on dev, which runs
a single replica, and was deliberately shipped as a plain rename because production had no users at
the time. Re-check that assumption before releasing it.

`0006_benchmark_native_scores` (OME-866, renaming `accuracy` to `score` and making
`correct_questions` nullable) is the second. Same reasoning, same rollout options as above.

### Private boards and rollback — run the preflight first

**Once any benchmark is private, `helm rollback` below the release that introduced private boards
publishes every submission on it.** Privacy is enforced by code that reads `Benchmark.visibility`;
the database only stores the column. Roll the code back and the column survives untouched while
nothing reads it.

This was executed, not reasoned about. Against a database holding one private board with three
submissions, the merge base `454253da` — whose `src/scoreboard/` contains no occurrence of
`visibility` at all — returned all three from `ScoreStore.leaderboard()`, submitter addresses
included. There is no configuration of the old code that filters, because it has nothing to filter
on.

**Helm cannot guard this, so do not look for a hook.** `helm rollback` executes the *target*
revision's hooks (`execHook(targetRelease, release.HookPreRollback, ...)` in Helm's
`pkg/action/rollback.go`). The revision being rolled back **to** is a pre-privacy one and its
stored manifest has no such hook, so nothing added to this chart can run in the dangerous
direction.

Package version is not a release identity here: both the privacy-blind base and the
privacy-aware release package `scoreboard 0.1.1`. For every known-safe deployment, record the Helm
revision, rendered image reference, and runtime `imageID` digest together in the deployment record:

```bash
NAMESPACE=scoreboard
RELEASE=scoreboard
DEPLOYMENT=scoreboard-scoreboard
SELECTOR='app.kubernetes.io/instance=scoreboard,app.kubernetes.io/name=scoreboard'

helm list --namespace "$NAMESPACE" --filter "^${RELEASE}$"
helm history "$RELEASE" --namespace "$NAMESPACE"
kubectl -n "$NAMESPACE" get deploy "$DEPLOYMENT" \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="scoreboard")].image}{"\n"}'
kubectl -n "$NAMESPACE" get pods -l "$SELECTOR" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[?(@.name=="scoreboard")].imageID}{"\n"}{end}'
```

Every serving pod must report the same immutable digest. Record it while the known-safe release is
live; a mutable image tag in old Helm values cannot reconstruct this evidence later. Before **any**
rollback, compare the requested target revision and image with that deployment record, then run the
database preflight in a pod on the current release:

```bash
TARGET_REVISION=<revision-from-helm-history>
helm get manifest "$RELEASE" --namespace "$NAMESPACE" --revision "$TARGET_REVISION" \
  | grep 'image:'
kubectl -n "$NAMESPACE" exec "deploy/$DEPLOYMENT" -- \
  python -m scoreboard.check_rollback_safety
```

It exits `0` when no benchmark is private, and non-zero — listing each private board and its
submission count — when one is. It is read-only and has no override flag: clearing the refusal by
flipping a board to public *is* the leak, performed deliberately.

If the target has recorded evidence that it is privacy-aware, a refusal is expected and the normal
rollback is safe. If that evidence is absent, treat the target as privacy-blind. Postpone the
rollback, or use this destructive fallback for **each** board listed by the preflight.

First, export through the still-privacy-aware pod to a staff-only file on the operator's machine.
The local shell performs the redirection; the file is not left in the pod:

```bash
BENCHMARK=healthbench-worst30
BACKUP_DIR=<absolute-path-to-staff-only-storage>
umask 077
kubectl -n "$NAMESPACE" exec "deploy/$DEPLOYMENT" -- \
  python -m scoreboard.export_private_submissions --benchmark "$BENCHMARK" \
  > "$BACKUP_DIR/$BENCHMARK.jsonl"
shasum -a 256 "$BACKUP_DIR/$BENCHMARK.jsonl"
EXPORT_SHA256=<64-hex-digest-printed-above>
```

Then make the application compare the database's current canonical export with that exact digest.
The first command is a dry run. Read its benchmark id, row count, and digest before repeating with
`--yes`:

```bash
kubectl -n "$NAMESPACE" exec "deploy/$DEPLOYMENT" -- \
  python -m scoreboard.purge_private_benchmark \
    --benchmark "$BENCHMARK" \
    --expected-export-sha256 "$EXPORT_SHA256"

kubectl -n "$NAMESPACE" exec "deploy/$DEPLOYMENT" -- \
  python -m scoreboard.purge_private_benchmark \
    --benchmark "$BENCHMARK" \
    --expected-export-sha256 "$EXPORT_SHA256" \
    --yes
```

The purge locks that exact benchmark, re-reads every submission, and deletes its scores,
idempotency mappings, and benchmark in one transaction. A new submission changes the digest and
refuses the purge without deleting anything. It also refuses an unknown/public board or one with a
baseline. Preserve the export; it contains participant identities and there is no automatic
re-import.

Repeat export and purge for every private board, then require the preflight to say `SAFE`. Only now
remove all serving endpoints and start the rollback:

```bash
kubectl -n "$NAMESPACE" exec "deploy/$DEPLOYMENT" -- \
  python -m scoreboard.check_rollback_safety

REPLICAS=$(kubectl -n "$NAMESPACE" get deploy "$DEPLOYMENT" \
  -o jsonpath='{.spec.replicas}')
kubectl -n "$NAMESPACE" scale deploy "$DEPLOYMENT" --replicas=0
kubectl -n "$NAMESPACE" wait --for=delete pod -l "$SELECTOR" --timeout=5m

SERVICE=scoreboard-scoreboard
test -z "$(kubectl -n "$NAMESPACE" get endpoints "$SERVICE" \
  -o jsonpath='{.subsets[*].addresses[*].ip}')"

helm rollback "$RELEASE" "$TARGET_REVISION" --namespace "$NAMESPACE" --wait
kubectl -n "$NAMESPACE" scale deploy "$DEPLOYMENT" --replicas="$REPLICAS"
kubectl -n "$NAMESPACE" rollout status deploy "$DEPLOYMENT" --timeout=5m
```

Do not continue unless the preflight exits `0`, the pod wait succeeds, and the endpoint assertion
is empty. `helm rollback` applies the target's stored replica count, so its pods can begin starting
during that command; the private rows must already be gone before it runs. The explicit final scale
restores the replica count recorded from the current release.

Re-importing after rolling forward again is manual; there is no tooling for it. That asymmetry is
deliberate — it should be easier to postpone a rollback than to destroy a challenge in progress.

**Ordering rule for activation:** deploy the privacy-aware release *before* flipping any board to
private, so a rollback target that understands `visibility` already exists in `helm history`. The
preflight cannot check this for you — it sees the database, not the release history.

## Troubleshooting

Inspect resources:

```bash
kubectl -n scoreboard get pods,job,svc,ingress,pvc
helm status scoreboard --namespace scoreboard
```

Inspect logs:

```bash
kubectl -n scoreboard logs job/scoreboard-scoreboard-migrate
kubectl -n scoreboard logs job/scoreboard-scoreboard-seed-benchmarks
kubectl -n scoreboard logs deploy/scoreboard-scoreboard
```

Check the database Secret:

```bash
kubectl -n scoreboard get secret scoreboard-db -o jsonpath='{.data.database-url}' | base64 --decode
```

If GHCR image pulls fail, create an image pull Secret and set `imagePullSecrets[0].name=<secret-name>`.

## Operations Notes

- The container listens on `0.0.0.0:9106` and exposes `/healthz`.
- `/healthz` is a liveness endpoint and does not query the database; Helm test also calls `/v1/benchmarks` for a DB-backed check.
- The migration and seed Jobs use the same image and database Secret as the app Deployment.
- The demo DB PVC owns the database state; deleting it deletes the database.
- Backups, HA Postgres, PodMonitor, and HPA are follow-up infrastructure work.
