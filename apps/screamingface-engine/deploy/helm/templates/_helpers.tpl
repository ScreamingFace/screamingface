{{/*
Name helpers + k8s recommended labels (app.kubernetes.io/*) — spec §9 / docs/protocol.md §9.
*/}}

{{- define "screamingface-engine.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "screamingface-engine.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "screamingface-engine.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "screamingface-engine.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Recommended labels MINUS `component` — shared by `labels` (fixes `control-plane`) and
`nodeLabels` (fixes `node`), so a label added or changed here reaches both call sites from one
place instead of two near-identical blocks that can silently drift apart. Uses the RELEASE's own
`instance` (not the node's own `<release>-node`) — object metadata is not a selector, so
`kubectl get -l app.kubernetes.io/instance=<release>` finds every object the release owns,
node-tier objects included.
*/}}
{{- define "screamingface-engine.labelsBase" -}}
helm.sh/chart: {{ include "screamingface-engine.chart" . }}
{{ include "screamingface-engine.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: screamingface
{{- end -}}

{{/* Common labels: k8s recommended set (name/instance/version/managed-by/part-of) + chart. */}}
{{- define "screamingface-engine.labels" -}}
{{ include "screamingface-engine.labelsBase" . }}
app.kubernetes.io/component: control-plane
{{- end -}}

{{/* Selector labels: the immutable identity subset (name + instance). */}}
{{- define "screamingface-engine.selectorLabels" -}}
app.kubernetes.io/name: {{ include "screamingface-engine.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "screamingface-engine.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "screamingface-engine.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "screamingface-engine.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{/*
Runner pool pods use the benchmark image, which layers private grading assets onto the matching
control-plane release. Deriving both repository and tag keeps mirrors and upgrades paired; an
operator may override either value when their registry uses a different naming convention.
*/}}
{{- define "screamingface-engine.runnerImage" -}}
{{- $repo := .Values.runner.image.repository | default (printf "%s-benchmark" .Values.image.repository) -}}
{{- $tag := .Values.runner.image.tag | default (default .Chart.AppVersion .Values.image.tag) -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}

{{/*
Where the App reaches NATS.

WHY a helper and not a plain value: the previous default hardcoded `nats://screamingface-engine-nats:4222`,
which only resolves when the release happens to be named `screamingface-engine` — the subchart's Service is
`<release>-nats`. Enabling the subchart under any other release name pointed the App at a Service
that does not exist, and nothing caught it until a live connect failed.

We deliberately do NOT derive this from the subchart's own `nats.fullname` helper: that reaches
into another chart's private template names and breaks on a dependency bump. Instead the operator
states the Service name once (`nats.fullnameOverride`) and this fails at render time — at
`helm install`, not on the first publish — if neither source is present.
*/}}
{{- define "screamingface-engine.natsUrl" -}}
{{- if .Values.config.natsUrl -}}
{{- .Values.config.natsUrl -}}
{{- else if .Values.nats.enabled -}}
{{- $n := required "nats.fullnameOverride is required when nats.enabled=true (it fixes the Service name this URL is built from) — or set config.natsUrl explicitly" .Values.nats.fullnameOverride -}}
{{- printf "nats://%s:4222" $n -}}
{{- else -}}
{{- fail "config.natsUrl is required when nats.enabled=false — the App has no bus to reach otherwise" -}}
{{- end -}}
{{- end -}}

{{/* Name of the Secret holding the JWT signing secret (created here or supplied). */}}
{{- define "screamingface-engine.authSecretName" -}}
{{- if .Values.auth.create -}}
{{- include "screamingface-engine.fullname" . -}}
{{- else -}}
{{- required "auth.existingSecret is required when auth.create is false" .Values.auth.existingSecret -}}
{{- end -}}
{{- end -}}

{{/*
Name of the Secret holding the Tavily web-tools key. An `existingSecret` wins (bring-your-own,
the prod shape); otherwise the chart creates `<fullname>-tavily` from `tavily.apiKey`.
Only referenced when `tavily.enabled` — the pool's pods name this Secret in their env and the
App never reads it.
*/}}
{{- define "screamingface-engine.tavilySecretName" -}}
{{- if .Values.tavily.existingSecret -}}
{{- .Values.tavily.existingSecret -}}
{{- else -}}
{{- printf "%s-tavily" (include "screamingface-engine.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
The Secret holding the object-storage secret access key (OME-929).

`artifactStorage.s3.existingSecret` wins when set (the prod shape — created out-of-band or by an
External Secrets / Sealed Secrets flow); otherwise the chart creates `<fullname>-artifact-storage`.

INVARIANT: attached by `envFrom.secretRef` to BOTH the App Deployment and the runner pool, which
injects each key under its OWN name — so the key MUST be `URL4_CLOUD_ARTIFACT_S3_SECRET_KEY`, the
variable both halves read. Unlike the Tavily Secret, the App reads this one too: it is the read
side of the hand-off.
*/}}
{{/*
The Secret carrying OTEL_EXPORTER_OTLP_HEADERS — an operator's own when supplied, else the
chart's. Same shape as the Tavily and artifact-storage helpers, so `existingSecret` means the
same thing everywhere in this chart.
*/}}
{{- define "screamingface-engine.tracingSecretName" -}}
{{- if .Values.tracing.existingSecret -}}
{{- .Values.tracing.existingSecret -}}
{{- else -}}
{{- printf "%s-tracing" (include "screamingface-engine.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Whether the pool should attach a tracing Secret at all. Distinct from `tracing.enabled`:
headers are OPTIONAL (an in-cluster collector needs no credential), so enabling tracing must
not by itself reference a Secret that will never be created — an unresolvable `envFrom` stops
the pool from starting, turning "I forgot the credential I did not need" into an outage.
*/}}
{{- define "screamingface-engine.tracingHasSecret" -}}
{{- if and .Values.tracing.enabled (or .Values.tracing.existingSecret .Values.tracing.headers) -}}
true
{{- end -}}
{{- end -}}

{{- define "screamingface-engine.artifactSecretName" -}}
{{- if .Values.artifactStorage.s3.existingSecret -}}
{{- .Values.artifactStorage.s3.existingSecret -}}
{{- else -}}
{{- printf "%s-artifact-storage" (include "screamingface-engine.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
The node tier's object name (`<fullname>-node`), shared by its Deployment, Service,
NetworkPolicy and PodDisruptionBudget. A helper rather than four copies of the same printf, so
the App's `node_base_url` cannot name a Service the chart does not render.
*/}}
{{- define "screamingface-engine.nodeName" -}}
{{- printf "%s-node" (include "screamingface-engine.fullname" .) -}}
{{- end -}}

{{/*
Where the App forwards a known mount (contracts.md C2, D6). Only the composition root knows a
node tier exists in a deployment, so this is derived from the same name helper the node objects
use — a wrong guess would silently forward to nothing. The App mounts its forwarder ONLY when
this value is set (`config.Settings.node_base_url`), so a disabled tier arms nothing.
*/}}
{{- define "screamingface-engine.nodeBaseUrl" -}}
{{- printf "http://%s:%v" (include "screamingface-engine.nodeName" .) .Values.node.service.port -}}
{{- end -}}

{{/*
Node-tier SELECTOR labels (FX-80, §2.5): the SAME `name` as the App and runner pool (aigateway's
NetworkPolicy admits by that name), but a DIFFERENT `instance` — `<release>-node` rather than
`<release>`.

WHY this must differ: the App's own Service and Deployment select on the plain {name, instance}
pair, WITH NO component qualifier (`screamingface-engine.selectorLabels`). Kubernetes selector
matching is a SUBSET test — a pod carrying extra labels still matches — so before this helper
existed the node pods (same name, same instance, PLUS component: node) were silently inside the
App Service's endpoints and the App Deployment's replace/evict blast radius too. Giving the node
its own instance breaks that subset match with no change on the App side at all: `<release>-node`
can never equal `<release>`.

Also carries `component: node` itself: every one of its five call sites (the node Deployment's
own selector AND its pod template, its Service, its NetworkPolicy, its PDB) appended the same
literal by hand right after including this, so the label belongs in the one place those call
sites share rather than five near-identical copies.
*/}}
{{- define "screamingface-engine.nodeSelectorLabels" -}}
app.kubernetes.io/name: {{ include "screamingface-engine.name" . }}
app.kubernetes.io/instance: {{ printf "%s-node" .Release.Name }}
app.kubernetes.io/component: node
{{- end -}}

{{/*
Full recommended labels for node-tier OBJECTS' own `metadata.labels` (FX-87, review round #3/#4):
`screamingface-engine.labels` always resolves `app.kubernetes.io/component: control-plane`, and
every node template used to append `component: node` right after it — a genuine YAML duplicate
mapping key. Most parsers silently keep the LAST occurrence (which happened to be correct here),
but that is luck, not a contract. Built from the SAME `labelsBase` as `labels`, so the key is
written exactly once and a label change has one home.

WHY `instance` is the RELEASE's own here, NOT `nodeSelectorLabels`' `<release>-node`: this is
OBJECT metadata, not a selector — `kubectl get -l app.kubernetes.io/instance=<release>` must
still find the node's Service/PDB/NetworkPolicy/Deployment. Only the SELECTOR-bearing fields
(the node's own Deployment `spec.selector`, its pod template labels, the node Service's
selector, the NetworkPolicy's `podSelector`, the PDB's selector) use `nodeSelectorLabels`
(§2.5) — that is the narrow set the App/node collision fix actually needs.
*/}}
{{- define "screamingface-engine.nodeLabels" -}}
{{ include "screamingface-engine.labelsBase" . }}
app.kubernetes.io/component: node
{{- end -}}

{{/*
Name of the Secret holding the shared artifact-signing key (OQ-3.2). An `existingSecret` wins
(the prod shape — created out-of-band or by an External Secrets / Sealed Secrets flow);
otherwise the chart creates `<fullname>-artifact-signing`. The SAME name reaches both tiers:
the node signs the 303, the App verifies it.
*/}}
{{- define "screamingface-engine.artifactSigningSecretName" -}}
{{- if .Values.artifactSigning.existingSecret -}}
{{- .Values.artifactSigning.existingSecret -}}
{{- else -}}
{{- printf "%s-artifact-signing" (include "screamingface-engine.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
The checksum BOTH tiers' `checksum/artifact-signing` pod annotations key on (review round #2).

WHY not hash the rendered `secret-artifact-signing.yaml` template (the ORIGINAL, and wrong,
approach): with no `existingSecret`/`signingKey`, that template's `lookup` reads the live
cluster and is EMPTY under `helm template` (no cluster to query — GitOps' own render path), so
it falls back to `randAlphaNum`, a NEW random value on every single offline render. Hashing that
rolls the App and the node on every GitOps sync even though nothing about the key actually
changed — and this App holds live WebSocket relays, so that is not a free restart.

This hashes the KEY'S SOURCE instead, which is stable unless an operator actually changes it:
`artifactSigning.signingKey` when pinned, else `artifactSigning.existingSecret`'s NAME (rotating
that Secret's contents out-of-band is the operator's own concern, same as any other
`existingSecret`), else one FIXED constant for the chart-generated-and-`lookup`-reused case — a
real `helm upgrade` reuses the SAME key via `lookup` there, so nothing needs to roll for it; only
`signingKey`/`existingSecret` are meant to change under an intentional rotation.
*/}}
{{- define "screamingface-engine.artifactSigningChecksum" -}}
{{- if .Values.artifactSigning.signingKey -}}
{{- .Values.artifactSigning.signingKey | sha256sum -}}
{{- else if .Values.artifactSigning.existingSecret -}}
{{- .Values.artifactSigning.existingSecret | sha256sum -}}
{{- else -}}
{{- "screamingface-engine.artifactSigning.chart-generated" | sha256sum -}}
{{- end -}}
{{- end -}}

{{/*
Where the object store lives. Explicit `artifactStorage.s3.endpointUrl` wins; otherwise, with the
bundled instance enabled, its in-cluster Service. Failing render is deliberate: an empty endpoint
would leave the App to refuse startup with a less specific message than this one.
*/}}
{{- define "screamingface-engine.artifactEndpointUrl" -}}
{{- if .Values.artifactStorage.s3.endpointUrl -}}
{{- .Values.artifactStorage.s3.endpointUrl -}}
{{- else if .Values.garage.enabled -}}
{{- printf "http://%s-garage:3900" (include "screamingface-engine.fullname" .) -}}
{{- else -}}
{{- fail "artifactStorage.backend=s3 needs either artifactStorage.s3.endpointUrl or garage.enabled=true" -}}
{{- end -}}
{{- end -}}
