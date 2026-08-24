#!/usr/bin/env bash
# =============================================================================
# local_k8s_deployment.sh — one command for the ScreamingFace local kind stack.
#
# PURPOSE
#   This script builds and runs the full ScreamingFace stack in a local
#   Kubernetes-in-Docker (kind) cluster. It does everything a manual setup does:
#
#     - create the kind cluster (control-plane + two workers)
#     - build the application images from this repository
#     - load the images into the cluster
#     - install the Helm charts (aigateway, screamingface-engine, scoreboard,
#       aigateway-ui, postgres databases)
#     - deploy the identity edge (nginx) that maps the Cloudflare Access email
#       header to the identity header the engine reads
#     - provision the OpenRouter API key for your Access identity
#     - write a revision-guard manifest beside every snapshot (the admin
#       upload in aigateway verifies it; see OME-951's spec)
#     - seed aigateway's global response cache from the DRACO backfill
#       (draco-cache-seed-v3) so a faithful draco re-run answers from cache
#     - start the cloudflared tunnel to the public test hostname
#
#   The command "down" removes the whole cluster and stops the tunnel.
#
# REQUIREMENTS
#   - docker, kind, kubectl, helm, cloudflared installed
#   - a Cloudflare tunnel and Access application for the test hostname
#     (see the TUNNEL section below)
#   - an OpenRouter API key (pass it with OPENROUTER_API_KEY)
#   - the DRACO cache seed package at draco-cache-seed-v3/ (or extract
#     draco-cache-seed-v3.tar.gz), unless SKIP_CACHE_SEED=1
#   - enough inotify instances for the cluster (see the INOTIFY note below)
#
# INOTIFY NOTE
#   Each kind node runs containerd and kubelet as root. Their inotify instances
#   count against the host's fs.inotify.max_user_instances (default 128). One
#   cluster uses about 100 instances. When the budget is full, a new node's
#   containerd fails with "failed to create fsnotify watcher: too many open
#   files" and cluster creation fails. If that happens, raise the limit once:
#
#     sudo sysctl -w fs.inotify.max_user_instances=1024 fs.inotify.max_user_watches=1048576
#     echo 'fs.inotify.max_user_instances=1024' | sudo tee /etc/sysctl.d/90-inotify.conf
#     echo 'fs.inotify.max_user_watches=1048576' | sudo tee -a /etc/sysctl.d/90-inotify.conf
#
# USAGE
#   ./local_k8s_deployment.sh up        create the stack
#   ./local_k8s_deployment.sh down      remove the stack
#   ./local_k8s_deployment.sh status    show the stack state
#   ./local_k8s_deployment.sh smoke     run quick checks
#   ./local_k8s_deployment.sh seed              seed the response cache into an existing stack
#   ./local_k8s_deployment.sh snapshot-cache   dump the live response cache to a file
#   ./local_k8s_deployment.sh restore-cache    load a cache snapshot back (replaces contents)
#   ./local_k8s_deployment.sh help      show this text
#
# OPTIONS (environment variables)
#   OPENROUTER_API_KEY   your OpenRouter key (no default; required to enable runs)
#   PRIMARY_IDENTITY     the Access identity that owns the key (default: ionesiojr@gmail.com)
#   SF_CLUSTER_NAME      kind cluster name (default: sf)
#   REBUILD_IMAGES=1     rebuild the images even when they exist
#   SKIP_IMAGE_BUILD=1   never build; fail if an image is missing
#   SKIP_TUNNEL=1        do not start the cloudflared tunnel
#   SKIP_PROVISION=1     do not provision the OpenRouter key
#   SKIP_CACHE_SEED=1    do not build the seed image or run the cache seed Job
#
# SECURITY NOTE
#   The script never stores secrets in the repository. The OpenRouter key comes
#   from the environment only. The Cloudflare tunnel uses the credentials that
#   already exist in ~/.cloudflared. Do not commit API keys to this file.
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="${SF_CLUSTER_NAME:-sf}"
NAMESPACE="screamingface"
IMAGE_TAG="dev"

# Cloudflare Access identity that owns the provisioned OpenRouter credential.
PRIMARY_IDENTITY="${PRIMARY_IDENTITY:-ionesiojr@gmail.com}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"

# DRACO cache seed: populate aigateway's global response cache from the archived
# DRACO run, so a faithful draco benchmark re-run is served from cache instead of
# paying OpenRouter. Rows are keyed for the CURRENT aigateway revisions; the loader
# refuses loudly on mismatch (see draco-cache-seed-v3/RUNBOOK.md).
SKIP_CACHE_SEED="${SKIP_CACHE_SEED:-0}"
SEED_IMAGE_NAME="screamingface-aigateway-seed"
SEED_IMAGE="ghcr.io/screamingface/$SEED_IMAGE_NAME:$IMAGE_TAG"
SEED_JOB="aigw-cache-seed"
SEED_DIR="$SCRIPT_DIR/draco-cache-seed-v3"

# Cloudflare tunnel (matches ~/.cloudflared/aigateway-test-config.yml).
TUNNEL_ID="c89275e9-23ab-44de-b26e-fded035ca198"
TUNNEL_CREDS="$HOME/.cloudflared/$TUNNEL_ID.json"
TUNNEL_HOSTNAME="aigateway-test.cuscuzymate.cc"
TUNNEL_CFG="$HOME/.cloudflared/sf-kind-$CLUSTER_NAME.yml"
TUNNEL_LOG="/tmp/cloudflared-$CLUSTER_NAME.log"
TUNNEL_PID="/tmp/cloudflared-$CLUSTER_NAME.pid"

