#!/usr/bin/env python3
"""Assert what the aigateway, aigateway-ui, report-intake and screamingface-engine charts render.

WHY this exists rather than a `helm lint` step: `helm lint` reports "0 chart(s) failed" on a chart
that cannot render at all — it reads the templates without executing them, so every `fail` guard
and every value interpolation is invisible to it. `screamingface-engine-tests.yml` documents the same
discovery. Rendering is the only check that exercises a template.

WHY it parses YAML instead of grepping: the properties worth asserting are structural. "The policy
names aigateway-ui" is satisfied by a grep against a policy that ALSO admits the whole namespace,
because grep cannot see that a namespaceSelector and a podSelector landed in two separate `from`
elements (ORed) rather than one (ANDed). That distinction is the entire security value of the
policy, and it is invisible to text matching.

WHY both charts in one script: the load-bearing properties are about the PAIR — the console must
point at the gateway's Service, and the gateway must admit the console's Pod. Each half can be
individually correct while the pair is broken, and neither chart's own test suite would notice.

Run:  python3 .github/scripts/verify_chart_wiring.py
"""

from __future__ import annotations

import ast
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
GATEWAY_CHART = REPO / "apps/aigateway/charts/aigateway"
CONSOLE_CHART = REPO / "apps/aigateway-ui/charts/aigateway-ui"
ENGINE_CHART = REPO / "apps/screamingface-engine/deploy/helm"
INTAKE_CHART = REPO / "apps/report-intake/charts/report-intake"
INTAKE_SETTINGS = REPO / "apps/report-intake/src/report_intake/config.py"

# The release name this repo uses for the gateway everywhere (release-aigateway.yml renders with
# it, and the console chart's `aigateway.serviceName` default is derived from it). The pair check
# below is what keeps that default honest.
GATEWAY_RELEASE = "aigw"
CONSOLE_RELEASE = "aigw-ui"
# INVARIANT: the Engine's RELEASE name is deliberately still the app's previous name, even though
# the chart is now `screamingface-engine` (OME-876). `fullname` is `<release>-<chart name>`, and the
# chart pins its name half with `nameOverride`; renaming the release would move every object name
# anyway and defeat the pin. The two must be changed together, in OME-877, or not at all.
ENGINE_RELEASE = "url4-cloud"
INTAKE_RELEASE = "reports"
# What `values-cloud.yaml` deliberately leaves empty, because a chart cannot know a Gateway's name,
# a Cloudflare application, a Pod CIDR or a mesh gateway's label — and refuses the render rather
# than inventing one. Placeholders, not deployment values — nothing here is installed.
#
# The last two are the ones a reader will wonder about. `allowedNetworks` and the NetworkPolicy
# peers are exactly the values it is tempting to default, because a default for either renders and
# works: blanket RFC1918 admits any private address to present a mesh identity, and no policy lets
# any pod in the cluster dial the ClusterIP and be believed. Both decide who may forge
# `X-User-Email`, so both are empty in values-cloud.yaml and named here the same way the Gateway is.
INTAKE_CLOUD_ARGS = (
    "--values",
    str(INTAKE_CHART / "values-cloud.yaml"),
    "--set",
    "gateway.parentRef.name=ci-placeholder-gateway",
    "--set",
    "gateway.identity.cloudflareAccess.teamDomain=ci-placeholder.cloudflareaccess.com",
    "--set",
    "gateway.identity.cloudflareAccess.audience=ci-placeholder-aud",
    "--set",
    "turnstile.existingSecret=ci-placeholder-turnstile",
    "--set",
    "database.existingSecret=ci-placeholder-db",
    "--set",
    "config.allowedNetworks[0]=10.42.0.0/16",
    "--set",
    "networkPolicy.clientPodNames[0]=ci-placeholder-envoy",
)

failures: list[str] = []
checks = 0


def check(condition: bool, description: str) -> None:
    global checks
    checks += 1
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        failures.append(description)


def render(chart: Path, release: str, *args: str) -> list[dict]:
    """Render a chart, returning its documents. Raises if helm refuses."""
    result = subprocess.run(
        ["helm", "template", release, str(chart), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def render_fails(chart: Path, release: str, *args: str) -> str | None:
    """Return the error when a render is REFUSED, or None when it unexpectedly succeeds."""
    try:
        render(chart, release, *args)
    except RuntimeError as exc:
        return str(exc)
    return None


def find(docs: list[dict], kind: str) -> dict:
    """The single document of `kind`. Raises rather than returning None: every caller here treats
    absence as a failure, and a None threaded onward reports as an attribute error twenty lines
    from the actual problem."""
    for doc in docs:
        if doc.get("kind") == kind:
            return doc
    raise AssertionError(f"no {kind} in the rendered chart")


def find_named(docs: list[dict], kind: str, name: str) -> dict:
    """The document of `kind` named `name`. The aigateway chart can render TWO NetworkPolicies
    (gateway + bundled Garage), and garage.yaml sorts before networkpolicy.yaml — so `find`
    would silently return whichever renders first. Policies are looked up by name."""
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind} named {name!r} in the rendered chart")


def find_data_owner(docs: list[dict], key: str) -> dict:
    """Return the single rendered object whose data contains ``key``."""
    matches = [doc for doc in docs if key in doc.get("data", {})]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one rendered object carrying {key!r}, found {len(matches)}"
        )
    return matches[0]


def peer_names(policy: dict, direction: str) -> set[str]:
    """Pod names admitted by a policy, counting ONLY properly-paired selectors.

    A `from`/`to` element carrying a podSelector WITHOUT a namespaceSelector matches that label in
    every namespace; one carrying a namespaceSelector without a podSelector matches every pod in
    that namespace. Both are wider than intended, so neither counts as naming a peer here — which
    is what makes this stricter than a grep.
    """
    names: set[str] = set()
    for rule in policy["spec"].get(direction, []):
        for element in rule.get("from", []) + rule.get("to", []):
            pod = element.get("podSelector", {}).get("matchLabels", {})
            ns = element.get("namespaceSelector", {}).get("matchLabels", {})
            if pod.get("app.kubernetes.io/name") and ns.get(
                "kubernetes.io/metadata.name"
            ):
                names.add(pod["app.kubernetes.io/name"])
    return names


def settings_fields() -> list[tuple[str, ast.expr]]:
    """Every `Settings` field as (environment name, annotation node), read with `ast`.

    WHY parsed rather than imported: this script runs on a bare runner with pyyaml and nothing
    else, and installing report-intake's whole dependency tree to read a list of attribute names
    would make the check cost a `uv sync` per chart edit. The parse is also immune to an import
    error somewhere else in the package turning these assertions into a skip.
    """
    module = ast.parse(INTAKE_SETTINGS.read_text())
    settings = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Settings"
    )
    return [
        (f"REPORT_INTAKE_{statement.target.id.upper()}", statement.annotation)
        for statement in settings.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id != "model_config"
    ]


def settings_env_names() -> set[str]:
    return {name for name, _ in settings_fields()}


def numeric_settings() -> set[str]:
    """The names whose field is annotated plainly `int` or `float`.

    Derived rather than listed, so a field that changes type is caught here instead of by a stale
    hardcoded set. This is what catches a chart value that renders as a NUMBER-SHAPED STRING —
    `deliveryTimeoutS: 3s` renders, passes every structural assertion in this file, and then
    CrashLoops the pod on a pydantic validation error at boot.
    """
    return {
        name
        for name, annotation in settings_fields()
        if isinstance(annotation, ast.Name) and annotation.id in {"int", "float"}
    }


def declared_auth_modes() -> set[str]:
    """The values of config.py's `AuthMode` Literal.

    Read from the source so a mode renamed in the app and not in the chart is a failure here,
    rather than a pod that cannot parse its own posture — the one variable whose loss is
    invisible from outside, since the default is `disabled`.
    """
    module = ast.parse(INTAKE_SETTINGS.read_text())
    # Matched on the assignment TARGET, not on any mention of the name: `Settings` also names
    # `AuthMode` (as `auth_mode`'s annotation) and a looser match would find whichever node the
    # walk reached first.
    literal = next(
        node.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "AuthMode"
            for target in node.targets
        )
    )
    return {
        element.value
        for element in ast.walk(literal)
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }


def rendered_env_names(docs: list[dict]) -> set[str]:
    """Every `REPORT_INTAKE_*` name the rendered manifest puts into a container's environment.

    Both sources count: the ConfigMap the Deployment reads via `envFrom`, and the `env:` entries
    naming a Secret. Reading only the ConfigMap would report the two secret-valued settings as
    missing, which is the check crying wolf about the one thing the chart is right to keep out of
    a ConfigMap.
    """
    names: set[str] = set()
    for doc in docs:
        for key in doc.get("data", {}) if doc.get("kind") == "ConfigMap" else {}:
            if key.startswith("REPORT_INTAKE_"):
                names.add(key)
        for container in containers_of(doc):
            for entry in container.get("env", []) or []:
                if entry["name"].startswith("REPORT_INTAKE_"):
                    names.add(entry["name"])
    return names


def containers_of(doc: dict) -> list[dict]:
    """Containers in any workload document — Deployment, Job or a bare Pod."""
    if doc.get("kind") == "Pod":
        return doc["spec"].get("containers", [])
    template = doc.get("spec", {}).get("template")
    if isinstance(template, dict):
        return template.get("spec", {}).get("containers", [])
    return []


