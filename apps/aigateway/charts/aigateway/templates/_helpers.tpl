{{- define "aigateway.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aigateway.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "aigateway.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "aigateway.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aigateway.labels" -}}
helm.sh/chart: {{ include "aigateway.chart" . }}
app.kubernetes.io/name: {{ include "aigateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: screamingface
{{- end -}}

{{/*
The resolved auth mode — the ONE place the chart decides how the gateway authenticates.

`config.authEnabled` is the legacy boolean and still means what it always did: false => every
caller is anonymous, which is the `disabled` mode. Resolving it here (rather than emitting both
variables) keeps a single value on the wire, so the app's own conflict check cannot be tripped by
a chart that says "enabled: true" and "mode: disabled" in two different keys.
*/}}
{{- define "aigateway.authMode" -}}
{{- if not .Values.config.authEnabled -}}
disabled
{{- else -}}
{{- .Values.config.authMode -}}
{{- end -}}
{{- end -}}

{{/*
Refuse the configurations that would quietly hand anyone any identity.

INVARIANT: `cloudflare_headers` trusts `X-User-Email` because the mesh guarantees a client cannot
set it. Publishing an Ingress straight to this Service removes that guarantee — the port
becomes directly reachable and a `curl -H 'X-User-Email: admin@…'` is a full impersonation. The
chart cannot verify the mesh, but it CAN refuse the one combination that is unsafe on its face.
*/}}
{{- define "aigateway.validateAuth" -}}
{{- if and (not .Values.config.authEnabled) (ne .Values.config.authMode "disabled") -}}
{{- fail (printf "config.authEnabled=false conflicts with config.authMode=%q — authEnabled is the legacy spelling of authMode=disabled; set one or the other, not two that disagree" .Values.config.authMode) -}}
{{- end -}}
{{- if and (eq (include "aigateway.authMode" .) "cloudflare_headers") (not .Values.config.allowedNetworks) -}}
{{- fail "config.authMode=cloudflare_headers with no config.allowedNetworks — the gateway trusts X-User-Email from any caller that can reach it, so the networks allowed to present it must be declared. The app refuses to start without AIGW_ALLOWED_NETWORKS; failing the render surfaces it here instead of as a CrashLoopBackOff. Set config.allowedNetworks to your cluster's Pod CIDR." -}}
{{- end -}}
{{- if and (eq (include "aigateway.authMode" .) "cloudflare_headers") .Values.ingress.enabled -}}
{{- fail "config.authMode=cloudflare_headers with ingress.enabled=true — header identity is only trustworthy while this Service is unreachable except through the mesh, and an Ingress makes it directly reachable, so any caller could set X-User-Email and become any principal. Either set ingress.enabled=false (keep aigateway internal) or use authMode=jwt." -}}
{{- end -}}
{{- end -}}

{{- define "aigateway.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aigateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
The gateway Pod's `app.kubernetes.io/component` value — the ONE place this chart decides it.

INVARIANT: the Pod template AND every selector that must name the gateway (the Service, the
NetworkPolicy, Garage's :3900 ingress) derive from this helper, so they cannot drift apart.

WHY configurable: `selectorLabels` (name+instance) match EVERY workload this chart renders — the
migrate Job and the bundled Garage included — so a selector that must name the gateway needs a
component label. But a platform that owns the network boundary may already have its own name for
this Pod (`component: server` across sf-aigw / sf-report-intake / sf-scoreboard). Hardcoding
`gateway` forced such a platform to restate it through `podLabels`, which rendered AFTER the Pod
template's own labels: the duplicate key won on the Pod, the Service selector kept demanding
`gateway`, and the Service matched ZERO Pods — Pod Running, Argo Synced, no Endpoints, nothing in
any log. Set `componentLabel` to adopt an existing convention and every selector moves with it.
*/}}
{{- define "aigateway.componentLabel" -}}
{{- .Values.componentLabel | default "gateway" -}}
{{- end -}}

{{/*
Refuse the `podLabels` spelling that silently empties this chart's Service.

`podLabels` cannot express a label this chart's selectors depend on: YAML duplicate-key
precedence decides the winner with no Helm error and no API-server rejection, so the override
detaches every caller from the gateway while everything still reports healthy. `componentLabel`
is the supported spelling because it moves the Pod label and the selectors together.
*/}}
{{- define "aigateway.validatePodLabels" -}}
{{- $reserved := "app.kubernetes.io/component" -}}
{{- if hasKey (.Values.podLabels | default dict) $reserved -}}
{{- fail (printf "podLabels sets %s=%q, which this chart's Service and NetworkPolicy select on. podLabels renders after the Pod template's own labels, so the override wins on the Pod and leaves the Service matching zero Pods (Pod Running, Argo Synced, no Endpoints). Set componentLabel=%q instead — it moves the Pod label and every selector together." $reserved (get .Values.podLabels $reserved) (get .Values.podLabels $reserved)) -}}
{{- end -}}
{{- end -}}

{{- define "aigateway.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "aigateway.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "aigateway.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "aigateway.authSecretName" -}}
{{- required "auth.existingSecret is required" .Values.auth.existingSecret -}}
{{- end -}}

{{- define "aigateway.snapshotSecretName" -}}
{{- printf "%s-snapshot-storage" (include "aigateway.fullname" .) -}}
{{- end -}}

{{/*
Refuse the one replica shape the snapshot design does not support.

INVARIANT (spec, accepted limitations): the weekly export assumes a SINGLE gateway replica.
Object keys share the second-resolution `cache-snapshots/<stamp>` prefix, and every replica
runs its own scheduler aimed at the same Friday 05:00 UTC — two replicas therefore fire with
the SAME stamp and can interleave their PUTs, pairing one replica's archive bytes with the
other's manifest. The v1 contract logs this as a single-replica assumption rather than
serializing (cross-replica locking is named future work), so the chart enforces what the
spec assumed: snapshots on means one writer, or the render fails here — not silently, a
week later, as a corrupted backup pair.
*/}}
{{- define "aigateway.validateSnapshot" -}}
{{- if and .Values.snapshot.enabled (gt (int .Values.replicaCount) 1) -}}
{{- fail (printf "snapshot.enabled=true requires replicaCount=1 (got %d): every replica runs its own export scheduler against the same second-resolution cache-snapshots/<stamp> keys, so two replicas firing at Friday 05:00 UTC can overwrite each other's archive/manifest pair. This is the spec's logged single-replica invariant (OME-1021); cross-replica serialization (Postgres advisory lock / CronJob) is future work. Set replicaCount=1 or snapshot.enabled=false." (int .Values.replicaCount)) -}}
{{- end -}}
{{- end -}}

{{- define "aigateway.snapshotEndpoint" -}}
{{- /* The S3 endpoint the gateway signs against: the bundled Garage Service when enabled,
     else the operator-declared external endpoint (the app fails fast if it is missing). */ -}}
{{- if .Values.snapshot.garage.enabled -}}
{{- printf "http://%s-garage:3900" (include "aigateway.fullname" .) -}}
{{- else -}}
{{- .Values.snapshot.storage.endpointUrl -}}
{{- end -}}
{{- end -}}
