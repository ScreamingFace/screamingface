"""The workbench's one redactor (review finding 1): every sink imports it.

WHY the fake secrets are assembled at runtime: a literal ``ghp_``/``AIza`` token in the repo
trips secret scanners, and these are never real.
"""

from __future__ import annotations

import pytest

from workbench.redaction import MASK, redact, redact_tree

GHP = "ghp_" + "a1B2" * 9
GH_PAT = "github_pat_" + "Z9y8" * 8
AIZA = "AIza" + "Sy" + "Q7x_" * 9
OPAQUE = "op4que-V4lue-zz9"
JWT = "eyJhbGciOi.eyJleHAiOjF9.c2ln"
SK = "sk-or-v1-abcdefghijklmnop0123"
TID = "4bf92f3577b34da6a3ce929d0e0e4736"
GLPAT = "glpat-" + "Xy7_" * 5
PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC"
PEM = f"-----BEGIN {'PRIVATE'} KEY-----\\n{PEM_BODY}\\n-----END {'PRIVATE'} KEY-----"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (f"key {SK}", SK),
        (f"tok {JWT}", JWT),
        ("hdr Bearer abc.def", "abc.def"),
        ("hdr Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        (f"git {GHP} end", GHP),
        (f"git {GH_PAT}", GH_PAT),
        (f"gemini {AIZA}", AIZA),
        (f"OPENROUTER_API_KEY={OPAQUE}", OPAQUE),
        (f"export AIGATEWAY_SECRET_KEY='{OPAQUE} more'", OPAQUE),
        (f'DB_PASSWORD = "{OPAQUE}"', OPAQUE),
        (f"Client(api_key='{OPAQUE}')", OPAQUE),
        (f"{{'access_token': '{OPAQUE}', 'x': 1}}", OPAQUE),
        (f'{{"client_secret": "{OPAQUE}"}}', OPAQUE),
        (f"GET https://h.test/v1?api_key={OPAQUE}&q=1", OPAQUE),
        (f"GET https://h.test/v1?x=1&token={OPAQUE}#frag", OPAQUE),
        (f"GET https://h.test/v1?key={OPAQUE}", OPAQUE),
        (f"https://user:{OPAQUE}@h.test/db", OPAQUE),
        # Review of R1, major: hyphenated header names and non-Bearer auth schemes.
        (f"x-api-key: {OPAQUE}", OPAQUE),
        (f"X-Goog-Api-Key: {OPAQUE}", OPAQUE),
        (f'{{"x-api-key": "{OPAQUE}"}}', OPAQUE),
        (f"api-key={OPAQUE}", OPAQUE),
        (f"Authorization: Token {OPAQUE}", OPAQUE),
        (f'{{"Authorization": "Token {OPAQUE}"}}', OPAQUE),
        (f"authorization={OPAQUE}", OPAQUE),
        (f"Authorization: ApiKey {OPAQUE}", OPAQUE),
        (f"Authorization: Key {OPAQUE}", OPAQUE),
        (f'Authorization: Digest username="u", response="{OPAQUE}"', OPAQUE),
        (f"Proxy-Authorization: Token {OPAQUE}", OPAQUE),
        # Review of R1, minor: escaped, prefixed, punctuated and un-named shapes.
        (f'{{\\"api_key\\": \\"{OPAQUE}\\"}}', OPAQUE),
        (f"""'{{"api_key": \\'{OPAQUE}\\'}}'""", OPAQUE),
        (f'api_key=b"{OPAQUE}"', OPAQUE),
        ("postgres://user:p@ss-0paque@h.test/db", "ss-0paque"),
        ("api_key=opaqueABC123zz(len)", "opaqueABC123zz"),
        (f"API_KEY=({OPAQUE})", OPAQUE),
        (f"api_key=[{OPAQUE}]", OPAQUE),
        ("api_key=v", "=v"),
        (f"gitlab {GLPAT}", GLPAT),
        (f"pem {PEM}", PEM_BODY),
    ],
    ids=[
        "sk",
        "jwt",
        "bearer",
        "basic",
        "ghp",
        "github-pat",
        "aiza",
        "env-assign",
        "env-quoted",
        "spaced-assign",
        "kwarg",
        "dict-repr",
        "json",
        "query-api-key",
        "query-token",
        "query-key",
        "userinfo",
        "header-hyphen",
        "header-goog",
        "json-hyphen",
        "assign-hyphen",
        "authz-token",
        "authz-json",
        "authz-assign",
        "authz-apikey",
        "authz-key",
        "authz-digest",
        "proxy-authz",
        "json-escaped",
        "repr-escaped",
        "bytes",
        "userinfo-at",
        "value-call-shape",
        "value-paren",
        "value-bracket",
        "one-char",
        "glpat",
        "pem",
    ],
)
def test_every_secret_shape_is_masked(text: str, secret: str) -> None:
    out = redact(text)
    assert secret not in out
    assert MASK in out