# In-cluster service names (fixed by the Helm release names below).
AIGW_SERVICE="aigw-aigateway"
ENGINE_SERVICE="screamingface-engine-url4-cloud"
ENGINE_BASE_URL="http://$AIGW_SERVICE.$NAMESPACE.svc.cluster.local:9105"
EDGE_NODE_PORT="30008"

KUBECTL="kubectl --context kind-$CLUSTER_NAME"
HELM="helm"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log()  { printf '\033[1;34m[sf]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[sf-warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[sf-error]\033[0m %s\n' "$*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------
preflight() {
  for tool in docker kind kubectl helm; do
    command -v "$tool" >/dev/null 2>&1 || die "missing tool: $tool"
  done
  if [ -z "$OPENROUTER_API_KEY" ] && [ "${SKIP_PROVISION:-0}" != "1" ]; then
    warn "OPENROUTER_API_KEY is not set; the OpenRouter credential will not be provisioned."
  fi
  _inotify_preflight
}

_inotify_preflight() {
  # Warn before a node boot fails with "too many open files" in containerd's CRI
  # watcher (see the INOTIFY NOTE). Counting every instance is expensive; count
  # the host plus any running kind nodes of THIS cluster, which is the case the
  # script actually hits.
  local max instances host_count=0 node_count=0
  max=$(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo 128)
  for p in /proc/[0-9]*; do
    host_count=$((host_count + $(ls -l "$p/fd" 2>/dev/null | grep -c anon_inode:inotify || true)))
  done
  if _cluster_exists; then
    for n in $($KUBECTL get nodes -o name 2>/dev/null || true); do
      local short c
      short=${n##*/}
      c=$(docker exec "$short" sh -c 'n=0; for p in /proc/[0-9]*; do c=$(ls -l $p/fd 2>/dev/null | grep -c anon_inode:inotify); n=$((n+c)); done; echo $n' 2>/dev/null || echo 0)
      node_count=$((node_count + c))
    done
  fi
  instances=$((host_count + node_count))
  if [ "$instances" -ge "$((max - 20))" ]; then
    warn "inotify instances are near the limit ($instances of $max). New kind nodes may fail to"
    warn "boot containerd. Raise the limit (see the INOTIFY NOTE in this script's header):"
    warn "  sudo sysctl -w fs.inotify.max_user_instances=1024 fs.inotify.max_user_watches=1048576"
  fi
}

# -----------------------------------------------------------------------------
# Images
# -----------------------------------------------------------------------------
image_exists() { docker image inspect "$1:$IMAGE_TAG" >/dev/null 2>&1; }

_seed_package_present() {
  # The loader needs exactly these three files; the rest of the package (generator/,
  # applytest.*) is provenance/test material that only bloats the image.
  [ -f "$SEED_DIR/seed_cache.py" ] && [ -f "$SEED_DIR/manifest.json" ] \
    && [ -f "$SEED_DIR/rows.jsonl" ]
}

build_images() {
  if [ "${SKIP_IMAGE_BUILD:-0}" = "1" ]; then
    for img in screamingface-aigateway screamingface-engine screamingface-engine-benchmark \
               screamingface-scoreboard screamingface-aigateway-ui; do
      image_exists "ghcr.io/screamingface/$img" || die "image missing (and SKIP_IMAGE_BUILD=1): $img"
    done
    if [ "$SKIP_CACHE_SEED" != "1" ]; then
      image_exists "ghcr.io/screamingface/$SEED_IMAGE_NAME" || die "image missing (and SKIP_IMAGE_BUILD=1): $SEED_IMAGE_NAME"
    fi
    return
  fi
  local rebuild="${REBUILD_IMAGES:-0}"
  local build=() aigw_rebuilt=0
  for img in screamingface-aigateway screamingface-engine screamingface-scoreboard \
             screamingface-aigateway-ui; do
    if [ "$rebuild" = "1" ] || ! image_exists "ghcr.io/screamingface/$img"; then
      build+=("$img")
      [ "$img" = "screamingface-aigateway" ] && aigw_rebuilt=1
    fi
  done
  # The cache-seed image derives from the aigateway image, so it must rebuild
  # whenever aigateway does (the loader's revision check imports aigateway code).
  local seed_needs=0
  if [ "$SKIP_CACHE_SEED" != "1" ] && { [ "$rebuild" = "1" ] || [ "$aigw_rebuilt" = "1" ] \
     || ! image_exists "ghcr.io/screamingface/$SEED_IMAGE_NAME"; }; then
    seed_needs=1
  fi
  if [ "${#build[@]}" -eq 0 ] && [ "$seed_needs" = "0" ] \
     && image_exists "ghcr.io/screamingface/screamingface-engine-benchmark"; then
    log "all images already exist; skip build (set REBUILD_IMAGES=1 to rebuild)"
    return
  fi
  log "building application images (this can take several minutes)…"
  for img in "${build[@]:-}"; do
    case "$img" in
      screamingface-aigateway) docker build -f "$SCRIPT_DIR/apps/aigateway/Dockerfile"        -t "ghcr.io/screamingface/$img:$IMAGE_TAG" "$SCRIPT_DIR" ;;
      screamingface-engine)     docker build -f "$SCRIPT_DIR/apps/screamingface-engine/Dockerfile" -t "ghcr.io/screamingface/$img:$IMAGE_TAG" "$SCRIPT_DIR" ;;
      screamingface-scoreboard) docker build -f "$SCRIPT_DIR/apps/scoreboard/Dockerfile"      -t "ghcr.io/screamingface/$img:$IMAGE_TAG" "$SCRIPT_DIR" ;;
      screamingface-aigateway-ui) docker build -f "$SCRIPT_DIR/apps/aigateway-ui/Dockerfile"  -t "ghcr.io/screamingface/$img:$IMAGE_TAG" "$SCRIPT_DIR" ;;
    esac
  done
  if [ "$seed_needs" = "1" ]; then
    if _seed_package_present; then
      log "building the cache seed image (rows.jsonl is ~147 MB)…"
      docker build -f "$SCRIPT_DIR/apps/aigateway/Dockerfile.seed" \
        -t "$SEED_IMAGE" "$SCRIPT_DIR"
    else
      warn "draco-cache-seed-v3/ is incomplete — the cache seed image will not be built"
    fi
  fi
  # The benchmark image layers on the control-plane image.
  if [ "$rebuild" = "1" ] || ! image_exists "ghcr.io/screamingface/screamingface-engine-benchmark"; then
    log "building benchmark image…"
    docker build -f "$SCRIPT_DIR/apps/screamingface-engine/Dockerfile.benchmark" \
      --build-arg "BASE=ghcr.io/screamingface/screamingface-engine:$IMAGE_TAG" \
      -t "ghcr.io/screamingface/screamingface-engine-benchmark:$IMAGE_TAG" "$SCRIPT_DIR"
  fi
}