def route_named(docs: list[dict], name: str) -> dict:
    """The HTTPRoute with this exact metadata name. Raises rather than returning None: this chart
    renders two routes with deliberately different header policies, and picking "the first
    HTTPRoute" would silently assert one route's properties against the other."""
    for doc in docs:
        if doc.get("kind") == "HTTPRoute" and doc["metadata"]["name"] == name:
            return doc
    raise AssertionError(f"no HTTPRoute named {name} in the rendered chart")


def headers_removed_by(route: dict) -> set[str]:
    """Header names the route's `RequestHeaderModifier` filters remove, lowercased.

    Lowercased because HTTP header names are case-insensitive and this assertion must not be
    satisfiable — or breakable — by a casing change in the template.
    """
    removed: set[str] = set()
    for rule in route["spec"]["rules"]:
        for filt in rule.get("filters", []):
            if filt.get("type") != "RequestHeaderModifier":
                continue
            for header in filt["requestHeaderModifier"].get("remove", []):
                removed.add(header.lower())
    return removed


def cidr_overlap(
    forwarded_allow_ips: str, allowed_networks: str
) -> tuple[str, str] | None:
    """The first overlapping (FORWARDED_ALLOW_IPS entry, allowed_networks entry) pair, or None.

    This is the render-time half of `report_intake.main._check_forwarded_allow_ips`. Uvicorn's
    proxy-headers middleware rewrites `request.client.host` from a client-supplied
    `X-Forwarded-For` for any peer inside FORWARDED_ALLOW_IPS, and that address is what both the
    mesh identity check and the rate-limit key read — so an entry landing inside the networks the
    identity check trusts re-opens the check for exactly the peers it exists to authenticate.
    Helm has no CIDR arithmetic, so the chart can only refuse `"*"`; this is where the general
    case is caught, before the pod CrashLoops on the app's own guard.
    """
    allowed = [
        ipaddress.ip_network(part.strip())
        for part in allowed_networks.split(",")
        if part.strip()
    ]
    for part in forwarded_allow_ips.split(","):
        entry = part.strip()
        if not entry or entry == "*":
            continue
        trusted = (
            ipaddress.ip_network(entry)
            if "/" in entry
            else ipaddress.ip_network(ipaddress.ip_address(entry))
        )
        for network in allowed:
            if trusted.version == network.version and trusted.overlaps(network):
                return entry, str(network)
    return None


print("aigateway chart")
gw = render(GATEWAY_CHART, GATEWAY_RELEASE)
gw_config = find(gw, "ConfigMap")
gw_policy = find_named(gw, "NetworkPolicy", f"{GATEWAY_RELEASE}-aigateway")
gw_service = find(gw, "Service")
gw_deployment = find(gw, "Deployment")

check(
    "aigateway-ui" in peer_names(gw_policy, "ingress"),
    "admits the aigateway-ui console, with namespace and pod selectors PAIRED in one element",
)
check(
    {"url4-cloud", "url4-runner"} <= peer_names(gw_policy, "ingress"),
    "still admits url4-cloud and url4-runner (the console did not displace them)",
)
check(
    "AIGATEWAY_ADMIN_EMAILS" in gw_config["data"],
    "emits AIGATEWAY_ADMIN_EMAILS even when empty — 'nobody may administer' is a stated posture",
)
check(
    gw_config["data"]["AIGATEWAY_ADMIN_EMAILS"] == "",
    "ships the allowlist EMPTY by default, so the admin API answers 503 rather than opening",
)

gw_with_admins = render(
    GATEWAY_CHART,
    GATEWAY_RELEASE,
    "--set-string",
    "config.adminEmails[0]=a@example.com",
    "--set-string",
    "config.adminEmails[1]=b@example.com",
)
check(
    find(gw_with_admins, "ConfigMap")["data"]["AIGATEWAY_ADMIN_EMAILS"]
    == "a@example.com,b@example.com",
    "joins the allowlist with commas — the app parses a comma list, not JSON (NoDecode)",
)
check(
    find(gw_with_admins, "Deployment")["spec"]["template"]["spec"]["containers"][0][
        "envFrom"
    ][0]["configMapRef"]["name"]
    == gw_config["metadata"]["name"],
    "the gateway container actually reads that ConfigMap",
)

gw_prod = render(
    GATEWAY_CHART, GATEWAY_RELEASE, "--values", str(GATEWAY_CHART / "values-prod.yaml")
)
check(
    "aigateway-ui" in peer_names(find(gw_prod, "NetworkPolicy"), "ingress"),
    "values-prod.yaml also admits the console (it overrides clientPodNames wholesale)",
)

print("\naigateway snapshot wiring (bundled Garage)")
# The bundled Garage shares the release's selectorLabels (name+instance), so every selector
# that must name ONE side needs the component label. These checks pin the review fix: the
# gateway policy must not capture Garage Pods (that denied the snapshot PUTs to :3900), and
# Garage must get its own scoped policy admitting exactly the gateway.
gw_snap = render(GATEWAY_CHART, GATEWAY_RELEASE, "--set", "snapshot.enabled=true")
gw_snap_policy = find_named(gw_snap, "NetworkPolicy", f"{GATEWAY_RELEASE}-aigateway")
garage_policy = find_named(
    gw_snap, "NetworkPolicy", f"{GATEWAY_RELEASE}-aigateway-garage"
)
garage_sts = find(gw_snap, "StatefulSet")
gw_pod_labels = gw_deployment["spec"]["template"]["metadata"]["labels"]

check(
    gw_pod_labels.get("app.kubernetes.io/component") == "gateway",
    "gateway Pods carry component: gateway — distinct from garage/migrate under shared selectorLabels",
)
check(
    "app.kubernetes.io/component"
    not in gw_deployment["spec"]["selector"]["matchLabels"],
    "the gateway Deployment selector stays name+instance — spec.selector is immutable, so "
    "adding the component label there breaks `helm upgrade` of an existing release",
)
check(
    gw_policy["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/component")
    == "gateway",
    "the gateway NetworkPolicy selects ONLY gateway Pods — it cannot capture Garage or migrate Pods",
)
check(
    gw_service["spec"]["selector"].get("app.kubernetes.io/component") == "gateway",
    "the Service routes ONLY to gateway Pods, not merely saved by the named targetPort",
)

# WHY these four (regression, 2026-09-01): the checks above render DEFAULT values, where the
# component label can only come from the chart itself — so they all passed while the deployed
# gateway had no Endpoints for 40 minutes. The platform sets `podLabels`, which rendered AFTER the
# Pod template's own labels, so its `component: server` won on the Pod by YAML duplicate-key
# precedence while this Service selector still demanded `gateway`. Zero Endpoints, Pod Running,
# Argo Synced, nothing in any log. A default-only render cannot see that class of break, so the
# gate now renders the OVERRIDE path too: the Pod label and every selector must move together,
# and the spelling that caused the outage must be refused outright.
gw_component = render(
    GATEWAY_CHART,
    GATEWAY_RELEASE,
    "--set",
    "componentLabel=server",
    "--set",
    "snapshot.enabled=true",
)
gwc_deployment = find_named(gw_component, "Deployment", f"{GATEWAY_RELEASE}-aigateway")
gwc_service = find_named(gw_component, "Service", f"{GATEWAY_RELEASE}-aigateway")
gwc_policy = find_named(gw_component, "NetworkPolicy", f"{GATEWAY_RELEASE}-aigateway")
gwc_garage_policy = find_named(
    gw_component, "NetworkPolicy", f"{GATEWAY_RELEASE}-aigateway-garage"
)

check(
    gwc_deployment["spec"]["template"]["metadata"]["labels"].get(
        "app.kubernetes.io/component"
    )
    == "server"
    and gwc_service["spec"]["selector"].get("app.kubernetes.io/component") == "server",
    "componentLabel moves the Pod label and the Service selector together — the Service keeps "
    "selecting the Pod it fronts under a platform's own component convention",
)
check(
    gwc_policy["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/component")
    == "server",
    "componentLabel moves the gateway NetworkPolicy podSelector too",
)
check(
    any(
        peer.get("podSelector", {})
        .get("matchLabels", {})
        .get("app.kubernetes.io/component")
        == "server"
        for rule in gwc_garage_policy["spec"]["ingress"]
        for peer in rule.get("from", [])
    ),
    "componentLabel moves Garage's :3900 ingress peer too — the snapshot PUTs keep working",
)
_pod_label_clash = render_fails(
    GATEWAY_CHART,
    GATEWAY_RELEASE,
    "--set-string",
    "podLabels.app\\.kubernetes\\.io/component=server",
)
check(
    _pod_label_clash is not None and "componentLabel" in _pod_label_clash,
    "podLabels cannot set app.kubernetes.io/component — the render is refused and names "
    "componentLabel, instead of silently emptying the Service",
)
check(
    garage_sts["spec"]["template"]["metadata"]["labels"].get(
        "app.kubernetes.io/component"
    )
    == "garage",
    "bundled Garage Pods carry component: garage",
)
check(
    garage_policy["spec"]["podSelector"]["matchLabels"].get(
        "app.kubernetes.io/component"
    )
    == "garage",
    "the Garage NetworkPolicy selects ONLY Garage Pods",
)
check(
    [
        p["port"]
        for rule in garage_policy["spec"]["ingress"]
        for p in rule.get("ports", [])
    ]
    == [3900],
    "Garage admits exactly one ingress port: the S3 API on 3900",
)

