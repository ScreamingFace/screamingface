#!/usr/bin/env python3
"""Assert what the aigateway, aigateway-ui, and screamingface-engine charts actually render.

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

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
GATEWAY_CHART = REPO / "apps/aigateway/charts/aigateway"
CONSOLE_CHART = REPO / "apps/aigateway-ui/charts/aigateway-ui"
ENGINE_CHART = REPO / "apps/screamingface-engine/deploy/helm"

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
garage_policy = find_named(gw_snap, "NetworkPolicy", f"{GATEWAY_RELEASE}-aigateway-garage")
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
check(
    garage_sts["spec"]["template"]["metadata"]["labels"].get("app.kubernetes.io/component")
    == "garage",
    "bundled Garage Pods carry component: garage",
)
check(
    garage_policy["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/component")
    == "garage",
    "the Garage NetworkPolicy selects ONLY Garage Pods",
)
check(
    [p["port"] for rule in garage_policy["spec"]["ingress"] for p in rule.get("ports", [])]
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
    gw_snap_policy["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/component")
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
    and external_secret["stringData"]["AIGW_CACHE_SNAPSHOT_S3_SECRET_KEY"] == "SKEXTERNAL",
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
engine_chart = render(
    ENGINE_CHART,
    ENGINE_RELEASE,
    "--set-string",
    "config.natsUrl=nats://nats.example:4222",
)
url4_deployment = find(engine_chart, "Deployment")
url4_config = find_data_owner(engine_chart, "URL4_CLOUD_RUNNER_IMAGE")
url4_app_image = url4_deployment["spec"]["template"]["spec"]["containers"][0]["image"]
url4_runner_image = url4_config["data"]["URL4_CLOUD_RUNNER_IMAGE"]
url4_app_repository, url4_app_tag = url4_app_image.rsplit(":", 1)
url4_runner_repository, url4_runner_tag = url4_runner_image.rsplit(":", 1)
check(
    url4_runner_repository == f"{url4_app_repository}-benchmark",
    "derives the Runner repository from the control-plane repository",
)
check(
    url4_runner_tag == url4_app_tag,
    "pins the Runner and control-plane images to the same tag",
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