load_images() {
  log "loading images into kind…"
  for img in screamingface-aigateway screamingface-engine screamingface-engine-benchmark \
             screamingface-scoreboard screamingface-aigateway-ui; do
    kind load docker-image "ghcr.io/screamingface/$img:$IMAGE_TAG" --name "$CLUSTER_NAME"
  done
  if [ "$SKIP_CACHE_SEED" != "1" ] && image_exists "ghcr.io/screamingface/$SEED_IMAGE_NAME"; then
    kind load docker-image "$SEED_IMAGE" --name "$CLUSTER_NAME"
  fi
}

# -----------------------------------------------------------------------------
# Cluster
# -----------------------------------------------------------------------------
cluster_up() {
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    log "cluster $CLUSTER_NAME already exists; reuse it (remove it with: $0 down)"
    return
  fi
  log "creating kind cluster $CLUSTER_NAME…"
  cat > "$TMP/kind.yaml" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: $CLUSTER_NAME
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF
  kind create cluster --config "$TMP/kind.yaml"
  $KUBECTL wait --for=condition=Ready node --all --timeout=180s
}

namespace_create() {
  $KUBECTL create namespace "$NAMESPACE" --dry-run=client -o yaml | $KUBECTL apply -f - >/dev/null
}

helm_deps() {
  log "fetching the NATS chart dependency…"
  ( cd "$SCRIPT_DIR/apps/screamingface-engine/deploy/helm" && helm dependency build >/dev/null )
}

# -----------------------------------------------------------------------------
# Helm installs
# -----------------------------------------------------------------------------
install_databases() {
  log "installing postgres (aigateway-db)…"
  helm upgrade --install aigw-db "$SCRIPT_DIR/apps/aigateway/charts/db" \
    --namespace "$NAMESPACE" \
    --values "$SCRIPT_DIR/apps/aigateway/charts/db-aigateway.values.yaml" \
    --set persistence.storageClass=standard \
    --wait --timeout 6m
  log "installing postgres (scoreboard-db)…"
  helm upgrade --install scoreboard-db "$SCRIPT_DIR/apps/scoreboard/charts/db" \
    --namespace "$NAMESPACE" \
    --values "$SCRIPT_DIR/apps/scoreboard/charts/db-scoreboard.values.yaml" \
    --set persistence.storageClass=standard \
    --wait --timeout 6m
}

install_aigateway() {
  log "installing the AI Gateway…"
  cat > "$TMP/aigw.yaml" <<EOF
image:
  tag: $IMAGE_TAG
config:
  authMode: cloudflare_headers
  allowedNetworks:
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16
    - 100.64.0.0/10
  # Both flags on are preconditions for the seeded DRACO cache to be READ at all
  # (draco-cache-seed-v3/RUNBOOK.md — with either off, every request bypasses).
  openrouter:
    enabled: true
  requestCache:
    enabled: true
database:
  existingSecret: aigw-db
  existingSecretKey: database-url
EOF
  helm upgrade --install aigw "$SCRIPT_DIR/apps/aigateway/charts/aigateway" \
    --namespace "$NAMESPACE" \
    --values "$TMP/aigw.yaml" \
    --wait --timeout 8m
}