admitted_peer: dict[str, str] = {}
for rule in garage_policy["spec"]["ingress"]:
    for element in rule.get("from", []):
        labels = element.get("podSelector", {}).get("matchLabels", {})
        if labels.get("app.kubernetes.io/component") == "gateway":
            admitted_peer = labels
check(
    bool(admitted_peer)
    and admitted_peer.get("app.kubernetes.io/name") == "aigateway"
    and admitted_peer.get("app.kubernetes.io/instance") == GATEWAY_RELEASE,
    "Garage's 3900 ingress names THIS release's gateway Pods (name+instance+component)",
)
check(
    all(gw_pod_labels.get(key) == value for key, value in admitted_peer.items()),
    "the peer Garage admits IS the label set the gateway Deployment renders — the pair holds",
)
check(
    gw_snap_policy["spec"]["podSelector"]["matchLabels"].get(
        "app.kubernetes.io/component"
    )
    == "gateway",
    "with snapshots on, the gateway policy still selects only gateway Pods",
)

check(
    not any(doc.get("kind") == "StatefulSet" for doc in gw),
    "snapshot disabled by default renders no Garage StatefulSet",
)
gw_no_np = render(
    GATEWAY_CHART,
    GATEWAY_RELEASE,
    "--set",
    "snapshot.enabled=true",
    "--set",
    "networkPolicy.enabled=false",
)
check(
    not any(doc.get("kind") == "NetworkPolicy" for doc in gw_no_np),
    "networkPolicy.enabled=false renders NO policies at all — gateway or Garage",
)

print("\naigateway snapshot refusals")
# The single-writer invariant (spec: logged single-replica assumption) is enforced at render,
# not left to operator discipline — two schedulers firing the same second-resolution stamp
# would interleave their archive/manifest PUTs.
replica_error = render_fails(
    GATEWAY_CHART,
    GATEWAY_RELEASE,
    "--set",
    "snapshot.enabled=true",
    "--set",
    "replicaCount=2",
)
check(
    replica_error is not None and "replicaCount=1" in replica_error,
    "REFUSES snapshots on more than one replica, naming the single-writer invariant",
)
external_error = render_fails(
    GATEWAY_CHART,
    GATEWAY_RELEASE,
    "--set",
    "snapshot.enabled=true",
    "--set",
    "snapshot.garage.enabled=false",
    "--set-string",
    "snapshot.storage.endpointUrl=http://s3.example.com",
)
check(
    external_error is not None and "bundled Garage" in external_error,
    "REFUSES to mint credentials for an external store — both keys or existingSecret required",
)
gw_external = render(
    GATEWAY_CHART,
    GATEWAY_RELEASE,
    "--set",
    "snapshot.enabled=true",
    "--set",
    "snapshot.garage.enabled=false",
    "--set-string",
    "snapshot.storage.endpointUrl=http://s3.example.com",
    "--set-string",
    "snapshot.storage.accessKey=AKIAEXTERNAL",
    "--set-string",
    "snapshot.storage.secretKey=SKEXTERNAL",
)
external_secret = find_named(
    gw_external, "Secret", f"{GATEWAY_RELEASE}-aigateway-snapshot-storage"
)
check(
    external_secret["stringData"]["AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY"] == "AKIAEXTERNAL"
    and external_secret["stringData"]["AIGW_CACHE_SNAPSHOT_S3_SECRET_KEY"]
    == "SKEXTERNAL",
    "external mode renders the OPERATOR's pair verbatim — nothing is generated",
)
bundled_secret = find_named(
    gw_snap, "Secret", f"{GATEWAY_RELEASE}-aigateway-snapshot-storage"
)
check(
    bundled_secret["stringData"]["AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY"].startswith("GK"),
    "bundled Garage still GENERATES its GK… key pair when no values are supplied",
)
gw_multi = render(GATEWAY_CHART, GATEWAY_RELEASE, "--set", "replicaCount=2")
check(
    isinstance(gw_multi, list) and len(gw_multi) > 0,
    "more than one replica renders fine while snapshots are OFF — the guard is scoped",
)

print("\naigateway-ui chart")
console = render(
    CONSOLE_CHART,
    CONSOLE_RELEASE,
    "--set",
    "networkPolicy.clientPodNames[0]=envoy-gateway",
)
c_config = find(console, "ConfigMap")
c_policy = find(console, "NetworkPolicy")
c_sa = find(console, "ServiceAccount")
c_deployment = find(console, "Deployment")

check(
    c_config["data"]["AIGATEWAY_ADMIN_BASE_URL"]
    == f"http://{GATEWAY_RELEASE}-aigateway.default.svc.cluster.local:9105",
    "resolves AIGATEWAY_ADMIN_BASE_URL to the gateway Service's fully-qualified DNS name",
)
check(
    find(
        render(
            CONSOLE_CHART,
            CONSOLE_RELEASE,
            "--set",
            "networkPolicy.clientPodNames[0]=envoy-gateway",
            "--set",
            "aigateway.baseUrl=http://elsewhere:8080/",
        ),
        "ConfigMap",
    )["data"]["AIGATEWAY_ADMIN_BASE_URL"]
    == "http://elsewhere:8080",
    "an explicit aigateway.baseUrl wins, with the trailing slash trimmed",
)
check(
    c_sa.get("automountServiceAccountToken") is False,
    "does not mount a Kubernetes API token — the console calls no Kubernetes API",
)
check(
    "aigateway" in peer_names(c_policy, "egress"),
    "egress NAMES the gateway rather than allowing everything",
)
check(
    all(rule.get("to") for rule in c_policy["spec"]["egress"]),
    "no egress rule omits `to:` — an empty `to:` would allow the console to reach anything",
)

dns_rule = next(
    (
        rule
        for rule in c_policy["spec"]["egress"]
        if any(p.get("port") == 53 for p in rule.get("ports", []))
    ),
    None,
)
check(
    dns_rule is not None,
    "allows DNS — without it the gateway's Service name never resolves",
)
check(
    dns_rule is not None
    and {p["protocol"] for p in dns_rule["ports"]} == {"UDP", "TCP"},
    "allows DNS over BOTH UDP and TCP — resolvers retry over TCP past 512 bytes",
)
check(
    "checksum/config" in c_deployment["spec"]["template"]["metadata"]["annotations"],
    "rolls the Pods when the ConfigMap changes, so an upgrade cannot silently keep the old address",
)

print("\naigateway-ui refusals")
ingress_error = render_fails(
    CONSOLE_CHART,
    CONSOLE_RELEASE,
    "--set",
    "networkPolicy.clientPodNames[0]=envoy-gateway",
    "--set",
    "ingress.enabled=true",
)
check(
    ingress_error is not None and "X-User-Email" in ingress_error,
    "REFUSES to render with an Ingress, explaining the impersonation it prevents",
)
no_peers_error = render_fails(CONSOLE_CHART, CONSOLE_RELEASE)
check(
    no_peers_error is not None and "admits every source" in no_peers_error,
    "REFUSES to render a NetworkPolicy with no peers rather than emitting an allow-all",
)

print("\nthe pair")
check(
    c_config["data"]["AIGATEWAY_ADMIN_BASE_URL"].split("//")[1].split(".")[0]
    == gw_service["metadata"]["name"],
    "the console's configured host IS the Service name the gateway chart renders",
)
gw_pod_name = gw_deployment["spec"]["template"]["metadata"]["labels"][
    "app.kubernetes.io/name"
]
check(
    gw_pod_name in peer_names(c_policy, "egress"),
    "the console's egress names the label the gateway's Pods actually carry",
)
console_pod_name = c_deployment["spec"]["template"]["metadata"]["labels"][
    "app.kubernetes.io/name"
]
check(
    console_pod_name in peer_names(gw_policy, "ingress"),
    "the gateway's ingress names the label the console's Pods actually carry",
)
check(
    str(c_config["data"]["AIGATEWAY_ADMIN_BASE_URL"]).endswith(
        f":{gw_service['spec']['ports'][0]['port']}"
    ),
    "the console's port IS the port the gateway's Service listens on",
)

print("\nscreamingface-engine chart")
# FX-86: `node.enabled` defaults to FALSE (the chart refuses it paired with any
# artifactStorage.backend other than `s3`, OME-929), so every check below that needs the node
# tier's objects renders with BOTH set explicitly.
ENGINE_NODE_ARGS = (
    "--set",
    "node.enabled=true",
    "--set",
    "artifactStorage.backend=s3",
    "--set-string",
    "artifactStorage.s3.endpointUrl=http://garage:3900",
)
engine_chart = render(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
    *ENGINE_NODE_ARGS,
)
# The chart now renders THREE Deployments (the App, the runner pool OME-1092, and the node tier
# of unit 3), so each is looked up by name rather than by `find` (which would silently return
# whichever renders first).
url4_deployment = find_named(
    engine_chart, "Deployment", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}"
)
url4_runner_deployment = find_named(
    engine_chart, "Deployment", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}-runner"
)
url4_node_deployment = find_named(
    engine_chart, "Deployment", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}-node"
)
url4_app_image = url4_deployment["spec"]["template"]["spec"]["containers"][0]["image"]
url4_runner_image = url4_runner_deployment["spec"]["template"]["spec"]["containers"][0][
    "image"
]
url4_app_repository, url4_app_tag = url4_app_image.rsplit(":", 1)
url4_runner_repository, url4_runner_tag = url4_runner_image.rsplit(":", 1)
check(
    url4_runner_repository == f"{url4_app_repository}-benchmark",
    "derives the Runner pool image from the control-plane repository",
)
check(
    url4_runner_tag == url4_app_tag,
    "pins the Runner pool and control-plane images to the same tag",
)

