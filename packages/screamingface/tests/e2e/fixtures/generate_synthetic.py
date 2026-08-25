"""Generate the SYNTHETIC replay fixture (OME-961) — authored, never recorded.

Run it from the aigateway project's venv (the key builder is the gateway's own code):

    cd <repo>/apps/aigateway && uv sync
    .venv/bin/python <repo>/packages/screamingface/tests/e2e/fixtures/generate_synthetic.py

Mental model: this script is the "record" button for a cassette no model ever sang on.
It authors two plain chat-completion exchanges — one candidate-shaped, one judge-shaped,
both through the SAME ``/v1/chat/completions`` seam (the harness half of parent R5) —
and computes each row's ``key_hash`` by calling the gateway's own
``build_global_cache_plan``. Hand-hashing is forbidden: the fingerprint embeds the
provider's projection and two revision constants, and only the real code can spell it.

Stages, in execution order:

1. Enable the openrouter plugin BEFORE importing it (its settings are read at module
   import), then compute the global cache key for each authored request body.
2. Emit ``synthetic.snapshot.gz`` — a minimal pg_dump-shaped COPY block of
   ``request_cache_entries`` (the exact OME-951 upload format), gzipped with
   ``mtime=0`` so the bytes are reproducible.
3. Emit ``synthetic.manifest.json`` — the revision-guard sidecar, with the LIVE
   revision constants; when the gateway's cache-key semantics bump, uploading this
   fixture refuses loudly instead of silently never hitting, and the fix is to re-run
   this script.
4. Emit ``synthetic.tape.json`` — the same exchanges in the harness tape schema, with
   ``provenance.authored=true``: this fixture proves PLUMBING, it is not a board
   recording and must never be presented as one.

Everything here is deterministic: fixed ids, fixed timestamps, compact JSON, no clock
and no network.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import uuid
from pathlib import Path
from typing import Any

os.environ.setdefault("AIGW_OPENROUTER_ENABLED", "true")

SNAPSHOT_NAME = "synthetic.snapshot.gz"
MANIFEST_NAME = "synthetic.manifest.json"
TAPE_NAME = "synthetic.tape.json"

_TAPE_SCHEMA = "screamingface.replay-tape.v1"
_MANIFEST_SCHEMA = "screamingface.cache-snapshot.v1"
_GENERATED_AT = "2026-08-24"
_ROW_TIMESTAMP = "2026-08-24 00:00:00+00"
_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "screamingface/ome-961/synthetic")

# The sentinel this authored tape hashes instead of a rendered url4 expression —
# board tapes record the real expression; the plumbing tape says out loud it has none.
_NO_EXPRESSION_SENTINEL = "synthetic gateway-seam plumbing tape (no url4 expression)"

_CANDIDATE_MODEL = "openrouter/openai/gpt-5.5"
_JUDGE_MODEL = "openrouter/google/gemini-3.1-pro-preview"  # the DRACO judge route


def _authored_exchanges() -> list[dict[str, Any]]:
    """The two request→response pairs, as plain data. Bodies are wire-exact."""
    return [
        {
            "label": "candidate",
            "model": _CANDIDATE_MODEL,
            "request_body": {
                "model": _CANDIDATE_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "SYNTHETIC candidate call for the OME-961 replay plumbing "
                            "check. Reply with the single word: replayed."
                        ),
                    }
                ],
            },
            "response": _chat_completion("synthetic-candidate-1", "openai/gpt-5.5", "replayed"),
        },
        {
            "label": "judge",
            "model": _JUDGE_MODEL,
            "request_body": {
                "model": _JUDGE_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "SYNTHETIC judge call for the OME-961 replay plumbing check "
                            "— the judge replays through the same seam as the "
                            "candidate. Reply with the single word: graded."
                        ),
                    }
                ],
            },
            "response": _chat_completion(
                "synthetic-judge-1", "google/gemini-3.1-pro-preview", "graded"
            ),
        },
    ]


def _chat_completion(completion_id: str, model: str, content: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{completion_id}",
        "object": "chat.completion",
        "created": 1787184000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _key_hash(body: dict[str, Any]) -> str:
    """The gateway's own fingerprint for this request body — never hand-rolled."""
    from aigateway.core.cache_ports import CacheBypass
    from aigateway.core.request_cache.global_controls import parse_global_cache_controls
    from aigateway.core.request_cache.global_plan import build_global_cache_plan
    from aigateway.plugins.openrouter_provider.plugin import PLUGIN

    working = json.loads(json.dumps(body))  # the plan may not mutate the original
    controls = parse_global_cache_controls(working)
    decision = build_global_cache_plan(
        body=working, plugin=PLUGIN, controls=controls, cache_enabled=True
    )
    if isinstance(decision, CacheBypass):
        raise SystemExit(f"authored request is not cacheable: {decision!r}")
    return decision.key_hash


