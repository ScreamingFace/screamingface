from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_PREFIX = "REPORT_INTAKE_"

DEFAULT_DATABASE_URL = "sqlite://./report-intake.sqlite3"

DEFAULT_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

DEFAULT_LINEAR_API_URL = "https://api.linear.app/graphql"
"""Linear's one GraphQL endpoint. A default rather than a required value, because there is
exactly one of them and an operator who had to type it could only get it wrong."""

AuthMode = Literal["disabled", "mesh_or_turnstile"]
"""The two postures this service runs in (plan §2.4).

`disabled` is the local development posture and is loopback-only, enforced by
:class:`report_intake.core.local_only.LoopbackOnlyMiddleware` — a service that admits every
caller and asks nothing of them is safe only while nothing but the operator can reach it.

`mesh_or_turnstile` is the deployed posture and is spec §7's two caller classes: an address the
mesh injected satisfies the gate, and everyone else presents a Turnstile token inside a rate
limit. There is deliberately no third mode: "mesh only" would make the richest reports
unsendable (the Python SDK holds an Access token but parses only `exp` from it, so it has no
address to present), and "turnstile only" would ask a verified caller to prove it is a browser.
"""


def normalize_database_url(database_url: str) -> str:
    """Accept the common relative-file sqlite spelling instead of writing to the filesystem root.

    ``sqlite:///report-intake.sqlite3`` reads as "relative file" to almost everyone and means
    ``/report-intake.sqlite3`` to the driver. In the container that path is not writable by the
    unprivileged service user, so the mistake surfaces as a database error at the first write
    rather than at startup. Rewritten here, exactly as `apps/scoreboard` does it.
    """
    sqlite_absolute_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_absolute_prefix):
        return database_url

    path = database_url.removeprefix(sqlite_absolute_prefix)
    if not path or "/" in path:
        return database_url

    return f"sqlite://./{path}"