def test_names_survive_so_the_reader_knows_what_was_masked() -> None:
    out = redact(f"OPENROUTER_API_KEY={OPAQUE} https://h.test/?api_key={OPAQUE}&q=1")
    assert out == f"OPENROUTER_API_KEY={MASK} https://h.test/?api_key={MASK}&q=1"


@pytest.mark.parametrize(
    "text",
    [
        f"trace_id={TID} gateway_call_id=abc123",
        "result lacks declared key 'run_ids'",
        "KeyError: 'trace_ids'",
        "aigateway: trace 4bf9 absent; engine: no log source",
        "SCREAMINGFACE_WORKBENCH_REQUIRE_ALL=1 and the workbench skipped",
        "http://127.0.0.1:9105/v1/models?limit=5",
        # Seen in a real passing replay bundle: masking these would only blur the evidence.
        "openrouter/microsoft/phi-4?max_tokens=256&temperature=0",
        "max_tokens=256 completion_tokens: 12",
        f"global cache hit provider=openrouter model='openrouter/x' key={TID}",
        'sf.connect("openrouter", api_key=os.environ["OPENROUTER_API_KEY"])',
        "client = Client(api_key=load_key())",
        'key = os.environ.get("OPENROUTER_API_KEY")',
        'api_key=os.getenv("OPENROUTER_API_KEY")',
        "--max-tokens=256",
    ],
    ids=[
        "trace-and-call-id",
        "declared-key",
        "key-error",
        "chain-gap",
        "require-all",
        "url",
        "query-count",
        "count-assign",
        "cache-key",
        "env-lookup",
        "call",
        "env-get",
        "getenv",
        "flag-count",
    ],
)
def test_non_secrets_are_left_alone(text: str) -> None:
    assert redact(text) == text


def test_redact_tree_masks_keys_and_values_in_nested_containers() -> None:
    tree = {"a": [f"x {GHP}", {"n": 1}], f"OPENROUTER_API_KEY={OPAQUE}": (AIZA,)}
    flat = repr(redact_tree(tree))
    for secret in (GHP, AIZA, OPAQUE):
        assert secret not in flat
    assert "'n': 1" in flat


@pytest.mark.parametrize(
    "text",
    [
        f"x-api-key: {OPAQUE}",
        f"Authorization: Token {OPAQUE}",
        f'{{\\"api_key\\": \\"{OPAQUE}\\"}}',
        f"api_key=[{OPAQUE}]",
        "postgres://user:p@ss-0paque@h.test/db",
        f"pem {PEM}",
    ],
)
def test_redact_is_idempotent(text: str) -> None:
    once = redact(text)
    assert redact(once) == once


def test_long_identifier_runs_redact_in_linear_time() -> None:
    """A long `[\\w-]` run (urlsafe base64, `-a-a-a…`) must not make the name match quadratic.

    Before the fix `-a` * 8000 took ~7 s; executed notebooks can carry MB-sized outputs.
    """
    import time

    for blob in ("-a" * 50_000, "A-" * 50_000 + "=", "x" * 100_000 + "_key=v"):
        started = time.perf_counter()
        redact(blob)
        assert time.perf_counter() - started < 1.0
    assert "v" not in redact("x" * 60 + "_key=v").split("=", 1)[1]
    # Re-review finding 1: no name-length cap — a 100 KB name is still masked, still linear.
    for blob in ("x" * 100_000 + "_key=v4lue", "a-" * 50_000 + "token: v4lue"):
        started = time.perf_counter()
        masked = redact(blob)
        assert time.perf_counter() - started < 1.0
        assert "v4lue" not in masked
        assert masked.endswith(MASK)


@pytest.mark.parametrize("length", [64, 65, 66, 200, 4096])
@pytest.mark.parametrize(
    "shape",
    [
        "{name}_key={value}",
        "{name}_API_KEY={value}",
        "{name}-api-key: {value}",
        "{name}_token = '{value}'",
        '{{"{name}_client_secret": "{value}"}}',
        "{name}PASSWORD={value}",
    ],
)
def test_secret_names_of_any_length_are_masked(length: int, shape: str) -> None:
    """Re-review finding 1: a name prefix past the old 64-char cap bypassed the redactor."""
    text = shape.format(name="N" * length, value=OPAQUE)
    masked = redact(text)
    assert OPAQUE not in masked
    assert MASK in masked
    assert redact(masked) == masked


@pytest.mark.parametrize("length", [65, 4096])
def test_long_non_secret_names_are_left_alone(length: int) -> None:
    for text in (f"{'n' * length}_max_tokens=256", f"{'n' * length}_keys=3", f"{'n' * length}=1"):
        assert redact(text) == text


@pytest.mark.parametrize(
    "line",
    [
        'os.environ["ANTHROPIC_API_KEY"] = "opaque-value-123"',
        "env['GH_TOKEN']='opaque-value-123'",
        'os.environ["OPENROUTER_API_KEY"]=opaque-value-123',
    ],
)
def test_a_secret_assigned_through_a_subscript_is_masked(line: str) -> None:
    assert "opaque-value-123" not in redact(line)
