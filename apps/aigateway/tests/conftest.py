from __future__ import annotations

import asyncio
import base64
import os
import sqlite3
import uuid
from collections.abc import Callable, Generator, Mapping
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise import Tortoise

from aigateway.core.background_error_sink import assert_no_unexpected, reset_unexpected
from aigateway.core.secrets.local import _SECRET_ENVELOPE_RE
from aigateway.core.secrets.mixin import SecretDecryptionError
from aigateway.db import build_tortoise_config

# Master key used by both the app (via AIGATEWAY_SECRET_KEY in the client fixture)
# and the CredentialBlobProbe below, so the probe is a faithful double of the
# encrypting ORMStore. These sync helpers mirror LocalSecretStore's v1 format;
# they are sync (AES-GCM is CPU-bound) so the async probe wrapper can call them
# from inside a running event loop without asyncio.run().
TEST_SECRET_KEY = b"k" * 32
_TEST_AESGCM = AESGCM(TEST_SECRET_KEY)


def _test_encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)
    ciphertext = _TEST_AESGCM.encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"v1:{base64.b64encode(nonce).decode()}:{base64.b64encode(ciphertext).decode()}"


def _test_decrypt(value: str) -> str:
    # Mirror LocalSecretStore.decrypt so the probe cannot diverge from the real
    # store on the reject/passthrough branches (SF-221 review #2): v1 -> decrypt;
    # any other versioned envelope -> raise; genuine legacy plaintext -> passthrough.
    if value.startswith("v1:"):
        _, nonce_b64, payload_b64 = value.split(":", 2)
        nonce = base64.b64decode(nonce_b64)
        payload = base64.b64decode(payload_b64)
        return _TEST_AESGCM.decrypt(nonce, payload, None).decode("utf-8")
    if _SECRET_ENVELOPE_RE.match(value):
        raise SecretDecryptionError("non-v1 secret envelope this probe cannot decrypt")
    return value


class _AsyncCredentialBlobProbe:
    def __init__(self, probe: CredentialBlobProbe) -> None:
        self._probe = probe

    async def read(self, service: str, account: str) -> str | None:
        return self._probe.read(service, account)

    async def write(self, service: str, account: str, value: str) -> None:
        self._probe.write(service, account, value)

    async def delete(self, service: str, account: str) -> None:
        self._probe.delete(service, account)

    async def mutate(
        self,
        service: str,
        account: str,
        mutator: Callable[[str | None], str | None],
    ) -> None:
        next_value = mutator(self._probe.read(service, account))
        if next_value is None:
            self._probe.delete(service, account)
        else:
            self._probe.write(service, account, next_value)


