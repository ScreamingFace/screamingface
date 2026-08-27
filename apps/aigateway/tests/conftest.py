from __future__ import annotations

import asyncio
import base64
import os
import sqlite3
import uuid
from collections.abc import Callable, Generator, Mapping
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from tortoise import Tortoise

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