install_engine() {
  log "installing the ScreamingFace Engine (NATS + Garage included)…"
  cat > "$TMP/engine.yaml" <<EOF
image:
  tag: $IMAGE_TAG
nats:
  enabled: true
  fullnameOverride: sf-nats
  config:
    jetstream:
      enabled: true
  natsBox:
    enabled: false
garage:
  enabled: true
artifactStorage:
  backend: s3
config:
  aigatewayBaseUrl: "$ENGINE_BASE_URL"
  aigatewayModel: "openrouter/openai/gpt-5.5"
  # Debug session: 0 disables the no-subscriber reaper — finished runs' streams are
  # NOT reaped and their frames stay inspectable in JetStream.
  orphanGraceS: 0
runner:
  image:
    repository: "ghcr.io/screamingface/screamingface-engine-benchmark"
    tag: $IMAGE_TAG
  # Debug session: keep finished Runner Jobs (and their logs) for 24h instead of the
  # ~2-minute token floor, keep their JetStream streams, and log at DEBUG per frame.
  jobTtlSeconds: 86400
  keepStreams: true
  debugLogs: true
EOF
  # Install without --wait first: the Garage StatefulSet needs the command fix
  # below before it can become Ready (chart bug: the image needs "command: [/garage]").
  helm upgrade --install screamingface-engine "$SCRIPT_DIR/apps/screamingface-engine/deploy/helm" \
    --namespace "$NAMESPACE" \
    --values "$TMP/engine.yaml" \
    --timeout 8m >/dev/null
  _patch_garage
  helm upgrade --install screamingface-engine "$SCRIPT_DIR/apps/screamingface-engine/deploy/helm" \
    --namespace "$NAMESPACE" \
    --values "$TMP/engine.yaml" \
    --wait --timeout 8m
  # NOTE: no _patch_garage here — it already ran between the two upgrades above.
  _patch_nats_debug
}

_patch_nats_debug() {
  # Debug session: the bundled nats subchart assembles nats.conf from per-section
  # templates and DROPS unknown top-level keys, so a `nats.config.debug` value never
  # reaches the server. Patch the rendered ConfigMap directly and bounce the pod.
  # A later `helm upgrade` re-renders the ConfigMap without the flag — `up`
  # re-applies this patch every run.
  if ! $KUBECTL get cm sf-nats-config -n "$NAMESPACE" -o jsonpath='{.data.nats\.conf}' 2>/dev/null \
      | grep -q '"debug"'; then
    log "enabling NATS server debug logging (ConfigMap patch + restart)…"
    # NOTE: nats.conf is JSON with ONE non-JSON escape ("server_name": $SERVER_NAME,
    # substituted by the config reloader), so it is patched as TEXT: the two flags
    # are inserted right after the opening brace. json.loads would refuse it.
    $KUBECTL get cm sf-nats-config -n "$NAMESPACE" -o json | python3 -c '
import json, sys
d = json.load(sys.stdin)
conf = d["data"]["nats.conf"]
head, _, rest = conf.partition("{")
d["data"]["nats.conf"] = head + "{\n  \"debug\": true,\n  \"trace\": false," + rest
json.dump(d, sys.stdout)
' | $KUBECTL apply --server-side --field-manager=helm --force-conflicts -f - >/dev/null
    $KUBECTL delete pod sf-nats-0 -n "$NAMESPACE" >/dev/null 2>&1
    $KUBECTL wait --for=condition=Ready pod/sf-nats-0 -n "$NAMESPACE" --timeout=120s >/dev/null || true
  fi
}

_patch_garage() {
  local sts
  sts=$($KUBECTL get sts -n "$NAMESPACE" -l 'app.kubernetes.io/name=url4-cloud' -o name 2>/dev/null | grep garage | head -1 || true)
  if [ -z "$sts" ]; then
    return
  fi
  if ! $KUBECTL get "$sts" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].command}' 2>/dev/null | grep -q "/garage"; then
    log "patching Garage command (chart workaround)…"
    $KUBECTL patch "$sts" -n "$NAMESPACE" --type=json \
      -p '[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["/garage"]}]'
  fi
}

install_scoreboard() {
  log "installing the scoreboard…"
  cat > "$TMP/score.yaml" <<EOF
image:
  tag: $IMAGE_TAG
database:
  existingSecret: scoreboard-db
  existingSecretKey: database-url
ingress:
  enabled: false
EOF
  helm upgrade --install scoreboard "$SCRIPT_DIR/apps/scoreboard/charts/scoreboard" \
    --namespace "$NAMESPACE" \
    --values "$TMP/score.yaml" \
    --wait --timeout 6m
}

install_ui() {
  log "installing the aigateway admin console…"
  cat > "$TMP/ui.yaml" <<EOF
image:
  tag: $IMAGE_TAG
aigateway:
  serviceName: $AIGW_SERVICE
  namespace: $NAMESPACE
networkPolicy:
  enabled: false
EOF
  helm upgrade --install aigw-ui "$SCRIPT_DIR/apps/aigateway-ui/charts/aigateway-ui" \
    --namespace "$NAMESPACE" \
    --values "$TMP/ui.yaml" \
    --wait --timeout 6m
}

