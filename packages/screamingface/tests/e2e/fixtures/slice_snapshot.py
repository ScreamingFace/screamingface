"""Bless one board's replay fixtures from the owner-held recordings (OME-964).

Bless = a human looks at an output once, decides "yes, this is the correct answer,"
and freezes it as the official answer that all future test runs must match.
Same idea as "golden file" — blessing is the act of stamping a file as golden.

Run it from the SDK project (docker running, benchmark assets prepared once via
``uv run screamingface prepare --all``):

    cd <repo>/packages/screamingface
    uv run python tests/e2e/fixtures/slice_snapshot.py \\
        --board draco-3pass \\
        --model openrouter/google/gemini-3-flash-preview \\
        --dump <owner-held production cache dump .sql.gz> \\
        --answers <owner-held archive eval_results .eval.jsonl>

    # OME-978 fusion mode — the SDK report is the ONLY recording:
    uv run python tests/e2e/fixtures/slice_snapshot.py \\
        --board healthbench-worst30 \\
        --report <owner-held SDK report .json>

Mental model: this script is the "bless" button — it turns two owner-held recordings
into the committed fixtures that make ``test_boards.py`` go green: a sliced cache
snapshot (only the rows one board replay actually touches), its manifest sidecar, and
the golden the replay is forever compared against. The recordings never enter the
repo; only the slice and the golden do, and neither may name a local machine path —
sources are described generically plus content shas.

Two recordings, two roles:

- the **production cache dump** (a full pg_dump of ``request_cache_entries``) holds
  the JUDGE rows verbatim — those replay as-is, because the engine renders judge
  requests exactly as production did;
- the **archive eval JSONL** from the original benchmark run is the authoritative
  case→answer source for the CANDIDATE rows. The dump's own candidate rows were
  synthesized by a legacy harness under keys our engine never renders, so candidate
  answers must be RE-KEYED (stage 4) before they can hit.

Stages, in execution order:

1. **Parse** — stream the dump's COPY block once: collect every ``key_hash`` and the
   candidate model's response payloads (verbatim text); read the archive JSONL into a
   question→answer map and pair each answer with its dump payload byte-for-byte.
2. **Boot** — the real gateway (Postgres testcontainer + migrations), reusing the
   harness's own boot stages; then upload the full dump through the admin snapshot
   route (mode=merge). Production ships no manifest, so the job carries the
   ``revisions_unverified`` warning — expected here, and only here.
3. **Capture** — a recording proxy sits between the engine and the gateway; the board
   runs once, keylessly. Every candidate request 404s loudly (nothing can spend) and
   its rendered body is captured — the body is the ONLY thing this pass is for.
4. **Re-key** — for each captured candidate body, the gateway's OWN
   ``build_global_cache_plan`` (run as a helper subprocess in the aigateway venv —
   single-authority rule, hashing is never re-implemented) computes the cache key,
   and the archived answer payload is stored under it via a second merge upload.
5. **Verify** — the board runs again; candidate and judge rows now all hit, still
   keyless. This report is the golden's source. ``--expect-score`` /
   ``--expect-coverage`` cross-check it against an independently saved report and
   fail the bless loudly on mismatch.
6. **Slice** — slicing is OBSERVATION, not curation: rows whose ``hit_count`` moved
   during the verified replay ARE the fixture. Postgres itself emits them
   (``COPY … TO STDOUT``, so the escaping authority is the same code that will parse
   it back) with timestamps normalized and counters zeroed for determinism.
7. **Write** — ``<board>.snapshot.gz`` (gzip mtime=0) + ``<board>.manifest.json``
   (the OME-951 sidecar: sha256, row_count, live ``active_cache_revisions()``) +
   ``<board>.golden.json`` validated through ``GoldenReport`` before it lands. A
   snapshot above ``--max-snapshot-mb`` is written to the work dir instead of the
   committed tree, and the bless fails asking the owner to decide.

Report mode (OME-978, ``--report``): for a FUSION run there may be no dump and no
answers file — the saved SDK report is the only recording, and it carries every
response text (member answers, the synthesis, every judge verdict). Stages 1 and 4
change shape: the payload source is ``report_tape.py`` and the single re-key pass
becomes an iterative capture→splice loop, because fusion request bytes embed
earlier ANSWERS (the synthesis prompt embeds the member answers; judge prompts
embed the synthesized answer) — each round unlocks one more tree level. Stages
2, 5, 6 and 7 are identical, and the verified replay must reproduce the report's
score, coverage AND per-case statuses or the bless refuses.

The helper modes (``--helper keys`` / ``--helper revisions``) are the same file
executed under the aigateway venv; they exist so the key math and the revision
constants are only ever spelled by gateway code.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_E2E_DIR = Path(__file__).resolve().parents[1]

_MANIFEST_SCHEMA = "screamingface.cache-snapshot.v1"
_BLESSED_AT = "2026-08-25"
#: Fixed row timestamp — committed fixtures carry no wall-clock traces.
_ROW_TIMESTAMP = "2026-08-25 00:00:00+00"
_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "screamingface/ome-964/bless")

#: pg_dump text-format COPY column order for request_cache_entries — the exact list
#: the OME-951 loader parses and generate_synthetic.py emits.
_COPY_COLUMNS = (
    "id, key_hash, prompt_hash, provider, model, response_json, "
    "response_size_bytes, created_at, updated_at, expires_at, last_hit_at, hit_count"
)

#: Which prepared-asset bundle each board reads (mirrors test_boards._ASSET_BUNDLE).
_ASSET_BUNDLE = {
    "draco": "draco",
    "draco-3pass": "draco",
    "ifeval": "ifeval",
    "healthbench-worst30": "healthbench",
    "healthbench-professional": "healthbench",
}

_ASSETS_ENV = "SCREAMINGFACE_E2E_ASSETS"


def _default_assets_root() -> Path:
    """Mirror test_boards._assets_root: where `screamingface prepare` writes (OME-1001)."""
    from screamingface._runtime.config import default_data_dir

    return default_data_dir() / "benchmark-assets"


_DUMP_UPLOAD_TIMEOUT_SECONDS = 1800.0


# -- pure seams (stdlib only; contract-tested in test_bless_contracts.py) ------------


def copy_unescape(value: str) -> str:
    """Undo pg text-format COPY escaping (the four spellings the cache rows use)."""
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            mapped = {"\\": "\\", "t": "\t", "n": "\n", "r": "\r"}.get(value[i + 1])
            if mapped is not None:
                out.append(mapped)
                i += 2
                continue
        out.append(char)
        i += 1
    return "".join(out)


def copy_escape(value: str) -> str:
    """pg text-format COPY escaping — the inverse of ``copy_unescape``."""
    return (
        value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    )


def iter_copy_rows(lines: Iterable[str]) -> Iterator[list[str]]:
    """Yield the data rows (still COPY-escaped) of the first COPY block in a dump.

    Everything before ``COPY … FROM stdin;`` and everything at/after the ``\\.``
    terminator is dump scaffolding, never data. Both degenerate inputs raise: a dump
    with no COPY block at all (silently yielding nothing would bless an empty
    fixture) and a TRUNCATED block — input ending before the ``\\.`` terminator —
    because a partial dump would silently bless a partial fixture.
    """
    in_block = False
    for line in lines:
        stripped = line.rstrip("\n")
        if not in_block:
            if stripped.startswith("COPY ") and stripped.endswith("FROM stdin;"):
                in_block = True
            continue
        if stripped == "\\.":
            return
        yield stripped.split("\t")
    if in_block:
        raise ValueError(
            "the dump's COPY block never reached its \\. terminator — truncated or "
            "corrupted dump; refusing to bless from partial data"
        )
    raise ValueError("no COPY block found in the dump — is this a pg_dump of the cache table?")


def match_case_question(user_text: str, questions: set[str]) -> str:
    """Find THE archived question a rendered candidate request is asking.

    Exact equality wins; otherwise the question must appear inside the rendered user
    text exactly once. Ambiguity and absence both refuse loudly — guessing would
    attach the wrong archived answer and freeze a wrong golden.
    """
    if user_text in questions:
        return user_text
    contained = [question for question in questions if question in user_text]
    if len(contained) == 1:
        return contained[0]
    head = user_text[:120].replace("\n", " ")
    if contained:
        raise ValueError(f"ambiguous case match ({len(contained)} archived questions) for: {head}…")
    raise ValueError(f"no archived case matches the rendered request: {head}…")


def index_payloads_by_content(payload_texts: Iterable[str]) -> dict[str, str]:
    """Map answer text → VERBATIM response payload (the bytes production graded).

    The payloads are reused byte-for-byte rather than re-serialized: the judge rows
    in the dump were recorded against exactly this answer text, so any rewrite risks
    a silent judge miss. Duplicate answer texts refuse — they could not be told apart
    when re-keying.
    """
    index: dict[str, str] = {}
    for payload in payload_texts:
        content = json.loads(payload)["choices"][0]["message"]["content"]
        if content in index:
            raise ValueError(f"duplicate answer text across payloads: {content[:80]!r}…")
        index[content] = payload
    return index


def splice_copy_line(*, key_hash: str, model: str, payload: str) -> str:
    """One synthesized cache row as a COPY data line, deterministic for a given key."""
    return "\t".join(
        (
            str(uuid.uuid5(_UUID_NAMESPACE, key_hash)),
            key_hash,
            key_hash,  # prompt_hash IS the key_hash (see aigateway global_keys)
            model.split("/", 1)[0],
            model,
            copy_escape(payload),
            str(len(payload.encode("utf-8"))),
            _ROW_TIMESTAMP,
            _ROW_TIMESTAMP,
            "\\N",
            "\\N",
            "0",
        )
    )


def parse_judge_param(text: str) -> tuple[str, Any]:
    """One ``--judge-param key=value`` flag → a typed (key, value) pair.

    Values that parse as JSON scalars keep their type (``4096`` → int, ``0.2`` →
    float); everything else stays a string (``low`` → ``"low"``). The typing matters
    because the transformed body is hashed by the gateway's key math — ``"4096"`` and
    ``4096`` are different bytes and therefore different cache keys.
    """
    key, sep, raw = text.partition("=")
    if not sep or not key:
        raise ValueError(f"--judge-param must be key=value, got {text!r}")
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    return key, value


def apply_judge_params(body: Mapping[str, Any], extra: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """A recorded judge body + the declared protocol delta → the new-protocol body.

    Adds fields only. A key the recording already carries refuses: overwriting would
    silently rewrite the recorded request instead of re-keying it, and the verified
    replay could no longer prove the transform preserved the recording's meaning.
    """
    new_body = json.loads(json.dumps(body))  # deep copy; the recording stays untouched
    for key, value in extra:
        if key in new_body:
            raise ValueError(
                f"recorded judge body already carries {key!r}; a transform may only ADD "
                f"the new protocol's fields, never overwrite recorded ones"
            )
        new_body[key] = value
    return new_body


def collect_payloads_for_keys(
    rows: Iterator[list[str]], *, model: str, wanted_keys: set[str]
) -> dict[str, str]:
    """Stream COPY rows once, keeping the payloads for exactly ``wanted_keys``.

    Refuses at the end if any wanted key never appeared: a hole means the
    old-protocol capture rendered a request the dump never recorded, and splicing
    around it would bless a fixture that silently cannot serve one call.
    """
    payloads: dict[str, str] = {}
    remaining = set(wanted_keys)
    for columns in rows:
        if columns[4] == model and columns[1] in remaining:
            payloads[columns[1]] = copy_unescape(columns[5])
            remaining.discard(columns[1])
            if not remaining:
                break
    if remaining:
        sample = ", ".join(sorted(remaining)[:3])
        raise ValueError(
            f"{len(remaining)} captured judge key(s) have no row in the dump "
            f"(e.g. {sample}) — the dump does not record the old protocol these "
            f"bodies were rendered under; refusing to splice a fixture with holes"
        )
    return payloads


def snapshot_gzip(text: str) -> bytes:
    """gzip with ``mtime=0`` so identical content is identical bytes, forever."""
    sink = io.BytesIO()
    with gzip.GzipFile(fileobj=sink, mode="wb", mtime=0) as archive:
        archive.write(text.encode("utf-8"))
    return sink.getvalue()


def author_golden(
    *,
    board: str,
    revision: str,
    model: str | None = None,
    kind: str = "model",
    recipe: str | None = None,
    members: list[str] | None = None,
    synthesizer: str | None = None,
    limit: int | None,
    rendered_url4: str,
    final_score: float | None,
    case_statuses: dict[str, str],
) -> dict[str, Any]:
    """The golden document for one verified replay, validated before it can land.

    Counters are DERIVED from the statuses (never passed in) and the score is
    canonicalized through the same ``canonical_score`` the compare ladder uses, so a
    blessed file can never be refused by ``load_golden`` or disagree with itself.
    ``kind: "model"`` goldens keep the pre-OME-978 document shape byte-for-byte (no
    ``kind``/``recipe``/``synthesizer`` keys), so a re-bless never churns old files;
    ``kind: "fusion"`` records the full replay lineup (ordered members + synthesizer).
    """
    from harness.goldens import GOLDEN_SCHEMA, GoldenReport, canonical_score, expression_sha

    golden: dict[str, Any] = {
        "schema": GOLDEN_SCHEMA,
        "board": board,
        "revision": revision,
        "models": [model] if kind == "model" else list(members or ()),
        "limit": limit,
        "expression_sha": expression_sha(rendered_url4),
        "final_score": canonical_score(final_score),
        "case_count": len(case_statuses),
        "gradeable_count": sum(1 for status in case_statuses.values() if status == "scored"),
        "case_statuses": dict(sorted(case_statuses.items())),
    }
    if kind != "model":
        golden["kind"] = kind
        golden["recipe"] = recipe
        golden["synthesizer"] = synthesizer
    GoldenReport.model_validate(golden)  # refuse to write a golden the lane would refuse
    return golden


# -- helper modes (executed under the aigateway venv — single-authority rule) --------


def _helper_keys() -> None:
    """stdin: JSON list of request bodies → stdout: JSON list of key hashes."""
    from aigateway.core.cache_ports import CacheBypass
    from aigateway.core.request_cache.global_controls import parse_global_cache_controls
    from aigateway.core.request_cache.global_plan import build_global_cache_plan
    from aigateway.plugins.openrouter_provider.plugin import PLUGIN

    bodies = json.load(sys.stdin)
    keys: list[str] = []
    for body in bodies:
        working = json.loads(json.dumps(body))  # the plan may not mutate the original
        controls = parse_global_cache_controls(working)
        decision = build_global_cache_plan(
            body=working, plugin=PLUGIN, controls=controls, cache_enabled=True
        )
        if isinstance(decision, CacheBypass):
            raise SystemExit(f"candidate request is not cacheable: {decision!r}")
        keys.append(decision.key_hash)
    json.dump(keys, sys.stdout)


def _helper_revisions() -> None:
    """stdout: JSON of the gateway's live cache-key revision constants."""
    import aigateway.plugins.openrouter_provider.global_cache  # noqa: F401  (registers)
    from aigateway.core.request_cache.revisions import active_cache_revisions

    json.dump(active_cache_revisions(), sys.stdout)