# --- the node tier (unit 3, prd/03 §2.1) -----------------------------------------------------
# A third Deployment serving the sync surface. The properties that matter are structural: which
# pods each object selects, which peer the NetworkPolicy admits, and which Secret reaches which
# tier. contracts.md §10 makes the App-only ingress a CORRECTNESS requirement — without it any
# pod in the cluster can set `X-User-Email` freely.
node_name = f"{ENGINE_RELEASE}-{ENGINE_RELEASE}-node"
url4_node_service = find_named(engine_chart, "Service", node_name)
url4_node_policy = find_named(engine_chart, "NetworkPolicy", node_name)
url4_node_pdb = find_named(engine_chart, "PodDisruptionBudget", node_name)
url4_node_container = url4_node_deployment["spec"]["template"]["spec"]["containers"][0]
node_pod_labels = url4_node_deployment["spec"]["template"]["metadata"]["labels"]

check(
    url4_node_container["command"] == ["screamingface-engine", "node"],
    "the node tier runs the `node` entry point (prd/03 §2.1)",
)
check(
    url4_node_container["readinessProbe"]["httpGet"]["path"] == "/readyz",
    "node readiness gates on /readyz — world built AND the collision guard passed (AC18)",
)
check(
    url4_node_container["livenessProbe"]["httpGet"]["path"] == "/livez"
    and url4_node_container["livenessProbe"]["httpGet"]["path"]
    != url4_node_container["readinessProbe"]["httpGet"]["path"],
    "node liveness is /livez, NOT /readyz — probing a downstream from liveness would restart "
    "every healthy pod when aigateway blinks (AC19)",
)
check(
    {port["name"] for port in url4_node_container["ports"]} >= {"http", "metrics"},
    "the node exposes both its http port and a metrics port",
)
check(
    url4_node_service["spec"]["selector"].get("app.kubernetes.io/component") == "node",
    "the node Service fronts ONLY node pods — name+instance would also front the App",
)
check(
    url4_node_policy["spec"]["podSelector"]["matchLabels"].get(
        "app.kubernetes.io/component"
    )
    == "node",
    "the NetworkPolicy selects ONLY node pods",
)

# The peer pairing is asserted explicitly: `peer_names` above already ignores an unpaired
# selector, but a rule with NO `from:` admits every source and is invisible to it.
node_from = [
    element
    for rule in url4_node_policy["spec"]["ingress"]
    for element in rule.get("from", [])
]
check(
    all(rule.get("from") for rule in url4_node_policy["spec"]["ingress"]),
    "no node ingress rule omits `from:` — an empty one would admit every source",
)
check(
    bool(node_from)
    and all(
        element.get("podSelector") and element.get("namespaceSelector")
        for element in node_from
    ),
    "every node ingress peer pairs its podSelector with its namespaceSelector in ONE element "
    "— split into two elements they are ORed, which admits the whole namespace",
)
check(
    peer_names(url4_node_policy, "ingress") == {"url4-cloud"},
    "the node NetworkPolicy admits the App (url4-cloud) and nothing else — the runner pool "
    "(url4-runner) is NOT admitted",
)
node_peer = next(
    (
        element.get("podSelector", {}).get("matchLabels", {})
        for element in node_from
        if element.get("podSelector")
    ),
    {},
)
url4_app_pod_labels = url4_deployment["spec"]["template"]["metadata"]["labels"]
check(
    node_peer.get("app.kubernetes.io/component") == "control-plane"
    and all(url4_app_pod_labels.get(key) == value for key, value in node_peer.items()),
    "the peer the node policy admits IS the label set the App pods render — the App carries "
    "component: control-plane, which is what distinguishes it from the node's own pods",
)
check(
    url4_node_pdb["spec"]["maxUnavailable"] == 1
    and url4_node_pdb["spec"]["selector"]["matchLabels"].get(
        "app.kubernetes.io/component"
    )
    == "node",
    "the node PDB serializes voluntary disruptions (maxUnavailable: 1) and selects node pods",
)
check(
    url4_node_deployment["spec"]["template"]["spec"].get("automountServiceAccountToken")
    is False,
    "the node mounts no Kubernetes API token — it calls aigateway and object storage only",
)
check(
    find_named(engine_chart, "ConfigMap", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}")[
        "data"
    ].get("URL4_CLOUD_NODE_BASE_URL")
    == f"http://{node_name}:{url4_node_service['spec']['ports'][0]['port']}",
    "the App's node_base_url names the node Service the chart renders, so the forwarder arms",
)
check(
    node_pod_labels.get("app.kubernetes.io/name")
    == url4_app_pod_labels.get("app.kubernetes.io/name"),
    "the node shares the App's name label so aigateway's ingress admits the node's calls",
)

# The secrets, in the object-storage shape the spill path requires. ONE signing Secret must
# reach BOTH tiers (the node signs the 303, the App verifies): reaching one half only means
# every redirect is unfetchable or every spill is a 502 (OQ-3.2).
engine_s3 = render(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
    *ENGINE_NODE_ARGS,
)
signing_name = f"{ENGINE_RELEASE}-{ENGINE_RELEASE}-artifact-signing"
artifact_name = f"{ENGINE_RELEASE}-{ENGINE_RELEASE}-artifact-storage"
node_s3_container = find_named(engine_s3, "Deployment", node_name)["spec"]["template"][
    "spec"
]["containers"][0]
app_s3_container = find_named(
    engine_s3, "Deployment", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}"
)["spec"]["template"]["spec"]["containers"][0]
check(
    "URL4_CLOUD_ARTIFACT_SIGNING_KEY"
    in find_named(engine_s3, "Secret", signing_name).get("stringData", {}),
    "the chart's signing Secret keys the value with the exact name `envFrom.secretRef` injects",
)
check(
    {"secretRef": {"name": artifact_name}} in node_s3_container["envFrom"],
    "the node pod receives the S3 credential pair the spill PUT needs (contracts.md C5)",
)
check(
    {"secretRef": {"name": signing_name}} in node_s3_container["envFrom"]
    and {"secretRef": {"name": signing_name}} in app_s3_container["envFrom"],
    "ONE artifact-signing Secret reaches the node (signs) and the App (verifies) — OQ-3.2",
)

# The override path, the same class the aigateway section pins: a platform's `podLabels` render
# AFTER the Pod template's own labels, and an override of the component label would silently
# stop the App from matching the node policy's peer. The chart renders that label last so it is
# chart-owned; this renders the override and proves the pair still holds.
engine_podlabels = render(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
    *ENGINE_NODE_ARGS,
    "--set-string",
    "podLabels.app\\.kubernetes\\.io/component=platform-convention",
)
node_podlabels_labels = find_named(engine_podlabels, "Deployment", node_name)["spec"][
    "template"
]["metadata"]["labels"]
check(
    node_podlabels_labels.get("app.kubernetes.io/component") == "node",
    "the node's OWN component label is ALSO chart-owned (FX-84) — a podLabels override cannot "
    "silently change which selector the node's own pods match either",
)
override_app_labels = find_named(
    engine_podlabels, "Deployment", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}"
)["spec"]["template"]["metadata"]["labels"]
override_node_policy = find_named(engine_podlabels, "NetworkPolicy", node_name)
override_peer = next(
    (
        element.get("podSelector", {}).get("matchLabels", {})
        for rule in override_node_policy["spec"]["ingress"]
        for element in rule.get("from", [])
        if element.get("podSelector")
    ),
    {},
)
check(
    override_app_labels.get("app.kubernetes.io/component") == "control-plane",
    "the App's component label is CHART-OWNED — a podLabels override cannot silently change it",
)
check(
    bool(override_peer)
    and all(
        override_app_labels.get(key) == value for key, value in override_peer.items()
    ),
    "under the podLabels override the node policy's peer STILL matches the App pods — a "
    "platform convention cannot lock the App out of the node",
)

# --- FX-80/FX-90: every selector matches EXACTLY its own Deployment's pod template -----------
# The bug this closes: the node used to share the App's {name, instance} pair, so the App's own
# Service and Deployment selectors (a plain {name, instance}, no component) were a SUPERSET
# match for the node's pods too — silently routing public traffic and eviction/replace churn to
# a tier that was never meant to receive either. Checked generically so the NEXT stray selector
# is caught the same way, not just this one.
engine_pod_templates = {
    doc["metadata"]["name"]: doc["spec"]["template"]["metadata"]["labels"]
    for doc in engine_chart
    if doc.get("kind") == "Deployment"
}
_ENGINE_SELECTOR_OWNERS = {
    (
        "Service",
        f"{ENGINE_RELEASE}-{ENGINE_RELEASE}",
    ): f"{ENGINE_RELEASE}-{ENGINE_RELEASE}",
    ("Service", node_name): node_name,
    (
        "Deployment",
        f"{ENGINE_RELEASE}-{ENGINE_RELEASE}",
    ): f"{ENGINE_RELEASE}-{ENGINE_RELEASE}",
    (
        "Deployment",
        f"{ENGINE_RELEASE}-{ENGINE_RELEASE}-runner",
    ): f"{ENGINE_RELEASE}-{ENGINE_RELEASE}-runner",
    ("Deployment", node_name): node_name,
    ("PodDisruptionBudget", node_name): node_name,
    ("NetworkPolicy", node_name): node_name,
}


