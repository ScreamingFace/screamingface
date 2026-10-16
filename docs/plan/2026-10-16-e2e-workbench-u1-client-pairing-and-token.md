# E2E workbench · Unit 1 — explicit engine/scoreboard pairing + injected Access token

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap that lets a non-default engine silently pair with the hosted
leaderboard, and let a caller supply a Cloudflare Access token through the environment.

**Architecture:** Both changes are in `packages/screamingface` (`client-sf`).
1. **Pairing** applies to the module-level default only: `sf.configure()` and the env-var path
   of `default_client()`. Explicit `sf.Client(...)` is unchanged (§Scope).
2. **Token seeding** reads `SCREAMINGFACE_ACCESS_TOKEN` when a `Client`/`AsyncClient` is built.
   It puts the token into the Client's `_AccessTokenStore` under every audience in the JWT's
   `aud` claim. The existing challenge path (`_adopt_cached_challenge`) then reuses it, and no
   browser login starts.

**Tech Stack:** Python 3.12/3.13, uv, pytest, httpx MockTransport.

**Spec:** `docs/spec/2026-10-16-e2e-notebook-workbench.md` §7 unit 1, §6 option B.

## Global Constraints

- **Hosted defaults today** (`src/screamingface/client.py:40-41`):
  - `DEFAULT_ENGINE_URL = "https://fusion.screamingface.ai"`
  - `DEFAULT_SCOREBOARD_URL = "https://leaderboard.screamingface.ai"`
- **Owner decision 2026-10-16:** a non-default `engine_url` with no `scoreboard_url` **raises**.
  It does not derive or warn.
- **Errors:** wrong configuration raises `ValueError`, matching `_http_origin` in
  `_client_connections.py:49-60`. A malformed env token raises
  `AuthenticationError(code="access_env_token_invalid", permanent=True)`.
- **The token value never appears in a message, repr or log.** `_AccessToken` is already
  `repr=False`.
- **Breaking change:** use commit type `feat(screamingface)!:` with a `BREAKING CHANGE:` footer.
  Add a CHANGELOG `Unreleased` entry.
- **Public surface snapshot:** regenerate deliberately with
  `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py`. That run fails by
  design; the next plain run passes.
- **Gates** (all run in `packages/screamingface`):
  - `uv run pytest`
  - `uv run ruff check`
  - `uv run pyright`
  - deterministic notebook check `uv run python scripts/check_notebooks.py`

## Scope

- `sf.Client(engine_url=X)` keeps defaulting `scoreboard_url`. 144 test call sites in 57 files
  use that form, and an explicit Client is a deliberate object a user owns. The leak this unit
  closes is in the module default, which the notebooks use.
- `SCREAMINGFACE_ENGINE_URL` without `SCREAMINGFACE_SCOREBOARD_URL` is the same leak through
  env, so the same rule applies.
- The local-stack auto-discovery path already adopts both URLs (`_default_client.py:51-58`)
  and is unchanged.

## Review Focus

1. **Equivalent spellings of the default.** `configure(engine_url="https://fusion.screamingface.ai/")`
   (trailing slash, upper-case host) is the default and must not raise. Compare normalized
   origins.
2. **Failed configure keeps the old client.** A `configure()` that raises must leave the previous
   default Client open and installed. Validate before the swap.
3. **Expired env token.** An expired or nearly expired token (`exp` within 30 s) fails at Client
   construction with a clear code. It never fails silently into a browser login.
4. **Token for a different audience.** If the token's `aud` doesn't match the engine's challenge,
   the existing browser login runs. Seeding never forces a token onto an audience it wasn't
   issued for.
5. **Token never printed.** Error messages for a bad token never include the token text.

---

### Task 1: `configure()` and the env path require an explicit scoreboard for a non-default engine

**Files:**
- Modify: `packages/screamingface/src/screamingface/_default_client.py:1-82`
- Modify: `packages/screamingface/tests/test_default_client_local_discovery.py:223-237`
  (`test_configure_ignores_discovery` now passes a scoreboard)
- Create: `packages/screamingface/tests/test_default_client_pairing.py`
- Modify: `packages/screamingface/tests/public_surface_snapshot.json` (regenerated)
- Modify: `packages/screamingface/README.md` (~line 780, the `sf.configure` paragraph)
- Modify: `packages/screamingface/scripts/build_notebooks.py:598` (the
  `sf.configure(engine_url="https://your-engine.example")` snippet gains `scoreboard_url=`),
  then regenerate `examples/`
- Modify: `packages/screamingface/CHANGELOG.md`