def _run_helper(mode: str, stdin_payload: str | None = None) -> str:
    """Run this same file under the aigateway venv — gateway code spells the answer."""
    sys.path.insert(0, str(_E2E_DIR))
    from harness._local_proc import clean_env, repo_root, sync_project, venv_bin

    gateway_dir = repo_root() / "apps" / "aigateway"
    sync_project(gateway_dir)
    result = subprocess.run(
        [str(venv_bin(gateway_dir, "python")), str(Path(__file__).resolve()), "--helper", mode],
        input=stdin_payload,
        env=clean_env({"AIGW_OPENROUTER_ENABLED": "true"}),
        cwd=gateway_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"aigateway helper '{mode}' failed:\n{result.stderr[-2000:]}")
    return result.stdout


# -- recording proxy (captures the engine-rendered request bodies) -------------------


class _CaptureProxy:
    """A loopback HTTP proxy between engine and gateway that records every
    ``/v1/chat/completions`` request body plus the gateway's verdict on it."""

    def __init__(self, gateway_url: str) -> None:
        import httpx
        from harness._local_proc import free_port

        self.records: list[dict[str, Any]] = []
        records = self.records
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # quiet
                pass

            def _forward(self, method: str, body: bytes | None) -> None:
                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower() in ("content-type", "x-profile", "accept")
                }
                with httpx.Client(timeout=120.0) as client:
                    resp = client.request(
                        method, gateway_url + self.path, content=body, headers=headers
                    )
                if method == "POST" and self.path.endswith("/chat/completions"):
                    record = {
                        "request_body": json.loads(body.decode("utf-8")) if body else None,
                        "status": resp.status_code,
                        "cache_header": resp.headers.get("X-AIGW-Cache"),
                    }
                    with lock:
                        records.append(record)
                payload = resp.content
                self.send_response(resp.status_code)
                for key in ("content-type", "x-aigw-cache"):
                    if key in resp.headers:
                        self.send_header(key, resp.headers[key])
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                self._forward("GET", None)

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                self._forward("POST", self.rfile.read(length) if length else b"")

        port = free_port()
        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{port}"

    def shutdown(self) -> None:
        self._server.shutdown()