def _selector_of(doc: dict) -> dict:
    if doc["kind"] == "Service":
        return doc["spec"]["selector"]
    if doc["kind"] == "NetworkPolicy":
        return doc["spec"]["podSelector"]["matchLabels"]
    return doc["spec"]["selector"]["matchLabels"]


_selector_mismatches: list[str] = []
for (kind, name), owner in _ENGINE_SELECTOR_OWNERS.items():
    selector = _selector_of(find_named(engine_chart, kind, name))
    for deployment_name, pod_labels in engine_pod_templates.items():
        matches = all(pod_labels.get(k) == v for k, v in selector.items())
        if deployment_name == owner and not matches:
            _selector_mismatches.append(
                f"{kind}/{name} does not even match its OWN pods"
            )
        elif deployment_name != owner and matches:
            _selector_mismatches.append(
                f"{kind}/{name} ALSO matches {deployment_name}'s pods"
            )
check(
    not _selector_mismatches,
    "every Service/Deployment/PDB/NetworkPolicy selector matches EXACTLY its intended "
    "Deployment's pod template and no other"
    + (f" — {_selector_mismatches}" if _selector_mismatches else ""),
)
check(
    not all(
        engine_pod_templates[node_name].get(k) == v
        for k, v in find_named(
            engine_chart, "Service", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}"
        )["spec"]["selector"].items()
    ),
    "the App's Service selector does NOT match the node pods (FX-90) — before the node's own "
    "instance existed, the App's plain name+instance selector silently fronted it too",
)
check(
    node_peer.get("app.kubernetes.io/component") == "control-plane"
    and not all(
        engine_pod_templates[node_name].get(k) == v for k, v in node_peer.items()
    ),
    "the node NetworkPolicy's admitted peer (component: control-plane) does NOT match the "
    "node's OWN pods — it names the App and only the App",
)

# --- FX-82: /metrics on its own port, admitted by a peer-scoped second ingress rule ----------
node_container = find_named(engine_chart, "Deployment", node_name)["spec"]["template"][
    "spec"
]["containers"][0]
node_ports = {p["name"]: p["containerPort"] for p in node_container["ports"]}
check(
    node_ports["http"] != node_ports["metrics"] and node_ports["metrics"] == 9110,
    "the node's http and metrics containerPorts are DISTINCT — a scrape can no longer share the "
    "request listener, and the NetworkPolicy can admit a scraper to metrics only",
)
check(
    len(url4_node_policy["spec"]["ingress"]) == 1,
    "with no node.metrics.scrapeFrom configured, the chart renders NO second ingress rule — "
    "metrics stays reachable from nowhere else in the cluster by default",
)
engine_scrape = render(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
    *ENGINE_NODE_ARGS,
    "--set-string",
    r"node.metrics.scrapeFrom[0].namespaceSelector.matchLabels.kubernetes\.io/metadata\.name=monitoring",
    "--set-string",
    r"node.metrics.scrapeFrom[0].podSelector.matchLabels.app\.kubernetes\.io/name=prometheus",
)
scrape_policy = find_named(engine_scrape, "NetworkPolicy", node_name)
scrape_rule = next(
    (
        rule
        for rule in scrape_policy["spec"]["ingress"]
        if any(p.get("port") == 9110 for p in rule.get("ports", []))
    ),
    None,
)
check(
    scrape_rule is not None
    and all(p.get("port") == 9110 for p in scrape_rule["ports"])
    and "monitoring"
    in {
        e.get("namespaceSelector", {})
        .get("matchLabels", {})
        .get("kubernetes.io/metadata.name")
        for e in scrape_rule["from"]
    },
    "a configured node.metrics.scrapeFrom peer is admitted to the metrics port ONLY, in its own "
    "ingress rule — never to the request port",
)

# --- FX-85: the node's own hard cap renders as a plain integer, never scientific notation -----
node_env = {e["name"]: e.get("value") for e in node_container["env"]}
check(
    node_env.get("URL4_CLOUD_RESULT_HARD_CAP_BYTES") == "67108864",
    "URL4_CLOUD_RESULT_HARD_CAP_BYTES renders as a plain integer string — Helm decodes large "
    "values.yaml integers as float64, and a bare `quote` would emit scientific notation "
    "(6.7108864e+07) that no Settings byte-size field can parse",
)

# --- FX-81: the App rolls when the shared signing Secret rotates, but only when node.enabled --
check(
    "checksum/artifact-signing"
    in url4_deployment["spec"]["template"]["metadata"]["annotations"],
    "the App pod carries checksum/artifact-signing when node.enabled — a rotated key must roll "
    "the App too, or it keeps verifying the node's NEW signatures against the OLD key",
)
engine_no_node = render(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
)
check(
    "checksum/artifact-signing"
    not in find_named(
        engine_no_node, "Deployment", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}"
    )["spec"]["template"]["metadata"]["annotations"],
    "with node.enabled=false (the default) the App carries NO checksum/artifact-signing "
    "annotation — there is no signer, so there is nothing to roll for",
)
check(
    not any(
        doc.get("kind") == "Deployment" and doc["metadata"]["name"] == node_name
        for doc in engine_no_node
    ),
    "node.enabled defaults to false (FX-86) — a bare `helm template` renders no node objects",
)

# --- FX-86: the chart REFUSES node.enabled without an s3 artifact backend --------------------
node_no_s3_error = render_fails(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
    "--set",
    "node.enabled=true",
)
check(
    node_no_s3_error is not None and "OME-929" in node_no_s3_error,
    "REFUSES node.enabled=true with the default filesystem artifactStorage.backend, naming the "
    "rule that governs the choice — a node with no shared object store cannot serve its own "
    "spilled results",
)

# --- FX-83: the chart REFUSES an unsafe timeout ladder or an unsafe grace period -------------
node_ladder_error = render_fails(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
    *ENGINE_NODE_ARGS,
    "--set",
    "node.aigatewayTimeoutS=30",
)
check(
    node_ladder_error is not None and "node.requestTimeoutS" in node_ladder_error,
    "REFUSES node.aigatewayTimeoutS >= node.requestTimeoutS — the inner failure must win so the "
    "caller gets a 502 naming aigateway rather than a bare 504",
)
node_grace_error = render_fails(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
    *ENGINE_NODE_ARGS,
    "--set",
    "node.terminationGracePeriodSeconds=38",
)
check(
    node_grace_error is not None and "node.spillTimeoutS" in node_grace_error,
    "REFUSES a node.terminationGracePeriodSeconds too small for preStop + requestTimeoutS + "
    "spillTimeoutS — otherwise the kubelet SIGKILLs an in-flight spill write",
)
engine_forward_configmap = find_named(
    engine_chart, "ConfigMap", f"{ENGINE_RELEASE}-{ENGINE_RELEASE}"
)
check(
    engine_forward_configmap["data"].get("URL4_CLOUD_NODE_FORWARD_TIMEOUT_S") == "35",
    "URL4_CLOUD_NODE_FORWARD_TIMEOUT_S is DERIVED (requestTimeoutS + spillTimeoutS + 1 = 35 by "
    "default), never a second literal that could drift from the node's own ladder",
)

print("\nreport-intake chart")
# THE DEFAULT INSTALL IS SAFE AND NOT USEFUL, deliberately: `authMode: disabled` is loopback-only
# and no edge is rendered. That is what keeps a bare `helm template` green on a clean checkout —
# and a green default render is what stops the chart's own refusals from being deleted under CI
# pressure, since they are the only render-time protection on this repo's first unauthenticated
# write.
intake = render(INTAKE_CHART, INTAKE_RELEASE)
intake_config = find(intake, "ConfigMap")
intake_deployment = find(intake, "Deployment")
intake_service = find(intake, "Service")
intake_container = intake_deployment["spec"]["template"]["spec"]["containers"][0]
declared_settings = settings_env_names()

check(
    not [
        doc
        for doc in intake
        if doc.get("kind") in {"HTTPRoute", "SecurityPolicy", "BackendTrafficPolicy"}
    ],
    "a bare install renders NO route and no edge policy — values.yaml is installable with no edge, "
    "as the engine's is",
)
check(
    not [doc for doc in intake if doc.get("kind") == "NetworkPolicy"],
    "a bare install renders no NetworkPolicy — enabled-with-no-peers is a refusal, not a default",
)
# The name checks run BEFORE anything reads a key by hand. A renamed key would otherwise abort
# this script on a KeyError, which reports as a broken verifier rather than as the drift it is.
check(
    rendered_env_names(intake) <= declared_settings,
    "renders no REPORT_INTAKE_ name Settings does not declare (extra='ignore' would drop it silently)",
)
check(
    intake_config["data"].get("REPORT_INTAKE_AUTH_MODE") == "disabled",
    "defaults to the LOOPBACK-ONLY posture: a forgotten authMode refuses callers, never admits them",
)
check(
    intake_container["envFrom"][0]["configMapRef"]["name"]
    == intake_config["metadata"]["name"],
    "the container actually reads that ConfigMap",
)
check(
    "checksum/config"
    in intake_deployment["spec"]["template"]["metadata"]["annotations"],
    "rolls the Pods when the ConfigMap changes — envFrom is read once, at container start",
)
check(
    intake_container["livenessProbe"]["httpGet"]["path"]
    != intake_container["readinessProbe"]["httpGet"]["path"],
    "liveness and readiness point at DIFFERENT endpoints (spec §10)",
)
check(
    intake_container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    and intake_container["readinessProbe"]["httpGet"]["path"] == "/readyz",
    "liveness is /healthz (never touches storage) and readiness is /readyz (fails closed)",
)
check(
    find(intake, "ServiceAccount").get("automountServiceAccountToken") is False,
    "mounts no Kubernetes API token — this service calls no Kubernetes API",
)