**Interfaces:**
- Produces: `configure(*, engine_url: str = DEFAULT_ENGINE_URL, scoreboard_url: str | None = None) -> Client`
- Produces: `_paired_scoreboard(engine_url: str, scoreboard_url: str | None, *, hint: str) -> str`
  (private; raises `ValueError`)

- [ ] **Step 1: Write the failing tests**

```python
# packages/screamingface/tests/test_default_client_pairing.py
"""A non-default Engine never silently pairs with the hosted Scoreboard (e2e workbench U1)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import screamingface as sf
from screamingface import _default_client
from screamingface.client import DEFAULT_ENGINE_URL, DEFAULT_SCOREBOARD_URL


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SCREAMINGFACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SCREAMINGFACE_ENGINE_URL", raising=False)
    monkeypatch.delenv("SCREAMINGFACE_SCOREBOARD_URL", raising=False)
    monkeypatch.setattr(_default_client, "_client", None)
    yield
    if _default_client._client is not None:
        _default_client._client.close()
    monkeypatch.setattr(_default_client, "_client", None)


def test_configure_with_a_non_default_engine_and_no_scoreboard_raises(isolated: None) -> None:
    with pytest.raises(ValueError, match="scoreboard_url") as caught:
        sf.configure(engine_url="http://127.0.0.1:9108")
    assert "http://127.0.0.1:9108" in str(caught.value)


def test_a_failed_configure_keeps_the_previous_default_client_open(isolated: None) -> None:
    before = sf.configure(
        engine_url="https://first.example", scoreboard_url="https://first-board.example"
    )
    with pytest.raises(ValueError):
        sf.configure(engine_url="https://second.example")
    assert before.closed is False
    assert _default_client.default_client() is before


@pytest.mark.parametrize(
    "spelling", [DEFAULT_ENGINE_URL, DEFAULT_ENGINE_URL + "/", DEFAULT_ENGINE_URL.upper()]
)
def test_the_default_engine_in_any_spelling_pairs_with_the_default_scoreboard(
    isolated: None, spelling: str
) -> None:
    client = sf.configure(engine_url=spelling)
    assert client.scoreboard_url == DEFAULT_SCOREBOARD_URL


def test_configure_with_both_urls_is_unchanged(isolated: None) -> None:
    client = sf.configure(
        engine_url="http://127.0.0.1:9108", scoreboard_url="http://127.0.0.1:9106"
    )
    assert (client.engine_url, client.scoreboard_url) == (
        "http://127.0.0.1:9108",
        "http://127.0.0.1:9106",
    )


def test_engine_env_var_without_scoreboard_env_var_raises_on_first_use(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "https://preview.example")
    with pytest.raises(ValueError, match="SCREAMINGFACE_SCOREBOARD_URL"):
        _default_client.default_client()


def test_both_env_vars_build_the_default_client(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "https://preview.example")
    monkeypatch.setenv("SCREAMINGFACE_SCOREBOARD_URL", "https://preview-board.example")
    client = _default_client.default_client()
    assert client.scoreboard_url == "https://preview-board.example"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/screamingface && uv run pytest tests/test_default_client_pairing.py -v`

Expected:
- FAIL: `test_configure_with_a_non_default_engine_and_no_scoreboard_raises`,
  `test_a_failed_configure_keeps_…`, `test_engine_env_var_without_…` (no error raised)
- PASS: the rest

- [ ] **Step 3: Implement**

In `_default_client.py`, add the import and helper below `_lock = Lock()`:

```python
from screamingface._client_connections import _engine_origin


def _paired_scoreboard(engine_url: str, scoreboard_url: str | None, *, hint: str) -> str:
    """The Scoreboard for ``engine_url``: the explicit one, else the hosted default for the
    hosted Engine, else refuse.

    WHY refuse rather than default: a local or preview Engine paired with the hosted
    Scoreboard publishes that Engine's scores to the public leaderboard (e2e workbench spec
    §1). The pairing must be stated, never inferred.
    """

    if scoreboard_url is not None:
        return scoreboard_url
    if _engine_origin(engine_url) == _engine_origin(DEFAULT_ENGINE_URL):
        return DEFAULT_SCOREBOARD_URL
    raise ValueError(
        f"engine_url {engine_url!r} is not the hosted Engine, so its Scoreboard must be "
        f"named too: {hint}"
    )
```

Inside `default_client()`, replace the `Client(...)` construction:

```python
            resolved_engine = engine_url if engine_url is not None else DEFAULT_ENGINE_URL
            _client = Client(
                engine_url=resolved_engine,
                scoreboard_url=_paired_scoreboard(
                    resolved_engine,
                    scoreboard_url,
                    hint="set SCREAMINGFACE_SCOREBOARD_URL alongside SCREAMINGFACE_ENGINE_URL",
                ),
            )
```

Replace `configure` (validation runs **before** the swap):

```python
def configure(
    *,
    engine_url: str = DEFAULT_ENGINE_URL,
    scoreboard_url: str | None = None,
) -> Client:
    """Replace the process-wide Client used by module-level convenience functions.

    A non-default ``engine_url`` needs an explicit ``scoreboard_url``; see
    ``_paired_scoreboard``. A refused call leaves the previous Client installed and open.
    """

    global _client
    paired = _paired_scoreboard(engine_url, scoreboard_url, hint="pass scoreboard_url=...")
    replacement = Client(engine_url=engine_url, scoreboard_url=paired)
    with _lock:
        previous = _client
        _client = replacement
    if previous is not None:
        previous.close()
    return replacement
```

In `tests/test_default_client_local_discovery.py:234`, change the call to
`_default_client.configure(engine_url="https://chosen.example", scoreboard_url="https://chosen-board.example")`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_default_client_pairing.py tests/test_default_client_local_discovery.py -v`

Expected: PASS

- [ ] **Step 5: Update the docs and the snapshot**

1. **README:** replace the paragraph near line 780 with:

```markdown
`sf.configure(...)` replaces and closes any existing default Client. A non-default `engine_url`
must come with its `scoreboard_url`; the call raises otherwise, so a local or preview Engine can
never publish to the hosted leaderboard by accident. The same holds for the environment:
`SCREAMINGFACE_ENGINE_URL` needs `SCREAMINGFACE_SCOREBOARD_URL`. `sf.close()` releases the
default Client so the next module-level operation constructs a fresh one.
```

2. **Notebook snippet:** in `scripts/build_notebooks.py`, change the snippet at line 598 to:

```python
sf.configure(
    engine_url="https://your-engine.example",
    scoreboard_url="https://your-scoreboard.example",
)
```

3. **Regenerate the notebooks and the snapshot:**

```bash
uv run python scripts/build_notebooks.py
uv run python scripts/check_notebooks.py
UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py   # fails by design
uv run pytest tests/test_public_surface.py                               # PASS
```

4. **Changelog:** add under `## Unreleased` → `### Breaking changes`. Create that heading if
   it is absent.

```markdown
* `sf.configure(engine_url=...)` with a non-default Engine now requires `scoreboard_url=`, and
  `SCREAMINGFACE_ENGINE_URL` requires `SCREAMINGFACE_SCOREBOARD_URL`. Previously the pair fell
  back to the hosted leaderboard, so a local or preview run could publish there.
  `sf.Client(...)` is unchanged.
```

- [ ] **Step 6: Run the full gates and commit**

```bash
uv run pytest && uv run ruff check && uv run pyright && uv run python scripts/check_notebooks.py
git add -A packages/screamingface
git commit -m "feat(screamingface)!: require an explicit scoreboard for a non-default engine

BREAKING CHANGE: sf.configure(engine_url=X) with a non-default X, and SCREAMINGFACE_ENGINE_URL
without SCREAMINGFACE_SCOREBOARD_URL, now raise ValueError instead of pairing with the hosted
leaderboard."
```

---

### Task 2: seed the Access token store from `SCREAMINGFACE_ACCESS_TOKEN`

**Files:**
- Modify: `packages/screamingface/src/screamingface/_access/contract.py` (add `_token_audiences`)
- Modify: `packages/screamingface/src/screamingface/_access/auth.py` (add
  `_seed_access_tokens`; export in-module only)
- Modify: `packages/screamingface/src/screamingface/client.py:73` (sync `Client`) and `:442`
  (`AsyncClient`): seed right after `self._access_tokens = _AccessTokenStore()`
- Create: `packages/screamingface/tests/test_access_env_token.py`
- Modify: `packages/screamingface/README.md` (the "Hosted caller authentication" section, ~line 258)
- Modify: `packages/screamingface/CHANGELOG.md` (`### Features`)

**Interfaces:**
- Consumes: `_access_token(value, monotonic_now, wall_now) -> _AccessToken` (`contract.py:140`),
  `_VALID_AUDIENCE` (`contract.py:24`), `_AccessTokenStore.put(audience, token)` (`auth.py:71`)