# -- gateway-side plumbing -----------------------------------------------------------


def _upload_snapshot(base_url: str, name: str, payload: bytes) -> dict[str, Any]:
    """Merge-upload one snapshot through the admin route; poll the job to its end.

    The harness's own upload has a fixture-sized timeout; the full production dump
    needs a longer leash, so blessing drives the route directly.
    """
    import httpx

    with httpx.Client(base_url=base_url, timeout=300.0) as client:
        accepted = client.post(
            "/v1/admin/cache/snapshots",
            files=[("snapshot", (name, payload, "application/gzip"))],
            data={"mode": "merge"},
        )
        if accepted.status_code != 202:
            raise SystemExit(f"upload not accepted: {accepted.status_code} {accepted.text[:300]}")
        job_id = accepted.json()["id"]
        deadline = time.monotonic() + _DUMP_UPLOAD_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            job = client.get(f"/v1/admin/cache/snapshots/jobs/{job_id}").json()
            if job.get("finished_at") is not None:
                if job["state"] != "complete":
                    raise SystemExit(
                        f"snapshot load '{name}' ended as {job['state']!r} "
                        f"(refusal={job.get('refusal')!r}, error={job.get('error')!r})"
                    )
                return job
            time.sleep(0.5)
    raise SystemExit(f"snapshot load '{name}' did not finish in time")