migrate = find(intake, "Job")
check(
    set(migrate["metadata"]["annotations"]["helm.sh/hook"].split(","))
    == {"pre-install", "pre-upgrade"},
    "applies the schema in a pre-install/pre-upgrade hook — the service never migrates itself",
)
check(
    "report_intake.db.TORTOISE_CONFIG"
    in migrate["spec"]["template"]["spec"]["containers"][0]["command"],
    "the migration names its config by dotted path, so the Job's working directory is not load-bearing",
)
migrate_env = {
    entry["name"]
    for entry in migrate["spec"]["template"]["spec"]["containers"][0]["env"]
}
check(
    migrate_env == {"REPORT_INTAKE_DATABASE_URL"},
    "the migration Job reads the database URL and NOTHING else — it runs no application code",
)

print("\nreport-intake cloud posture")
# The posture that actually deploys: two hostnames, Turnstile wired, mesh identity trusted.
intake_cloud = render(INTAKE_CHART, INTAKE_RELEASE, *INTAKE_CLOUD_ARGS)
cloud_config = find(intake_cloud, "ConfigMap")
cloud_deployment = find(intake_cloud, "Deployment")
cloud_container = cloud_deployment["spec"]["template"]["spec"]["containers"][0]
public_route = route_named(intake_cloud, f"{INTAKE_RELEASE}-report-intake-public")
identity_route = route_named(intake_cloud, f"{INTAKE_RELEASE}-report-intake-identity")
policy = find(intake_cloud, "SecurityPolicy")
provider = policy["spec"]["jwt"]["providers"][0]

check(
    rendered_env_names(intake_cloud) == declared_settings,
    f"renders EXACTLY the {len(declared_settings)} Settings fields — no name missing, none invented",
)
cloud_data: dict[str, str] = cloud_config["data"]
check(
    cloud_data.get("REPORT_INTAKE_AUTH_MODE") == "mesh_or_turnstile"
    and bool(cloud_data.get("REPORT_INTAKE_ALLOWED_NETWORKS")),
    "the cloud posture declares mesh_or_turnstile AND the networks that make it mean something",
)
# THE VALUES, not only the names. Every assertion above is about which keys exist; a key whose
# VALUE the app cannot parse renders perfectly, survives every structural check, and CrashLoops the
# pod at boot on a pydantic error — which is the same class of surprise the name checks exist to
# remove, one layer down.
numeric = numeric_settings()
unparseable = sorted(
    key
    for key, value in cloud_data.items()
    if key in numeric and not re.fullmatch(r"-?\d+(\.\d+)?", str(value))
)
check(
    not unparseable,
    f"every numeric setting renders as a number ({len(numeric)} of them) — `3s` would render fine "
    f"and then fail pydantic at boot",
)
check(
    cloud_data.get("REPORT_INTAKE_AUTH_MODE") in declared_auth_modes(),
    "AUTH_MODE is one of the values config.py's AuthMode Literal actually declares",
)
check(
    cloud_data.get("REPORT_INTAKE_TRUST_CLIENT_IP_HEADER") in {"true", "false"},
    "TRUST_CLIENT_IP_HEADER renders a bool pydantic accepts, not Helm's Go-template spelling",
)
networks_strict = True
try:
    for part in cloud_data.get("REPORT_INTAKE_ALLOWED_NETWORKS", "").split(","):
        if part.strip():
            ipaddress.ip_network(part.strip(), strict=True)
except ValueError:
    networks_strict = False
check(
    networks_strict,
    "every allowed network parses with strict=True — config.py refuses a value with host bits set "
    "rather than widening it to the enclosing network",
)

# Emitted at all, before it is compared: it is not a REPORT_INTAKE_ name, so the equality check
# above says nothing about it, and an absent one silently falls back to uvicorn's own default.
check(
    bool(cloud_data.get("FORWARDED_ALLOW_IPS")),
    "states FORWARDED_ALLOW_IPS in the manifest rather than inheriting a uvicorn default that moves",
)
check(
    cidr_overlap(
        cloud_data.get("FORWARDED_ALLOW_IPS", ""),
        cloud_data.get("REPORT_INTAKE_ALLOWED_NETWORKS", ""),
    )
    is None,
    "FORWARDED_ALLOW_IPS is DISJOINT from ALLOWED_NETWORKS — otherwise uvicorn lets a client "
    "rewrite the peer address the identity check and the rate-limit key both read",
)
turnstile_env = next(
    (
        entry
        for entry in cloud_container["env"]
        if entry["name"] == "REPORT_INTAKE_TURNSTILE_SECRET"
    ),
    {},
)
check(
    "valueFrom" in turnstile_env and "value" not in turnstile_env,
    "the Turnstile secret comes from a Secret — the chart never holds the literal",
)
check(
    "TURNSTILE_SITE_KEY" not in yaml.safe_dump(intake_cloud),
    "renders no Turnstile SITE key — it is a browser-side value this service never reads",
)

check(
    {"x-user-email", "cf-connecting-ip"} <= headers_removed_by(public_route),
    "the PUBLIC route strips X-User-Email and CF-Connecting-IP — unconditionally, no value gates it",
)
check(
    "cf-connecting-ip" in headers_removed_by(identity_route),
    "the identity route strips CF-Connecting-IP too — a verified caller is still not the rate-limit key",
)
check(
    "x-user-email" not in headers_removed_by(identity_route),
    "the identity route does NOT strip X-User-Email: claimToHeaders SETS it, and removing it here "
    "would make the outcome depend on filter order and demote every mesh caller to anonymous",
)
check(
    policy["spec"]["targetRefs"][0]["name"] == identity_route["metadata"]["name"],
    "the SecurityPolicy targets the identity route BY THE NAME that route actually has",
)
check(
    "optional" not in yaml.safe_dump(policy["spec"]["jwt"]),
    "the JWT filter declares no `optional` — with optional:true claimToHeaders never runs for a "
    "token-less request and a client-supplied X-User-Email reaches the backend intact",
)
check(
    bool(provider.get("audiences")),
    "scopes acceptance to ONE Access application — without an audience the whole team is admitted",
)
check(
    {"claim": "email", "header": "X-User-Email"} in provider["claimToHeaders"],
    "maps the verified email claim onto the one header identity/mesh_identity.py reads",
)
backends = {
    ref["name"]
    for route in (public_route, identity_route)
    for rule in route["spec"]["rules"]
    for ref in rule["backendRefs"]
}
check(
    backends == {intake_service["metadata"]["name"]},
    "both routes name the Service this chart renders, and no other backend",
)
route_prefixes = {
    match["path"]["value"]
    for route in (public_route, identity_route)
    for rule in route["spec"]["rules"]
    for match in rule["matches"]
}
check(
    route_prefixes == {"/v1/reports"},
    "both routes publish the WRITE endpoint only — a `/` prefix would put the ungated, "
    "unbudgeted /readyz (one database query per request) on a public hostname",
)

# SPEC §7's EDGE RATE LIMIT. `config.anonRate` is NOT it: that limiter keys on the TCP peer, which
# inside the cluster is the mesh proxy on every request, so it is one bucket shared by every
# anonymous caller on the internet. Only the edge can see a caller, which is why this is an object.
# Read tolerantly, never with `find`: a policy that stopped rendering must report as the four named
# failures below rather than aborting this script twenty lines from the problem. That is the lesson
# the first pass over this chart paid for, and "the object is gone" is exactly the case that
# re-teaches it.
edge_rate_limit = next(
    (doc for doc in intake_cloud if doc.get("kind") == "BackendTrafficPolicy"), {}
)
edge_spec = edge_rate_limit.get("spec", {})
edge_limit = edge_spec.get("rateLimit", {})
edge_rules = edge_limit.get("global", {}).get("rules", [])
check(
    bool(edge_rate_limit),
    "the cloud posture renders spec §7's edge rate limit for anonymous callers — the in-process "
    "config.anonRate is the service-side backstop, keyed on the mesh proxy, not the per-caller limit",
)
check(
    [ref.get("name") for ref in edge_spec.get("targetRefs", [])]
    == [public_route["metadata"]["name"]],
    "the edge rate limit targets the PUBLIC route BY THE NAME that route actually has, and targets "
    "nothing else — a policy naming a route that does not exist limits nothing and reports Accepted",
)
check(
    edge_limit.get("type") == "Global",
    "the edge rate limit is Global — Envoy's LOCAL limiter cannot do Distinct matching, so the only "
    "thing it could express is the one shared bucket config.anonRate already is, one layer out",
)
check(
    bool(edge_rules)
    and all(
        rule.get("clientSelectors")
        and all(
            selector.get("sourceCIDR", {}).get("type") == "Distinct"
            for selector in rule["clientSelectors"]
        )
        for rule in edge_rules
    ),
    "every rule buckets PER CLIENT ADDRESS (Distinct) — the default Exact would give 0.0.0.0/0 one "
    "budget shared by everyone, and a rule with NO selector is that same shared bucket unlabelled",
)

