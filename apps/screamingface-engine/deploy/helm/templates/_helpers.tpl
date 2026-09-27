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
Recommended labels MINUS `component` — shared by every helper that fixes a `component` value
(`labels` fixes `control-plane`, `garageSelectorLabels` fixes `garage`), so a label added or
changed here reaches every call site from one place instead of several near-identical blocks
that can silently drift apart. Uses the RELEASE's own `instance` — object metadata is not a
selector, so `kubectl get -l app.kubernetes.io/instance=<release>` finds every object the
release owns.
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

{{/*
The bundled Garage's selector labels. WHY a name of its own (kind suite finding): Garage pods
carrying the App's `selectorLabels` (plus a component label) were ALSO matched by the App
Service's name+instance selector, so App traffic — and a port-forward to the App — could land on
Garage. A StatefulSet selector cannot change in place: an existing bundled Garage (dev only) must
be deleted before upgrading past this change.
*/}}
{{- define "screamingface-engine.garageSelectorLabels" -}}
app.kubernetes.io/name: {{ include "screamingface-engine.name" . }}-garage
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: garage
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

{{/*
DEC-2 / DC-D1 (uniform executor PRD 05): the node tier is gone, and `values.schema.json` stubs
`node` to a bare, permissive description so a leftover `node:` block passes schema validation
instead of failing with `additionalProperties` noise. This is the clear failure in its place —
included at the top of `configmap.yaml`, the one template that always renders, so ANY values
file that still sets `node` (any key under it, not only `node.enabled`) fails the render with a
message naming the change and pointing at the plan, rather than being silently ignored.
*/}}
{{- define "screamingface-engine.nodeTierRemoved" -}}
{{- if hasKey .Values "node" -}}
{{- fail "node: the node tier was removed — mount calls run as direct runs on the runner pool (apps/screamingface-engine/docs/plans/uniform-executor/prd/05-node-tier-decommission.md). Delete the node: block from your values." -}}
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
Name of the Secret holding the shared artifact-signing key (OQ-3.2). An `existingSecret` wins
(the prod shape — created out-of-band or by an External Secrets / Sealed Secrets flow);
otherwise the chart creates `<fullname>-artifact-signing`. The App both signs a mount result's
303 with it and verifies it on fetch (uniform executor PRD 05, DC-D3).
*/}}
{{/*
Whether the App holds an artifact-signing key (uniform executor PRD 05, DC-D3): a key or an
existing Secret is configured. The App signs the 303 of a mount result over 1 MiB with it; with
neither, such a result is streamed inline and counted (MC-D9).
*/}}
{{- define "screamingface-engine.artifactSigningConfigured" -}}
{{- if or .Values.artifactSigning.signingKey .Values.artifactSigning.existingSecret -}}true{{- end -}}
{{- end -}}

{{- define "screamingface-engine.artifactSigningSecretName" -}}
{{- if .Values.artifactSigning.existingSecret -}}
{{- .Values.artifactSigning.existingSecret -}}
{{- else -}}
{{- printf "%s-artifact-signing" (include "screamingface-engine.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
The checksum the App's `checksum/artifact-signing` pod annotation keys on (review round #2).

It hashes the KEY'S SOURCE: `artifactSigning.signingKey` when pinned, else
`artifactSigning.existingSecret`'s NAME (rotating that Secret's contents out-of-band is the
operator's own concern, same as any other `existingSecret`). The annotation renders only when
one of the two is set (`artifactSigningConfigured`); the chart never generates a key (DC-D3).
*/}}
{{- define "screamingface-engine.artifactSigningChecksum" -}}
{{- if .Values.artifactSigning.signingKey -}}
{{- .Values.artifactSigning.signingKey | sha256sum -}}
{{- else -}}
{{- .Values.artifactSigning.existingSecret | sha256sum -}}
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