- Produces: `_token_audiences(value: str) -> tuple[str, ...]` (raises `_invalid_token()`)
- Produces: `_seed_access_tokens(store: _AccessTokenStore, environ: Mapping[str, str], *, monotonic_now: float, wall_now: float) -> None`
- Produces: env var `SCREAMINGFACE_ACCESS_TOKEN` (used by Unit 4's UI and by people running
  notebooks against a hosted or preview target)

- [ ] **Step 1: Write the failing tests**

```python
# packages/screamingface/tests/test_access_env_token.py
"""SCREAMINGFACE_ACCESS_TOKEN pre-seeds the Access store (e2e workbench U1, spec §6 option B)."""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

import screamingface as sf
from screamingface._access import auth as access_auth_module
from screamingface._access.auth import _AccessTokenStore, _CloudflareAccessAuth, _seed_access_tokens

_AUDIENCE = "a" * 64
_OTHER = "b" * 64
_ENGINE = "https://engine.example"
_SCOREBOARD = "https://scoreboard.example"


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _jwt(exp: float, aud: object) -> str:
    header = _b64u(json.dumps({"alg": "RS256"}).encode())
    payload = _b64u(json.dumps({"exp": exp, "aud": aud}).encode())
    return f"{header}.{payload}.sig"


def test_no_env_var_seeds_nothing() -> None:
    store = _AccessTokenStore()
    _seed_access_tokens(store, {}, monotonic_now=100.0, wall_now=1_800_000_000.0)
    assert store.usable(_AUDIENCE, 100.0) is None


@pytest.mark.parametrize("aud", [_AUDIENCE, [_AUDIENCE, _OTHER]])
def test_token_is_stored_under_every_audience_it_names(aud: object) -> None:
    token = _jwt(1_800_000_900.0, aud)
    store = _AccessTokenStore()
    _seed_access_tokens(
        store, {"SCREAMINGFACE_ACCESS_TOKEN": token}, monotonic_now=100.0, wall_now=1_800_000_000.0
    )
    expected = [aud] if isinstance(aud, str) else aud
    for audience in expected:
        assert store.usable(audience, 100.0) == token


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        _jwt(1_800_000_010.0, _AUDIENCE),   # expires inside the 30 s skew
        _jwt(1_800_000_900.0, None),         # no aud
        _jwt(1_800_000_900.0, ["short"]),    # aud fails _VALID_AUDIENCE
    ],
)
def test_an_unusable_env_token_fails_loudly_without_echoing_it(token: str) -> None:
    with pytest.raises(sf.AuthenticationError) as caught:
        _seed_access_tokens(
            _AccessTokenStore(),
            {"SCREAMINGFACE_ACCESS_TOKEN": token},
            monotonic_now=100.0,
            wall_now=1_800_000_000.0,
        )
    assert caught.value.code == "access_env_token_invalid"
    assert token not in str(caught.value)


def test_client_uses_the_env_token_and_never_opens_a_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _jwt(time.time() + 900, _AUDIENCE)
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    browser_urls: list[str] = []
    seen: list[str | None] = []

    def auth(origin: str, *, token_store: _AccessTokenStore, discovery_error=None):
        return _CloudflareAccessAuth(
            origin,
            access_transport=httpx.MockTransport(lambda r: httpx.Response(500)),
            browser_presenter=browser_urls.append,
            token_store=token_store,
        )

    def scoreboard(request: httpx.Request) -> httpx.Response:
        sent = request.headers.get("Cf-Access-Token")
        seen.append(sent)
        if sent is None:
            kid = f"https://team.cloudflareaccess.com/cdn-cgi/access/login?kid={_AUDIENCE}"
            return httpx.Response(302, headers={"location": kid})
        return httpx.Response(404)

    monkeypatch.setattr(access_auth_module, "_client_caller_auth", auth)
    with sf.Client(
        engine_url=_ENGINE,
        scoreboard_url=_SCOREBOARD,
        scoreboard_transport=httpx.MockTransport(scoreboard),
    ) as client:
        with pytest.raises(sf.LeaderboardError):
            client.leaderboards.get_score("00000000-0000-0000-0000-000000000001")

    assert seen == [None, token]
    assert browser_urls == []


def test_a_token_for_another_audience_falls_back_to_the_browser_login() -> None:
    store = _AccessTokenStore()
    _seed_access_tokens(
        store,
        {"SCREAMINGFACE_ACCESS_TOKEN": _jwt(1_800_000_900.0, _OTHER)},
        monotonic_now=100.0,
        wall_now=1_800_000_000.0,
    )
    assert store.usable(_AUDIENCE, 100.0) is None
```

