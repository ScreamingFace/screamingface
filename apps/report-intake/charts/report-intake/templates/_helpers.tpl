{{- define "report-intake.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "report-intake.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "report-intake.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "report-intake.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "report-intake.labels" -}}
helm.sh/chart: {{ include "report-intake.chart" . }}
app.kubernetes.io/name: {{ include "report-intake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: screamingface
{{- end -}}

{{- define "report-intake.selectorLabels" -}}
app.kubernetes.io/name: {{ include "report-intake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "report-intake.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "report-intake.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "report-intake.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{/*
The name of the route the identity edge attaches to.

Resolved in a helper because TWO objects have to agree on it — the identity HTTPRoute and the
SecurityPolicy that targets it BY NAME. A policy naming a route that does not exist attaches to
nothing, verifies nothing, and still reports Accepted; the engine chart learned that the same way.
*/}}
{{- define "report-intake.identityRouteName" -}}
{{- printf "%s-identity" (include "report-intake.fullname" .) -}}
{{- end -}}

{{/*
The database URL, from a Secret. The Deployment and the migration Job both need it and must not
disagree, and the URL carries a password, so it is never a chart value.
*/}}
{{- define "report-intake.databaseEnv" -}}
- name: REPORT_INTAKE_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ required "database.existingSecret is required — the database URL carries a password and is never a chart value" .Values.database.existingSecret }}
      key: {{ .Values.database.existingSecretKey }}
{{- end -}}

{{/*
Refuse, at render time, every configuration this service would refuse at boot — and the one the
chart alone can see.

WHY a render-time refusal rather than a note in values.yaml: each combination below produces a
deployment that LOOKS installed. `helm upgrade` reports success, the object count is right, and
the failure is either a CrashLoopBackOff whose reason is one line deep in a pod log, or — worse —
a pod that serves happily with a posture nobody chose. Both are discovered by someone forging a
request rather than by the person who typed the value.

The three `mesh_or_turnstile` conditions MIRROR `report_intake.main`'s own startup guards
(`_check_auth_mode`). Duplicating them here is deliberate: the app's guard fires after the image
is pulled and scheduled, and its message reaches a log nobody is watching during an upgrade.

WHAT THIS CANNOT CHECK: whether `config.forwardedAllowIps` overlaps `config.allowedNetworks` —
that needs CIDR arithmetic Helm's template functions do not have. The `"*"` case is a string
compare and IS refused here; the general overlap is asserted by
`.github/scripts/verify_chart_wiring.py`, which has Python's `ipaddress`, and by the app itself
at boot.

WHY THIS IS INCLUDED FROM EVERY TEMPLATE THAT CAN FAIL, rather than once: Helm aborts a render at
the first template that raises, and the order it walks them in is not something this chart
controls. Included only from the ConfigMap, `--set anonymous.enabled=true` aborted inside the
public route's `required` on `gateway.parentRef.name` — a true statement about a missing value,
and completely the wrong sentence to hand someone who has just turned on an unauthenticated
write. Every template carrying a `required` or a `fail` opens with this line so the diagnosis is
the same whichever one Helm reaches first; the three that can raise nothing do not.
*/}}
{{- define "report-intake.validate" -}}
{{- $modes := list "disabled" "mesh_or_turnstile" -}}
{{- if not (has .Values.config.authMode $modes) -}}
{{- fail (printf "config.authMode=%q is not a mode this service has. It is one of: disabled (loopback-only, for local development) or mesh_or_turnstile (the deployed posture). A value pydantic cannot parse is a pod that crashes on every start." .Values.config.authMode) -}}
{{- end -}}
{{- if eq .Values.config.authMode "mesh_or_turnstile" -}}
{{- if not .Values.config.allowedNetworks -}}
{{- fail "config.authMode=mesh_or_turnstile trusts an identity header the mesh injects, so the peers allowed to inject it must be declared — set config.allowedNetworks to your cluster's Pod CIDR. Left empty, the peer check denies everything: no request can ever be mesh-verified, every caller including the mesh's own falls to the bot gate, and the pod refuses to start." -}}
{{- end -}}
{{- if not .Values.turnstile.enabled -}}
{{- fail "config.authMode=mesh_or_turnstile gates anonymous callers on Cloudflare Turnstile, so set turnstile.enabled=true and turnstile.existingSecret. Without the secret siteverify rejects THIS service's own credentials, which the gate correctly reads as unevaluable — so every anonymous report is answered 503 forever while the pod reports itself healthy and ready. The app refuses to start for the same reason." -}}
{{- end -}}
{{- if not (or .Values.networkPolicy.enabled .Values.networkPolicy.acknowledgeUnrestricted) -}}
{{- fail "config.authMode=mesh_or_turnstile with networkPolicy.enabled=false — the peer check authenticates a NETWORK, and config.allowedNetworks is at best your whole Pod CIDR, so every workload in the cluster can dial this ClusterIP and have its X-User-Email believed as mesh-verified. The HTTPRoute filters strip that header only from traffic through the edge; the direct in-cluster path has no filter, and a caller admitted on identity skips the Turnstile gate and the rate limit too. Set networkPolicy.enabled=true with networkPolicy.clientPodNames naming your mesh gateway's data plane — or, where something outside this chart already restricts who may reach the Service, set networkPolicy.acknowledgeUnrestricted=true to say so deliberately." -}}
{{- end -}}
{{- end -}}
{{- if .Values.anonymous.enabled -}}
{{- if not .Values.turnstile.enabled -}}
{{- fail "anonymous.enabled=true with turnstile.enabled=false — that renders a public hostname with no Cloudflare Access in front of it and no bot gate behind it, which is an unauthenticated write straight into the private tracker the team works in. Spec §7 admits anonymous callers only inside Turnstile and a rate limit: set turnstile.enabled=true with turnstile.existingSecret, or leave anonymous.enabled=false and serve the identity hostname only." -}}
{{- end -}}
{{- if not .Values.gateway.enabled -}}
{{- fail "anonymous.enabled=true requires gateway.enabled=true — the public intake hostname IS an HTTPRoute, and with no Gateway API edge there is nothing to render it on." -}}
{{- end -}}
{{- end -}}
{{- if .Values.gateway.enabled -}}
{{- if ne .Values.config.authMode "mesh_or_turnstile" -}}
{{- fail (printf "gateway.enabled=true with config.authMode=%q — authMode=disabled is not \"no auth\", it is LOOPBACK-ONLY, so every request arriving through the mesh gets a 403 and the deployment looks like a routing fault rather than a chosen posture. Set config.authMode=mesh_or_turnstile for any deployment with an edge in front of it." .Values.config.authMode) -}}
{{- end -}}
{{- if not (or .Values.anonymous.enabled .Values.gateway.identity.enabled) -}}
{{- fail "gateway.enabled=true but neither anonymous.enabled nor gateway.identity.enabled is set — that renders a Gateway API edge with no route attached to it, so the Service is published to nothing and nobody can file a report." -}}
{{- end -}}
{{- end -}}
{{- if and .Values.gateway.identity.enabled (not .Values.gateway.enabled) -}}
{{- fail "gateway.identity.enabled=true requires gateway.enabled=true — the SecurityPolicy targets the identity HTTPRoute this chart renders, and with no route it attaches to nothing and verifies nothing." -}}
{{- end -}}
{{- if eq (.Values.config.forwardedAllowIps | trim) "*" -}}
{{- fail "config.forwardedAllowIps=\"*\" — uvicorn's proxy-headers middleware would then rewrite request.client.host from a client-supplied X-Forwarded-For for EVERY peer, no proxy relationship required. The mesh identity check and the rate-limit key both read that address, so the peer check would authenticate whoever asked to be authenticated. Name the real proxy's address(es), disjoint from config.allowedNetworks." -}}
{{- end -}}
{{- end -}}
