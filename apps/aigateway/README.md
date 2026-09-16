# aigateway

The AI gateway: the component the ScreamingFace Engine calls to reach model
providers, and the place provider credentials live. It is LiteLLM-based and
exposes one OpenAI-shaped `/v1/chat/completions` endpoint to every provider,
dispatching through registered provider plugins via
[LiteLLM](https://github.com/BerriAI/litellm). The registered providers are
Anthropic, Antigravity, Codex, Gemini CLI, Hugging Face, Ollama and OpenRouter.
Concept page: https://docs.screamingface.ai/learn/ai-gateway

The AI gateway is the system's credential boundary: the Engine and Client never
see raw keys. Keys are stored encrypted at rest (see Secrets at rest below), and
the master key `AIGATEWAY_SECRET_KEY` is never stored with the data or logged;
there is no OS keychain.

The request *shape* is OpenAI-compatible; the provider set is not. Codex targets
its own ChatGPT subscription backend, which is distinct from the OpenAI Platform
API: AIGateway does not currently include a first-class OpenAI Platform
provider. Providers are plugins, enabled per deployment (for example the
OpenRouter plugin ships disabled until `AIGW_OPENROUTER_ENABLED=true`). Provider
concerns, OAuth tokens, refresh, response shaping, live in self-contained
plugins under `src/aigateway/plugins/`; every direct subpackage exposing a
`PLUGIN` attribute is discovered automatically.

Local development uses SQLite at `sqlite://./aigateway.sqlite3` by default.
Hosted deployments should set `AIGATEWAY_DATABASE_URL` to Postgres.

## Secrets at rest

Credential values stored in `credential_blobs` (OAuth tokens, the JWT secret) are
encrypted at rest with AES-256-GCM via an abstract `SecretStoreMixin` (see
`core/secrets/`). `ORMStore` encrypts on write and decrypts on read, so call
sites are unchanged. Ciphertext is stored as `v1:<nonce-b64>:<ciphertext-b64>`.

Configuration:

| Env var | Required | Default | Notes |
|---|---|---|---|
| `AIGATEWAY_SECRET_KEY` | hosted / multi-worker | auto-generated (local) | base64 of 32 raw bytes |
| `AIGATEWAY_SECRET_PROVIDER` | no | `local` | `local` (AES-GCM) or `kms` (stub) |

Generate a key:

```bash
python -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())'
```

If `AIGATEWAY_SECRET_KEY` is unset under the `local` provider, the gateway
generates one and persists it to the `secret_master_keys` table, logging a
warning. This is a single-worker local convenience only. **Multi-worker
(`uvicorn --workers N`) and hosted deployments MUST set `AIGATEWAY_SECRET_KEY`**
so every worker shares one key — and so the master key does not live inside the
same database it protects.

Rows written before encryption was introduced (plaintext) are read transparently
and upgraded to ciphertext on their next write; no migration step is required.

## Quick start

```bash
cd apps/aigateway
uv sync

# Apply migrations for a persistent local DB. Re-running is safe.
# If your DB URL is in .env, export it first: set -a && source .env && set +a
uv run tortoise -c aigateway.db.TORTOISE_CONFIG migrate

uv run uvicorn aigateway.main:app --port 9105 --reload

# Sanity check
curl -sf http://localhost:9105/healthz
```

On first boot with auth enabled, set `AIGATEWAY_ADMIN_PASSWORD` to choose the
admin password. The gateway does not generate or log bootstrap passwords; if the
variable is missing before the initial admin account exists, startup fails with a
recovery-oriented error.

Authenticated endpoints require a JWT:

```bash
TOKEN=$(curl -sX POST http://localhost:9105/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<admin-password>"}' | jq -r .token)

curl http://localhost:9105/v1/models -H "Authorization: Bearer $TOKEN"
```

For local-only development, auth can be bypassed with `AIGATEWAY_AUTH_ENABLED=0`.
Protected endpoints then run as an anonymous account with ID
`00000000-0000-0000-0000-000000000000`. Auth is enabled by default; do not use
this mode for shared or hosted deployments. OAuth profiles created in this mode
are scoped to the anonymous account.

User provisioning is intentionally separate from JWT auth. Set
`AIGATEWAY_PROVISIONING_TOKEN` to enable `POST /v1/accounts`:

```bash
curl -sX POST http://localhost:9105/v1/accounts \
  -H "X-Aigw-Provisioning-Token: $AIGATEWAY_PROVISIONING_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alicepass123","display_name":"Alice"}'
```

If you expose aigateway to the public internet, you MUST front it with
rate-limiting such as a CDN edge or `nginx limit_req`. v1 does not implement
application-level rate limiting on `/v1/auth/login`.

Multi-worker deployments (`uvicorn --workers N` or a process manager equivalent)
MUST set `AIGATEWAY_JWT_SECRET` explicitly. The generated database fallback is a
local/single-worker convenience only.

## Chat parameters

`GET /v1/model-parameters` publishes the authoritative per-model contract: which optional
parameters are enabled, their JSON Schema, and each one's cache behavior. Provider-native
parameters are addressed under a `provider_params` object rather than at the top level.

The response's `context.execution_access` is `configured` or `missing` for the authenticated
account and selected `X-Profile`, including supported environment-key and no-auth access.
This reports configuration only: it does not validate credentials, refresh tokens, run inference,
or guarantee provider acceptance. Default credential-free datasheets remain available with
`missing`; explicit profile selection errors keep their existing status codes. Responses are
`private, no-store`. Consumers of older Gateways must treat an absent field as unknown.

OpenRouter callers can additionally constrain a request by unit price and downstream data policy —
see [OpenRouter price and privacy routing controls](docs/openrouter-routing-controls.md).

## Google Code Assist providers

Gemini and Antigravity both use Google's Code Assist OAuth/token contract, with
shared helper code in `core/google_code_assist.py` and provider-specific settings
under `plugins/`.

Antigravity intentionally sends `ideType="ANTIGRAVITY"` and
`pluginType="GEMINI"` to `loadCodeAssist`. The live service rejects
`pluginType="ANTIGRAVITY"` as an invalid enum even for real Antigravity clients;
if setup starts failing with `INVALID_ARGUMENT`, re-check that upstream enum
contract before changing provider registration or model routing.

Google OAuth blobs that do not include `expires_at_ms` are treated as not locally
expired. The gateway then relies on upstream 401/403 dispatch failures to mark
the profile or connection for re-authentication instead of guessing an expiry.

## Operations

### Rotate `AIGATEWAY_JWT_SECRET`

Changing the JWT secret invalidates all sessions.

For explicit-env deployments, change `AIGATEWAY_JWT_SECRET` and restart all
workers. For local generated-secret deployments, delete the `credential_blobs`
row with service `aigateway:jwt-secret` and account `default`, then restart.

### Rotate `AIGATEWAY_PROVISIONING_TOKEN`

Change the `AIGATEWAY_PROVISIONING_TOKEN` environment variable and restart the
gateway. Existing JWTs are unaffected.

### Rotate `AIGATEWAY_SECRET_KEY`

The master key encrypts every credential in `credential_blobs`. **Losing it makes
all stored OAuth tokens unrecoverable** — users must re-authenticate.

Full online key rotation (dual-read with the old key, re-encrypt on next write) is
not implemented yet; the `ciphertext_version` column and versioned format exist so
it can be added without a schema change. Until then:

- **Hosted / explicit key:** rotating `AIGATEWAY_SECRET_KEY` invalidates all
  existing encrypted rows (they can no longer be decrypted). Treat it as a
  credential reset — rotate the key and have users re-authenticate their providers.
- **Local generated key:** delete the `secret_master_keys` row (`provider='local'`)
  and restart; the gateway generates a fresh key. Existing rows become
  undecryptable, so re-authenticate providers.

> **SQLite downgrade caveat (local dev only):** `tortoise downgrade` past `0005`
> on SQLite rebuilds `credential_blobs` and, due to a Tortoise SQLite
> table-rebuild limitation, drops its `(service, account)` unique constraint and
> indexes. Re-run `tortoise migrate` forward (or recreate the dev DB) to restore
> them. Postgres downgrade (`ALTER TABLE … DROP COLUMN`) is unaffected.

## Layout

```
src/aigateway/
  main.py            FastAPI app + plugin loader + uvicorn entry
  config.py          Settings (port, plugin discovery)
  cli.py             `aigateway` console-script entry point
  core/
    plugin_base.py   ProviderPluginBase contract
    registry.py      ProviderRegistry (custom_llm_provider → plugin)
    loader.py        Discovers plugins under aigateway.plugins.*
    auth/            Account model, JWT, password, provisioning helpers
  routes/
    auth_session.py  POST /v1/auth/login and GET /v1/auth/me
    accounts.py      POST /v1/accounts provisioning endpoint
    chat.py          POST /v1/chat/completions (stream + non-stream)
    models.py        GET /v1/models (aggregated from plugins)
    health.py        GET /healthz
  plugins/           Provider plugins land here in follow-up PRs
tests/
  unit/
```

## Licensing note (LiteLLM)

We depend only on the MIT-licensed core `litellm` PyPI package. We must
**never** install `litellm-enterprise` or import from `litellm.enterprise.*` /
`litellm_enterprise.*` — those are governed by BerriAI's proprietary
Enterprise License. A CI guard in `scripts/check_no_enterprise.py` enforces
this.