def _copy_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    )


def _snapshot_bytes(rows: list[dict[str, Any]]) -> bytes:
    columns = (
        "id, key_hash, prompt_hash, provider, model, response_json, "
        "response_size_bytes, created_at, updated_at, expires_at, last_hit_at, hit_count"
    )
    lines = [
        "--",
        "-- Synthetic OME-961 plumbing snapshot (authored; see generate_synthetic.py)",
        "--",
        "",
        f"COPY public.request_cache_entries ({columns}) FROM stdin;",
    ]
    for row in rows:
        payload = json.dumps(row["response"], separators=(",", ":"), ensure_ascii=False)
        row_id = uuid.uuid5(_UUID_NAMESPACE, row["label"])
        lines.append(
            "\t".join(
                (
                    str(row_id),
                    row["key_hash"],
                    row["key_hash"],  # prompt_hash IS the key_hash (see global_keys)
                    "openrouter",
                    row["model"],
                    _copy_escape(payload),
                    str(len(payload.encode("utf-8"))),
                    _ROW_TIMESTAMP,
                    _ROW_TIMESTAMP,
                    "\\N",
                    "\\N",
                    "0",
                )
            )
        )
    lines.append("\\.")
    lines.append("")
    plain = "\n".join(lines).encode("utf-8")
    sink = io.BytesIO()
    with gzip.GzipFile(fileobj=sink, mode="wb", mtime=0) as archive:
        archive.write(plain)
    return sink.getvalue()


def _manifest(snapshot: bytes, row_count: int) -> dict[str, Any]:
    import aigateway.plugins.openrouter_provider.global_cache  # noqa: F401  (registers)
    from aigateway.core.request_cache.revisions import active_cache_revisions

    return {
        "schema": _MANIFEST_SCHEMA,
        "generated_at": _GENERATED_AT,
        "row_count": row_count,
        "sha256": hashlib.sha256(snapshot).hexdigest(),
        "revisions": active_cache_revisions(),
    }


def _tape(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": _TAPE_SCHEMA,
        "provenance": {
            "board": "synthetic",
            "revision": "synthetic-2026-08-24",
            "expression_sha": hashlib.sha256(_NO_EXPRESSION_SENTINEL.encode()).hexdigest(),
            "engine_sha": "authored — no engine rendered this tape",
            "recorded_at": f"{_GENERATED_AT}T00:00:00Z",
            "run_ref": "packages/screamingface/tests/e2e/fixtures/generate_synthetic.py",
            "authored": True,
        },
        "exchanges": [
            {
                "normalized": {
                    "provider": "openrouter",
                    "model": row["model"],
                    "fingerprint": row["key_hash"],
                },
                "request": {
                    "method": "POST",
                    "path": "/v1/chat/completions",
                    "body": row["request_body"],
                },
                "response": {
                    "status": 200,
                    "media_type": "application/json",
                    "body_b64": base64.b64encode(
                        json.dumps(
                            row["response"], separators=(",", ":"), ensure_ascii=False
                        ).encode("utf-8")
                    ).decode("ascii"),
                },
            }
            for row in rows
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "snapshots",
        help="directory for the snapshot, manifest, and tape (default: ./snapshots)",
    )
    out_dir = parser.parse_args().out
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _authored_exchanges()
    for row in rows:
        row["key_hash"] = _key_hash(row["request_body"])

    snapshot = _snapshot_bytes(rows)
    (out_dir / SNAPSHOT_NAME).write_bytes(snapshot)
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(_manifest(snapshot, len(rows)), indent=2, sort_keys=True) + "\n"
    )
    (out_dir / TAPE_NAME).write_text(json.dumps(_tape(rows), indent=2) + "\n")
    for row in rows:
        print(f"{row['label']}: key_hash={row['key_hash']}")
    print(f"wrote {SNAPSHOT_NAME}, {MANIFEST_NAME}, {TAPE_NAME} to {out_dir}")


if __name__ == "__main__":
    main()