print("\nreport-intake refusals")
anonymous_error = render_fails(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "anonymous.enabled=true"
)
check(
    anonymous_error is not None and "unauthenticated write" in anonymous_error,
    "REFUSES anonymous.enabled with turnstile.enabled=false, naming what the guard protects",
)
mesh_error = render_fails(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "config.authMode=mesh_or_turnstile"
)
check(
    mesh_error is not None and "config.allowedNetworks" in mesh_error,
    "REFUSES mesh_or_turnstile with no allowedNetworks — nothing could ever be mesh-verified",
)
secret_error = render_fails(
    INTAKE_CHART,
    INTAKE_RELEASE,
    "--set",
    "config.authMode=mesh_or_turnstile",
    "--set",
    "config.allowedNetworks[0]=10.0.0.0/8",
)
check(
    secret_error is not None and "503" in secret_error,
    "REFUSES mesh_or_turnstile with no Turnstile secret — every anonymous report would be 503 forever",
)
loopback_error = render_fails(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "gateway.enabled=true"
)
check(
    loopback_error is not None and "LOOPBACK-ONLY" in loopback_error,
    "REFUSES an edge in front of a loopback-only pod, which would 403 every request through it",
)
forwarded_error = render_fails(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "config.forwardedAllowIps=*"
)
check(
    forwarded_error is not None and "X-Forwarded-For" in forwarded_error,
    "REFUSES FORWARDED_ALLOW_IPS='*', which lets any caller rewrite the peer address",
)
# Selecting the `linear` sink is a DECISION, not a knob: it is the selection CLAUDE.md rule 9
# governs, and it puts a long-lived credential to the private tracker into the pod. Both halves
# are required for the same reason the Turnstile secret is — a pod missing either accepts every
# report, answers 202, files none of them, and reports itself ready.
linear_team_error = render_fails(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "config.ticketSink=linear"
)
check(
    linear_team_error is not None and "config.linearTeamId" in linear_team_error,
    "REFUSES ticketSink=linear with no team — an issue create with no teamId is refused on every "
    "report, which is a queue quietly growing rather than a pod that fails",
)
linear_secret_error = render_fails(
    INTAKE_CHART,
    INTAKE_RELEASE,
    "--set",
    "config.ticketSink=linear",
    "--set",
    "config.linearTeamId=b9c1f0de-0000-4000-8000-000000000000",
    "--set",
    "linear.existingSecret=",
)
check(
    linear_secret_error is not None and "OME-976" in linear_secret_error,
    "REFUSES ticketSink=linear with no API key Secret, naming the rule that governs the choice",
)
linear_env = next(
    (
        entry
        for entry in intake_container["env"]
        if entry["name"] == "REPORT_INTAKE_LINEAR_API_KEY"
    ),
    {},
)
check(
    "valueFrom" in linear_env
    and "value" not in linear_env
    and linear_env["valueFrom"]["secretKeyRef"].get("optional") is True,
    "the Linear API key comes from an OPTIONAL Secret — the chart holds no literal, and the "
    "Secret not existing is the normal state rather than a Pod stuck in CreateContainerConfigError",
)
# `optional: true` does NOT exempt `name` from Kubernetes' own validation
# (`validateSecretKeySelector` requires it), so an empty one is rejected at APPLY with
# `secretKeyRef.name: Required value` — after helm has already run the pre-install migration hook.
# Clearing this value is the natural way an operator says "reference no Linear secret at all", and
# values.schema.json deliberately gives it no minLength, so the entry is guarded on a non-empty
# name rather than merely documented.
secretless_intake = render(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "linear.existingSecret="
)
secretless_container = find(secretless_intake, "Deployment")["spec"]["template"][
    "spec"
]["containers"][0]
check(
    not [
        entry
        for entry in secretless_container["env"]
        if not entry.get("valueFrom", {}).get("secretKeyRef", {}).get("name", "x")
    ],
    "an EMPTY linear.existingSecret renders no empty-named secretKeyRef — an env entry naming no "
    "Secret is rejected at apply even with optional: true, and by then the migration hook has run",
)
# GHCR org packages are private by default and the migration Job is a pre-install hook at weight
# -5: without a pull secret a private-registry install stops at ImagePullBackOff before any Pod is
# scheduled, and the Deployment that would have worked never renders. The Deployment carried this
# block and the Job did not — the same asymmetry apps/scoreboard's chart does not have.
pulled = render(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "imagePullSecrets[0].name=ghcr-creds"
)
check(
    all(
        doc["spec"]["template"]["spec"].get("imagePullSecrets")
        == [{"name": "ghcr-creds"}]
        for doc in pulled
        if doc.get("kind") in {"Deployment", "Job"}
    ),
    "EVERY pod-carrying object renders imagePullSecrets, the migration hook included — a private "
    "registry otherwise blocks the whole release on a Job whose only symptom is a pull error",
)
rate_limit_error = render_fails(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "gateway.public.rateLimit.enabled=true"
)
check(
    rate_limit_error is not None and "reports Accepted" in rate_limit_error,
    "REFUSES an edge rate limit with anonymous.enabled=false — the policy targets the public route "
    "by name, and with no such route it attaches to nothing, limits nothing, and reports Accepted",
)
peerless_error = render_fails(
    INTAKE_CHART, INTAKE_RELEASE, "--set", "networkPolicy.enabled=true"
)
check(
    peerless_error is not None and "admits every source" in peerless_error,
    "REFUSES a NetworkPolicy with no peers rather than emitting an allow-all",
)
# The cloud posture with the one value that quietly returns it to "any pod in the cluster may
# forge an identity". Everything else in values-cloud.yaml is empty-and-required; this is the
# value an operator could turn OFF, so the refusal is what makes doing it deliberate.
unrestricted_error = render_fails(
    INTAKE_CHART,
    INTAKE_RELEASE,
    *INTAKE_CLOUD_ARGS,
    "--set",
    "networkPolicy.enabled=false",
)
check(
    unrestricted_error is not None and "acknowledgeUnrestricted" in unrestricted_error,
    "REFUSES mesh_or_turnstile with no NetworkPolicy unless the operator acknowledges it — the "
    "peer check authenticates a NETWORK, and the edge header-strip does not cover the in-cluster path",
)
acknowledged = render(
    INTAKE_CHART,
    INTAKE_RELEASE,
    *INTAKE_CLOUD_ARGS,
    "--set",
    "networkPolicy.enabled=false",
    "--set",
    "networkPolicy.acknowledgeUnrestricted=true",
)
check(
    not [doc for doc in acknowledged if doc.get("kind") == "NetworkPolicy"],
    "the acknowledgement is an escape hatch and not a second way to render the policy — a cluster "
    "restricting the Service some other way installs, with the choice recorded in its values",
)

intake_policy = find(
    render(
        INTAKE_CHART,
        INTAKE_RELEASE,
        "--set",
        "networkPolicy.enabled=true",
        "--set",
        "networkPolicy.clientPodNames[0]=envoy-gateway",
    ),
    "NetworkPolicy",
)
check(
    "envoy-gateway" in peer_names(intake_policy, "ingress"),
    "admits the named peer with namespace and pod selectors PAIRED in one element",
)
check(
    intake_policy["spec"]["policyTypes"] == ["Ingress"],
    "declares Ingress only — this pod dials Cloudflare's siteverify, whose ranges are not knowable here",
)

print("\nthe publishing lanes")
# A chart naming an image nobody publishes is installable and permanently ImagePullBackOff, and
# neither the chart nor the workflow can notice on its own — renaming either side is a silent
# break. This is the only place they are compared.
lane = yaml.safe_load((REPO / ".github/workflows/release-aigateway-ui.yml").read_text())
published_image = lane["env"]["IMAGE"]
console_image = c_deployment["spec"]["template"]["spec"]["containers"][0]["image"]
check(
    console_image.rsplit(":", 1)[0] == published_image,
    f"the chart's image ({console_image.rsplit(':', 1)[0]}) IS the one the release lane publishes",
)

# report-intake publishes from two lanes — a release lane on the `report-intake-v*` tag and a dev
# lane on every merge to main — and this is the only place either is compared to the chart.
intake_lane = yaml.safe_load(
    (REPO / ".github/workflows/release-report-intake.yml").read_text()
)
intake_published = intake_lane["env"]["IMAGE"]
intake_image = intake_container["image"]
check(
    intake_image.rsplit(":", 1)[0] == intake_published,
    f"report-intake's chart image ({intake_image.rsplit(':', 1)[0]}) IS the one its release lane publishes",
)
# `on:` reaches pyyaml as YAML 1.1's boolean True rather than the string, which is why every
# other lane check in this file reads `env` or `jobs`. Both spellings accepted so this does not
# depend on which YAML version the loader implements.
intake_triggers = intake_lane.get("on") or intake_lane[True]
intake_component = json.loads((REPO / "release-please-config.json").read_text())[
    "packages"
]["apps/report-intake"]
check(
    intake_triggers["push"]["tags"]
    == [f"{intake_component['component']}{intake_component['tag-separator']}v*"],
    "report-intake's release lane consumes exactly the tag release-please-config.json emits — a "
    "renamed component would otherwise leave the tag building nothing, silently",
)
check(
    intake_image.rsplit(":", 1)[1] != "",
    "report-intake's chart pins an image TAG (appVersion, set from the tag at package time)",
)