# -----------------------------------------------------------------------------
# DRACO cache seed (draco-cache-seed-v3)
# -----------------------------------------------------------------------------
seed_cache() {
  if [ "$SKIP_CACHE_SEED" = "1" ]; then
    warn "skip seeding the aigateway response cache (SKIP_CACHE_SEED=1)"
    return
  fi
  _seed_package_present \
    || die "the DRACO cache seed package is missing at $SEED_DIR/ (need seed_cache.py, manifest.json, rows.jsonl). Extract draco-cache-seed-v3.tar.gz, or set SKIP_CACHE_SEED=1."
  image_exists "ghcr.io/screamingface/$SEED_IMAGE_NAME" \
    || die "cache seed image missing — run up without SKIP_IMAGE_BUILD=1"
  log "seeding the aigateway global response cache (189,339 DRACO rows; create-only and idempotent)…"
  $KUBECTL delete job "$SEED_JOB" -n "$NAMESPACE" --ignore-not-found=true >/dev/null
  cat > "$TMP/seed.yaml" <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $SEED_JOB
  namespace: $NAMESPACE
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: seed
          image: $SEED_IMAGE
          imagePullPolicy: IfNotPresent
          # The image's ENTRYPOINT is "python /seed/seed_cache.py" (dry-run by
          # default); this runs the same migration the chart's pre-install hook
          # runs (idempotent), then seeds.
          command: ["sh", "-c", "python -m tortoise -c aigateway.db.TORTOISE_CONFIG migrate && python /seed/seed_cache.py --apply --directory /seed"]
          env:
            - name: AIGATEWAY_DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: aigw-db
                  key: database-url
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 1Gi
EOF
  $KUBECTL apply -f "$TMP/seed.yaml" >/dev/null
  if ! $KUBECTL wait --for=condition=complete "job/$SEED_JOB" -n "$NAMESPACE" --timeout=30m >/dev/null 2>&1; then
    warn "cache seed Job failed — its guards (revision/checksum) are intentional; the"
    warn "rows would never be served otherwise. Job logs:"
    $KUBECTL logs "job/$SEED_JOB" -n "$NAMESPACE" --tail=40 2>/dev/null | sed 's/^/    /' || true
    die "aigateway cache seed failed"
  fi
  log "cache seed complete:"
  $KUBECTL logs "job/$SEED_JOB" -n "$NAMESPACE" --tail=14 2>/dev/null | sed 's/^/    /' || true
}