def _psql(container: Any, sql: str) -> str:
    """Run one statement inside the Postgres container; return its STDOUT text only.

    The streams are demuxed deliberately (``exec_run(demux=True)`` instead of the
    testcontainers ``exec`` wrapper, which merges them): the slice's ``COPY … TO
    STDOUT`` flows through this stdout straight into the committed snapshot, and a
    psql NOTICE on stderr must never interleave junk into fixture bytes. Failures
    surface stderr in the error instead.
    """
    result = container.get_wrapped_container().exec_run(
        [
            "psql",
            "-U",
            container.username,
            "-d",
            container.dbname,
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        demux=True,
    )
    stdout, stderr = result.output
    if result.exit_code != 0:
        detail = (stderr or stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"psql failed ({result.exit_code}):\n{detail[-2000:]}")
    return (stdout or b"").decode("utf-8", errors="replace")


_BASELINE_SQL = (
    "CREATE TABLE public.bless_baseline AS "
    "SELECT key_hash, hit_count FROM public.request_cache_entries;"
)

#: The slice: rows the verified replay actually touched, normalized for commit —
#: fixed timestamps, no expiry, counters zeroed — emitted by Postgres' own COPY so
#: the escaping authority is the code that parses it back on upload.
_SLICE_SQL = f"""COPY (
  SELECT r.id, r.key_hash, r.prompt_hash, r.provider, r.model, r.response_json,
         r.response_size_bytes,
         '{_ROW_TIMESTAMP}'::timestamptz, '{_ROW_TIMESTAMP}'::timestamptz,
         NULL::timestamptz, NULL::timestamptz, 0
  FROM public.request_cache_entries r
  LEFT JOIN public.bless_baseline b USING (key_hash)
  WHERE r.hit_count > COALESCE(b.hit_count, 0)
  ORDER BY r.key_hash
) TO STDOUT"""


# -- the bless flow ------------------------------------------------------------------


def _dump_content_sha(dump: Path) -> str:
    """sha256 of the DECOMPRESSED dump — stable provenance regardless of who gzipped
    the recording or when (gzip headers embed a timestamp; the content does not)."""
    digest = hashlib.sha256()
    with gzip.open(dump, "rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_dump(dump: Path, model: str) -> tuple[int, list[str]]:
    """One streaming pass: (total row count, the candidate model's payload texts)."""
    payloads: list[str] = []
    total = 0
    with gzip.open(dump, "rt", encoding="utf-8") as stream:
        for columns in iter_copy_rows(stream):
            total += 1
            if columns[4] == model:
                payloads.append(copy_unescape(columns[5]))
    return total, payloads


def _parse_answers(answers: Path, archive_model: str) -> dict[str, str]:
    """The archive's question → answer map for one model; the case→answer authority."""
    questions: dict[str, str] = {}
    with answers.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("model") != archive_model:
                continue
            question = row["question"]
            if question in questions:
                raise SystemExit(f"archive holds duplicate rows for question: {question[:80]!r}…")
            questions[question] = row["model_answer"]
    if not questions:
        raise SystemExit(f"archive holds no rows for model {archive_model!r}")
    return questions


def _candidate_bodies(records: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    """Distinct captured candidate bodies (the engine may retry a failing call)."""
    seen: set[str] = set()
    bodies: list[dict[str, Any]] = []
    for record in records:
        body = record.get("request_body")
        if not body or body.get("model") != model:
            continue
        fingerprint = json.dumps(body, sort_keys=True)
        if fingerprint not in seen:
            seen.add(fingerprint)
            bodies.append(body)
    return bodies


def _user_text(body: dict[str, Any]) -> str:
    for message in reversed(body["messages"]):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    raise SystemExit(f"captured candidate body has no user message: {json.dumps(body)[:200]}")


def _evaluate(engine_url: str, candidate: Any, board: str, limit: int | None) -> Any:
    import screamingface as sf

    with sf.Client(engine_url=engine_url) as client:
        return client.evaluate(candidate, benchmark=board, limit=limit, progress=False)


def _model_candidate(model: str) -> Any:
    import screamingface as sf

    return sf.Model(model)


def _cross_check(candidate: Any, expect_score: str | None, expect_coverage: str | None) -> None:
    """Fail the bless loudly when the replay contradicts an independently saved report."""
    from harness.goldens import canonical_score

    if expect_score is not None:
        actual = canonical_score(candidate.score)
        if actual != expect_score and (
            candidate.score is None or float(expect_score) != candidate.score
        ):
            raise SystemExit(
                f"BLESS REFUSED — replay score {actual!r} contradicts the saved report's "
                f"{expect_score!r}; the recordings do not reproduce the published run"
            )
    if expect_coverage is not None and round(candidate.coverage, 4) != round(
        float(expect_coverage), 4
    ):
        raise SystemExit(
            f"BLESS REFUSED — replay coverage {round(candidate.coverage, 4)} contradicts "
            f"the saved report's {expect_coverage}"
        )


def _snapshot_header(
    board: str, dump_sha: str, answers_sha: str, judge_params: list[str] | None = None
) -> list[str]:
    # Provenance rule: sources are described generically + shas — NEVER local paths.
    if judge_params:
        # INTERIM disclosure: these verdicts were produced under the OLD protocol and
        # re-keyed; the golden pins the PIPELINE, not the new-protocol score.
        judge_line = (
            "-- Judge rows INTERIM-RE-KEYED: verdict payloads from the owner-held "
            f"production cache dump (content sha256 {dump_sha}), recorded under the "
            f"pre-change protocol, re-keyed with the delta {sorted(judge_params)}. "
            "Pipeline pin, NOT a new-protocol score pin — replace with a true "
            "recording at the next paid run."
        )
    else:
        judge_line = (
            "-- Judge rows verbatim from the owner-held production cache dump "
            f"(content sha256 {dump_sha})."
        )
    return [
        "--",
        f"-- Sliced replay fixture for board '{board}' (OME-964; see slice_snapshot.py).",
        judge_line,
        "-- Candidate rows re-keyed from the owner-held original-run archive "
        f"(sha256 {answers_sha}).",
        "--",
        "",
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bless one board's e2e replay fixtures.")
    parser.add_argument("--helper", choices=("keys", "revisions"), help=argparse.SUPPRESS)
    parser.add_argument("--board", help="benchmark id, e.g. draco-3pass")
    parser.add_argument(
        "--model", help="candidate model, e.g. openrouter/google/gemini-3-flash-preview"
    )
    parser.add_argument("--dump", type=Path, help="owner-held production cache dump (.sql.gz)")
    parser.add_argument(
        "--report",
        type=Path,
        help="OME-978 fusion mode: the owner-held SDK report (.json) of the recorded "
        "run — the ONLY recording; replaces --model/--dump/--answers. The tape is "
        "synthesized via an iterative capture→splice loop and the replay must "
        "reproduce the report's score/coverage/statuses exactly.",
    )
    parser.add_argument(
        "--answers", type=Path, help="owner-held archive eval_results (.eval.jsonl)"
    )
    parser.add_argument(
        "--archive-model",
        help="model name as the archive spells it (default: --model minus the provider prefix)",
    )
    parser.add_argument("--limit", type=int, default=None, help="case limit (default: full board)")
    parser.add_argument("--expect-score", help="saved report's score; mismatch refuses the bless")
    parser.add_argument(
        "--expect-coverage", help="saved report's coverage; mismatch refuses the bless"
    )
    parser.add_argument(
        "--max-snapshot-mb",
        type=float,
        default=10.0,
        help="size gate: a bigger slice is NOT committed; the owner decides (default 10)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/tmp/screamingface-e2e-bless"),
        help="scratch dir for service logs and oversized output",
    )
    parser.add_argument(
        "--dump-judge-bodies",
        type=Path,
        help="PHASE A of a judge re-key: after the verified replay, write every "
        "captured judge request body + its cache key (this checkout's gateway math) "
        "to this JSON file, and write NO fixtures. Run on the checkout whose "
        "protocol the dump was recorded under.",
    )
    parser.add_argument(
        "--judge-bodies",
        type=Path,
        help="PHASE B of a judge re-key: a --dump-judge-bodies file recorded under "
        "the OLD protocol; each body is re-keyed under THIS checkout's protocol "
        "(after applying every --judge-param) and its old verdict payload spliced "
        "under the new key. The verified replay is the proof of the transform.",
    )
    parser.add_argument(
        "--judge-param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="protocol delta applied to each recorded judge body in phase B "
        "(repeatable), e.g. reasoning_effort=low; may only ADD fields",
    )
    return parser.parse_args()


@dataclass(frozen=True, slots=True)
class _ReplayEvidence:
    """What the verified replay proved — everything stages 6–7 need to write."""

    revision: str
    rendered_url4: str
    final_score: float | None
    case_statuses: dict[str, str]
    slice_rows: list[str]


def _splice_candidates(
    gateway_url: str,
    bodies: list[dict[str, Any]],
    answers: dict[str, str],
    payload_by_answer: dict[str, str],
    model: str,
) -> None:
    """Stage 4 — re-key: gateway-computed keys, archived answers as payloads."""
    keys = json.loads(_run_helper("keys", json.dumps(bodies)))
    lines: list[str] = []
    for body, key in zip(bodies, keys, strict=True):
        question = match_case_question(_user_text(body), set(answers))
        payload = payload_by_answer.get(answers[question])
        if payload is None:
            raise SystemExit(
                f"archive answer has no verbatim dump payload for question: {question[:80]!r}…"
            )
        lines.append(splice_copy_line(key_hash=key, model=model, payload=payload))
    splice_text = "\n".join(
        [f"COPY public.request_cache_entries ({_COPY_COLUMNS}) FROM stdin;", *lines, "\\.", ""]
    )
    job = _upload_snapshot(gateway_url, "bless-splice.snapshot.gz", snapshot_gzip(splice_text))
    print(
        f"[re-key] spliced {len(lines)} candidate rows "
        f"(inserted={job.get('inserted_rows')}, updated={job.get('updated_rows')})",
        flush=True,
    )


def _run_helper_keys_chunked(bodies: list[dict[str, Any]], chunk: int = 2000) -> list[str]:
    """Key every body via the gateway helper, chunked so stdin stays bounded."""
    keys: list[str] = []
    for start in range(0, len(bodies), chunk):
        keys.extend(json.loads(_run_helper("keys", json.dumps(bodies[start : start + chunk]))))
    return keys


def _distinct_judge_bodies(
    records: list[dict[str, Any]], candidate_model: str
) -> list[dict[str, Any]]:
    """Every distinct non-candidate (= judge) body the proxy saw, both passes."""
    seen: set[str] = set()
    bodies: list[dict[str, Any]] = []
    for record in records:
        body = record.get("request_body")
        if not body or body.get("model") == candidate_model:
            continue
        fingerprint = json.dumps(body, sort_keys=True)
        if fingerprint not in seen:
            seen.add(fingerprint)
            bodies.append(body)
    return bodies


def _write_judge_bodies(out: Path, records: list[dict[str, Any]], candidate_model: str) -> None:
    """Phase A output: [{key, body}] for every judge request, keyed by THIS gateway."""
    bodies = _distinct_judge_bodies(records, candidate_model)
    if not bodies:
        raise SystemExit("no judge bodies captured — did the verified replay run?")
    keys = _run_helper_keys_chunked(bodies)
    out.write_text(
        json.dumps([{"key": key, "body": body} for key, body in zip(keys, bodies, strict=True)])
    )
    print(f"[judge-bodies] wrote {len(bodies)} judge bodies + old keys → {out}", flush=True)


def _splice_judges(
    gateway_url: str,
    entries: list[dict[str, Any]],
    judge_params: list[str],
    payload_by_old_key: dict[str, str],
) -> None:
    """Phase B — re-key judges: old verdict payloads under new-protocol keys.

    Mirrors the candidate splice exactly: the transform only ADDS the declared
    protocol delta to each recorded body, the NEW gateway's own key math computes
    where the row files, and the verified replay afterwards is the only accepted
    proof the transform matched what the engine now renders.
    """
    extra = [parse_judge_param(flag) for flag in judge_params]
    new_bodies = [apply_judge_params(entry["body"], extra) for entry in entries]
    new_keys = _run_helper_keys_chunked(new_bodies)
    if len(set(new_keys)) != len(new_keys):
        raise SystemExit("judge re-key produced duplicate new keys — transform is degenerate")
    lines: list[str] = []
    for entry, new_key, new_body in zip(entries, new_keys, new_bodies, strict=True):
        lines.append(
            splice_copy_line(
                key_hash=new_key,
                model=str(new_body["model"]),
                payload=payload_by_old_key[entry["key"]],
            )
        )
    splice_text = "\n".join(
        [f"COPY public.request_cache_entries ({_COPY_COLUMNS}) FROM stdin;", *lines, "\\.", ""]
    )
    job = _upload_snapshot(
        gateway_url, "bless-judge-splice.snapshot.gz", snapshot_gzip(splice_text)
    )
    print(
        f"[re-key] spliced {len(lines)} judge rows under new-protocol keys "
        f"(inserted={job.get('inserted_rows')}, updated={job.get('updated_rows')})",
        flush=True,
    )


def _boot_gateway(args: argparse.Namespace) -> tuple[Any, str]:
    """Stage 2 boot — Postgres + migrations + gateway, no snapshot yet.

    Mirrors ``start_sync``'s own guarantee: a failure at any boot stage tears down
    whatever already started (``stop_sync`` is stage-safe), so a broken migrate can
    never orphan the Postgres container until Ryuk reaps it.
    """
    from harness.cache_seeded import CacheSeededGateway

    backend = CacheSeededGateway(snapshot=args.dump, manifest=None, work_dir=args.work_dir)
    try:
        database_url = backend._start_postgres()
        backend._migrate(database_url)
        gateway_url = backend._start_gateway(database_url)
        backend._base_url = gateway_url
    except BaseException:
        backend.stop_sync()
        raise
    return backend, gateway_url


def _capture_pass(
    engine_url: str, proxy: _CaptureProxy, args: argparse.Namespace
) -> list[dict[str, Any]]:
    """Stage 3 — run the board keylessly just to record the rendered candidate bodies."""
    print(f"[capture] engine {engine_url} → replaying {args.board} keylessly…", flush=True)
    _evaluate(engine_url, _model_candidate(args.model), args.board, args.limit)
    bodies = _candidate_bodies(proxy.records, args.model)
    if not bodies:
        raise SystemExit("capture pass rendered no candidate bodies — wrong board or model?")
    print(f"[capture] {len(bodies)} distinct candidate bodies", flush=True)
    return bodies


def _verified_replay(
    engine_url: str, args: argparse.Namespace, candidate: Any | None = None
) -> tuple[Any, dict[str, str]]:
    """Stage 5 — the replay the golden is written from, cross-checked loudly."""
    from collections import Counter

    started = time.monotonic()
    replay_candidate = candidate if candidate is not None else _model_candidate(args.model)
    report = _evaluate(engine_url, replay_candidate, args.board, args.limit)
    outcome = report.candidates.only
    statuses = {str(case.case_id): str(case.status) for case in outcome.cases}
    print(
        f"[verify] score={outcome.score} coverage={outcome.coverage} "
        f"statuses={dict(Counter(statuses.values()))} in {time.monotonic() - started:.0f}s",
        flush=True,
    )
    if report.benchmark.id != args.board:
        raise SystemExit(f"engine ran {report.benchmark.id!r}, not {args.board!r}")
    _cross_check(outcome, args.expect_score, args.expect_coverage)
    return report, statuses


def _replay_and_slice(
    args: argparse.Namespace,
    answers: dict[str, str],
    payload_by_answer: dict[str, str],
    assets_root: Path,
    judge_entries: list[dict[str, Any]] | None = None,
    payload_by_old_key: dict[str, str] | None = None,
) -> _ReplayEvidence:
    """Stages 2–6: boot, seed, capture, re-key, verify, slice — one gateway lifetime.

    The harness's boot stages are reused piecewise (not ``start_sync``) because that
    method couples boot to a fixture-sized upload; the full production dump needs the
    longer poll in ``_upload_snapshot``.
    """
    from harness.stack import EngineProcess

    backend, gateway_url = _boot_gateway(args)
    proxy: _CaptureProxy | None = None
    engine = EngineProcess(work_dir=args.work_dir, assets_dir=assets_root)
    try:
        job = _upload_snapshot(gateway_url, args.dump.name, args.dump.read_bytes())
        print(f"[seed] dump loaded: rows={job.get('live_after')}", flush=True)

        # Stage 3 — capture pass: render the candidate bodies (they miss, loudly).
        proxy = _CaptureProxy(gateway_url)
        engine_url = engine.start(proxy.url)
        bodies = _capture_pass(engine_url, proxy, args)

        _splice_candidates(gateway_url, bodies, answers, payload_by_answer, args.model)
        if args.judge_bodies is not None:
            _splice_judges(
                gateway_url,
                judge_entries or [],
                args.judge_param,
                payload_by_old_key or {},
            )

        # Baseline BEFORE the verified replay, so the slice can observe movement.
        _psql(backend._container, _BASELINE_SQL)
        report, statuses = _verified_replay(engine_url, args)

        if args.dump_judge_bodies is not None:
            _write_judge_bodies(args.dump_judge_bodies, proxy.records, args.model)

        # Stage 6 — slice by observation: exactly the rows the replay touched.
        slice_output = _psql(backend._container, _SLICE_SQL)
    finally:
        engine.stop()
        if proxy is not None:
            proxy.shutdown()
        backend.stop_sync()
    candidate = report.candidates.only
    return _ReplayEvidence(
        revision=report.benchmark.revision,
        rendered_url4=str(candidate.url4),
        final_score=candidate.score,
        case_statuses=statuses,
        slice_rows=[line for line in slice_output.split("\n") if line and not line.isspace()],
    )


def _write_fixtures(
    args: argparse.Namespace,
    evidence: _ReplayEvidence,
    header_lines: list[str],
    golden: dict[str, Any],
) -> None:
    """Stage 7 — write snapshot + manifest + golden, behind the size gate."""
    print(f"[slice] {len(evidence.slice_rows)} rows touched by the verified replay", flush=True)
    snapshot_text = "\n".join(
        [
            *header_lines,
            f"COPY public.request_cache_entries ({_COPY_COLUMNS}) FROM stdin;",
            *evidence.slice_rows,
            "\\.",
            "",
        ]
    )
    snapshot = snapshot_gzip(snapshot_text)
    manifest = {
        "schema": _MANIFEST_SCHEMA,
        "generated_at": _BLESSED_AT,
        "row_count": len(evidence.slice_rows),
        "sha256": hashlib.sha256(snapshot).hexdigest(),
        "revisions": json.loads(_run_helper("revisions")),
    }

    size_mb = len(snapshot) / (1024 * 1024)
    oversized = size_mb > args.max_snapshot_mb
    out_dir = args.work_dir if oversized else Path(__file__).resolve().parent
    (out_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    (out_dir / "goldens").mkdir(parents=True, exist_ok=True)
    (out_dir / "snapshots" / f"{args.board}.snapshot.gz").write_bytes(snapshot)
    (out_dir / "snapshots" / f"{args.board}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (out_dir / "goldens" / f"{args.board}.golden.json").write_text(
        json.dumps(golden, indent=2) + "\n"
    )
    print(
        f"[write] {args.board}: snapshot {size_mb:.2f} MB ({len(evidence.slice_rows)} rows), "
        f"golden score={golden['final_score']} → {out_dir}",
        flush=True,
    )
    if oversized:
        raise SystemExit(
            f"BLESS NOT COMMITTED — the slice is {size_mb:.2f} MB "
            f"(> {args.max_snapshot_mb} MB); output left in {out_dir}. "
            f"Options for the owner: bless a case subset (--limit, golden scoped "
            f"accordingly), git-lfs, or a fetch step."
        )


def _bless(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(_E2E_DIR))
    configured = os.environ.get(_ASSETS_ENV)
    assets_root = Path(configured) if configured else _default_assets_root()
    bundle = assets_root / _ASSET_BUNDLE[args.board]
    if not bundle.is_dir():
        raise SystemExit(
            f"prepared assets missing at {bundle} — run `uv run screamingface prepare --all`"
        )
    args.work_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1 — parse the recordings.
    archive_model = args.archive_model or args.model.split("/", 1)[1]
    dump_sha = _dump_content_sha(args.dump)
    answers_sha = hashlib.sha256(args.answers.read_bytes()).hexdigest()
    total_rows, payloads = _parse_dump(args.dump, args.model)
    print(f"[parse] dump rows={total_rows}, {args.model} payloads={len(payloads)}", flush=True)
    answers = _parse_answers(args.answers, archive_model)
    payload_by_answer = index_payloads_by_content(payloads)
    print(f"[parse] archive cases for {archive_model}: {len(answers)}", flush=True)

    judge_entries, payload_by_old_key = _load_judge_rekey_inputs(args)

    evidence = _replay_and_slice(
        args, answers, payload_by_answer, assets_root, judge_entries, payload_by_old_key
    )
    if args.dump_judge_bodies is not None:
        print("[phase-a] judge bodies recorded; fixtures deliberately NOT written", flush=True)
        return
    golden = author_golden(
        board=args.board,
        revision=evidence.revision,
        model=args.model,
        limit=args.limit,
        rendered_url4=evidence.rendered_url4,
        final_score=evidence.final_score,
        case_statuses=evidence.case_statuses,
    )
    header = _snapshot_header(
        args.board,
        dump_sha,
        answers_sha,
        args.judge_param if args.judge_bodies is not None else None,
    )
    _write_fixtures(args, evidence, header, golden)


def _load_judge_rekey_inputs(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]] | None, dict[str, str] | None]:
    """Phase B input — recorded judge bodies + their old keys → old verdict payloads."""
    if args.judge_bodies is None:
        return None, None
    entries: list[dict[str, Any]] = json.loads(args.judge_bodies.read_text())
    old_keys = {str(entry["key"]) for entry in entries}
    judge_models = {str(entry["body"]["model"]) for entry in entries}
    if len(judge_models) != 1:
        raise SystemExit(f"judge bodies span {len(judge_models)} models: {judge_models}")
    with gzip.open(args.dump, "rt", encoding="utf-8") as stream:
        payload_by_old_key = collect_payloads_for_keys(
            iter_copy_rows(stream), model=judge_models.pop(), wanted_keys=old_keys
        )
    print(
        f"[parse] judge re-key: {len(entries)} recorded bodies, "
        f"{len(payload_by_old_key)} dump payloads matched",
        flush=True,
    )
    return entries, payload_by_old_key


# -- the report-sourced bless flow (OME-978) -----------------------------------------
#
# No dump, no answers: the owner-held SDK report of the recorded fusion run is the
# ONLY recording. Request bytes are rendered by this checkout's engine during
# keyless capture passes, keys are computed by the gateway's own key math, and the
# response texts come verbatim from the report (fixtures/report_tape.py). Fusion
# request bytes embed earlier ANSWERS (synthesis embeds the member answers; judges
# embed the synthesized answer), so one capture pass cannot render the whole tree —
# the loop below splices one tree level per round until a pass misses nothing new.

#: Upper bound on capture→splice rounds. The fusion tree is 3 levels (members →
#: synthesis → judges) + 1 convergence pass; 8 leaves generous headroom without
#: letting a non-converging tape loop forever.
_MAX_CAPTURE_ROUNDS = 8


def _report_header(board: str, report_sha: str) -> list[str]:
    # Provenance rule: sources are described generically + shas — NEVER local paths.
    return [
        "--",
        f"-- Sliced replay fixture for board '{board}' (OME-978; see slice_snapshot.py).",
        "-- Every row SYNTHESIZED from the owner-held SDK report of the recorded run "
        f"(content sha256 {report_sha}): request bytes rendered by this checkout's",
        "-- engine, keys computed by the gateway's own key math, response texts "
        "verbatim from the report. The bless cross-check proved the replayed",
        "-- score/coverage/statuses reproduce that report exactly.",
        "--",
        "",
    ]


def _fusion_candidate(tape: Any) -> Any:
    import screamingface as sf

    return sf.Fusion(list(tape.member_routes), name=tape.recipe, synthesizer=tape.synthesizer_route)


def _splice_rows(gateway_url: str, lines: list[str], name: str) -> dict[str, Any]:
    splice_text = "\n".join(
        [f"COPY public.request_cache_entries ({_COPY_COLUMNS}) FROM stdin;", *lines, "\\.", ""]
    )
    return _upload_snapshot(gateway_url, name, snapshot_gzip(splice_text))


def _new_misses(
    records: list[dict[str, Any]], served: set[str], skipped: set[str]
) -> dict[str, dict[str, Any]]:
    """Fingerprint → body for every 404'd request this round not yet handled."""
    missed: dict[str, dict[str, Any]] = {}
    for record in records:
        body = record.get("request_body")
        if not body or record.get("status") != 404:
            continue
        fingerprint = json.dumps(body, sort_keys=True)
        if fingerprint not in served and fingerprint not in skipped:
            missed.setdefault(fingerprint, body)
    return missed


def _splice_matched(
    gateway_url: str, matches: list[tuple[str, Any, dict[str, Any]]], round_no: int
) -> None:
    """Key the matched bodies via the gateway helper and merge-upload their rows."""
    from collections import Counter

    from report_tape import fabricate_payload

    keys = _run_helper_keys_chunked([body for _, _, body in matches])
    lines = [
        splice_copy_line(
            key_hash=key,
            model=match.model,
            payload=fabricate_payload(
                model=match.model, content=match.content, finish_reason=match.finish_reason
            ),
        )
        for key, (_, match, _) in zip(keys, matches, strict=True)
    ]
    job = _splice_rows(gateway_url, lines, f"bless-report-round-{round_no}.snapshot.gz")
    roles = Counter(match.role for _, match, _ in matches)
    print(
        f"[splice {round_no}] {len(lines)} rows ({dict(roles)}) "
        f"inserted={job.get('inserted_rows')}, updated={job.get('updated_rows')}",
        flush=True,
    )


def _capture_splice_rounds(
    engine_url: str, gateway_url: str, proxy: _CaptureProxy, tape: Any, args: argparse.Namespace
) -> None:
    """The iterative capture→splice loop — one fusion-tree level per round.

    Round N: replay keylessly; every request whose row is not yet spliced 404s and
    its body is captured. Each new miss is matched to a report payload
    (``match_body``), keyed by the gateway helper, and spliced. Deeper requests
    only RENDER once their inputs hit (a synthesis body embeds the member
    answers), so each round unlocks the next level. Convergence = a pass whose
    misses are all deliberate failed-case holes (or none at all).
    """
    from report_tape import BodySkip, match_body

    candidate = _fusion_candidate(tape)
    served: set[str] = set()
    skipped: set[str] = set()
    for round_no in range(1, _MAX_CAPTURE_ROUNDS + 1):
        offset = len(proxy.records)
        print(f"[capture {round_no}] replaying {args.board} keylessly…", flush=True)
        _evaluate(engine_url, candidate, args.board, args.limit)
        missed = _new_misses(proxy.records[offset:], served, skipped)
        if not missed:
            print(f"[capture {round_no}] no new misses — tape converged", flush=True)
            return
        matches: list[tuple[str, Any, dict[str, Any]]] = []
        for fingerprint, body in missed.items():
            outcome = match_body(tape, body)
            if isinstance(outcome, BodySkip):
                # The report recorded nothing for this case — the hole is the point:
                # the verified replay must fail it exactly like the paid run did.
                skipped.add(fingerprint)
            else:
                matches.append((fingerprint, outcome, body))
        if not matches:
            print(
                f"[capture {round_no}] {len(missed)} misses, all deliberate failed-case "
                f"holes — tape converged",
                flush=True,
            )
            return
        _splice_matched(gateway_url, matches, round_no)
        served.update(fingerprint for fingerprint, _, _ in matches)
    raise SystemExit(
        f"BLESS REFUSED — capture→splice did not converge in {_MAX_CAPTURE_ROUNDS} rounds; "
        f"the engine keeps rendering requests the spliced rows never serve (drifted "
        f"prompt/params rendering, or non-deterministic request bytes)"
    )


def _load_tape(args: argparse.Namespace) -> tuple[Any, str]:
    """Stage 1 (report mode) — parse the report into the tape + its content sha."""
    from report_tape import parse_report

    tape = parse_report(json.loads(args.report.read_text(encoding="utf-8")))
    if tape.board != args.board:
        raise SystemExit(f"the report describes board {tape.board!r}, not {args.board!r}")
    print(
        f"[parse] report: recipe {tape.recipe!r}, members {list(tape.member_routes)}, "
        f"synthesizer {tape.synthesizer_route!r}, judge {tape.judge_route!r}, "
        f"{len(tape.cases)} cases, expected score={tape.expected_score} "
        f"coverage={tape.expected_coverage}",
        flush=True,
    )
    return tape, hashlib.sha256(args.report.read_bytes()).hexdigest()


def _require_assets(board: str) -> Path:
    configured = os.environ.get(_ASSETS_ENV)
    assets_root = Path(configured) if configured else _default_assets_root()
    bundle = assets_root / _ASSET_BUNDLE[board]
    if not bundle.is_dir():
        raise SystemExit(
            f"prepared assets missing at {bundle} — run `uv run screamingface prepare --all`"
        )
    return assets_root


def _report_replay_and_slice(
    args: argparse.Namespace, tape: Any, assets_root: Path
) -> _ReplayEvidence:
    """Report-mode stages 2–6: boot, capture→splice loop, verify, slice."""
    from harness.stack import EngineProcess

    backend, gateway_url = _boot_gateway(args)
    proxy: _CaptureProxy | None = None
    engine = EngineProcess(work_dir=args.work_dir, assets_dir=assets_root)
    try:
        proxy = _CaptureProxy(gateway_url)
        engine_url = engine.start(proxy.url)
        _capture_splice_rounds(engine_url, gateway_url, proxy, tape, args)

        # Baseline BEFORE the verified replay, so the slice can observe movement.
        _psql(backend._container, _BASELINE_SQL)
        report, statuses = _verified_replay(engine_url, args, candidate=_fusion_candidate(tape))
        if statuses != tape.case_statuses:
            drifted = {
                case: (tape.case_statuses.get(case), statuses.get(case))
                for case in tape.case_statuses.keys() | statuses.keys()
                if tape.case_statuses.get(case) != statuses.get(case)
            }
            raise SystemExit(
                f"BLESS REFUSED — replayed case statuses diverge from the report "
                f"(report, replay): {drifted}"
            )
        slice_output = _psql(backend._container, _SLICE_SQL)
    finally:
        engine.stop()
        if proxy is not None:
            proxy.shutdown()
        backend.stop_sync()

    candidate = report.candidates.only
    return _ReplayEvidence(
        revision=report.benchmark.revision,
        rendered_url4=str(candidate.url4),
        final_score=candidate.score,
        case_statuses=statuses,
        slice_rows=[line for line in slice_output.split("\n") if line and not line.isspace()],
    )


def _bless_from_report(args: argparse.Namespace) -> None:
    """The OME-978 flow: report → tape → capture/splice loop → verify → slice → write."""
    sys.path.insert(0, str(_E2E_DIR))
    from harness.goldens import canonical_score

    tape, report_sha = _load_tape(args)
    assets_root = _require_assets(args.board)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    # WHY defaults from the report: the report IS the independently saved outcome the
    # replay must reproduce — explicit flags remain as overrides only.
    if args.expect_score is None:
        args.expect_score = canonical_score(tape.expected_score)
    if args.expect_coverage is None:
        args.expect_coverage = str(tape.expected_coverage)

    evidence = _report_replay_and_slice(args, tape, assets_root)
    golden = author_golden(
        board=args.board,
        revision=evidence.revision,
        kind="fusion",
        recipe=tape.recipe,
        members=list(tape.member_routes),
        synthesizer=tape.synthesizer_route,
        limit=args.limit,
        rendered_url4=evidence.rendered_url4,
        final_score=evidence.final_score,
        case_statuses=evidence.case_statuses,
    )
    _write_fixtures(args, evidence, _report_header(args.board, report_sha), golden)


def main() -> None:
    args = _parse_args()
    if args.helper is not None:
        {"keys": _helper_keys, "revisions": _helper_revisions}[args.helper]()
        return
    if args.report is not None:
        if args.board is None:
            raise SystemExit("--board is required with --report")
        for excluded in ("model", "dump", "answers", "judge_bodies", "dump_judge_bodies"):
            if getattr(args, excluded) is not None:
                raise SystemExit(
                    f"--{excluded.replace('_', '-')} cannot be combined with --report — "
                    f"the report is the only recording in this mode"
                )
        _bless_from_report(args)
        return
    for required in ("board", "model", "dump", "answers"):
        if getattr(args, required) is None:
            raise SystemExit(f"--{required} is required (unless running a --helper mode)")
    _bless(args)


if __name__ == "__main__":
    main()
