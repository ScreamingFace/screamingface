"""A fake AI Gateway and row builders for the Local adapter's effective-row tests (OME-1138, L7b).

Test-only. Shared by `test_connections_aigateway_effective.py` (the listing) and
`test_connections_aigateway_effective_writes.py` (`connect`, `start_oauth`, `disconnect`), so the
two suites read one gateway and never copy it.
"""

from __future__ import annotations

import json

import httpx

from screamingface_engine.connections.aigateway import AigatewayConnections

SECRET = "sk-or-v1-unit-secret"
E_ID = "00000000-0000-0000-0000-00000000000e"
OTHER_ID = "00000000-0000-0000-0000-000000000002"
THIRD_ID = "00000000-0000-0000-0000-000000000003"
CREATED_ID = "00000000-0000-0000-0000-0000000000c0"
ROWS_PATH = "/v1/oauth/connections"
ACCESS_PATH = "/v1/provider-access"


def provider(
    provider_id: str = "openrouter",
    display_name: str = "OpenRouter",
    auth_methods: tuple[str, ...] = ("api_key",),
) -> dict[str, object]:
    return {
        "object": "provider",
        "id": provider_id,
        "display_name": display_name,
        "auth_methods": list(auth_methods),
    }


BOTH = provider("anthropic", "Anthropic", ("api_key", "oauth"))
# The listing row without the field at all, as a gateway older than L7a lists it.
ABSENT = object()


def row(
    connection_id: str = E_ID,
    *,
    status: str = "active",
    auth_type: str = "api_key",
    label: str = "screamingface",
    provider: str = "openrouter",
    account: object = None,
    effective: object = False,
) -> dict[str, object]:
    built: dict[str, object] = {
        "id": connection_id,
        "account_id": "00000000-0000-0000-0000-000000000099",
        "provider": provider,
        "label": label,
        "status": status,
        "auth_type": auth_type,
        "account": account,
        "created_at": "2026-11-04T00:00:00Z",
        "last_used_at": None,
        "last_refreshed_at": None,
        "error_message": None,
        "is_duplicate": False,
    }
    if effective is not ABSENT:
        built["effective"] = effective
    return built


def written(listed: dict[str, object]) -> dict[str, object]:
    """A write's response: the row as the gateway returns it, active, with no listing flag."""
    unflagged = {key: value for key, value in listed.items() if key != "effective"}
    return unflagged | {"status": "active"}


class Gateway:
    """A fake AI Gateway: catalogue, flagged row listing, provider access, and the writes.

    `access` is what `/v1/provider-access` lists; `access_after_write` replaces it once any write
    lands, so a test tells a status read after the write from one derived from a row.
    """

    def __init__(
        self,
        *rows: dict[str, object],
        providers: tuple[dict[str, object], ...] = (provider(),),
        access: dict[str, str] | None = None,
        access_after_write: dict[str, str] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.providers = list(providers)
        self.access = dict(access or {})
        self.access_after_write = access_after_write
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, httpx.Response | Exception] = {}

    def adapter(self) -> AigatewayConnections:
        client = httpx.AsyncClient(
            base_url="http://aigateway.test", transport=httpx.MockTransport(self._handle)
        )
        return AigatewayConnections(client)

    def calls(self) -> list[str]:
        return [f"{request.method} {request.url.path}" for request in self.requests]

    def writes(self) -> list[str]:
        return [call for call in self.calls() if not call.startswith("GET ")]

    def bodies(self) -> list[object]:
        return [json.loads(r.content) for r in self.requests if r.method in {"POST", "PUT"}]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        failure = self.fail.get(f"{request.method} {request.url.path}")
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if request.method == "GET":
            return self._read(request)
        if self.access_after_write is not None:
            self.access = dict(self.access_after_write)
        return self._write(request)

    def _write(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        call = f"{request.method} {request.url.path}"
        if request.method == "DELETE":
            connection_id = request.url.path.rsplit("/", 1)[-1]
            before = len(self.rows)
            self.rows = [kept for kept in self.rows if kept["id"] != connection_id]
            return httpx.Response(204 if len(self.rows) < before else 404)
        if call == f"POST {ROWS_PATH}/api-key":
            body = json.loads(request.content)
            created = row(CREATED_ID, label=body["label"], provider=body["provider"])
            return httpx.Response(201, json=written(created))
        if request.method == "PUT":
            connection_id = request.url.path.split("/")[-2]
            (target,) = [listed for listed in self.rows if listed["id"] == connection_id]
            return httpx.Response(200, json=written(target))
        if call == f"POST {ROWS_PATH}":
            return httpx.Response(
                201,
                json={
                    "connection_id": CREATED_ID,
                    "authorize_url": "https://claude.example/authorize",
                    "state": "private",
                    "expires_in": 600,
                },
            )
        raise AssertionError(f"unexpected gateway call {call}")

    def _read(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json={"object": "list", "data": self.providers})
        if request.url.path == ROWS_PATH:
            wanted = request.url.params.get("provider")
            assert "status" not in request.url.params, "a status filter could hide a non-active E"
            rows = [
                listed for listed in self.rows if wanted is None or listed["provider"] == wanted
            ]
            return httpx.Response(200, json={"connections": rows})
        assert request.url.path == ACCESS_PATH, request.url.path
        listed = [{"provider": key, "status": value} for key, value in self.access.items()]
        return httpx.Response(200, json={"object": "list", "providers": listed})