Use `_client_access_fixture` in `tests/test_authentication.py:287` as the reference for how
`_client_caller_auth` is patched. If the private factory signature has moved, match that test,
not this sketch.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_access_env_token.py -v`

Expected: FAIL with `ImportError: cannot import name '_seed_access_tokens'`

- [ ] **Step 3: Implement**

In `contract.py`, add after `_access_token`:

```python
def _token_audiences(value: str) -> tuple[str, ...]:
    """Every Access audience a token names in its ``aud`` claim (string or list).

    Signature is NOT verified here — the edge verifies it; this only decides which store
    slots the caller-supplied token may occupy.
    """

    parts = value.split(".")
    if len(parts) != 3:
        raise _invalid_token()
    try:
        payload = json.loads(_base64url_decode(parts[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise _invalid_token() from exc
    claim = payload.get("aud") if isinstance(payload, dict) else None
    values = [claim] if isinstance(claim, str) else claim
    if not isinstance(values, list) or not values:
        raise _invalid_token()
    if not all(isinstance(v, str) and _VALID_AUDIENCE.fullmatch(v) for v in values):
        raise _invalid_token()
    return tuple(values)
```

In `auth.py`, add above `_access_discovery_error`:

```python
ACCESS_TOKEN_ENV = "SCREAMINGFACE_ACCESS_TOKEN"


def _seed_access_tokens(
    store: _AccessTokenStore,
    environ: Mapping[str, str],
    *,
    monotonic_now: float,
    wall_now: float,
) -> None:
    """Pre-load a caller-supplied Access token (e2e workbench spec §6, option B).

    WHY seed the store rather than add a header: the challenge path (`_adopt_cached_challenge`)
    only reuses a token once the origin PROVES its audience, so a token is never sent to an
    origin of another audience — the same rule a browser-acquired token follows.
    """

    value = environ.get(ACCESS_TOKEN_ENV, "").strip()
    if not value:
        return
    try:
        audiences = _token_audiences(value)
        token = _access_token(value, monotonic_now, wall_now)
    except AuthenticationError:
        raise AuthenticationError(
            f"{ACCESS_TOKEN_ENV} is not a usable Cloudflare Access token "
            "(malformed, expired, or without a valid aud claim)",
            code="access_env_token_invalid",
            permanent=True,
        ) from None
    for audience in audiences:
        store.put(audience, token)
```

Import `_token_audiences` next to the existing `contract` imports, and `os`/`Mapping` as needed.
`from None` keeps the token-bearing cause out of tracebacks.

In `client.py`, after line 73 (sync) and line 442 (async):

```python
        self._access_tokens = _AccessTokenStore()
        _seed_access_tokens(
            self._access_tokens, os.environ, monotonic_now=time.monotonic(), wall_now=time.time()
        )
```

Add `_seed_access_tokens` to the local import block at `client.py:59-62` and `:424-427`, and
`import os, time` at module top if absent.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_access_env_token.py tests/test_authentication.py -v`

Expected: PASS. `test_authentication.py` is unchanged, which proves the browser path didn't
regress.

- [ ] **Step 5: Docs + changelog**

1. **README:** replace "No authentication selector, Cloudflare service token, or provider key is
   passed to the Client" (~line 262) with:

```markdown
Hosted Engines may be protected by Cloudflare Access. The Client logs in through the browser on
first use. For an unattended run that a person started (for example the e2e workbench), set
`SCREAMINGFACE_ACCESS_TOKEN` to an Access application token (`cloudflared access token -app=<engine
url>`); the Client uses it for every origin whose Access audience matches the token's `aud`, and
falls back to the browser login otherwise. The token acts as the person it was issued to.
```

2. **Changelog** `### Features`:

```markdown
* `SCREAMINGFACE_ACCESS_TOKEN` pre-seeds the Client's Cloudflare Access login, so a run a person
  started can reach a hosted Engine without a browser window. A malformed or expired token fails
  at Client construction with `access_env_token_invalid`.
```

- [ ] **Step 6: Full gates + commit**

```bash
uv run pytest && uv run ruff check && uv run pyright
UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py || true   # only if it moved
uv run pytest tests/test_public_surface.py
git add -A packages/screamingface
git commit -m "feat(screamingface): pre-seed the Access login from SCREAMINGFACE_ACCESS_TOKEN"
```

## Done when

- Both tasks are committed on one branch with all four gates green.
- PR-open filing: one `client-sf` leaf under the workbench epic.
