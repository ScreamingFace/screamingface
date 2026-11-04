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
   pods labelled `component: control-plane` and `component: migrate`. If the namespace or the
   database server has a NetworkPolicy or firewall allow-list, add both to it, as for aigateway.

4. Point the environment's values at it:

   ```yaml
   database:
     existingSecret: engine-db
   ```

On the next `helm upgrade`, the chart's `migrate` Job creates the tables before the App starts.
The App reads the URL; the runner pool never does.

### What can go wrong

- **The App refuses to start with "schema is older than this Engine".** The migrate Job did not
  run or failed. Check the Job's logs (`kubectl logs job/<release>-migrate`), or run the migration
  by hand from an App image with `URL4_CLOUD_DATABASE_URL` set:
  `python -m tortoise -c screamingface_engine.runs.db.TORTOISE_CONFIG migrate`.
- **The App refuses to start with "SQLite URL".** A hosted App needs Postgres: a pod's SQLite file
  is wiped on every restart.
- **The release hangs, then fails, on the migrate Job.** `database.existingSecret` names a Secret
  that does not exist yet, and the Job cannot start without it. Create the Secret (step 2) first.
- **The App refuses to start with "database … did not answer".** The URL is wrong, the database
  is down, or the pod cannot reach it (step 3). The error names the host with the password hidden.

## The outcome stream

Every run's outcome reaches the App on the JetStream stream `url4-candidate-outcomes`, which the
App and the runner pool create at startup. Its limits are `candidateOutcomes.maxAgeS` (24 h) and
`candidateOutcomes.maxBytes` (64 MiB). Both halves apply them at their next start. When the stream
is full, a publish is refused and logged rather than an older outcome dropped.