# -----------------------------------------------------------------------------
# Identity edge (nginx): maps Cf-Access-Authenticated-User-Email -> X-User-Email
# -----------------------------------------------------------------------------
deploy_edge() {
  log "deploying the identity edge (nginx)…"
  cat > "$TMP/edge.yaml" <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: sf-edge
  namespace: screamingface
data:
  nginx.conf: |
    events {
        worker_connections 1024;
    }
    http {
        map $http_upgrade $connection_upgrade {
            default upgrade;
            ''      close;
        }
        # The SDK submits Runs as `GET /?q=<url4 expression>`, and a Candidate's
        # expression embeds its system prompts — several KB percent-encoded. nginx's
        # default `large_client_header_buffers 4 8k` rejects that request line with
        # 414. In the real deployment Envoy fronts the Engine with no such cap, so
        # this edge must not be the narrow gate either. 32k keeps this nginx behind
        # Cloudflare's ~16k URI ceiling: the outermost proxy stays the real limit,
        # exactly as in production.
        large_client_header_buffers 4 32k;
        server {
            listen 8080;
            server_name _;
            client_max_body_size 64m;
            location / {
                proxy_pass http://screamingface-engine-url4-cloud:9108;
                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection $connection_upgrade;
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_read_timeout 86400s;
                proxy_send_timeout 86400s;
                proxy_set_header X-User-Email $http_cf_access_authenticated_user_email;
                proxy_set_header Cf-Access-Token $http_cf_access_token;
            }
        }
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sf-edge
  namespace: screamingface
  labels:
    app: sf-edge
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sf-edge
  template:
    metadata:
      labels:
        app: sf-edge
    spec:
      containers:
        - name: nginx
          image: nginx:1.27-alpine
          ports:
            - name: http
              containerPort: 8080
          volumeMounts:
            - name: conf
              mountPath: /etc/nginx/nginx.conf
              subPath: nginx.conf
      volumes:
        - name: conf
          configMap:
            name: sf-edge
---
apiVersion: v1
kind: Service
metadata:
  name: sf-edge
  namespace: screamingface
spec:
  type: NodePort
  selector:
    app: sf-edge
  ports:
    - name: http
      port: 8080
      targetPort: 8080
      nodePort: 30008
EOF
  $KUBECTL apply -f "$TMP/edge.yaml"
  sed -i "s/namespace: screamingface/namespace: $NAMESPACE/g" "$TMP/edge.yaml"
  $KUBECTL apply -f "$TMP/edge.yaml"
  $KUBECTL rollout status deploy/sf-edge -n "$NAMESPACE" --timeout=180s >/dev/null
}

# -----------------------------------------------------------------------------
# Cache snapshot / restore (postgres table dump of the live cache corpus)
# -----------------------------------------------------------------------------
# The gateway owns no local state; the whole cache lives in the `aigw-db` postgres
# table `request_cache_entries`. A plain-SQL pg_dump of that one table is MVCC-
# consistent, so it snapshots a LIVE gateway with zero downtime. Restore is a COPY
# load (~seconds for 189k rows), unlike the seed loader's row-by-row inserts.

_deployed_cache_revisions() {
  # Read the cache-key revision constants from the DEPLOYED aigateway image - never from
  # this checkout, which may be older or newer than what the cluster runs. The admin upload
  # (OME-952's routes) refuses snapshots whose manifest revisions disagree with the gateway
  # it targets, because those rows would load cleanly and then never serve: a silent miss.
  local probe="sf-revision-probe-$RANDOM"
  kubectl --context "kind-$CLUSTER_NAME" run "$probe" \
    --image="ghcr.io/screamingface/screamingface-aigateway:$IMAGE_TAG" \
    --restart=Never --rm -i -q -n "$NAMESPACE" --command -- \
    python -c 'import json; from aigateway.core.request_cache.global_keys import PARAMETER_CONTRACT_REVISION; from aigateway.plugins.openrouter_provider.global_cache import GLOBAL_CACHE_ADAPTER_REVISION; print(json.dumps({"parameter_contract": PARAMETER_CONTRACT_REVISION, "openrouter_adapter": GLOBAL_CACHE_ADAPTER_REVISION}))' \
    2>/dev/null
}

snapshot_cache() {
  local out="${1:-draco-cache-snapshot.sql.gz}"
  _cluster_exists || die "cluster $CLUSTER_NAME is down; run: $0 up"
  $KUBECTL get deploy/aigw-db -n "$NAMESPACE" >/dev/null 2>&1 \
    || die "aigw-db is not deployed; run: $0 up"
  log "snapshotting request_cache_entries (live, consistent) -> $out"
  $KUBECTL exec deploy/aigw-db -n "$NAMESPACE" -- \
    pg_dump -U aigateway -d aigateway -t request_cache_entries \
    --no-owner --no-privileges | gzip > "$out"
  local rows
  rows=$(zcat "$out" | sed -n '/^COPY public.request_cache_entries/,/^\\\.$/p' | sed '1d;$d' | wc -l)
  log "snapshot written: $out ($(du -h "$out" | cut -f1), $rows rows)"
  _write_snapshot_manifest "$out" "$rows"
}
_write_snapshot_manifest() {
  # OME-954: the sidecar the admin upload verifies (sha256 + row count + revision constants).
  # A snapshot without one still loads, but only with the console's `revisions_unverified`
  # warning - the manifest is what makes the revision guard strict. Failure to probe the
  # cluster is a warning, not an error: the snapshot itself is complete and usable.
  local archive="$1" rows="$2" digest revisions
  local manifest="${archive%.sql.gz}.manifest.json"
  digest=$(sha256sum "$archive" | cut -d' ' -f1)
  if ! revisions=$(_deployed_cache_revisions); then
    warn "could not read the deployed gateway's revisions - no manifest written; the upload will warn"
    return 0
  fi
  cat > "$manifest" <<EOF
{
  "schema": "screamingface.cache-snapshot.v1",
  "generated_at": "$(date +%F)",
  "row_count": $rows,
  "sha256": "$digest",
  "revisions": $revisions
}
EOF
  log "manifest written: $manifest (verified against the deployed gateway's revisions)"
}


restore_cache() {
  local in="${1:-draco-cache-snapshot.sql.gz}"
  _cluster_exists || die "cluster $CLUSTER_NAME is down; run: $0 up"
  [ -f "$in" ] || die "snapshot file not found: $in"
  $KUBECTL get deploy/aigw-db -n "$NAMESPACE" >/dev/null 2>&1 \
    || die "aigw-db is not deployed; run: $0 up"
  # A data-only restore needs the table to exist. The seed Job (or the chart's
  # own migrate hook) creates it; here we ensure it before loading.
  local existing
  existing=$($KUBECTL exec deploy/aigw-db -n "$NAMESPACE" -- \
    psql -U aigateway -d aigateway -t -A -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_name='request_cache_entries'")
  if [ "$existing" != "1" ]; then
    # WHY generate_schemas and NOT `tortoise migrate`: migrate diffs models against
    # migration FILES and skips anything the aerich state table already records — a
    # dropped table with intact aerich state is invisible to it (observed: Job
    # completes, table stays missing). generate_schemas(safe=True) inspects the LIVE
    # database and creates only what is absent, so it rebuilds a dropped table and
    # is a no-op on an intact one. Safe for data: it never alters existing tables.
    log "table missing — creating it from the aigateway models (safe generate_schemas)…"
    $KUBECTL delete job aigw-cache-snapshot-migrate -n "$NAMESPACE" --ignore-not-found=true >/dev/null
    cat > "$TMP/snap-mig.yaml" <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: aigw-cache-snapshot-migrate
  namespace: $NAMESPACE
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: $SEED_IMAGE
          imagePullPolicy: IfNotPresent
          command:
            - python
            - -c
            - |
              import asyncio, os
              from tortoise import Tortoise
              from aigateway.db import build_tortoise_config
              async def main():
                  await Tortoise.init(config=build_tortoise_config(os.environ['AIGATEWAY_DATABASE_URL']))
                  await Tortoise.generate_schemas(safe=True)
                  await Tortoise.close_connections()
              asyncio.run(main())
          env:
            - name: AIGATEWAY_DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: aigw-db
                  key: database-url
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 1Gi
EOF
    $KUBECTL apply -f "$TMP/snap-mig.yaml" >/dev/null
    $KUBECTL wait --for=condition=complete job/aigw-cache-snapshot-migrate \
      -n "$NAMESPACE" --timeout=10m >/dev/null \
      || { $KUBECTL logs job/aigw-cache-snapshot-migrate -n "$NAMESPACE" --tail=30 2>/dev/null | sed 's/^/    /'; \
           die "schema bootstrap Job failed"; }
  fi
  # SAFETY: refuse to destroy rows the snapshot does not hold. The table is
  # create-only (the gateway never deletes), so live_count > snapshot rows can
  # mean exactly one thing: rows were written AFTER the snapshot was taken, and
  # the TRUNCATE below would permanently discard them. Snapshot first, or force.
  local snap_rows live_rows
  snap_rows=$(zcat "$in" | sed -n '/^COPY public\.request_cache_entries/,/^\\\.$/p' | sed '1d;$d' | wc -l)
  live_rows=$($KUBECTL exec deploy/aigw-db -n "$NAMESPACE" -- \
    psql -U aigateway -d aigateway -t -A -c "SELECT count(*) FROM request_cache_entries")
  if [ "$live_rows" -gt "$snap_rows" ]; then
    if [ "${FORCE_RESTORE:-0}" != "1" ]; then
      die "the live table has $live_rows rows but the snapshot holds only $snap_rows — $((live_rows - snap_rows)) row(s) were written AFTER the snapshot and would be destroyed. Run '$0 snapshot-cache' first, or set FORCE_RESTORE=1 to discard them."
    fi
    warn "FORCE_RESTORE=1 — discarding $((live_rows - snap_rows)) row(s) newer than the snapshot"
  fi
  # The snapshot is a plain pg_dump: CREATE TABLE + COPY data + constraints. The
  # table already exists here (created above if it was missing), so replaying the
  # whole dump would abort at CREATE TABLE. Restore the DATA only: extract the
  # COPY block (statement + rows + `\\.` terminator — COPY escapes such a sequence
  # inside values, so the terminator line is unambiguous) and run it after TRUNCATE
  # in one psql session. -c is deliberately NOT used: psql ignores stdin under -c.
  #
  # TRUNCATE first: the table holds only cached provider responses — never account
  # or profile identity — so replacing its contents wholesale is safe, and rows
  # accumulated AFTER the snapshot (other callers' cache writes) are discarded.
  log "restoring $in into request_cache_entries (COPY load; replaces the table's contents)…"
  local before
  before=$($KUBECTL exec deploy/aigw-db -n "$NAMESPACE" -- \
    psql -U aigateway -d aigateway -t -A -c "SELECT count(*) FROM request_cache_entries")
  { echo "TRUNCATE request_cache_entries;"; \
    zcat "$in" | sed -n '/^COPY public\.request_cache_entries/,/^\\\.$/p'; } \
    | $KUBECTL exec -i deploy/aigw-db -n "$NAMESPACE" -- \
      psql -U aigateway -d aigateway -v ON_ERROR_STOP=1 >"$TMP/restore.log" 2>&1 \
    || { sed 's/^/    /' "$TMP/restore.log"; die "restore failed"; }
  local after
  after=$($KUBECTL exec deploy/aigw-db -n "$NAMESPACE" -- \
    psql -U aigateway -d aigateway -t -A -c "SELECT count(*) FROM request_cache_entries")
  log "restore complete: $before -> $after rows"
}

# -----------------------------------------------------------------------------
# OpenRouter credential provisioning
# -----------------------------------------------------------------------------
ensure_curlpod() {
  # A small helper pod (labeled to pass the aigateway NetworkPolicy) does API calls.
  if ! $KUBECTL get pod curlpod -n "$NAMESPACE" >/dev/null 2>&1; then
    $KUBECTL run curlpod --image=curlimages/curl:8.10.1 --restart=Never \
      -n "$NAMESPACE" --labels 'app.kubernetes.io/name=url4-runner' --command -- sleep 3600
    $KUBECTL wait --for=condition=Ready pod/curlpod -n "$NAMESPACE" --timeout=120s >/dev/null
  fi
}

provision_key() {
  if [ "${SKIP_PROVISION:-0}" = "1" ] || [ -z "$OPENROUTER_API_KEY" ]; then
    warn "skip provisioning the OpenRouter credential"
    return
  fi
  log "provisioning the OpenRouter credential for identity $PRIMARY_IDENTITY…"
  ensure_curlpod
  cat > "$TMP/openrouter.json" <<EOF
{"api_key":"$OPENROUTER_API_KEY"}
EOF
  local code
  code=$($KUBECTL exec -i curlpod -n "$NAMESPACE" -- curl -sS -o /dev/null -w '%{http_code}' -m 60 \
    -X PUT -H 'Content-Type: application/json' -H "X-User-Email: $PRIMARY_IDENTITY" \
    --data-binary @- "http://$ENGINE_SERVICE:9108/v1/connections/openrouter" < "$TMP/openrouter.json")
  if [ "$code" = "200" ]; then
    log "OpenRouter credential provisioned (provider=openrouter, identity=$PRIMARY_IDENTITY)"
  else
    warn "OpenRouter provisioning returned HTTP $code; check the engine and gateway logs"
  fi
}

# -----------------------------------------------------------------------------
# cloudflared tunnel
# -----------------------------------------------------------------------------
node_ip() {
  $KUBECTL get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}'
}

start_tunnel() {
  if [ "${SKIP_TUNNEL:-0}" = "1" ]; then
    log "tunnel skipped (SKIP_TUNNEL=1)"
    return
  fi
  command -v cloudflared >/dev/null 2>&1 || { warn "cloudflared not installed; tunnel skipped"; return; }
  [ -f "$TUNNEL_CREDS" ] || { warn "tunnel credentials missing at $TUNNEL_CREDS; tunnel skipped"; return; }
  if pgrep -f "cloudflared tunnel.*$TUNNEL_ID" >/dev/null 2>&1; then
    if [ -f "$TUNNEL_PID" ] && kill -0 "$(cat "$TUNNEL_PID")" 2>/dev/null; then
      log "tunnel already running (hostname=$TUNNEL_HOSTNAME)"
    else
      warn "a cloudflared tunnel for $TUNNEL_ID is already running, but not one this script"
      warn "started. It may point at an old cluster IP. Stop it with '$0 down', or"
      warn "run: pkill -f 'cloudflared tunnel.*$TUNNEL_ID'"
    fi
    return
  fi
  local ip
  ip="$(node_ip)"
  log "rendering tunnel config for $TUNNEL_HOSTNAME -> http://$ip:$EDGE_NODE_PORT"
  cat > "$TUNNEL_CFG" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $TUNNEL_CREDS

ingress:
  - hostname: $TUNNEL_HOSTNAME
    service: http://$ip:$EDGE_NODE_PORT
  - service: http_status:404
EOF
  log "starting cloudflared (log: $TUNNEL_LOG)"
  nohup cloudflared tunnel --config "$TUNNEL_CFG" run >"$TUNNEL_LOG" 2>&1 &
  echo "$!" > "$TUNNEL_PID"
  sleep 6
  log "tunnel started; public URL: https://$TUNNEL_HOSTNAME"
}

stop_tunnel() {
  if [ -f "$TUNNEL_PID" ]; then
    kill "$(cat "$TUNNEL_PID")" 2>/dev/null || true
    rm -f "$TUNNEL_PID"
  fi
  pkill -f "cloudflared tunnel.*$TUNNEL_ID" 2>/dev/null || true
}

# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------
cmd_up() {
  preflight
  cluster_up
  namespace_create
  helm_deps
  build_images
  load_images
  install_databases
  seed_cache
  install_aigateway
  install_engine
  install_scoreboard
  install_ui
  deploy_edge
  provision_key
  start_tunnel
  log "stack is up"
  cat <<EOF

  Public engine URL : https://$TUNNEL_HOSTNAME
  Namespace          : $NAMESPACE (cluster $CLUSTER_NAME)
  In-cluster gateway : $ENGINE_BASE_URL

  Next steps:
    - log in once from your machine:
        from the repo:   uv run python -c "from screamingface import Client; Client(engine_url='https://$TUNNEL_HOSTNAME').login()"
    - run an evaluation, for example:
        uv run python -c "from screamingface import Client, Model; c=Client(engine_url='https://$TUNNEL_HOSTNAME'); c.login(); print(c.evaluate(Model('openrouter/openai/gpt-5.5'), benchmark='healthbench-worst30', limit=1))"
EOF
}

cmd_down() {
  stop_tunnel
  if _cluster_exists; then
    log "deleting kind cluster $CLUSTER_NAME…"
    kind delete cluster --name "$CLUSTER_NAME"
  else
    log "no cluster $CLUSTER_NAME to delete"
  fi
  log "down complete (images are kept for the next up)"
}

_cluster_exists() { kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; }

cmd_status() {
  echo "== cluster =="
  _cluster_exists && $KUBECTL get nodes -o wide || echo "no cluster $CLUSTER_NAME"
  echo "== helm releases =="
  _cluster_exists && helm ls -n "$NAMESPACE" || true
  echo "== pods =="
  _cluster_exists && $KUBECTL get pods -n "$NAMESPACE" -o wide || true
  echo "== tunnel =="
  if pgrep -f "cloudflared tunnel.*$TUNNEL_ID" >/dev/null 2>&1; then
    echo "running (log: $TUNNEL_LOG)"
  else
    echo "not running"
  fi
}

cmd_smoke() {
  _cluster_exists || die "cluster $CLUSTER_NAME is down; run: $0 up"
  ensure_curlpod
  log "gateway health…"
  $KUBECTL exec curlpod -n "$NAMESPACE" -- curl -sS -m 10 http://aigw-aigateway:9105/healthz
  echo
  log "engine health (via identity edge)…"
  $KUBECTL exec curlpod -n "$NAMESPACE" -- curl -sS -m 10 http://sf-edge:8080/healthz
  echo
  log "providers (openrouter present?)…"
  $KUBECTL exec curlpod -n "$NAMESPACE" -- curl -sS -m 10 \
    -H "X-User-Email: $PRIMARY_IDENTITY" http://aigw-aigateway:9105/v1/providers \
    | grep -o '"id":"openrouter"' || true
  log "connections (identity=$PRIMARY_IDENTITY)…"
  $KUBECTL exec curlpod -n "$NAMESPACE" -- curl -sS -m 10 \
    -H "X-User-Email: $PRIMARY_IDENTITY" http://screamingface-engine-url4-cloud:9108/v1/connections \
    | grep -o '"provider":"openrouter","display_name":"OpenRouter"[^}]*' | head -1 || true
  log "gateway chat (model openrouter/openai/gpt-5.5)…"
  $KUBECTL exec -i curlpod -n "$NAMESPACE" -- curl -sS -m 120 -X POST \
    -H 'Content-Type: application/json' -H "X-User-Email: $PRIMARY_IDENTITY" \
    --data-binary @- http://aigw-aigateway:9105/v1/chat/completions <<'EOF' | head -c 300
{"model":"openrouter/openai/gpt-5.5","messages":[{"role":"user","content":"Reply with exactly: pong"}],"max_tokens":16}
EOF
  echo
  log "smoke done"
}

cmd_help() {
  sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-help}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  smoke)  cmd_smoke ;;
  seed)   _cluster_exists || die "cluster $CLUSTER_NAME is down; run: $0 up"
          seed_cache ;;
  snapshot-cache) shift; snapshot_cache "${1:-}" ;;
  restore-cache)  shift; restore_cache "${1:-}" ;;
  help|-h|--help) cmd_help ;;
  *) echo "unknown command: $1"; cmd_help ;;
esac