class Settings(BaseSettings):
    """The sole authority on this service's environment.

    Every variable this service reads is a field here, and the Helm chart renders exactly this
    set — nothing more. That is a contract, not a tidiness preference: ``extra="ignore"`` makes a
    name mismatch completely silent, so a chart rendering ``REPORT_INTAKE_IDENTITY_MODE`` against
    a field called ``auth_mode`` produces a pod that boots happily with the DEFAULT posture
    instead of the configured one. A guard in :func:`report_intake.main.create_app` turns that
    silence into a startup failure; a chart-side assertion is the second half.

    Fields are added by the item that reads them — this module is edited, never re-created.
    """

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    host: str = "127.0.0.1"
    port: int = 9109
    log_level: str = "info"

    database_url: str = DEFAULT_DATABASE_URL
    """Where the one `reports` table lives.

    The schema is applied by ``tortoise migrate``, never by the service itself. Auto-migrating on
    startup would mean every replica racing the same DDL on a fresh database, and this service is
    deployed with more than one (`OME-1010` claims retry rows by lease precisely because of it).
    Until the migration has run, ``/readyz`` fails closed — which is the correct answer for a pod
    whose database has no schema, and is what keeps it out of the load balancer.
    """

    idempotency_ttl_h: int = 24
    """Spec §5's replay window, in hours. Within it a repeated `Idempotency-Key` returns the
    ORIGINAL record with `200`; after it the same key is a new report. Matches the scoreboard's
    existing `idempotency_keys` TTL, deliberately — a client retrying against two ScreamingFace
    services should not have to learn two windows."""

    retention_days: int = 90
    """Spec §5's row retention. The ticket is the durable artifact; the row exists for
    idempotency, retry, and operational forensics, so it is purged rather than kept forever."""

    ticket_sink: str = "queue"
    """Which `TicketSink` adapter this deployment files through.

    The authority on the valid names is ``report_intake.delivery.registry.SINKS``, which
    ``create_app`` resolves this against at boot and refuses to start on a name it does not know.
    Deliberately NOT an enum here: the field is a plain string so that adding an adapter is one
    registry line rather than an edit to config, a chart, and this module at once.
    """

    delivery_timeout_s: float = 3.0
    """Spec §2.2 and §6's inline delivery deadline — 3 s, not the drafting pass's 10 s (plan §11
    conflict 18).

    It bounds how long a reporter waits for a sink that may be slow or gone. Past it the row stays
    `pending`, the response is still `202`, and the retry queue owns the report — so raising this
    number does not make delivery more likely, it only makes a bug report slower to file.
    """

    # --- the `linear` sink's four fields ------------------------------------------------------
    #
    # ALL FOUR ARE INERT unless `ticket_sink` names `linear`. Nothing reads them otherwise: the
    # registry builds one adapter, and `queue` is the default (spec §9). They are declared here
    # anyway rather than being read from the environment behind `Settings`' back, because this
    # class is the sole authority on this service's environment and `create_app` refuses to start
    # on a `REPORT_INTAKE_*` name no field reads — so the field and its reader land together or
    # neither does. CLAUDE.md rule 9 governs *selecting* that sink; see `delivery/linear_sink.py`.
    #
    # NO `NoDecode` on any of them: none is a collection. `NoDecode` exists on the two tuple
    # fields below because pydantic-settings JSON-decodes complex types read from the environment,
    # and a scalar is never JSON-decoded.

    linear_api_key: SecretStr = SecretStr("")
    """The Linear API key, from a Secret. Never logged, never in a `repr`, never in an exception.

    `SecretStr` for the same reason :attr:`turnstile_secret` is: the value has to survive being
    near a `repr` of these settings — a traceback, a debug dump, a startup log line — and the type
    is what makes that safe rather than a rule every future reader has to remember. Read it with
    `.get_secret_value()`, which is spelled out in exactly one place (`delivery/registry.py`).

    A PERSONAL/scoped API key, which Linear authenticates with a bare `Authorization: <key>`
    header — no `Bearer` prefix, which is an OAuth token's spelling and is silently rejected here.

    Empty by default, and empty is what keeps the adapter inert: `build_sink` refuses to start a
    `ticket_sink=linear` deployment that has no key rather than accepting reports and filing none
    of them behind a healthy `/readyz`.
    """

    linear_team_id: str = ""
    """The Linear team every issue is created in — `IssueCreateInput.teamId`, a UUID.

    Not a team KEY (`OME`): the mutation takes an id, and a key posted as one is a validation
    error on every report rather than a boot failure on none. Required alongside the key, and
    checked at boot for the same reason.
    """

    linear_api_url: str = DEFAULT_LINEAR_API_URL
    """Where the mutation is posted. A field rather than a constant so a test — and a future
    air-gapped or proxied deployment — can point it somewhere else without patching a module,
    exactly as :attr:`turnstile_verify_url` is."""

    linear_timeout_s: float = 3.0
    """How long the outbound call to Linear has, on its own.

    Matches :attr:`delivery_timeout_s`, which is the OUTER bound the dispatcher already imposes
    (`asyncio.wait_for`). This one exists so the HTTP client gives up by itself rather than being
    cancelled mid-flight, and so the adapter is bounded when something other than the dispatcher
    calls it. Raising it past `delivery_timeout_s` buys nothing: the dispatcher's deadline still
    fires first and the row stays `pending` for the retry queue either way.
    """

    # WHY `NoDecode` on every list/tuple field: pydantic-settings JSON-decodes complex field
    # types read from the environment, so without it `REPORT_INTAKE_ALLOWED_NETWORKS=10.0.0.0/8`
    # fails as malformed JSON before the validator below ever runs. These values are
    # comma-separated lists, not JSON.
    allowed_networks: Annotated[tuple[IPv4Network | IPv6Network, ...], NoDecode] = Field(default=())
    """Peers that may present a mesh-injected identity header, as CIDR networks.

    AIDEV-NOTE: setting this makes the truthfulness of ``request.client.host`` load-bearing,
    which pulls in an env var that is NOT a field here — uvicorn's own ``FORWARDED_ALLOW_IPS``.
    A guard in :func:`report_intake.main.create_app` enforces the relationship. If you are
    auditing "what must be configured correctly for the peer check to mean anything" and read
    only this module, you will miss it.
    """

    auth_mode: AuthMode = "disabled"
    """Which of spec §7's postures this process runs in. See :data:`AuthMode`.

    Defaults to `disabled`, which is loopback-only, because the failure direction matters: a
    deployment that forgets to set this is a local-only process that refuses network callers,
    not an open one. `create_app` refuses to build a `mesh_or_turnstile` app that cannot
    actually run the gate — no `allowed_networks` means nothing can ever be mesh-verified, and
    no `turnstile_secret` means every anonymous caller gets an unevaluable gate forever.
    """

    trust_client_ip_header: bool = False
    """Whether the rate-limit key may come from the edge's client-IP header rather than the peer.

    INVARIANT: default false, and even when true the header is read **only** from a peer inside
    :attr:`allowed_networks`. Trusting it from any peer would mean trusting it always — the mesh
    proxy is the peer on every request — and a rotated header then yields a fresh bucket per
    request *and* evicts real callers' windows from a capped table. Turn this on only where the
    edge is known to overwrite the header rather than forward a client's copy.
    """

    turnstile_secret: SecretStr = SecretStr("")
    """The Cloudflare Turnstile secret, from a Secret. Never logged, never echoed to a client.

    `SecretStr` for the same reason aigateway's credentials are: the value has to survive being
    near a `repr` of these settings — in a traceback, a debug dump, a future startup log line —
    and the type is what makes that safe rather than a rule everyone has to remember. Read it
    with `.get_secret_value()`, which is the one place it is spelled out.

    The matching *site* key is deliberately absent from this service's environment: it is a
    browser-side value this process never reads, and rendering it into the pod would be cargo
    cult (plan §2.4).
    """

    turnstile_verify_url: str = DEFAULT_TURNSTILE_VERIFY_URL
    """Where the bot gate verifies a token. A field rather than a constant so a test — and a
    future air-gapped deployment — can point it somewhere else without patching a module."""

    turnstile_timeout_s: float = 3.0
    """How long siteverify has. Past it the gate is *unevaluable*, which is a `503` and not a
    `403`: the client must retry unchanged rather than fetch a token that was never the problem.
    Matches :attr:`delivery_timeout_s`, and for the same reason — it bounds how long a reporter
    waits on somebody else's service."""

    # `ge=1` on all four, because each is a divisor or a capacity: a zero rate is a division by
    # zero inside the bucket and a zero burst is a service that admits nobody. Refusing the value
    # at boot is better than either.
    anon_rate_limit: int = Field(default=30, ge=1)
    """Sustained anonymous requests per :attr:`anon_rate_window_s`, per key."""

    anon_rate_window_s: int = Field(default=60, ge=1)
    """The window :attr:`anon_rate_limit` is measured over, and the `Retry-After` a caller with an
    empty bucket is given."""

    anon_rate_burst: int = Field(default=5, ge=1)
    """How many requests a key may make back to back before the sustained rate binds.

    Deliberately smaller than :attr:`anon_rate_limit`: a human filing a bug report sends one
    request, occasionally two after a retry, and the burst is what a legitimate double-click
    needs — not what a submission loop needs.
    """

    anon_rate_max_keys: int = Field(default=10_000, ge=1)
    """The ceiling on the key table. Reaching it refuses NEW keys as throttled rather than
    evicting old ones (plan §11 conflict 14): evict-oldest would make filling the table the way
    to clear somebody else's window, so overflow fails closed instead."""

    # WHY `NoDecode` here too: same reason as `allowed_networks` below — a comma-separated list
    # read from the environment is not JSON.
    cors_origins: Annotated[tuple[str, ...], NoDecode] = Field(default=())
    """Browser origins allowed to post a report (spec §2.1: the portal and aigateway-ui are
    first-class callers, not an exception).

    INVARIANT: this is not an authorization control. It decides which origins a *browser* will
    let read a response; it decides nothing about who may file a report, which is what the mesh
    check and the bot gate are for. Credentials are never allowed on these responses.
    """

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, database_url: str) -> str:
        return normalize_database_url(database_url)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return tuple(origin for part in value.split(",") if (origin := part.strip()))

    @field_validator("allowed_networks", mode="before")
    @classmethod
    def _parse_allowed_networks(cls, value: object) -> object:
        """Parse the comma-separated CIDR list.

        ``strict=True`` deliberately: it rejects a value with host bits set (``192.168.0.0/8``)
        instead of widening it to the enclosing network, which would silently trust far more
        addresses than the operator named.
        """
        if not isinstance(value, str):
            return value
        return tuple(
            ip_network(entry, strict=True) for part in value.split(",") if (entry := part.strip())
        )