class CredentialBlobProbe:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self.store = _AsyncCredentialBlobProbe(self)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def read(self, service: str, account: str) -> str | None:
        """Logical (decrypted) credential value, mirroring ORMStore.read."""
        raw = self.read_raw(service, account)
        return None if raw is None else _test_decrypt(raw)

    def read_raw(self, service: str, account: str) -> str | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "select value from credential_blobs where service = ? and account = ?",
                (service, account),
            ).fetchone()
        return row[0] if row is not None else None

    def read_ciphertext_version(self, service: str, account: str) -> str | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "select ciphertext_version from credential_blobs where service = ? and account = ?",
                (service, account),
            ).fetchone()
        return row[0] if row is not None else None

    def write(self, service: str, account: str, value: str) -> None:
        """Store an encrypted credential value, mirroring ORMStore.write."""
        self.write_raw(service, account, _test_encrypt(value), ciphertext_version="v1")

    def write_raw(
        self, service: str, account: str, value: str, ciphertext_version: str | None = None
    ) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                insert into credential_blobs
                    (id, service, account, value, ciphertext_version, created_at, updated_at)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                on conflict(service, account) do update set
                    value = excluded.value,
                    ciphertext_version = excluded.ciphertext_version,
                    updated_at = datetime('now')
                """,
                (str(uuid.uuid4()), service, account, value, ciphertext_version),
            )

    def delete(self, service: str, account: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "delete from credential_blobs where service = ? and account = ?",
                (service, account),
            )


@pytest.fixture
def credential_blobs(tmp_path: Path, monkeypatch) -> CredentialBlobProbe:
    db_path = tmp_path / "aigateway.sqlite3"
    database_url = f"sqlite://{db_path}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    _prepare_sqlite_db(database_url)
    return CredentialBlobProbe(db_path)


@pytest.fixture(autouse=True)
def _no_discovery_egress(monkeypatch):
    """INVARIANT: the unit suite never dials a real public catalog.

    # WHY a guard rather than trust: a provider now DECLARES a discovery source
    # (OME-629), so any test that enables that provider and reads
    # /v1/model-parameters would otherwise reach the live internet — silently
    # passing on a good network and flaking on a bad one.
    # WHY only the default transport: ``HttpxDiscoveryClient`` is legitimately
    # exercised with an injected ``httpx.MockTransport``; production builds it with
    # none. Gating on that keeps those tests running the real adapter code while
    # blocking exactly the path that opens a socket.
    # OME-1026 (CC-1): the wrapper must accept and forward the adapter's OPTIONAL
    # ``headers`` (a credentialed Anthropic catalog dial carries them). Left on the
    # legacy signature it would raise TypeError, which ``ModelCatalog`` sanitizes into
    # a degraded seeds listing — so a test that genuinely reached the internet would go
    # QUIETLY green instead of failing. The AssertionError check therefore stays FIRST,
    # before any argument forwarding, so a real-transport dial trips loudly either way.
    """
    from aigateway.core.parameter_discovery import HttpxDiscoveryClient

    real_get = HttpxDiscoveryClient.get

    async def _guarded(
        self,
        url: str,
        *,
        timeout_s: float,
        max_bytes: int,
        headers: Mapping[str, str] | None = None,
    ):
        if self._transport is None:
            raise AssertionError(f"test attempted real discovery egress to {url}")
        return await real_get(self, url, timeout_s=timeout_s, max_bytes=max_bytes, headers=headers)

    monkeypatch.setattr(HttpxDiscoveryClient, "get", _guarded)


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch):
    from aigateway.core.auth import passwords

    monkeypatch.setattr(passwords, "_BCRYPT_ROUNDS", 4)
    passwords._dummy_hash = None
    yield
    passwords._dummy_hash = None


def _prepare_sqlite_db(database_url: str) -> None:
    async def _prepare() -> None:
        await Tortoise.close_connections()
        await Tortoise.init(
            config=build_tortoise_config(database_url), _enable_global_fallback=True
        )
        await Tortoise.generate_schemas()
        await Tortoise.close_connections()

    asyncio.run(_prepare())


@pytest.fixture
def client(
    monkeypatch,
    credential_blobs,
) -> Generator[TestClient, None, None]:
    database_url = f"sqlite://{credential_blobs.db_path}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_PROVISIONING_TOKEN", "p" * 32)
    # Deterministic master key so the encrypted JWT-secret round-trips across the
    # lifespan (proves the secret store is installed before the JWT bootstrap), and
    # so the app's ORMStore and the CredentialBlobProbe share one key.
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", base64.b64encode(TEST_SECRET_KEY).decode())
    _prepare_sqlite_db(database_url)

    from aigateway.main import create_app

    # A routable peer plus the network that contains it, so tests exercising `cloudflare_headers`
    # mode take the production-shaped path. Starlette defaults the peer to `("testclient", 50000)`,
    # which is not an address, and the header-mode guard fails closed on anything it cannot parse.
    monkeypatch.setenv("AIGW_ALLOWED_NETWORKS", "10.0.0.0/8")
    with TestClient(create_app(), client=("10.1.2.3", 50000)) as test_client:
        yield test_client
        # OME-1026 F6: land the app's background discovery BEFORE the suite-wide
        # assertion reads the error sink, and before the lifespan's own shutdown
        # CANCELS those tasks (a cancelled task reports nothing, so asserting after
        # shutdown would make a parked real-egress attempt silent).
        drain_app_discovery(test_client)
    asyncio.run(Tortoise.close_connections())


@pytest.fixture
def authenticated_client(client: TestClient) -> TestClient:
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


@pytest.fixture
def provisioned_user_factory(client: TestClient) -> Callable[[str, str], dict]:
    def _create(username: str, password: str = "test-user-password") -> dict:
        response = client.post(
            "/v1/accounts",
            headers={"X-Aigw-Provisioning-Token": "p" * 32},
            json={"username": username, "password": password},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _create


# A bound on the teardown barrier, not on discovery itself. A test that parks a
# refresh on an event it never sets would otherwise hang the whole session here.
_DRAIN_TIMEOUT_S = 5.0


def drain_app_discovery(client: TestClient) -> None:
    """Barrier: await this app's in-flight discovery, PUBLIC and PRIVATE, without cancelling.

    ``TestClient`` runs the app in another thread, so a synchronous test cannot await
    its tasks directly; the blocking portal installed by ``__enter__`` submits the
    managers' own ``drain`` into the app's loop.

    # WHY awaiting rather than cancelling: cancellation is how the lifespan shuts
    # discovery down, and ``_reap`` deliberately reports nothing for a cancelled task.
    # Draining first is what makes a background bug — a real-egress attempt above all —
    # reach the error sink before anything reads it.
    # WHY the shield: ``wait_for`` cancels what it awaits on timeout. Shielding the
    # drain means a slow refresh keeps running (the lifespan will cancel it moments
    # later) instead of being torn down by the barrier meant to observe it.
    """
    portal = client.portal
    if portal is None:  # not entered as a context manager; nothing was started
        return
    app = cast("FastAPI", client.app)
    targets = [
        target
        for target in (
            getattr(app.state, "profile_model_catalog", None),
            getattr(app.state, "public_refreshes", None),
        )
        if target is not None
    ]

    async def _drain() -> None:
        for target in targets:
            try:
                await asyncio.wait_for(asyncio.shield(target.drain()), timeout=_DRAIN_TIMEOUT_S)
            except TimeoutError:
                # A deliberately parked refresh. The lifespan's bounded aclose owns it.
                pass

    portal.call(_drain)


def drain_private_catalog(client: TestClient) -> None:
    """Barrier: finish the app's in-flight PRIVATE discovery inside its own loop.

    Publishing a credential starts a post-commit refresh, and ``TestClient`` runs the
    app in another thread. Sleeping and hoping is a race; the blocking portal that
    ``TestClient.__enter__`` installs lets a synchronous test submit the catalog's own
    ``drain`` into the app's loop and wait for it.
    """
    portal = client.portal
    assert portal is not None, "the TestClient must be entered as a context manager"
    catalog = cast("FastAPI", client.app).state.profile_model_catalog
    if catalog is not None:
        portal.call(catalog.drain)


def observe_background_discovery_errors(context: str) -> None:
    """The suite-wide observation point: fail ``context`` for a background bug.

    A plain function so it can be driven directly by a test — a fixture that only
    ever runs as teardown is a fixture whose failure path nothing pins.
    """
    assert_no_unexpected(context)


@pytest.fixture(autouse=True)
def _background_discovery_errors(request):
    """OME-1026 F6 — a background programming error FAILS the test that caused it.

    ``BackgroundRefreshManager`` retains an unexpected exception from a refresh nobody
    awaited — the no-egress tripwire's ``AssertionError`` above all — until something
    observes it. This is that observation point, for every test in the suite.

    # WHY it can assert now, where the previous pass could only drain: the blocker was
    # that publishing an api key starts a post-commit PRIVATE refresh and Anthropic's
    # ``live_models`` default is ``True``, so ~236 credential tests tripped the tripwire
    # in the background. Owner decision: tests that do not exercise profile discovery
    # DISABLE it (``_anthropic_private_discovery_disabled`` below) and discovery suites
    # opt in explicitly. Production defaults are untouched — the lever is this process's
    # plugin instance, not the setting's default.
    # AIDEV-NOTE: reset on the way IN as well. A leak escaping some earlier path must
    # be attributed to the test that produced it, never to the next one.
    """
    reset_unexpected()
    yield
    observe_background_discovery_errors(request.node.name)


@pytest.fixture(autouse=True)
def _anthropic_private_discovery_disabled(monkeypatch):
    """Anthropic private discovery is OFF for the shared unit suite (OME-1026 F6).

    # WHY per-instance rather than per-env: ``AnthropicPluginSettings.live_models``
    # defaults to ``True`` in PRODUCTION and a prior test pins that default
    # (``tests/unit/anthropic/test_settings.py`` constructs the settings object
    # directly). Overriding the loaded plugin's instance leaves both facts intact while
    # making the default test app perform zero private discovery.
    # WHY ``model_copy`` rather than a fresh settings object: a fresh one would re-read
    # ``AIGW_ANTHROPIC_*`` from the environment and quietly discard whatever an
    # enclosing fixture had configured.
    """
    from aigateway.plugins.anthropic_provider.plugin import PLUGIN

    monkeypatch.setattr(
        PLUGIN, "settings", PLUGIN.settings.model_copy(update={"live_models": False})
    )


@pytest.fixture(autouse=True)
def _public_catalog_prewarm_disabled(monkeypatch):
    """Startup prewarm of PUBLIC catalogs is OFF for the shared unit suite (OME-1026 F6).

    # WHY (the same owner principle as the Anthropic default above): a test must not
    # perform discovery it never asked for. Several suites enable a public provider
    # through a fixture that runs BEFORE the app is built — ``openrouter_enabled`` in
    # ``tests/unit/core/test_contract_source_revision_identity.py`` and five siblings —
    # so app startup dialled the live model LIST with the real client and no transport.
    # The no-egress tripwire caught it, which is exactly why the suite-wide assertion
    # cannot coexist with prewarm-by-default.
    # INVARIANT (nothing under test is weakened): prewarm is a latency optimisation. A
    # request keys its refresh identically, so it starts its own instead of joining
    # one — the route behaviour every test asserts is unchanged. That prewarm really
    # does start refreshes during a real lifespan is pinned by the
    # ``public_catalog_prewarm`` opt-in below and by the direct prewarm tests in
    # ``tests/unit/core/test_background_failure_semantics.py``.
    """
    from aigateway import main

    monkeypatch.setattr(main, "start_public_prewarm", lambda _app: 0)


@pytest.fixture
def public_catalog_prewarm(monkeypatch):
    """Explicit opt-in: let this test's app run the real startup prewarm."""
    # Imported from its DEFINING module, which the autouse fixture above never
    # touches — it patches the name ``main`` resolves at lifespan time.
    from aigateway import main
    from aigateway.discovery_lifecycle import start_public_prewarm

    monkeypatch.setattr(main, "start_public_prewarm", start_public_prewarm)


@pytest.fixture
def anthropic_live_discovery(monkeypatch):
    """Explicit opt-in: this test DOES exercise Anthropic private discovery.

    Requesting this fixture is the declaration. It is not autouse, and because
    autouse fixtures are set up first, it reliably overrides the suite-wide default
    above.
    """
    from aigateway.plugins.anthropic_provider.plugin import PLUGIN

    monkeypatch.setattr(
        PLUGIN, "settings", PLUGIN.settings.model_copy(update={"live_models": True})
    )
    return PLUGIN.settings
