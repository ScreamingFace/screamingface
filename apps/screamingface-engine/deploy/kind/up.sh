#!/usr/bin/env bash
set -euo pipefail

# Bring up the uniform executor kind environment (test-plan §5). Idempotent: re-running
# rebuilds the images, reloads them, and `helm upgrade`s the existing release in place rather
# than failing on anything that already exists.
#
#   deploy/kind/up.sh                             # queue runner
#
# Any extra arguments are passed straight through to `helm upgrade --install` after
# `-f values-kind.yaml`, so `--set`/`-f` overrides both work.
#
# ROLLOUT ORDER (implementation-notes.md D7): the App and the worker refuse to start while a
# legacy `url4-cloud_<topic>` stream still exists. A fresh cluster has none, so this script never
# needs `admin purge-legacy-streams` — see README.md for the upgrade-from-legacy order.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${HERE}/../.." && pwd)"       # apps/screamingface-engine
REPO_ROOT="$(cd "${APP_ROOT}/../.." && pwd)"  # repo root — the build context every image needs

CLUSTER_NAME="sf-uniform"
KIND_CONTEXT="kind-${CLUSTER_NAME}"
RELEASE="sf-uniform"
NAMESPACE="default"
APP_DEPLOYMENT="${RELEASE}-url4-cloud"
RUNNER_DEPLOYMENT="${RELEASE}-url4-cloud-runner"
NATS_STATEFULSET="sf-uniform-nats" # must match values-kind.yaml's nats.fullnameOverride

ENGINE_BASE_TAG="screamingface-engine:kind-base"
ENGINE_TAG="screamingface-engine:kind"
BENCHMARK_TAG="screamingface-engine-benchmark:kind"
STUB_TAG="aigw-stub:kind"

echo "==> [1/6] kind cluster (${CLUSTER_NAME})"
if ! kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  kind create cluster --name "${CLUSTER_NAME}" --config "${HERE}/kind-config.yaml"
else
  echo "    already exists"
fi

echo "==> [2/6] docker build (context: ${REPO_ROOT})"
# The base image (no overlay), then the kind-only world-config overlay, then the benchmark
# image FROM the overlay — the same three-image shape release-screamingface-engine.yml builds,
# with one extra layer in between (engine-kind.Dockerfile) that only this environment needs.
docker build -f "${APP_ROOT}/Dockerfile" -t "${ENGINE_BASE_TAG}" "${REPO_ROOT}"
docker build -f "${HERE}/engine-kind.Dockerfile" \
  --build-arg "BASE=${ENGINE_BASE_TAG}" \
  -t "${ENGINE_TAG}" "${REPO_ROOT}"
# Gated datasets (xstest_safe, OME-1269) download only with a Hugging Face token. docker build
# never sees shell variables, so the token goes in as the `hf_token` BuildKit secret. Without
# one, this local cluster skips gated boards ON PURPOSE (a PR-build-style skip) rather than
# failing step 2 for every developer; the skipped board says so if you run it.
benchmark_build_args=(--build-arg "BASE=${ENGINE_TAG}")
if [ -n "${HF_TOKEN:-}" ]; then
  benchmark_build_args+=(--secret "id=hf_token,env=HF_TOKEN")
else
  echo "    NOTE: HF_TOKEN is not set, so gated benchmarks (xstest_safe) are skipped in this image."
  echo "          To include them: export HF_TOKEN=<read-only token from a Hugging Face account"
  echo "          that accepted https://huggingface.co/datasets/walledai/XSTest>"
  benchmark_build_args+=(--build-arg "SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN=1")
fi
docker build -f "${APP_ROOT}/Dockerfile.benchmark" \
  "${benchmark_build_args[@]}" \
  -t "${BENCHMARK_TAG}" "${REPO_ROOT}"
docker build -f "${HERE}/aigw-stub/Dockerfile" -t "${STUB_TAG}" "${HERE}/aigw-stub"

echo "==> [3/6] kind load docker-image"
kind load docker-image "${ENGINE_TAG}" "${BENCHMARK_TAG}" "${STUB_TAG}" --name "${CLUSTER_NAME}"
# WHY: each load leaves the previous image behind in the nodes' containerd as an untagged
# `import-<date>@sha256:...` ref that `crictl rmi --prune` does not collect; a day of rebuilds
# filled the Docker VM's disk (the next build then failed with "Not enough disk space").
for node in $(kind get nodes --name "${CLUSTER_NAME}"); do
  docker exec "${node}" sh -c \
    'ctr -n k8s.io images ls -q | grep "^import-" | xargs -r ctr -n k8s.io images rm >/dev/null 2>&1 || true'
done

echo "==> [4/6] aigw-stub"
kubectl --context "${KIND_CONTEXT}" apply -f "${HERE}/aigw-stub/k8s.yaml"
# WHY restart: the image TAG never changes (`:kind`), so a re-run's freshly loaded image is
# not picked up by an unchanged pod spec — without this a redeploy silently keeps old code.
kubectl --context "${KIND_CONTEXT}" rollout restart deployment/aigw-stub
kubectl --context "${KIND_CONTEXT}" rollout status deployment/aigw-stub --timeout=120s

echo "==> [5/6] helm upgrade --install ${RELEASE}"
# WHY no `helm dependency build`: charts/nats-1.2.2.tgz is already vendored (Chart.lock); a
# fresh machine has no `helm repo` registered for the upstream nats-io repo, and dependency
# build fails resolving it for no benefit — templating/installing reads the vendored archive
# directly (the same reasoning as the CI `chart` job's own "Template with the bundled NATS
# subchart" step).
helm upgrade --install "${RELEASE}" "${APP_ROOT}/deploy/helm" \
  --kube-context "${KIND_CONTEXT}" \
  --namespace "${NAMESPACE}" \
  --create-namespace \
  -f "${HERE}/values-kind.yaml" \
  "$@" \
  --wait --timeout 5m

echo "==> [6/6] restart onto the freshly loaded images, then rollout status"
# Same reason as the stub above: the `:kind` tag does not change between runs.
kubectl --context "${KIND_CONTEXT}" -n "${NAMESPACE}" rollout restart \
  "deployment/${APP_DEPLOYMENT}" "deployment/${RUNNER_DEPLOYMENT}"
kubectl --context "${KIND_CONTEXT}" -n "${NAMESPACE}" rollout status \
  "deployment/${APP_DEPLOYMENT}" --timeout=180s
kubectl --context "${KIND_CONTEXT}" -n "${NAMESPACE}" rollout status \
  "deployment/${RUNNER_DEPLOYMENT}" --timeout=180s
kubectl --context "${KIND_CONTEXT}" -n "${NAMESPACE}" rollout status \
  "statefulset/${NATS_STATEFULSET}" --timeout=180s

cat <<EOF

Ready.

Port-forward the App (a session fixture in tests/kind/conftest.py does this automatically):
  kubectl --context ${KIND_CONTEXT} -n ${NAMESPACE} port-forward svc/${APP_DEPLOYMENT} 18108:9108

Then e.g.:
  curl -sX POST http://127.0.0.1:18108/token

Run the kind test suite:
  uv run pytest tests/kind -m kind -q
EOF