# The dev lane, same contract as aigateway-ui's: a dev cluster tracks main by overriding image.tag
# on the chart it already has, which only works while the dev image is the SAME repository the
# chart and the release lane already agree on. A dev image under another name is one the chart can
# never be pointed at without editing values, and nothing else in CI compares the two.
# TWO LANES RENDER `values-cloud.yaml` AND BOTH NEED THE SAME PLACEHOLDERS, because that file
# deliberately ships every value a chart cannot know as empty-and-required. This comparison exists
# because the drift already happened: when the review pass emptied `config.allowedNetworks` and
# `networkPolicy.clientPodNames`, `charts.yml` gained three placeholders and the release lane did
# not — and a lane that runs only on a `report-intake-v*` tag cannot notice that it can no longer
# render. `charts.yml` runs on every PR touching the chart, so it is the one that stays current;
# this makes the release lane keep up with it.
def cloud_render_flags(workflow: str, job: str, step_name: str) -> set[str]:
    """The `--set` KEYS in one workflow step's shell block. Keys, not values: the placeholders are
    arbitrary strings and only the set of values being supplied is the contract."""
    spec = yaml.safe_load((REPO / ".github/workflows" / workflow).read_text())
    step = next(s for s in spec["jobs"][job]["steps"] if s.get("name") == step_name)
    return set(re.findall(r"--set '?([A-Za-z0-9_.\[\]]+)=", step["run"]))


charts_lane_flags = cloud_render_flags(
    "charts.yml", "render", "Render report-intake's cloud values"
)
check(
    bool(charts_lane_flags)
    and cloud_render_flags("release-report-intake.yml", "chart", "Render")
    == charts_lane_flags,
    f"the release lane renders values-cloud.yaml with the SAME {len(charts_lane_flags)} "
    f"placeholders charts.yml does — a lane that only runs on a release tag cannot notice that a "
    f"newly-required value has left it unable to render",
)

# The GitHub Release body is the ONE artefact a downstream installer reads without opening the
# repo, and it counted the install-time values in prose. It said "five" for a while after the
# chart had grown to eight — omitting the two that decide who may present an identity to this
# service. Prose about a number drifts silently, so the number is asserted against the `--set`
# keys that same lane passes. Whitespace is collapsed first: the body is a folded YAML block and
# the phrase wraps across lines in it.
lane_prose = " ".join(
    (REPO / ".github/workflows/release-report-intake.yml").read_text().split()
)
count_words = {
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}
expected_count = count_words.get(len(charts_lane_flags))
check(
    expected_count is not None
    and lane_prose.count(f"{expected_count} install-time values") == 2
    and not [
        word
        for count, word in count_words.items()
        if count != len(charts_lane_flags)
        and f"{word} install-time values" in lane_prose
    ],
    f"the release lane's header AND its Release body both say {expected_count!r} install-time "
    f"values, matching the placeholders it renders with — the Release body is what an installer "
    f"reads instead of the repo",
)

intake_dev_lane = yaml.safe_load(
    (REPO / ".github/workflows/dev-build-report-intake.yml").read_text()
)
intake_dev_tags = [
    tag.strip()
    for tag in intake_dev_lane["jobs"]["image"]["steps"][-1]["with"]["tags"].split("\n")
    if tag.strip()
]
check(
    any(tag.rsplit(":", 1)[0] == intake_published for tag in intake_dev_tags),
    "report-intake's dev lane pushes the SAME image repository the chart and release lane name",
)
check(
    all(":main-" in tag for tag in intake_dev_tags)
    and not any(tag.endswith(":latest") for tag in intake_dev_tags),
    "report-intake's dev lane publishes only immutable main-<sha> tags — never :latest",
)

# The dev lane feeds the dev cluster (OME-714, following #452). It pushes the same repository under
# a main-<sha> tag to two registries, so the chart can be pointed at either by overriding
# image.repository/tag. What must hold is that the GHCR name is the same repository the chart and
# the release lane already agree on — a dev image under a different name is one the chart can never
# be pointed at without editing values.
dev_lane = yaml.safe_load(
    (REPO / ".github/workflows/dev-build-aigateway-ui.yml").read_text()
)
dev_tags = [
    t.strip()
    for t in dev_lane["jobs"]["image"]["steps"][-1]["with"]["tags"].split("\n")
    if t.strip()
]
check(
    any(t.rsplit(":", 1)[0] == published_image for t in dev_tags),
    "the dev lane pushes the SAME image repository the chart and release lane name",
)
check(
    all(":main-" in t for t in dev_tags)
    and not any(t.endswith(":latest") for t in dev_tags),
    "the dev lane publishes only immutable main-<sha> tags — never :latest",
)

url4_dev_lane = yaml.safe_load(
    (REPO / ".github/workflows/dev-build-screamingface-engine.yml").read_text()
)
url4_benchmark_tags = {
    tag.strip()
    for tag in url4_dev_lane["jobs"]["benchmark-image"]["steps"][-1]["with"][
        "tags"
    ].split("\n")
    if tag.strip()
}
check(
    {
        "ghcr.io/screamingface/screamingface-engine-benchmark:"
        "main-${{ needs.image.outputs.short }}",
        "acropenmined.azurecr.io/screamingface-engine-benchmark:"
        "main-${{ needs.image.outputs.short }}",
        "acropenmined.azurecr.io/screamingface-engine-benchmark:main-${{ github.sha }}",
    }
    <= url4_benchmark_tags,
    "the dev lane publishes the paired benchmark image to GHCR and ACR",
)

url4_release_lane = yaml.safe_load(
    (REPO / ".github/workflows/release-screamingface-engine.yml").read_text()
)
release_benchmark_job = url4_release_lane["jobs"]["benchmark-image"]
release_benchmark_repo = release_benchmark_job["env"]["REPO"]
release_benchmark_tags = {
    tag.strip().replace("${{ env.REPO }}", release_benchmark_repo)
    for tag in release_benchmark_job["steps"][-1]["with"]["tags"].split("\n")
    if tag.strip()
}
check(
    {tag.rsplit(":", 1)[0] for tag in release_benchmark_tags}
    == {url4_runner_repository},
    "the release lane publishes the Runner repository rendered by the chart",
)
check(
    release_benchmark_tags
    and not any(tag.endswith(":latest") for tag in release_benchmark_tags),
    "the benchmark image is published only under immutable version tags",
)

# analytics publishes from ONE lane — the dev lane on every merge to main. There is no release
# lane yet, so unlike the pairs above there is no second publisher to agree with: the chart default
# and this lane are the whole agreement, which is why it is asserted here rather than left to a
# release lane that does not exist. A chart naming an image nobody pushes is installable and
# permanently ImagePullBackOff.
analytics_chart_values = yaml.safe_load(
    (REPO / "apps/analytics/charts/analytics/values.yaml").read_text()
)
analytics_dev_lane = yaml.safe_load(
    (REPO / ".github/workflows/dev-build-analytics.yml").read_text()
)
analytics_dev_tags = [
    tag.strip()
    for tag in analytics_dev_lane["jobs"]["image"]["steps"][-1]["with"]["tags"].split(
        "\n"
    )
    if tag.strip()
]
check(
    any(
        tag.rsplit(":", 1)[0] == analytics_chart_values["image"]["repository"]
        for tag in analytics_dev_tags
    ),
    f"analytics's dev lane pushes the SAME image repository the chart names "
    f"({analytics_chart_values['image']['repository']})",
)
check(
    all(":main-" in tag for tag in analytics_dev_tags)
    and not any(tag.endswith(":latest") for tag in analytics_dev_tags),
    "analytics's dev lane publishes only immutable main-<sha> tags — never :latest",
)

# A shared GHA cache scope between images with disjoint layer sets (uv/Python vs node/Next.js) is
# not incorrect, but it is pure eviction pressure with no hits. Cheap to assert, easy to get wrong
# by copying a sibling lane.
scopes = {}
for wf in sorted((REPO / ".github/workflows").glob("dev-build-*.yml")):
    spec = yaml.safe_load(wf.read_text())
    step = spec["jobs"]["image"]["steps"][-1]["with"]
    scopes[wf.name] = step.get("cache-to", "")
check(
    len(set(scopes.values())) == len(scopes),
    f"every dev-build lane has its OWN cache scope "
    f"({len(scopes)} lanes, {len(set(scopes.values()))} distinct)",
)
# `helm package --app-version "$VERSION"` sets appVersion from the tag, and the chart's image
# helper falls back to appVersion when image.tag is empty — so a released chart pins the exact
# version that release built, without the values file naming a version at all.
check(
    console_image.rsplit(":", 1)[1] != "" and ":" in console_image,
    "the chart pins an image TAG rather than leaving it floating at :latest",
)

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("\nFAILED:")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)
print("chart wiring verified")
