{{- define "scoreboard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "scoreboard.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "scoreboard.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "scoreboard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "scoreboard.labels" -}}
helm.sh/chart: {{ include "scoreboard.chart" . }}
app.kubernetes.io/name: {{ include "scoreboard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: screamingface
{{- end -}}

{{- define "scoreboard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "scoreboard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "scoreboard.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "scoreboard.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "scoreboard.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{/*
Refuse the configurations that would quietly hand anyone any identity.

INVARIANT: `cloudflare_headers` trusts `X-User-Email` because only the mesh can reach this Service
and the mesh removes any client copy of the header. A direct Ingress, an empty network list, or a
FORWARDED_ALLOW_IPS of "*" removes that guarantee. The CIDR overlap of FORWARDED_ALLOW_IPS and
allowedNetworks cannot be checked in Helm; `.github/scripts/verify_chart_wiring.py` checks it.
*/}}
{{- define "scoreboard.validateAuth" -}}
{{- if not (has .Values.config.authMode (list "disabled" "cloudflare_headers")) -}}
{{- fail (printf "config.authMode=%q is not a scoreboard auth mode — set config.authMode to disabled or cloudflare_headers" .Values.config.authMode) -}}
{{- end -}}
{{- if eq .Values.config.authMode "cloudflare_headers" -}}
{{- if not .Values.config.allowedNetworks -}}
{{- fail "config.authMode=cloudflare_headers with no config.allowedNetworks — the scoreboard trusts X-User-Email from any caller that can reach it, so the networks allowed to present it must be declared (the app refuses to start without SCOREBOARD_ALLOWED_NETWORKS). Set config.allowedNetworks to the Envoy data plane's Pod CIDR." -}}
{{- end -}}
{{- if eq (toString .Values.config.forwardedAllowIps) "*" -}}
{{- fail "config.authMode=cloudflare_headers with config.forwardedAllowIps=\"*\" — uvicorn would rewrite the peer address from a client-supplied X-Forwarded-For, and the identity check trusts that address (the app refuses to start, main.py). Set config.forwardedAllowIps to an address outside config.allowedNetworks, for example 127.0.0.1." -}}
{{- end -}}
{{- if .Values.ingress.enabled -}}
{{- fail "config.authMode=cloudflare_headers with ingress.enabled=true — header identity is only trustworthy while this Service is unreachable except through the mesh, and an Ingress makes it directly reachable, so any caller could set X-User-Email and become an administrator. Set ingress.enabled=false and route the host through the Envoy edge." -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Refuse E14 key and publish settings that the app would refuse at start (or accept in a broken half).
*/}}
{{- define "scoreboard.validateE14" -}}
{{- $secret := .Values.e14Secret -}}
{{- $publish := .Values.config.publish -}}
{{- if and $secret.replayGrantSigningKey (not $secret.replayGrantSigningKid) -}}
{{- fail "e14Secret.replayGrantSigningKey is set without e14Secret.replayGrantSigningKid — the scoreboard refuses a grant key without its kid (and the reverse) at start. Set both." -}}
{{- end -}}
{{- if and $secret.replayGrantSigningKid (not $secret.replayGrantSigningKey) -}}
{{- fail "e14Secret.replayGrantSigningKid is set without e14Secret.replayGrantSigningKey — the scoreboard refuses a grant kid without its key at start. Set both." -}}
{{- end -}}
{{- if and $secret.githubAppPrivateKey (not $publish.enabled) -}}
{{- fail "e14Secret.githubAppPrivateKey is set while config.publish.enabled=false — the App key is one of the github_app_* settings, and the scoreboard refuses a partial set at start. Set config.publish.enabled=true with the App id and installation id, or remove the key." -}}
{{- end -}}
{{- if $publish.enabled -}}
{{- if ne .Values.config.authMode "cloudflare_headers" -}}
{{- fail "config.publish.enabled=true needs config.authMode=cloudflare_headers — publishing works only with a verified identity and answers 503 publish_unavailable otherwise." -}}
{{- end -}}
{{- if not $publish.githubAppId -}}
{{- fail "config.publish.enabled=true with an empty config.publish.githubAppId — set the GitHub App id." -}}
{{- end -}}
{{- if not $publish.githubAppInstallationId -}}
{{- fail "config.publish.enabled=true with an empty config.publish.githubAppInstallationId — set the GitHub App installation id." -}}
{{- end -}}
{{- if not $publish.archive.endpointUrl -}}
{{- fail "config.publish.enabled=true with an empty config.publish.archive.endpointUrl — set the S3 endpoint of the cache-version bucket." -}}
{{- end -}}
{{- if and (not $secret.existingSecret) (not (and $secret.githubAppPrivateKey $secret.archiveAccessKeyId $secret.archiveSecretAccessKey)) -}}
{{- fail "config.publish.enabled=true with no Secret source — set e14Secret.existingSecret (recommended), or all of e14Secret.githubAppPrivateKey, e14Secret.archiveAccessKeyId and e14Secret.archiveSecretAccessKey (dev only)." -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
The Secret carrying the E14 key material — an operator's own when supplied, else the chart's.
*/}}
{{- define "scoreboard.e14SecretName" -}}
{{- if .Values.e14Secret.existingSecret -}}
{{- .Values.e14Secret.existingSecret -}}
{{- else -}}
{{- printf "%s-e14" (include "scoreboard.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Prints `true` when any inline E14 secret value is set, else nothing (so `if include ...` works).
*/}}
{{- define "scoreboard.e14InlineSecret" -}}
{{- with .Values.e14Secret -}}
{{- if or .replayGrantSigningKey .replayGrantSigningKid .githubAppPrivateKey .archiveAccessKeyId .archiveSecretAccessKey -}}
true
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Prints `true` when the Pod has an E14 Secret to read (an existing one, or the inline one), else
nothing. A Pod that names no Secret when none exists is the default (dev) install.
*/}}
{{- define "scoreboard.e14HasSecret" -}}
{{- if or .Values.e14Secret.existingSecret (include "scoreboard.e14InlineSecret" .) -}}
true
{{- end -}}
{{- end -}}
