# OME-965 — tenant Preview automation specification

## Result

A same-repository pull request selects only affected deployable components, publishes only
their pull-request images, and enters the bounded Preview queue after exact-revision readiness.

## Selection contract

- AI Gateway, AI Gateway UI, Scoreboard, and Engine use independent component and image labels.
- A chart-only change selects its runtime component without rebuilding its image.
- Tests and documentation alone select no Preview runtime.
- `packages/url4/` selects the Engine runtime and builds Engine plus its benchmark image.
- A root `.dockerignore` change selects every runtime and all five images.
- Rename detection considers both old and new paths.

## Supply contract

- Only same-repository, non-draft pull requests can use the Azure Preview identity.
- Images publish to `acropenminedpreview.azurecr.io` with tag `pr-<number>-<sha7>`.
- The benchmark image uses the exact pull-request Engine image as its base.
- The workflow records the full 40-character revision in OCI labels and its maintained comment.
- Pull-request automation receives no Kubernetes credential.

## Lifecycle contract

- `preview-building` means required images are not ready.
- `preview-queued` means images are ready but no slot is available.
- `preview` authorizes Argo discovery.
- `preview-expired` records automatic removal after 72 hours.
- `no-preview` disables Preview automation.
- At most three open pull requests carry `preview`.
- A serialized default-branch reconciler promotes queued requests and expires active requests.
- Close, merge, draft conversion, fork origin, and empty selection remove managed Preview labels.

## Developer contract

The maintained pull-request comment shows status, exact revision, selected images, application
URLs, one trusted Kubernetes access helper command, reconnect steps, copy-ready debug commands,
and namespace-filtered SigNoz links.

The helper performs Cloudflare login, GitHub author verification, safe download, and kubeconfig
validation. It comes from trusted `main`, never from pull-request code.

Debug commands use the exact pull-request namespace, stable deployment names, and stable pod
labels. SigNoz filters use the `k8s.namespace.name` field.

The downloaded kubeconfig stays on the developer machine. Its Kubernetes token lasts one hour.

## Security

- The image workflow uses `pull_request`, never `pull_request_target`.
- Azure OIDC runs only when the pull-request head repository equals the base repository.
- The Preview identity can push only to the disposable Preview registry.
- The admission workflow runs trusted default-branch code and never checks out pull-request code.
