# Deploying screamingface-engine

This file holds the deployment steps the chart cannot do for you. The chart itself is
`deploy/helm/`; its values are documented in `deploy/helm/values.yaml`.

## Turn Runs on

First-class Runs (`/runs`, E5 P1 spec D2 and R10) keep their records in a Postgres database called
`engine`, on the environment's existing Postgres server. Until this is done, the App runs with
**Runs off**: it logs `Runs are off` at start, `/runs` answers 404, and the Client falls back to
its own records. Everything else works as before.

Do this once per environment. It is a manual step because the Postgres chart creates its
database only when its volume is empty.

1. Create the role and the database, as the server's superuser:

   ```sql
   CREATE ROLE engine LOGIN PASSWORD '<a new password>';
   CREATE DATABASE engine OWNER engine;
   ```

2. Create the Secret in the Engine's namespace. The key is `database-url`, as for aigateway and
   scoreboard:

   ```bash
   kubectl -n <engine namespace> create secret generic engine-db \
     --from-literal=database-url='postgres://engine:<the password>@<postgres host>:5432/engine'
   ```

3. Let the App and the migrate Job reach the database. Both run in the Engine's namespace, as
   pods labelled `app.kubernetes.io/component: control-plane` and
   `app.kubernetes.io/component: migrate`. A namespace with a `default-deny` NetworkPolicy needs an
   egress rule for both on port 5432. For a managed Postgres server outside the cluster, copy
   aigateway's `allow-egress-managed-postgres`:

   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: allow-engine-egress-managed-postgres
     namespace: <engine namespace>
   spec:
     podSelector:
       matchExpressions:
         - key: app.kubernetes.io/component
           operator: In
           values: [control-plane, migrate]
     policyTypes: [Egress]
     egress:
       - ports:
           - port: 5432
             protocol: TCP
         to:
           - ipBlock:
               cidr: 0.0.0.0/0
               except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16]
   ```

   For a Postgres pod in the cluster, name its pods in `to` instead, and give the database an
   ingress rule for the same two components. If the server has a firewall allow-list, add the
   cluster's egress address to it.

4. Point the environment's values at it:

   ```yaml
   database:
     existingSecret: engine-db
   ```

On the next `helm upgrade`, the chart's `migrate` Job creates the tables before the App starts.
The App reads the URL; the runner pool never does.

**Changing the URL later** (a new password, another host): update the Secret, run
`helm upgrade` so the `migrate` Job runs against the new database, then
`kubectl -n <engine namespace> rollout restart deployment/<release>`. The App reads the URL only
at start, so without the restart it keeps the old one.

### What can go wrong

- **The App refuses to start with "schema is older than this Engine".** The migrate Job did not
  run or failed. Check the Job's logs (`kubectl logs job/<release>-migrate`), or run the migration
  by hand from an App image with `URL4_CLOUD_DATABASE_URL` set:
  `python -m tortoise -c screamingface_engine.runs.db.TORTOISE_CONFIG migrate`.
- **The App refuses to start with "SQLite URL".** A hosted App needs Postgres: a pod's SQLite file
  is wiped on every restart.
- **The release hangs, then fails, on the migrate Job.** `database.existingSecret` names a Secret
  that does not exist yet. Neither the Job nor the App can start without it. Create the Secret
  (step 2) first.
- **The App refuses to start with "database … did not answer".** The URL is wrong, the database
  is down, or the pod cannot reach it (step 3). The error names the host with the password hidden.

## The outcome stream

Every run's outcome reaches the App on the JetStream stream `url4-candidate-outcomes`, which the
App and the runner pool create at startup. Its limits are `candidateOutcomes.maxAgeS` (24 h) and
`candidateOutcomes.maxBytes` (512 MiB, which the broker's JetStream file store must hold beside
`events.maxBytes`). Both halves apply them at their next start. When the stream is full, a publish
is refused and logged rather than an older outcome dropped.

## The run-results store

With Runs on, every result of a run the Engine's driver starts, and each Run's context, is kept in
an S3 bucket of its own for the Run's 30 days (E5 P2 spec D9a). The render fails with Runs on and
no store. By default the chart renders a third bundled Garage (`<fullname>-garage-run-results`):
one replica, no backup and no lifecycle rule, which suits a test cluster only. In production:

1. Create a durable bucket, and give it a lifecycle rule one day longer than the Runs' retention,
   31 days. Retention deletes the objects a Run names; the rule removes the ones nothing names (a
   second execution of one start, a lost outcome).

   ```json
   {"Rules": [{"ID": "expire-run-results", "Status": "Enabled", "Filter": {"Prefix": ""},
               "Expiration": {"Days": 31}}]}
   ```

2. Create two keys: the App's, with read, write and delete on the bucket; the runner pool's, which
   may only write, since a runner never reads a result back. Put each in a Secret with the keys
   `URL4_CLOUD_RUN_RESULTS_S3_ACCESS_KEY` and `URL4_CLOUD_RUN_RESULTS_S3_SECRET_KEY`.

3. Set the values:

   ```yaml
   runResults:
     storage:
       s3:
         endpointUrl: https://<your S3 endpoint>
         bucket: <the bucket>
         region: <its region>
         existingSecret: <the App's Secret>
         poolExistingSecret: <the pool's Secret>
   ```

A runner retries a write the store refuses for `runResults.writeBudgetS` (60 s), then fails the
run `result_store_unavailable`, which the Client may retry. A pool with no store fails such a run
`result_store_missing` before any model call.

The runner pool also creates a NATS key-value bucket, `url4-claims`, at startup, with the event
stream's retention, replicas and storage. It needs no step of its own, but the pool must roll
before the App: a pool of the previous version refuses the App's new run messages
(`unsupported_spec_version`).

A store the App cannot reach answers `POST /runs` with a context `503 result_store_unavailable`,
and registers nothing, and the context and result routes answer the same until it is back.

## The Run event stream

A Client follows a Run on one WebSocket, `GET /runs/{id}/events`, which the App checks against
the Run's owner like every `/runs` route. The edge must pass the verified `X-User-Email` on the
WebSocket upgrade, as it does on HTTP requests: without it the App closes the socket at once
(1008, `identity_required`). Check it on staging before a P2 Client is released:

```sh
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  https://<engine host>/runs/<one of your Run ids>/events
```

`101` means the edge passed the identity; `403` means the App refused it.

While a follower is connected, the App stamps the Run every `URL4_CLOUD_RUN_FOLLOW_STAMP_S`
(30 s); an attached Run nobody has followed for `URL4_CLOUD_ORPHAN_GRACE_S` (120 s) is stopped.
The driver's lease and the follow stamps live in Postgres, so the Run routes add no reason to
keep the App at one replica beyond those it already has (E5 P2 spec D5).
