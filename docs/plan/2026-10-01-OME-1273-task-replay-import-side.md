# Task-replay import side and the first Task-replay Benchmarks (PRs 3–5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the importer to import an eval by Task replay (call its task function in a clean
child, record every Case Source, seal the Cases with a Case Digest taken twice, write the
declaration), then import the first Task-replay Benchmarks with network-blocked grading tests.

> **Amended 2026-10-02 (owner direction, PR #1219):** the Cases are rendered by **capture**,
> not by the shared imitation writer. The import child runs the Task's own `setup` and
> `solver` on each Sample with a stand-in `generate` and records the prompt; the declaration
> carries no `prompt_template`, `choice_template` or `system_message`, and the facts carry no
> template references or "unreproduced solver" flags. Where this plan's tasks below name
> those fields, read "captured". Plan: `docs/plan/2026-10-02-OME-1273-capture-rendering.md`.

**Architecture:** Two new plugin modules. `case_sources.py` wraps the fetch primitives by
identity and records one Case Source per top-level fetch. `import_replay.py` is the import-mode
child: it installs the recorder, calls the task function, reads the scorer facts and the
multiple-choice witness off the built Task, renders the Cases by capture, and returns Cases,
Case Sources and facts through `result.json`. The parent runs it once, writes a declaration from the result,
then runs the image-side `replayed_cases` on that declaration as the second run; the two Case
Digests must agree. `importer.py` routes its four "can't see the fetch" refusals to that path
and renders the `TaskReplayCasesSpec` entry plus the usual `BenchmarkSpec` row. The image side
(PR #1150) is untouched.

**Tech Stack:** Python 3.12, uv, pytest, `inspect-ai` 0.3.263, `inspect-evals` 0.20.0,
`datasets` 5.0.0, `huggingface_hub`.

**Spec:** `docs/spec/2026-09-30-OME-1273-task-replay-import.md` (approved 2026-09-30). This
plan covers R1–R7 and R13–R17, and amends the spec where the recon below contradicts it. PR 2
(image side, R5 and R9–R12) merged as #1150.

## Global Constraints

- One worktree per PR, off `upstream/main`:
  `git worktree add .claude/worktrees/<slug> -b OME-1273-<slug> upstream/main`. PR 3's is
  `ome-1273-task-replay-import`, already created with this plan as its first commit.
- All paths are relative to `apps/screamingface-engine/` unless they start with `docs/`.
- `uv sync --extra inspect --inexact` once per worktree, then `uv run pytest <path> -q`.
- Gates before each PR, from the repo root: `uv run .claude/scripts/run_gates.py screamingface-engine`
  (append-only test check, ruff, format, pyright, layering, pytest with coverage ≥ 80).
- `tests/unit/inspect/test_published_revisions.py` passes unchanged. No published Benchmark
  Revision moves. Every existing import renders byte-identical generated code (R1): the
  `render_generated_rows` tests in `test_inspect_importer.py` pin that.
- Glossary words only (`CONTEXT.md`): Case, Case Preparation, Case Source, Case Digest,
  Grading Material, Benchmark key, Answer key, Imported Benchmark. Never "board", "bake",
  "exam", "row" (for a Case) in new code, comments or test names.
- Plain `test_` functions. Type every argument, return value and non-obvious local.
  Every function gets a one-sentence intuition docstring.
- Tests are append-only across commits. A test from an earlier commit is edited only with
  the owner's `--skip-append-only`, asked for by name (PR 4 needs one; see Task 4.2).
- Commits: conventional, `feat(screamingface-engine): …`, no `Co-Authored-By`. Stage
  explicit paths, never `git add -A`.
- Files that import `inspect_ai` or `inspect_evals` carry the file-level
  `# pyright: reportMissingImports=false` header with its WHY comment. `task_replay.py` is
  the counter-example: it imports neither, so it carries none.
- Nothing in any test touches the network. Task replay tests use a stand-in eval written to
  `tmp_path` and put on `PYTHONPATH`, the pattern in `tests/unit/inspect/test_task_replay.py`.
- Paid model runs are the owner's. Nothing here calls a model.

## Decisions taken in this plan (owner can flip any before coding starts)

| # | Decision | Why | Flip means |
| -- | -- | -- | -- |
| D1 | **One Benchmark per inspect task**, key `<package>_<task>` (`agieval_lsat_ar`), as lab_bench did | one task = one question style = one score; the spec's own example is `mgsm(languages=["en"])` | fewer, mixed Benchmarks; the recipe in PR 4 changes only the key list |
| D2 | **mgsm imports English only** as `mgsm_en` (250 Cases) | the spec's example; the other 10 languages are one `--task-arg` each later | `languages="all"`, 2,750 Cases in one Benchmark |
| D3 | **PR 4 of the spec (R8, scorer lookup in helper files) is dropped** | recon: bbeh's scorer is defined in its task file, livebench's is re-exported into its task file (`hasattr` finds it), and livebench is out anyway (D5); no remaining package needs it | keep a 20-line `_scorer_reference` widening; add it the day an import refuses with "cannot resolve scorer" |
| D4 | **PRs renumber:** PR 3 import side · PR 4 agieval, medqa, mgsm · PR 5a and 5b the rest | D3, plus the ~500-line cap: 11 packages are ~21 Benchmarks | — |
| D5 | **livebench leaves the 14** with the reason "needs the `livebench` git dependency in the image and downloads nltk data inside its scorer (R17)" | both facts from the installed package | a Dockerfile change plus nltk data in the image: its own ticket |
| D6 | **Unseeded shuffles are pinned by a declared task arg**, never by a seed we add in our code: worldsense and chembench get `shuffle=False`, sad gets `seed=<int>` (its choice order changes the answer letters) | the declaration must say everything the fetch depends on | — |
| D7 | **The recorder also wraps `datasets.DownloadManager.download`** (spec R3 lists five primitives; this is the sixth) | piqa's unpinned zip and jsonl go through it, and the spec promises the recorder lists piqa's unpinned URLs | piqa's Case Sources would show only the HF snapshot |
| D8 | **`license` is a field on `TaskReplayCasesSpec`, default `"TODO"`** | spec R6; a default keeps PR 2's tests untouched; R7's gate test reads the field | a `License:` comment on the BenchmarkSpec row, as the Hugging Face path does, with a regex-based gate |
| D9 | **R14 shrinks to a ledger note**: no upstream issue is drafted | recon: three of the four "upstream bugs" were our stub's fake Sample (no id, no metadata); the fourth is a missing optional dependency on our side | draft the two hygiene notes as issues |
| D10 | **The import-mode child is its own module** (`import_replay.py`), not a flag on `task_replay.py` | the image side's child protocol stays byte-for-byte what #1150 shipped and reviewed | one child with a mode flag |
| D11 | **`keep_sample_metadata` is on whenever the scorer is not one of `inspect_ai.scorer`'s own** | an eval's own scorer may read `state.metadata` (chembench's `state.metadata["task_type"]`); metadata is inside the Case Digest, so it cannot be flipped by hand after import; inspect's built-in scorers never read it | a `--keep-sample-metadata` flag the importing agent must remember |
| D12 | **`--task-replay` forces the Task-replay path** | bbh, personality_TRAIT and sciknoweval crash inside the Hugging Face reader's stand-in Sample with a plain exception, so no route fires; R14's re-check needs a way in | drop the re-check promise |
| D13 | **A card license outside `CLEARED_DATASET_LICENSES` is written as `license="TODO"`**, with the card's value in the TODO comment | medqa's card says `unknown`; written as the value it would pass R7's gate with nobody deciding | the gate also refuses `unknown` and `other` by name |

## Review Focus

1. **A fetch inside a recorded fetch.** agieval's `_download_remote` calls
   `inspect_ai._util.file.file` for the download; one fetch must be one Case Source, not two.
   Pinned in Task 2 (`test_a_fetch_inside_a_recorded_fetch_is_not_a_second_case_source`).
2. **A primitive bound by name before the recorder installs.** mgsm does
   `from inspect_ai.util import download` at import time; the recorder must still see the call.
   Pinned in Task 2 (`test_the_recorder_rebinds_a_primitive_imported_by_name`).
3. **The eval reads its own cached download.** After `download`, mgsm reads the TSV from the
   cache; that read must not count as a Case Source, and must not hide a missing one. Pinned in
   Task 2 (`test_a_read_from_the_replay_cache_is_not_a_case_source`).
4. **The second run must take the image-side path.** If run 2 used the import child again, a
   declaration that renders differently at build (a template reference the importer wrote
   wrongly) would pass import and go SKIPPED at every build. Pinned in Task 5
   (`test_the_second_run_takes_the_image_side_path`).
5. **A Hub license string lands in generated code.** The card's license is interpolated into
   `prepare.py`; it must pass `_LICENSE_CHARSET` or be refused. Pinned in Task 6
   (`test_a_hub_license_outside_the_charset_is_refused`).
6. **Task args land in generated Python, not JSON.** `{"shuffle": False}` must come out as
   `False`, never `false`: `ast.parse` accepts `false` as a name, and importing `prepare.py`
   would then raise `NameError` and take every Benchmark down (D6 gives worldsense and
   chembench exactly this argument). Pinned in Task 6
   (`test_task_args_render_as_python_that_evaluates_to_the_same_value`).
7. **The two MCQ witnesses.** The Task-replay facts compute MCQ as the Hugging Face reader
   does: the `multiple_choice` solver OR the `choice` scorer (mmlu hides its solver inside its
   own). Pinned in Task 3 (`test_a_wrapped_mcq_solver_is_still_mcq_by_its_choice_scorer`).
8. **The `dataset_url` must be a web URL.** `BenchmarkSpec` refuses anything but an absolute
   http(s) URL (`definition.py:238`), so a `hugging-face` Case Source renders as
   `https://huggingface.co/datasets/<repo>`. `dataset_url` is a required field, so when no
   Case Source has a web page the row writes `dataset_url="TODO"` with a review note, refused
   at registration like the difficulty tier. Pinned
   in Task 6 (`test_task_replay_benchmark_row_builds_for_a_hugging_face_source`).

A sixth fact the plan leans on: `case_records` numbers Cases 1..N itself (`prepare.py:906`),
so a Task-replay Case's `id` is never the upstream Sample id. R4's duplicate check therefore
reads the Sample ids the child reports, and the grading tests write Cases with ids 1 and 2.

---

## PR 3 — the import side (branch `OME-1273-task-replay-import`)

> **As built (2026-10-01).** Three places differ from the tasks below; the ledger records why.
> (1) The renderers and the license lookup live in a new module, `task_replay_rows.py`
> (`render_task_replay_rows`, `write_task_replay_rows`, `card_license_of`), not in
> `importer.py`: it keeps the 1,600-line importer from growing and removes the import cycle,
> so `importer.py` imports `TaskReplayImport` for typing only. Their tests are in
> `test_task_replay_rows.py`. (2) A Case Source comment is two lines (`CaseSource.comment_lines`:
> what was fetched, then the pin), so a long URL never breaks the 100-column gate the
> generated file must pass. (3) The recorder binds each call to the primitive's own
> signature, so a positional or keyword argument describes the same way (`_download_remote`'s
> parameter is `remote_url`).

### Task 0: Ledger

**Files:**
- Create: `docs/work/2026-10-01-ome-1273-task-replay-import-side.md` from `docs/work/TEMPLATE.md`

- [ ] **Step 1: Write the ledger** with `ticket: OME-1273` (the ticket exists), Intent (this
  plan's Goal), Planned changes (the file list of Tasks 1–8), Test plan (the test files below),
  Acceptance (spec Acceptance 1 for PR 3's part, 2, 4), status `in_progress`.
- [ ] **Step 2: Commit**

```bash
git add docs/work/2026-10-01-ome-1273-task-replay-import-side.md
git commit -m "docs(screamingface-engine): open the ledger for the Task-replay import side"
```

### Task 1: The `no_network` fixture (R17's tool, and every recorder test runs under it)

**Files:**
- Create: `tests/unit/inspect/conftest.py`
- Test: `tests/unit/inspect/test_no_network_fixture.py` (new)

**Interfaces:**
- Produces: a pytest fixture `no_network` that makes any socket connection to a non-loopback
  address raise `RuntimeError("outbound network is blocked in this test (spec R17)")`, DNS
  included, while loopback still works. Task 2's recorder tests and PR 4's grading tests
  request it by name.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/inspect/test_no_network_fixture.py
"""The no_network fixture: a grading test that reaches the internet fails here, not in prod.

INVARIANT (spec R16, R17): Grading downloads nothing. Loopback stays open because the
grading tests drive a url4 node over it.
"""

from __future__ import annotations

import socket

import pytest


def test_an_outbound_connection_is_refused(no_network: None) -> None:
    with pytest.raises(RuntimeError, match="outbound network is blocked"):
        socket.create_connection(("example.com", 443), timeout=1)


def test_dns_is_refused_too(no_network: None) -> None:
    with pytest.raises(RuntimeError, match="outbound network is blocked"):
        socket.getaddrinfo("example.com", 443)


def test_loopback_still_works(no_network: None) -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client = socket.create_connection(server.getsockname(), timeout=1)
        client.close()
    finally:
        server.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/inspect/test_no_network_fixture.py -q`
Expected: ERROR, `fixture 'no_network' not found`

- [ ] **Step 3: Write the fixture**

```python
# tests/unit/inspect/conftest.py
"""Fixtures for the inspect lane. `no_network` is spec R17's tool: a Benchmark's grading test
runs under it, so a scorer that downloads fails in CI instead of in a run pod with no egress."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", ""})


def _refuse(host: Any) -> None:
    """Raise unless the host is loopback."""

    if str(host) not in _LOOPBACK:
        raise RuntimeError(f"outbound network is blocked in this test (spec R17): {host!r}")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Block every socket connection and DNS lookup that is not loopback."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> None:
        _refuse(address[0] if isinstance(address, tuple) else address)
        original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        _refuse(address[0] if isinstance(address, tuple) else address)
        return original_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        _refuse(host)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/inspect/test_no_network_fixture.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/inspect/conftest.py tests/unit/inspect/test_no_network_fixture.py
git commit -m "test(screamingface-engine): a no_network fixture for grading tests"
```

### Task 2: The Case Source recorder

**Files:**
- Create: `src/screamingface_engine_inspect/case_sources.py`
- Test: `tests/unit/inspect/test_case_sources.py` (new). Every test that calls a primitive
  takes `no_network: None`, so a wrapped primitive that reaches the original fails fast and
  offline (`pytest.raises(Exception)` catches the fixture's `RuntimeError`).

**Interfaces:**
- Produces: `CaseSource(kind: str, location: str, pin: str)`, frozen dataclass. `kind` is one
  of `"hugging-face"`, `"url"`, `"file"`. `pin` is `"revision <sha>"`, `"commit <sha>"`,
  `"sha256 <hex>"`, `"inspect_evals==<version>"` or `"unpinned"`.
- Produces: `CaseSource.as_comment(self) -> str`, one line without a leading `#`:
  `url https://…/lsat-ar.jsonl · pin commit 84ab72d9…7552 (no upstream hash: the Case Digest is the only pin)`.
- Produces: `CaseSourceRecorder(cache_root: Path)` with `.sources: list[CaseSource]`,
  `.install() -> None` and `.uninstall() -> None`. Install wraps every primitive in
  `PRIMITIVES` and rebinds, in every loaded module, every attribute that *is* the original
  function, remembering each rebind; uninstall puts back every attribute still holding its
  wrapper (and `DownloadManager.download`). WHY uninstall: the child process dies with its
  patches, but the recorder tests install into the pytest process; without it every later
  test in the session runs through stacked wrappers.
- Test shape: every test in `test_case_sources.py` gets its recorder from a `recorder`
  fixture that installs it and uninstalls in teardown, never from a bare `install()`; one
  more test, `test_uninstall_puts_every_primitive_back`, pins the teardown.
- Produces: `pin_from_url(url: str) -> str`: `"commit <sha>"` when a 40-hex path segment is in
  the URL, else `"unpinned"`.
- Produces: `PRIMITIVES: tuple[Primitive, ...]` where
  `Primitive(module: str, attribute: str, describe: Callable[..., CaseSource | None])`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/inspect/test_case_sources.py
# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The Case Source recorder: one Case Source per top-level fetch, by identity (spec R3).

INVARIANT: a fetch is recorded once however the eval reached the primitive (by module
attribute or by a name imported earlier), and a read from the replay's own cache is never a
Case Source.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.case_sources import (  # noqa: E402
    CaseSource,
    CaseSourceRecorder,
    pin_from_url,
)

_COMMIT = "84ab72d94318290aad2e4ec820d535a95a1f7552"


def test_pin_from_url_reads_a_commit_out_of_the_path() -> None:
    url = f"https://raw.githubusercontent.com/ruixiangcui/AGIEval/{_COMMIT}/data/v1_1/lsat-ar.jsonl"

    assert pin_from_url(url) == f"commit {_COMMIT}"
    assert pin_from_url("https://openaipublic.blob.core.windows.net/simple-evals/mgsm_en.tsv") == "unpinned"


def test_a_url_download_with_a_sha256_is_pinned_by_the_hash(tmp_path: Path, no_network: None) -> None:
    """inspect_ai.util.download(url, sha256, dest): mgsm's primitive."""

    recorder = CaseSourceRecorder(tmp_path / "cache")
    recorder.install()
    import inspect_ai.util as inspect_util

    # WHY call the wrapper directly with a dest that already exists: the real download
    # would hit the network; the describe step runs before the original either way.
    with pytest.raises(Exception):
        inspect_util.download("https://example.invalid/mgsm_en.tsv", "ab" * 32, tmp_path / "x")

    assert recorder.sources == [
        CaseSource("url", "https://example.invalid/mgsm_en.tsv", "sha256 " + "ab" * 32)
    ]


def test_the_recorder_rebinds_a_primitive_imported_by_name(tmp_path: Path, no_network: None) -> None:
    """Review Focus 2: mgsm binds `download` at import time, before any recorder exists."""

    from inspect_ai.util import download as bound_before_install

    stand_in = types.ModuleType("stand_in_eval_that_imported_download")
    stand_in.download = bound_before_install  # type: ignore[attr-defined]
    sys.modules[stand_in.__name__] = stand_in
    try:
        recorder = CaseSourceRecorder(tmp_path / "cache")
        recorder.install()

        assert stand_in.download is not bound_before_install  # type: ignore[attr-defined]
        with pytest.raises(Exception):
            stand_in.download("https://example.invalid/a.tsv", "cd" * 32, tmp_path / "y")  # type: ignore[attr-defined]
        assert [source.location for source in recorder.sources] == ["https://example.invalid/a.tsv"]
    finally:
        del sys.modules[stand_in.__name__]


def test_a_fetch_inside_a_recorded_fetch_is_not_a_second_case_source(
    tmp_path: Path, no_network: None
) -> None:
    """Review Focus 1: agieval's _download_remote calls inspect_ai's file() for the bytes."""

    from inspect_evals.utils import load_dataset as evals_load_dataset

    recorder = CaseSourceRecorder(tmp_path / "cache")
    recorder.install()
    url = f"https://raw.githubusercontent.com/ruixiangcui/AGIEval/{_COMMIT}/data/v1_1/lsat-ar.jsonl"

    with pytest.raises(Exception):
        evals_load_dataset._download_remote(url, tmp_path / "cache" / "lsat-ar.jsonl")

    assert recorder.sources == [CaseSource("url", url, f"commit {_COMMIT}")]


def test_a_read_from_the_replay_cache_is_not_a_case_source(tmp_path: Path) -> None:
    """Review Focus 3: after downloading, mgsm reads the TSV back from the cache."""

    from inspect_ai._util.file import file as inspect_file

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "mgsm_en.tsv").write_text("q\ta\n", encoding="utf-8")
    recorder = CaseSourceRecorder(cache)
    recorder.install()

    with inspect_file(str(cache / "mgsm_en.tsv"), "r") as handle:
        assert handle.read() == "q\ta\n"

    assert recorder.sources == []


def test_a_file_outside_the_cache_is_a_file_case_source(tmp_path: Path) -> None:
    """persistbench reads a file inside the inspect_evals package; a stand-in reads tmp_path."""

    from inspect_ai._util.file import file as inspect_file

    data = tmp_path / "data.jsonl"
    data.write_text("{}\n", encoding="utf-8")
    recorder = CaseSourceRecorder(tmp_path / "cache")
    recorder.install()

    with inspect_file(str(data), "r"):
        pass

    assert recorder.sources == [CaseSource("file", str(data), "unpinned")]


def test_a_hugging_face_load_is_pinned_by_its_revision(tmp_path: Path, no_network: None) -> None:
    import datasets

    recorder = CaseSourceRecorder(tmp_path / "cache")
    recorder.install()

    with pytest.raises(Exception):
        datasets.load_dataset("acme/sums", "main", split="test", revision="c" * 40)

    assert recorder.sources == [CaseSource("hugging-face", "acme/sums/main", "revision " + "c" * 40)]


def test_download_manager_urls_are_recorded_unpinned(tmp_path: Path, no_network: None) -> None:
    """D7: piqa's builder fetches two unpinned URLs through datasets' DownloadManager."""

    from datasets.download.download_manager import DownloadManager

    recorder = CaseSourceRecorder(tmp_path / "cache")
    recorder.install()

    with pytest.raises(Exception):
        DownloadManager().download(
            ["https://storage.googleapis.com/x/physicaliqa-train-dev.zip", "data_clean.zip"]
        )

    assert recorder.sources == [
        CaseSource("url", "https://storage.googleapis.com/x/physicaliqa-train-dev.zip", "unpinned")
    ]


def test_the_comment_says_when_the_digest_is_the_only_pin() -> None:
    assert CaseSource("url", "https://x/y.jsonl", "unpinned").as_comment() == (
        "url https://x/y.jsonl · pin unpinned (no upstream hash: the Case Digest is the only pin)"
    )
    assert CaseSource("hugging-face", "bigbio/med_qa", "revision " + "d" * 40).as_comment() == (
        f"hugging-face bigbio/med_qa · pin revision {'d' * 40}"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_case_sources.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screamingface_engine_inspect.case_sources'`

- [ ] **Step 3: Write the recorder**

```python
# src/screamingface_engine_inspect/case_sources.py
# pyright: reportMissingImports=false
# WHY file-level: the primitives live in the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Case Sources: where an eval's Cases really come from, recorded as it fetches them (OME-1273).

FEATURE: Task-replay Imported Benchmarks — the importer calls the eval's own task function,
and this module watches every fetch primitive it can reach, so the generated declaration can
list each Case Source for review (spec R3).

Think of it as a customs officer at every door of the clean room: each top-level fetch is
logged once, with what it fetched and what pins it. Stages:

    Stage 1 — install: wrap each primitive in PRIMITIVES and rebind, in every loaded module,
              every attribute that IS the original (evals import helpers by name: mgsm does
              `from inspect_ai.util import download`, so patching inspect_ai.util alone
              would miss it).
    Stage 2 — on a call: only a top-level call records (depth 1); a primitive called by
              another primitive is the same fetch (agieval's _download_remote reads the
              bytes through inspect_ai's file()).
    Stage 3 — describe: the primitive's arguments become one CaseSource, or None when the
              call is not a fetch (a read from the replay's own cache, a local path inside
              a snapshot already recorded).
"""

from __future__ import annotations

import functools
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

_COMMIT_IN_URL = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
_URL_SCHEMES: tuple[str, ...] = ("http://", "https://", "s3://", "gs://", "hf://")

#: Kinds a Case Source can be. The comment the importer writes starts with the kind.
HUGGING_FACE = "hugging-face"
URL = "url"
FILE = "file"
UNPINNED = "unpinned"


@dataclass(frozen=True)
class CaseSource:
    """One place Cases were fetched from, and what pins its content."""

    kind: str
    location: str
    pin: str

    def as_comment(self) -> str:
        """The review line the importer writes above the declaration (spec R6)."""

        line: str = f"{self.kind} {self.location} · pin {self.pin}"
        if self.pin == UNPINNED:
            line += " (no upstream hash: the Case Digest is the only pin)"
        return line


def pin_from_url(url: str) -> str:
    """A commit sha in the URL path is a pin; anything else is unpinned."""

    match = _COMMIT_IN_URL.search(url)
    return f"commit {match.group(0)}" if match else UNPINNED


def _is_url(value: Any) -> bool:
    """Whether a path-like argument names something on the network."""

    return isinstance(value, str) and value.startswith(_URL_SCHEMES)


def _describe_load_dataset(*args: Any, **kwargs: Any) -> CaseSource | None:
    """datasets.load_dataset(path, name=None, ..., revision=None)."""

    path: Any = args[0] if args else kwargs.get("path")
    name: Any = args[1] if len(args) > 1 else kwargs.get("name")
    revision: Any = kwargs.get("revision")
    location: str = f"{path}/{name}" if name else str(path)
    return CaseSource(HUGGING_FACE, location, f"revision {revision}" if revision else UNPINNED)


def _describe_snapshot_download(*args: Any, **kwargs: Any) -> CaseSource | None:
    """huggingface_hub.snapshot_download(repo_id, *, revision=None, ...)."""

    repo_id: Any = args[0] if args else kwargs.get("repo_id")
    revision: Any = kwargs.get("revision")
    return CaseSource(HUGGING_FACE, str(repo_id), f"revision {revision}" if revision else UNPINNED)


def _describe_hf_hub_download(*args: Any, **kwargs: Any) -> CaseSource | None:
    """huggingface_hub.hf_hub_download(repo_id, filename, *, revision=None, ...)."""

    repo_id: Any = args[0] if args else kwargs.get("repo_id")
    filename: Any = args[1] if len(args) > 1 else kwargs.get("filename")
    revision: Any = kwargs.get("revision")
    return CaseSource(
        HUGGING_FACE, f"{repo_id}/{filename}", f"revision {revision}" if revision else UNPINNED
    )


def _describe_inspect_download(*args: Any, **kwargs: Any) -> CaseSource | None:
    """inspect_ai.util.download(url, sha256, dest, ...)."""

    url: Any = args[0] if args else kwargs.get("url")
    sha256: Any = args[1] if len(args) > 1 else kwargs.get("sha256")
    return CaseSource(URL, str(url), f"sha256 {sha256}" if sha256 else pin_from_url(str(url)))


def _describe_download_remote(*args: Any, **kwargs: Any) -> CaseSource | None:
    """inspect_evals.utils.load_dataset._download_remote(url, ...): no hash, maybe a commit."""

    url: Any = args[0] if args else kwargs.get("url")
    return CaseSource(URL, str(url), pin_from_url(str(url)))


def _describe_download_manager(*args: Any, **kwargs: Any) -> list[CaseSource]:
    """datasets DownloadManager.download(self, url_or_urls): every URL in a str, list or dict."""

    url_or_urls: Any = args[1] if len(args) > 1 else kwargs.get("url_or_urls")
    flat: list[Any] = []
    stack: list[Any] = [url_or_urls]
    while stack:
        item: Any = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        else:
            flat.append(item)
    # WHY skip non-URLs: medqa's builder "downloads" data_clean.zip, a relative path inside
    # the snapshot already recorded by snapshot_download.
    return [CaseSource(URL, str(url), pin_from_url(str(url))) for url in flat if _is_url(url)]


@dataclass(frozen=True)
class Primitive:
    """One fetch primitive the recorder wraps: where it lives and how to describe a call."""

    module: str
    attribute: str
    describe: Callable[..., CaseSource | list[CaseSource] | None]


class CaseSourceRecorder:
    """The customs officer: installs the wraps and keeps the list of Case Sources."""

    def __init__(self, cache_root: Path) -> None:
        self.sources: list[CaseSource] = []
        self._cache_root: Path = cache_root.resolve()
        self._depth: int = 0
        self._package_root: Path | None = None

    def _describe_file(self, *args: Any, **kwargs: Any) -> CaseSource | None:
        """inspect_ai._util.file.file(path, mode, ...): a URL, a package file, or a cache read."""

        path: Any = args[0] if args else kwargs.get("file")
        text: str = str(path)
        if _is_url(text):
            return CaseSource(URL, text, pin_from_url(text))
        resolved: Path = Path(text).resolve()
        if resolved.is_relative_to(self._cache_root):
            return None  # Stage 3: the eval reading its own download back
        if self._package_root is not None and resolved.is_relative_to(self._package_root):
            relative: str = str(resolved.relative_to(self._package_root))
            return CaseSource(FILE, f"inspect_evals/{relative}", f"inspect_evals=={version('inspect_evals')}")
        return CaseSource(FILE, str(resolved), UNPINNED)

    def _primitives(self) -> tuple[Primitive, ...]:
        """The six primitives of spec R3 plus D7."""

        return (
            Primitive("datasets", "load_dataset", _describe_load_dataset),
            Primitive("huggingface_hub", "snapshot_download", _describe_snapshot_download),
            Primitive("huggingface_hub", "hf_hub_download", _describe_hf_hub_download),
            Primitive("inspect_ai.util", "download", _describe_inspect_download),
            Primitive("inspect_evals.utils.load_dataset", "_download_remote", _describe_download_remote),
            Primitive("inspect_ai._util.file", "file", self._describe_file),
        )

    def install(self) -> None:
        """Stage 1 — wrap every primitive and rebind it wherever it is already bound."""

        try:
            import inspect_evals

            self._package_root = Path(os.path.dirname(inspect_evals.__file__)).resolve()
        except ImportError:  # pragma: no cover - the import tests always have the extra
            self._package_root = None
        for primitive in self._primitives():
            module: Any = import_module(primitive.module)
            original: Any = getattr(module, primitive.attribute)
            wrapped: Any = self._wrap(original, primitive.describe)
            _rebind_everywhere(original, wrapped)
        # The DownloadManager primitive is a method: patch the class, not module attributes.
        from datasets.download.download_manager import DownloadManager

        DownloadManager.download = self._wrap(DownloadManager.download, _describe_download_manager)  # type: ignore[method-assign]

    def _wrap(self, original: Any, describe: Callable[..., Any]) -> Any:
        """Stage 2 — a pass-through that records a top-level call before running the original."""

        @functools.wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self._depth += 1
            try:
                if self._depth == 1:
                    self._record(describe(*args, **kwargs))
                return original(*args, **kwargs)
            finally:
                self._depth -= 1

        return wrapped

    def _record(self, described: CaseSource | list[CaseSource] | None) -> None:
        """Keep each Case Source once, in first-seen order."""

        for source in described if isinstance(described, list) else [described]:
            if source is not None and source not in self.sources:
                self.sources.append(source)


def _rebind_everywhere(original: Any, wrapped: Any) -> None:
    """Replace every loaded-module attribute that IS `original` (spec R3's identity rule)."""

    for module in list(sys.modules.values()):
        if module is None:
            continue
        for name, value in list(vars(module).items()):
            if value is original:
                setattr(module, name, wrapped)


__all__ = [
    "FILE",
    "HUGGING_FACE",
    "UNPINNED",
    "URL",
    "CaseSource",
    "CaseSourceRecorder",
    "Primitive",
    "pin_from_url",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/inspect/test_case_sources.py -q`
Expected: 9 passed. If `test_a_fetch_inside_a_recorded_fetch…` records two sources, the inner
`file()` call is running at depth 1: check that `_download_remote` is the wrapped function
(the test imports the module, not the name, so the rebind must have replaced the module
attribute).

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/case_sources.py tests/unit/inspect/test_case_sources.py
git commit -m "feat(screamingface-engine): record every Case Source a Task replay fetches from"
```

### Task 3: The import-mode replay child

**Files:**
- Create: `src/screamingface_engine_inspect/import_replay.py`
- Test: `tests/unit/inspect/test_import_replay.py` (new)

**Interfaces:**
- Consumes: `replay_environment(cache_root, base)`, `TaskReplayError`, `_failure_reason`,
  `_log_child_stderr`, `TASK_REPLAY_TIMEOUT_SECONDS` from `task_replay.py`;
  `case_records`, `TaskReplayCasesSpec`, `PreparedCase` from `prepare.py`;
  `_solver_facts(task, module, task_ref)` and `_scorer_reference(task, module)` and
  `_custom_metrics(task)` from `importer.py`; `CaseSourceRecorder` from Task 2.
- Produces: `TaskReplayFacts` frozen dataclass: `task_ref: str`, `task_args: dict[str, Any] | None`,
  `prompt_template: str | None`, `choice_template: str | None`, `system_message: str | None`,
  `unreproduced_solvers: tuple[str, ...]`, `mcq: bool`, `scorer: str`,
  `scorer_kwargs: dict[str, Any]`, `custom_metrics: tuple[str, ...]`, `keep_sample_metadata: bool`.
  - `mcq` is `uses_multiple_choice or scorer_name == "choice"`, the Hugging Face reader's two
    witnesses (`importer.py:226`); the child keeps `_scorer_reference`'s third value for it.
  - `keep_sample_metadata` is `not scorer.startswith("inspect_ai.scorer:")` (D11). The child
    builds its run-1 spec with it, so the Cases it renders, and the Case Digest, carry the
    Sample metadata exactly when the declaration will.
- Tests this adds to Step 1: `test_a_wrapped_mcq_solver_is_still_mcq_by_its_choice_scorer`
  (a stand-in task whose `multiple_choice` hides inside its own `@solver`, scored by
  `choice()`) and `test_an_evals_own_scorer_keeps_the_sample_metadata` (a stand-in scorer
  defined in the stand-in module; the prepared Cases carry `metadata`).
- Produces: `ImportReplay(prepared: list[PreparedCase], sample_ids: tuple[str, ...], case_sources: tuple[CaseSource, ...], facts: TaskReplayFacts)`.
  `sample_ids` are the upstream Sample ids as text, in the order the Task holds its Samples: Cases are numbered 1..N
  by the writer, so only the child sees the ids R4's duplicate check needs. A Sample with no
  id reports `None` (typed `tuple[str | None, ...]`), never the text `"None"`.
- Produces: `replay_for_import(task_ref: str, task_args: Mapping[str, Any] | None, *, timeout: float = TASK_REPLAY_TIMEOUT_SECONDS) -> ImportReplay`.
  Raises `TaskReplayError` when the child fails, times out, or writes an unreadable result.
- Produces: `UNSEALED_DIGEST = "0" * 64`, the placeholder digest the child's spec carries
  (`replayed_cases` never compares it).
- The child protocol: `python -m screamingface_engine_inspect.import_replay request.json result.json`.
  `request.json` is `{"task": str, "task_args": dict | null, "cache_root": str}`. `result.json` is
  `{"prepared": [...], "case_sources": [{"kind","location","pin"}, ...], "facts": {...}}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/inspect/test_import_replay.py
# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The import-mode Task replay: a clean child calls the task function, records the Case
Sources, reads the solver and scorer facts, and renders the Cases (spec R2, R3).

INVARIANT: the import child and the image-side child render a Case with the same writer, so
the Case Digest the importer records is the one Case Preparation will compute.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    ImportReplay,
    replay_for_import,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec, case_digest  # noqa: E402
from screamingface_engine_inspect.task_replay import TaskReplayError, replayed_cases  # noqa: E402

#: A stand-in eval whose tasks fetch through a recorded primitive: json_dataset reads a file
#: through inspect_ai._util.file.file, which the recorder sees as a `file` Case Source.
FAKE_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, MemoryDataset, Sample, json_dataset
    from inspect_ai.scorer import choice, match
    from inspect_ai.solver import generate, multiple_choice, prompt_template

    TEMPLATE = "Answer with the number only.\\n\\n{prompt}\\n"
    DATA = os.environ["FAKE_IMPORT_EVAL_DATA"]

    @task
    def arithmetic(extra: bool = False) -> Task:
        # the stand-in's one Case Source: a JSONL file read through inspect_ai's file()
        dataset = json_dataset(DATA, FieldSpec(input="q", target="a", id="id"))
        if extra:
            dataset = MemoryDataset(list(dataset) + [Sample(id=3, input="1 plus 1?", target="2")])
        return Task(dataset=dataset, solver=[prompt_template(TEMPLATE), generate()],
                    scorer=match(numeric=True))

    @task
    def quiz() -> Task:
        return Task(dataset=json_dataset(DATA, FieldSpec(input="q", target="a", id="id",
                                                        choices="choices")),
                    solver=multiple_choice(), scorer=choice())

    @task
    def from_memory() -> Task:
        # yields Samples with no fetch at all: spec R4 refuses it
        return Task(dataset=MemoryDataset([Sample(id=1, input="x", target="y")]), scorer=match())

    @task
    def shuffled() -> Task:
        # an unseeded shuffle over four rows: the two runs disagree 23 times in 24
        dataset = json_dataset(os.environ["FAKE_IMPORT_EVAL_DATA4"],
                               FieldSpec(input="q", target="a", id="id"))
        dataset.shuffle()
        return Task(dataset=dataset, scorer=match())

    @task
    def broken() -> Task:
        raise RuntimeError("upstream URL returned 404")
    """
)

_ROWS: list[dict[str, object]] = [
    {"id": 1, "q": "What is 6 times 7?", "a": "42", "choices": ["41", "42"]},
    {"id": 2, "q": "What is 2 plus 2?", "a": "4", "choices": ["4", "5"]},
]


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval and its data where the child process can import them."""

    (tmp_path / "fake_import_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    data: Path = tmp_path / "cases.jsonl"
    data.write_text("".join(json.dumps(row) + "\n" for row in _ROWS), encoding="utf-8")
    monkeypatch.setenv("FAKE_IMPORT_EVAL_DATA", str(data))
    four: list[dict[str, object]] = _ROWS + [
        {"id": 3, "q": "What is 1 plus 1?", "a": "2", "choices": ["2", "3"]},
        {"id": 4, "q": "What is 3 times 3?", "a": "9", "choices": ["6", "9"]},
    ]
    (tmp_path / "cases4.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in four), encoding="utf-8"
    )
    monkeypatch.setenv("FAKE_IMPORT_EVAL_DATA4", str(tmp_path / "cases4.jsonl"))
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_import_eval"


def test_the_child_returns_cases_case_sources_and_facts(fake_eval: str, tmp_path: Path) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:arithmetic", None)

    assert [item["case"]["input"] for item in replay.prepared] == [
        "Answer with the number only.\n\nWhat is 6 times 7?\n",
        "Answer with the number only.\n\nWhat is 2 plus 2?\n",
    ]
    assert replay.case_sources == (CaseSource("file", str(tmp_path / "cases.jsonl"), "unpinned"),)
    assert replay.sample_ids == ("1", "2")
    assert replay.facts.prompt_template == f"{fake_eval}:TEMPLATE"
    assert replay.facts.scorer == "inspect_ai.scorer:match"
    assert replay.facts.scorer_kwargs == {"numeric": True}
    assert replay.facts.mcq is False


def test_an_mcq_task_reports_its_choice_scorer_and_mcq(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:quiz", None)

    assert replay.facts.mcq is True
    assert replay.facts.scorer == "inspect_ai.scorer:choice"
    assert replay.prepared[0]["grading_material"]["choices"] == ["41", "42"]


def test_task_args_reach_the_task_function(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:arithmetic", {"extra": True})

    assert len(replay.prepared) == 3
    assert replay.facts.task_args == {"extra": True}


def test_the_import_child_and_the_image_child_render_the_same_cases(fake_eval: str) -> None:
    """INVARIANT: one writer. The declaration the importer records reproduces at build."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:arithmetic", None)
    declaration = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic",
        case_count=2,
        case_digest=case_digest(replay.prepared),
        prompt_template=replay.facts.prompt_template,
    )

    assert case_digest(replayed_cases(declaration)) == declaration.case_digest


def test_a_task_that_raises_is_a_named_replay_failure(fake_eval: str) -> None:
    with pytest.raises(TaskReplayError, match="upstream URL returned 404"):
        replay_for_import(f"{fake_eval}:broken", None)


def test_a_task_with_no_fetch_records_no_case_source(fake_eval: str) -> None:
    """The refusal itself lives in Task 4; here the child just reports an empty list."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:from_memory", None)

    assert replay.case_sources == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_import_replay.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screamingface_engine_inspect.import_replay'`

- [ ] **Step 3: Write the module**

```python
# src/screamingface_engine_inspect/import_replay.py
# pyright: reportMissingImports=false
# WHY file-level: the child half imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Import-mode Task replay: the first of the two runs the importer makes (OME-1273, spec R2–R4).

FEATURE: Task-replay Imported Benchmarks. The image side (task_replay.py) replays a
DECLARATION it already has. The importer has none yet: it needs the Cases, where they came
from, and the solver and scorer facts of the built Task, all from one clean child. This
module is that child and its parent-side call. It never calls inspect's ``eval()``: no
solver, scorer, model or Judge runs.

Stages, in execution order:

    Stage 1 — parent: write request.json (task, args, cache root); build the clean-room
              environment exactly as the image side does (replay_environment).
    Stage 2 — child: import the task module, THEN install the Case Source recorder, so a
              name the module bound at import (`from inspect_ai.util import download`) is
              rebound too; call the task function with its args.
    Stage 3 — child: read the facts from the built Task with the importer's own readers
              (_solver_facts, _scorer_reference, _custom_metrics); render the Samples with
              the shared Case writer, using those facts.
    Stage 4 — child: write result.json: prepared Cases, Case Sources, facts. WHY a file:
              evals print while they load.
    Stage 5 — parent: a non-zero exit, a timeout or an unreadable result is a
              TaskReplayError carrying the child's final error line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from screamingface_engine_inspect.case_sources import CaseSource, CaseSourceRecorder
from screamingface_engine_inspect.prepare import PreparedCase, TaskReplayCasesSpec, case_records
from screamingface_engine_inspect.task_replay import (
    TASK_REPLAY_TIMEOUT_SECONDS,
    TaskReplayError,
    _failure_reason,
    _log_child_stderr,
    replay_environment,
)

#: The digest the import child's spec carries: nothing compares it (replayed_cases never does).
UNSEALED_DIGEST: str = "0" * 64


@dataclass(frozen=True)
class TaskReplayFacts:
    """What the importer reads off the built Task: the prompt and scorer facts (spec R6)."""

    task_ref: str
    task_args: dict[str, Any] | None
    prompt_template: str | None
    choice_template: str | None
    system_message: str | None
    unreproduced_solvers: tuple[str, ...]
    mcq: bool
    scorer: str
    scorer_kwargs: dict[str, Any]
    custom_metrics: tuple[str, ...]


@dataclass(frozen=True)
class ImportReplay:
    """One import-mode run: the Cases, the upstream Sample ids, where they came from, and the
    Task's facts."""

    prepared: list[PreparedCase]
    sample_ids: tuple[str, ...]
    case_sources: tuple[CaseSource, ...]
    facts: TaskReplayFacts


def replay_for_import(
    task_ref: str,
    task_args: Mapping[str, Any] | None,
    *,
    timeout: float = TASK_REPLAY_TIMEOUT_SECONDS,
) -> ImportReplay:
    """Run the import child once and read back Cases, Case Sources and facts.

    Args:
        task_ref: ``"module:attr"`` of the eval's task function.
        task_args: forwarded to the task function; None for none.
        timeout: seconds before a stalled replay is abandoned.

    Raises:
        TaskReplayError: the child failed, timed out, or wrote an unreadable result.
    """

    # Stage 1 — request file + clean-room environment.
    with tempfile.TemporaryDirectory(prefix="task-replay-import-") as scratch:
        root: Path = Path(scratch)
        cache_root: Path = root / "cache"
        request_path: Path = root / "request.json"
        result_path: Path = root / "result.json"
        request: dict[str, Any] = {
            "task": task_ref,
            "task_args": dict(task_args) if task_args else None,
            "cache_root": str(cache_root),
        }
        request_path.write_text(json.dumps(request), encoding="utf-8")
        command: list[str] = [sys.executable, "-m", __name__, str(request_path), str(result_path)]
        try:
            completed: subprocess.CompletedProcess[str] = subprocess.run(  # noqa: S603 — argv is ours; no shell
                command,
                env=replay_environment(cache_root, os.environ),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log_child_stderr(task_ref, exc.stderr)
            raise TaskReplayError(f"{task_ref}: replay timed out after {timeout:g}s") from exc
        # Stage 5 — any failure is one named line; the tail goes to the log.
        if completed.returncode != 0 or not result_path.is_file():
            _log_child_stderr(task_ref, completed.stderr)
            raise TaskReplayError(
                f"{task_ref}: replay failed (exit {completed.returncode}): "
                f"{_failure_reason(completed.stderr)}"
            )
        try:
            result: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TaskReplayError(f"{task_ref}: replay wrote an unreadable result: {exc}") from exc
    facts: TaskReplayFacts = TaskReplayFacts(
        **{
            **result["facts"],
            "unreproduced_solvers": tuple(result["facts"]["unreproduced_solvers"]),
            "custom_metrics": tuple(result["facts"]["custom_metrics"]),
        }
    )
    return ImportReplay(
        prepared=result["prepared"],
        sample_ids=tuple(result["sample_ids"]),
        case_sources=tuple(CaseSource(**source) for source in result["case_sources"]),
        facts=facts,
    )


def _replay_in_this_process(request_path: Path, result_path: Path) -> None:
    """Stages 2 to 4 — the child's half."""

    # WHY import here: importer.py imports the plugin's registries; the child needs only
    # its three readers, and the image-side child (task_replay.py) must not import it.
    from screamingface_engine_inspect.importer import (
        _custom_metrics,
        _scorer_reference,
        _solver_facts,
    )

    request: dict[str, Any] = json.loads(request_path.read_text(encoding="utf-8"))
    task_ref: str = request["task"]
    task_args: dict[str, Any] | None = request["task_args"]
    module_name, _, attribute = task_ref.partition(":")
    module: Any = import_module(module_name)
    # Stage 2 — the recorder installs AFTER the import, so names bound at import are rebound.
    recorder: CaseSourceRecorder = CaseSourceRecorder(Path(request["cache_root"]))
    recorder.install()
    task: Any = getattr(module, attribute)(**(task_args or {}))
    # Stage 3 — facts from the built Task, then the Cases through the shared writer.
    template_ref, choice_ref, system_ref, custom, mcq = _solver_facts(task, module, task_ref)
    scorer_ref, scorer_kwargs, _ = _scorer_reference(task, module)
    facts: TaskReplayFacts = TaskReplayFacts(
        task_ref=task_ref,
        task_args=task_args,
        prompt_template=template_ref,
        choice_template=choice_ref,
        system_message=system_ref,
        unreproduced_solvers=custom,
        mcq=mcq,
        scorer=scorer_ref,
        scorer_kwargs=scorer_kwargs,
        custom_metrics=_custom_metrics(task),
    )
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref,
        case_count=0,
        case_digest=UNSEALED_DIGEST,
        task_args=task_args,
        prompt_template=template_ref,
        choice_template=choice_ref,
        system_message=system_ref,
    )
    samples: list[Any] = list(task.dataset)
    prepared: list[PreparedCase] = case_records(samples, spec)
    # Stage 4 — one file back to the parent. WHY sample_ids: the writer numbers Cases 1..N,
    # so the upstream ids R4's duplicate check reads exist only here.
    result: dict[str, Any] = {
        "prepared": prepared,
        "sample_ids": [str(sample.id) for sample in samples],
        "case_sources": [asdict(source) for source in recorder.sources],
        "facts": asdict(facts),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


__all__ = ["UNSEALED_DIGEST", "ImportReplay", "TaskReplayFacts", "replay_for_import"]


if __name__ == "__main__":  # pragma: no cover - child-process entrypoint, run via replay_for_import
    _replay_in_this_process(Path(sys.argv[1]), Path(sys.argv[2]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/inspect/test_import_replay.py -q`
Expected: 6 passed. If `test_the_child_returns_cases…` reports `case_sources == ()`, the
`json_dataset` read is reaching `file()` through a name the rebind missed: check
`inspect_ai.dataset._sources.json` (or wherever 0.3.263 binds it) imports `file` by name and
that `_rebind_everywhere` ran after that module was imported (it is: `inspect_ai.dataset` is
imported by the stand-in before the recorder installs).

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/import_replay.py tests/unit/inspect/test_import_replay.py
git commit -m "feat(screamingface-engine): replay a task for import with Case Sources and facts"
```

### Task 4: Route the four refusals to Task replay

**Files:**
- Modify: `src/screamingface_engine_inspect/importer.py` (`ImporterError` at :82; the four raise
  sites at :189, :507, :518, :491)
- Test: `tests/unit/inspect/test_inspect_importer.py` (append only)

**Interfaces:**
- Produces: `class TaskReplayRoute(ImporterError)`: "the Hugging Face reader cannot see this
  eval's fetch; Task replay can import it" (spec R1). A subclass, so every existing
  `pytest.raises(ImporterError, match=…)` still passes.

- [ ] **Step 1: Write the failing tests** (append at the end of `test_inspect_importer.py`)

```python
# ── OME-1273: the four refusals that route to Task replay (spec R1) ─────────────


def test_a_module_with_no_hf_dataset_binding_routes_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]

    with pytest.raises(TaskReplayRoute, match="no hf_dataset binding"):
        read_inspect_task(f"{_FAKE_MODULE}:sums")


def test_a_task_that_never_calls_hf_dataset_routes_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def from_memory() -> Task:
        return Task(dataset=MemoryDataset([Sample(input="x", target="y")]), scorer=match())

    _install_fake_eval(monkeypatch, from_memory=from_memory)

    with pytest.raises(TaskReplayRoute, match="never called hf_dataset"):
        read_inspect_task(f"{_FAKE_MODULE}:from_memory")


def test_several_calls_none_the_tasks_dataset_route_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def two_loads_neither_held() -> Task:
        module = sys.modules[_FAKE_MODULE]
        for split in ("train", "test"):
            module.hf_dataset(path="acme/sums", split=split, sample_fields=module.record_to_sample)
        return Task(dataset=MemoryDataset([Sample(input="x", target="y")]), scorer=match())

    _install_fake_eval(monkeypatch, two=two_loads_neither_held)

    with pytest.raises(TaskReplayRoute, match="none is the Task's dataset"):
        read_inspect_task(f"{_FAKE_MODULE}:two")


def test_a_task_local_record_to_sample_routes_to_task_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def local_converter() -> Task:
        module = sys.modules[_FAKE_MODULE]

        def record_to_sample(row: dict[str, Any]) -> Sample:
            return Sample(input=str(row["q"]), target=str(row["a"]))

        return Task(
            dataset=module.hf_dataset(path="acme/sums", split="test", sample_fields=record_to_sample),
            scorer=match(),
        )

    _install_fake_eval(monkeypatch, local=local_converter)

    with pytest.raises(TaskReplayRoute, match="task-local"):
        read_inspect_task(f"{_FAKE_MODULE}:local")


def test_every_other_refusal_stays_a_plain_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec R1: only the four 'can't see the fetch' refusals route; a real mismatch never does."""

    def two_scorers() -> Task:
        module = sys.modules[_FAKE_MODULE]
        return Task(
            dataset=module.hf_dataset(path="acme/sums", split="test", sample_fields=module.record_to_sample),
            scorer=[match(), choice()],
        )

    _install_fake_eval(monkeypatch, two_scorers=two_scorers)

    with pytest.raises(ImporterError, match="exactly one scorer") as caught:
        read_inspect_task(f"{_FAKE_MODULE}:two_scorers")
    assert not isinstance(caught.value, TaskReplayRoute)
```

Add `TaskReplayRoute` to the file's existing `from screamingface_engine_inspect.importer import (…)`
block, and `MemoryDataset` to its `inspect_ai.dataset` import if absent (both are import-line
additions, not edits to earlier tests).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_inspect_importer.py -q -k "task_replay or stays_a_plain"`
Expected: FAIL with `ImportError: cannot import name 'TaskReplayRoute'`

- [ ] **Step 3: Add the class and change the four raise sites**

Below `class ImporterError(Exception)` (:82):

```python
class TaskReplayRoute(ImporterError):
    """The Hugging Face reader cannot see this eval's fetch; Task replay can import it (OME-1273).

    WHY a subclass: to every caller that only knows refusals it IS one; the CLI alone tells
    the two apart and takes the Task-replay path (spec R1).
    """
```

Then change exactly the exception class at the four sites, leaving each message as it is:
- :189 `raise TaskReplayRoute(f"{module_name} has no hf_dataset binding — …")`
- :507 `raise TaskReplayRoute(f"{task_ref}: the task never called hf_dataset")`
- :518 `raise TaskReplayRoute(f"{task_ref}: {len(recorded)} hf_dataset call(s) and none is the Task's dataset — …")`
- :491 `raise TaskReplayRoute(f"{task_ref}: record_to_sample is a task-local function — …")`

Add `"TaskReplayRoute"` to `__all__` if the module has one.

- [ ] **Step 4: Run the whole importer suite**

Run: `uv run pytest tests/unit/inspect/test_inspect_importer.py -q`
Expected: all pass (the earlier refusal tests match on message substrings; a subclass satisfies
`pytest.raises(ImporterError)`).

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/importer.py tests/unit/inspect/test_inspect_importer.py
git commit -m "feat(screamingface-engine): route the four fetch-blind refusals to Task replay"
```

### Task 5: The double run and the import refusals

**Files:**
- Modify: `src/screamingface_engine_inspect/import_replay.py` (add `import_by_task_replay`, `TaskReplayImport`)
- Test: `tests/unit/inspect/test_import_replay.py` (append only)

**Interfaces:**
- Consumes: `replayed_cases(spec)` and `TaskReplayError` from `task_replay.py`; `case_digest`.
- Produces: `TaskReplayImport(declaration: TaskReplayCasesSpec, case_sources: tuple[CaseSource, ...], facts: TaskReplayFacts)`.
- Produces: `import_by_task_replay(task_ref: str, task_args: Mapping[str, Any] | None, *, timeout: float = TASK_REPLAY_TIMEOUT_SECONDS) -> TaskReplayImport`.
  Raises `ImporterError` for each R4 refusal, by name: the task raised; no Samples; Samples but
  no Case Source; two Samples share an id; the two runs' Case Digests differ.
  - The duplicate check skips Samples with no id (inspect numbers those itself at eval time,
    so they cannot collide); pinned by `test_samples_with_no_id_are_not_duplicates`.
  - The sealed declaration carries `keep_sample_metadata=first.facts.keep_sample_metadata`,
    so run 2 renders the Cases run 1 sealed.

- [ ] **Step 1: Write the failing tests** (append to `test_import_replay.py`)

```python
# ── the double run and the import refusals (spec R4) ────────────────────────────

from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayImport,
    import_by_task_replay,
)
from screamingface_engine_inspect.importer import ImporterError  # noqa: E402


def test_an_import_seals_the_cases_with_a_digest_both_runs_agree_on(fake_eval: str) -> None:
    imported: TaskReplayImport = import_by_task_replay(f"{fake_eval}:arithmetic", None)

    assert imported.declaration.case_count == 2
    assert len(imported.declaration.case_digest) == 64
    assert imported.declaration.prompt_template == f"{fake_eval}:TEMPLATE"
    assert imported.declaration.task_args is None
    assert case_digest(replayed_cases(imported.declaration)) == imported.declaration.case_digest


def test_the_second_run_takes_the_image_side_path(
    fake_eval: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 4: run 2 is what the image build will do, so the written declaration is
    proven to reproduce, not just the import child."""

    from screamingface_engine_inspect import import_replay

    calls: list[str] = []
    original = import_replay.replayed_cases

    def spy(spec: TaskReplayCasesSpec, **kwargs: object) -> list[dict[str, object]]:
        calls.append(spec.task)
        return original(spec, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(import_replay, "replayed_cases", spy)

    import_by_task_replay(f"{fake_eval}:arithmetic", None)

    assert calls == [f"{fake_eval}:arithmetic"]


def test_a_task_that_raises_is_refused_by_name(fake_eval: str) -> None:
    with pytest.raises(ImporterError, match="upstream URL returned 404"):
        import_by_task_replay(f"{fake_eval}:broken", None)


def test_samples_with_no_case_source_are_refused(fake_eval: str) -> None:
    """A fetch nobody can see is a fetch nobody can review."""

    with pytest.raises(ImporterError, match="no Case Source was recorded"):
        import_by_task_replay(f"{fake_eval}:from_memory", None)


def test_no_samples_is_refused(fake_eval: str, tmp_path: Path) -> None:
    (tmp_path / "cases.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(ImporterError, match="yielded no Samples"):
        import_by_task_replay(f"{fake_eval}:arithmetic", None)


def test_two_samples_sharing_an_id_are_refused(fake_eval: str, tmp_path: Path) -> None:
    rows: list[dict[str, object]] = [dict(_ROWS[0]), {**_ROWS[1], "id": 1}]
    (tmp_path / "cases.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    with pytest.raises(ImporterError, match="share the id 1"):
        import_by_task_replay(f"{fake_eval}:arithmetic", None)


def test_two_runs_that_disagree_are_refused(fake_eval: str) -> None:
    """An unseeded shuffle passes once and would go SKIPPED at every build (spec R4).

    WHY three attempts: the stand-in shuffles four rows, so the two runs agree by chance
    1 time in 24 per attempt; three attempts leave 1 in 13,824.
    """

    refused: bool = False
    for _ in range(3):
        try:
            import_by_task_replay(f"{fake_eval}:shuffled", None)
        except ImporterError as exc:
            assert "different Cases" in str(exc)
            refused = True
            break

    assert refused
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_import_replay.py -q -k "refused or seals or second_run"`
Expected: FAIL with `ImportError: cannot import name 'import_by_task_replay'`

- [ ] **Step 3: Write the parent-side import**

Append to `import_replay.py` (before `__all__`):

```python
@dataclass(frozen=True)
class TaskReplayImport:
    """What the importer writes from: the sealed declaration, its Case Sources and facts."""

    declaration: TaskReplayCasesSpec
    case_sources: tuple[CaseSource, ...]
    facts: TaskReplayFacts


def import_by_task_replay(
    task_ref: str,
    task_args: Mapping[str, Any] | None,
    *,
    timeout: float = TASK_REPLAY_TIMEOUT_SECONDS,
) -> TaskReplayImport:
    """Import one eval by Task replay: run 1 reads, the declaration is sealed, run 2 proves it.

    Think of it as printing the question booklet twice and checking both prints match
    before the booklet is filed. Stages:

        Stage 1 — run 1, the import child: Cases, Case Sources, facts (replay_for_import).
        Stage 2 — refuse by name (spec R4): the task raised; no Samples; Samples but no Case
                  Source; two Samples share an id.
        Stage 3 — seal: the declaration carries the count and the Case Digest of run 1.
        Stage 4 — run 2, the IMAGE-SIDE child (task_replay.replayed_cases) on that
                  declaration: what every build will do. A different digest is refused:
                  an unseeded shuffle or generated Cases would pass once and go SKIPPED at
                  every build.

    Raises:
        ImporterError: one of the Stage 2 or Stage 4 refusals, named.
    """

    from screamingface_engine_inspect.importer import ImporterError
    from screamingface_engine_inspect.prepare import case_digest
    from screamingface_engine_inspect.task_replay import replayed_cases

    # Stage 1
    try:
        first: ImportReplay = replay_for_import(task_ref, task_args, timeout=timeout)
    except TaskReplayError as exc:
        raise ImporterError(str(exc)) from exc
    # Stage 2
    if not first.prepared:
        raise ImporterError(f"{task_ref}: the task yielded no Samples")
    if not first.case_sources:
        raise ImporterError(
            f"{task_ref}: the task yielded {len(first.prepared)} Samples but no Case Source "
            "was recorded — a fetch nobody can see is a fetch nobody can review; the eval "
            "downloads through a primitive the recorder does not wrap"
        )
    seen: set[str] = set()
    for sample_id in first.sample_ids:
        if sample_id in seen:
            raise ImporterError(f"{task_ref}: two Samples share the id {sample_id}")
        seen.add(sample_id)
    # Stage 3
    declaration: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref,
        case_count=len(first.prepared),
        case_digest=case_digest(first.prepared),
        task_args=dict(task_args) if task_args else None,
        prompt_template=first.facts.prompt_template,
        choice_template=first.facts.choice_template,
        system_message=first.facts.system_message,
    )
    # Stage 4
    try:
        second: list[PreparedCase] = replayed_cases(declaration, timeout=timeout)
    except TaskReplayError as exc:
        raise ImporterError(str(exc)) from exc
    if case_digest(second) != declaration.case_digest:
        raise ImporterError(
            f"{task_ref}: two Task replays produced different Cases (Case Digest "
            f"{declaration.case_digest[:12]}… then {case_digest(second)[:12]}…) — an unseeded "
            "shuffle or generated Cases; pass task args that fix the order, e.g. "
            "--task-arg shuffle=False or --task-arg seed=42"
        )
    return TaskReplayImport(declaration=declaration, case_sources=first.case_sources, facts=first.facts)
```

Move `from screamingface_engine_inspect.task_replay import replayed_cases` to the module's
top-level import block (the spy test patches `import_replay.replayed_cases`, which needs a
module attribute); the `ImporterError` and `case_digest` imports can also go to the top
(`prepare` is already imported there; `importer` is not, and importing it at module level
would make the child import the whole importer: keep that one local).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/inspect/test_import_replay.py -q`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/import_replay.py tests/unit/inspect/test_import_replay.py
git commit -m "feat(screamingface-engine): seal a Task-replay import with a digest two runs agree on"
```

### Task 6: The generated declaration and its BenchmarkSpec row

**Files:**
- Modify: `src/screamingface_engine_inspect/prepare.py` (`TaskReplayCasesSpec` :314; `TASK_REPLAY_CASES` :771)
- Modify: `src/screamingface_engine_inspect/importer.py` (anchors :75–77; `_benchmark_lines` :1176;
  `_refuse_existing_rows` :1408; new render and write functions)
- Test: `tests/unit/inspect/test_inspect_importer.py` (append only)

**Interfaces:**
- Produces, in `prepare.py`: `LICENSE_TODO = "TODO"`; `TaskReplayCasesSpec.license: str = LICENSE_TODO`
  as its last field; `TASK_REPLAY_CASES` becomes a dict literal holding the anchor comment line.
- Produces, in `importer.py`: `_TASK_REPLAY_CASES_ANCHOR = "# --- importer: generated TaskReplayCasesSpec rows land above this line ---"`.
- Produces: `TaskReplayRows(cases: str, benchmark: str)` frozen dataclass.
- Produces: `render_task_replay_rows(key: str, imported: TaskReplayImport, license: str) -> TaskReplayRows`.
- Produces: `write_task_replay_rows(key: str, imported: TaskReplayImport, *, engine_src: Path, license: str) -> TaskReplayRows`.
- Produces: `_scorer_lines(scorer: str, scorer_kwargs: Mapping[str, Any], custom_metrics: tuple[str, ...], mcq: bool, judged: bool) -> list[str]`,
  extracted from `_benchmark_lines` so both row renderers share it. `_benchmark_lines` keeps its
  signature and output byte-for-byte (the existing render tests pin it).
- Produces: `_is_judged_by(scorer: str, scorer_kwargs: Mapping[str, Any]) -> bool`, the body of
  `_is_judged` on plain values; `_is_judged(facts)` becomes `_is_judged_by(facts.scorer, facts.scorer_kwargs)`.

- [ ] **Step 1: Write the failing tests** (append to `test_inspect_importer.py`)

```python
# ── OME-1273: the generated Task-replay declaration (spec R6) ───────────────────

from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayFacts,
    TaskReplayImport,
)
from screamingface_engine_inspect.importer import (  # noqa: E402
    render_task_replay_rows,
    write_task_replay_rows,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402

_AGIEVAL_URL = (
    "https://raw.githubusercontent.com/ruixiangcui/AGIEval/"
    "84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/lsat-ar.jsonl"
)


def _task_replay_import(**overrides: Any) -> TaskReplayImport:
    """A sealed import as import_by_task_replay would return it, with agieval-shaped values."""

    facts = TaskReplayFacts(
        task_ref="inspect_evals.agieval.agieval:agie_lsat_ar",
        task_args=None,
        prompt_template=None,
        choice_template="inspect_evals.agieval.utils:MULTIPLE_CHOICE_TEMPLATE_EN",
        system_message=None,
        unreproduced_solvers=(),
        mcq=True,
        scorer="inspect_ai.scorer:choice",
        scorer_kwargs={},
        custom_metrics=(),
    )
    declaration = TaskReplayCasesSpec(
        task=facts.task_ref,
        case_count=230,
        case_digest="e" * 64,
        choice_template=facts.choice_template,
    )
    values: dict[str, Any] = {
        "declaration": declaration,
        "case_sources": (
            CaseSource("url", _AGIEVAL_URL, "commit 84ab72d94318290aad2e4ec820d535a95a1f7552"),
        ),
        "facts": facts,
        **overrides,
    }
    return TaskReplayImport(**values)


def test_task_replay_rows_carry_the_sources_as_comments_and_the_seal_as_values() -> None:
    rows = render_task_replay_rows("agieval_lsat_ar", _task_replay_import(), "TODO")

    assert rows.cases == (
        "    # agieval_lsat_ar — imported by Task replay on "
        + _datetime.date.today().isoformat()
        + " from\n"
        "    #   inspect_evals.agieval.agieval:agie_lsat_ar.\n"
        "    # Case Sources, as recorded at import (review these; the Case Digest pins the content):\n"
        f"    #   url {_AGIEVAL_URL} · pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552\n"
        '    "agieval_lsat_ar": TaskReplayCasesSpec(\n'
        '        task="inspect_evals.agieval.agieval:agie_lsat_ar",\n'
        "        case_count=230,\n"
        f'        case_digest="{"e" * 64}",\n'
        '        choice_template="inspect_evals.agieval.utils:MULTIPLE_CHOICE_TEMPLATE_EN",\n'
        "        # TODO(review): the owner decides this license; no dataset card to read.\n"
        '        license="TODO",\n'
        "    ),\n"
    )


def test_task_replay_rows_write_task_args_and_an_unpinned_source_note() -> None:
    declaration = TaskReplayCasesSpec(
        task="inspect_evals.mgsm.mgsm:mgsm",
        case_count=250,
        case_digest="f" * 64,
        task_args={"languages": ["en"]},
    )
    imported = _task_replay_import(
        declaration=declaration,
        case_sources=(CaseSource("url", "https://x/mgsm_en.tsv", "unpinned"),),
    )

    rows = render_task_replay_rows("mgsm_en", imported, "TODO")

    assert '        task_args={"languages": ["en"]},\n' in rows.cases
    assert "    #   url https://x/mgsm_en.tsv · pin unpinned (no upstream hash: the Case Digest is the only pin)\n" in rows.cases


def test_a_hub_license_lands_as_the_license_value() -> None:
    rows = render_task_replay_rows("medqa", _task_replay_import(), "apache-2.0")

    assert '        license="apache-2.0",\n' in rows.cases
    assert "TODO(review): the owner decides this license" not in rows.cases


def test_task_replay_benchmark_row_points_at_the_first_case_source() -> None:
    rows = render_task_replay_rows("agieval_lsat_ar", _task_replay_import(), "TODO")

    assert f'        dataset_url="{_AGIEVAL_URL}",\n' in rows.benchmark
    assert '        scorer="inspect_ai.scorer:choice",\n' in rows.benchmark
    assert "        # License: TODO.\n" in rows.benchmark
    assert "with_check_surface" not in rows.benchmark  # MCQ


def test_a_hub_license_outside_the_charset_is_refused() -> None:
    """Review Focus 5: the license lands in generated Python."""

    with pytest.raises(ImporterError, match="license"):
        render_task_replay_rows("medqa", _task_replay_import(), 'mit")\nimport os  # ("')


def test_write_task_replay_rows_lands_in_prepare_and_benchmarks_only(engine_src_copy: Path) -> None:
    write_task_replay_rows("agieval_lsat_ar", _task_replay_import(), engine_src=engine_src_copy, license="TODO")

    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    benchmarks_text: str = (engine_src_copy / "benchmarks.py").read_text()
    assert '"agieval_lsat_ar": TaskReplayCasesSpec(' in prepare_text
    assert 'key="agieval_lsat_ar"' in benchmarks_text
    assert (engine_src_copy / "pins.py").read_text() == (_SRC_DIR / "pins.py").read_text()
    for name in ("prepare.py", "benchmarks.py"):
        ast.parse((engine_src_copy / name).read_text())


def test_write_task_replay_rows_refuses_a_key_already_declared(engine_src_copy: Path) -> None:
    write_task_replay_rows("agieval_lsat_ar", _task_replay_import(), engine_src=engine_src_copy, license="TODO")

    with pytest.raises(ImporterError, match="already exists"):
        write_task_replay_rows("agieval_lsat_ar", _task_replay_import(), engine_src=engine_src_copy, license="TODO")


def test_the_hugging_face_rows_render_byte_identical_after_the_shared_extraction(
    engine_src_copy: Path,
) -> None:
    """Spec R1: every existing import produces byte-identical generated code."""

    _generate(engine_src_copy)

    text: str = (engine_src_copy / "benchmarks.py").read_text()
    assert '        scorer="inspect_ai.scorer:match",\n' in text
    assert "        with_check_surface=True,\n" in text
```

Add `import ast` and `import datetime as _datetime` at the top of the test file if absent
(import-line additions only).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_inspect_importer.py -q -k "task_replay_rows or hub_license or shared_extraction"`
Expected: FAIL with `ImportError: cannot import name 'render_task_replay_rows'`

- [ ] **Step 3: The declaration gains a license; the registry gains an anchor**

In `prepare.py`, above `TaskReplayCasesSpec`:

```python
#: The license value the importer writes when no dataset card can be read; a test refuses
#: a Task-replay declaration that still carries it (spec R7). The owner decides each license.
LICENSE_TODO: str = "TODO"
```

Append to `TaskReplayCasesSpec`'s fields:

```python
    #: The dataset license, from the Hugging Face card when the one Case Source has one,
    #: otherwise the owner's decision replacing LICENSE_TODO in the diff (spec R6, R7).
    license: str = LICENSE_TODO
```

Replace `TASK_REPLAY_CASES: dict[str, TaskReplayCasesSpec] = {}` with:

```python
TASK_REPLAY_CASES: dict[str, TaskReplayCasesSpec] = {
    # --- importer: generated TaskReplayCasesSpec rows land above this line ---
}
```

Add `LICENSE_TODO` to `prepare.py`'s `__all__`.

- [ ] **Step 4: The renderers in `importer.py`**

Below the three anchors (:77):

```python
_TASK_REPLAY_CASES_ANCHOR = "# --- importer: generated TaskReplayCasesSpec rows land above this line ---"
```

Extract the scorer tail of `_benchmark_lines`. The body from `f'        scorer="{facts.scorer}",'`
through the `with_check_surface=True,` block moves, unchanged line for line, into:

```python
def _scorer_lines(
    scorer: str,
    scorer_kwargs: Mapping[str, Any],
    custom_metrics: tuple[str, ...],
    mcq: bool,
    judged: bool,
) -> list[str]:
    """The scorer, metric and judge lines of a BenchmarkSpec row, shared by both importers."""
    ...  # the moved lines, with facts.X replaced by the parameter X
```

`_benchmark_lines` then ends with
`benchmark_lines.extend(_scorer_lines(facts.scorer, facts.scorer_kwargs, facts.custom_metrics, facts.mcq, _is_judged(facts)))`
followed by the existing `benchmark_lines.append("    ),")`. Split `_is_judged` the same way:
its body becomes `_is_judged_by(scorer, scorer_kwargs)` and `_is_judged(facts)` delegates.
Run `uv run pytest tests/unit/inspect/test_inspect_importer.py -q` now: every existing render
test must still pass before you go on.

Then add the Task-replay renderers next to `render_generated_rows`:

```python
@dataclass(frozen=True)
class TaskReplayRows:
    """The two generated rows of a Task-replay import: no pins row, no import names."""

    cases: str
    benchmark: str


def render_task_replay_rows(key: str, imported: TaskReplayImport, license: str) -> TaskReplayRows:
    """Render a Task-replay declaration and its BenchmarkSpec row (spec R6).

    Case Sources go in as comments (COPIED: the reviewer judges where the Cases come from);
    the Case count and Case Digest go in as values (CAPTURED: the code enforces what they are).
    """

    if not _LICENSE_CHARSET.match(license):
        raise ImporterError(f"license {license!r} holds characters that cannot land in generated code")
    for source in imported.case_sources:
        if not _CASE_SOURCE_CHARSET.match(source.location) or not _CASE_SOURCE_CHARSET.match(source.pin):
            raise ImporterError(f"Case Source {source.location!r} holds characters that cannot land in generated code")
    declaration: TaskReplayCasesSpec = imported.declaration
    facts: TaskReplayFacts = imported.facts
    today: str = _datetime.date.today().isoformat()
    lines: list[str] = [
        f"    # {key} — imported by Task replay on {today} from",
        f"    #   {declaration.task}.",
        "    # Case Sources, as recorded at import (review these; the Case Digest pins the content):",
        *[f"    #   {source.as_comment()}" for source in imported.case_sources],
        f'    "{key}": TaskReplayCasesSpec(',
        f'        task="{declaration.task}",',
    ]
    if declaration.task_args:
        lines.append(f"        task_args={_python_literal_source(declaration.task_args)},")
    lines.append(f"        case_count={declaration.case_count},")
    lines.append(f'        case_digest="{declaration.case_digest}",')
    for name in ("prompt_template", "choice_template", "system_message"):
        value: str | None = getattr(declaration, name)
        if value is not None:
            lines.append(f'        {name}="{value}",')
    for flag in facts.unreproduced_solvers:
        lines.append(f"        # TODO(review): solver {flag} is not reproduced by Case Preparation.")
    if license == LICENSE_TODO:
        lines.append("        # TODO(review): the owner decides this license; no dataset card to read.")
    lines.append(f'        license="{license}",')
    lines.append("    ),")
    cases: str = "\n".join(lines) + "\n"
    benchmark: str = "\n".join(_task_replay_benchmark_lines(key, imported, license)) + "\n"
    return TaskReplayRows(cases=cases, benchmark=benchmark)


def _task_replay_benchmark_lines(key: str, imported: TaskReplayImport, license: str) -> list[str]:
    """The BenchmarkSpec row of a Task-replay import: prose as TODOs, the first Case Source as URL."""

    facts: TaskReplayFacts = imported.facts
    lines: list[str] = [
        "    BenchmarkSpec(",
        f'        key="{key}",',
        "        # TODO(review): title/description/focus are catalogue prose — the",
        "        # importing agent writes them from the eval's own docs; the human",
        "        # reviewer verifies them against the dataset.",
        '        title="TODO",',
        '        description="TODO",',
        '        focus="TODO",',
        f'        dataset_url="{imported.case_sources[0].location}",',
        "        # TODO(review): assign the catalogue's easy→hard tier (OME-1257) —",
        '        # "easy" | "medium" | "hard". The literal TODO is',
        "        # refused by name at registration, so an unassigned tier cannot ship.",
        '        difficulty="TODO",  # type: ignore[arg-type]',
        "        # Provenance: this scorer is declared by the Task of",
        f"        #   {facts.task_ref}.",
        f"        # License: {license}.",
    ]
    lines.extend(
        _scorer_lines(
            facts.scorer,
            facts.scorer_kwargs,
            facts.custom_metrics,
            facts.mcq,
            _is_judged_by(facts.scorer, facts.scorer_kwargs),
        )
    )
    lines.append("    ),")
    return lines


def write_task_replay_rows(
    key: str, imported: TaskReplayImport, *, engine_src: Path, license: str
) -> TaskReplayRows:
    """Insert a Task-replay import's two rows into prepare.py and benchmarks.py, in place."""

    prepare_path: Path = engine_src / "prepare.py"
    benchmarks_path: Path = engine_src / "benchmarks.py"
    texts: dict[Path, str] = {path: path.read_text() for path in (prepare_path, benchmarks_path)}
    _refuse_existing_rows(key, _pin_prefix(key), texts)
    rows: TaskReplayRows = render_task_replay_rows(key, imported, license)
    new_texts: dict[Path, str] = {
        prepare_path: _with_generated_row(texts[prepare_path], _TASK_REPLAY_CASES_ANCHOR, rows.cases, "prepare.py"),
        benchmarks_path: _with_generated_row(texts[benchmarks_path], _BENCHMARKS_ANCHOR, rows.benchmark, "benchmarks.py"),
    }
    for path, text in new_texts.items():
        _write_verified_python(path, text)
    return rows
```

Next to the three charsets (:1343), add the one Case Source locations need. URLs carry `?`,
`=`, `&` and `%` (sad's `…structs.zip?ref=dfc5c983…`); a quote, a backslash or a newline is
what could escape a comment, and those stay refused:

```python
_CASE_SOURCE_CHARSET = re.compile(r"^[A-Za-z0-9._:/\-?=&%+#~ ]*\Z")
```

In `_refuse_existing_rows`, widen the needles:
`needles = (f'"{key}": CasesSpec(', f'"{key}": TaskReplayCasesSpec(', f'key="{key}"')`.

`_python_literal_source` (:1267) renders `json.dumps(value)` for a str and `repr(value)` for
everything else, so a dict of task args would come out single-quoted and fail the emitted
file's ruff-format gate. Widen it without changing the str and scalar branches:

```python
def _python_literal_source(value: Any) -> str:
    """One kwarg or task-arg value as source text the emitted file's gates accept."""

    if isinstance(value, (dict, list)):
        # WHY json.dumps: double quotes and no trailing spaces, as ruff format writes them;
        # task args are JSON-shaped (str, int, float, bool, None, lists, dicts) by R6.
        return json.dumps(value)
    return json.dumps(value) if isinstance(value, str) else repr(value)
```

**Correction (Review Focus 6): that sketch is wrong.** The renderer passes the WHOLE
`task_args` dict, so every value, `shuffle=False` included, would go through `json.dumps`
and come out `false`/`null`; `ast.parse` accepts both as names, and `prepare.py` would raise
`NameError` on import. Render containers recursively instead, leaving the str and scalar
branches as they are (so every existing row renders byte-identical):

```python
def _python_literal_source(value: Any) -> str:
    """One kwarg or task-arg value as Python source the emitted file's gates accept."""

    if isinstance(value, dict):
        items: str = ", ".join(
            f"{json.dumps(str(name))}: {_python_literal_source(item)}" for name, item in value.items()
        )
        return f"{{{items}}}"
    if isinstance(value, (list, tuple)):
        # WHY a list for a tuple too: task args cross request.json, which has no tuple.
        return f"[{', '.join(_python_literal_source(item) for item in value)}]"
    return json.dumps(value) if isinstance(value, str) else repr(value)
```

Pinned by `test_task_args_render_as_python_that_evaluates_to_the_same_value`: render
`{"shuffle": False, "languages": ["en"], "limit": None, "nested": {"on": True}}`, `eval` the
rendered text, assert it equals the input.

**The `dataset_url` line (Review Focus 8)** comes from `_dataset_url(source)`:
`hugging-face` → `https://huggingface.co/datasets/<repo id>` (the repo id helper is shared
with Task 7's license lookup), `url` → the location, `file` → `None`; the row takes the first
browsable source, else `"TODO"` with a review note (the field is required). Pinned by `test_task_replay_benchmark_row_builds_for_a_hugging_face_source`, which
`exec`s the rendered BenchmarkSpec row against the real `BenchmarkSpec`.

**`keep_sample_metadata`** renders as `        keep_sample_metadata=True,` when the
declaration carries it (D11), before the license lines.

Import `TaskReplayImport` and `TaskReplayFacts` from `import_replay` at the top of
`importer.py` under `if TYPE_CHECKING:` only. WHY: `import_replay`'s child imports
`importer` lazily; a module-level import the other way would be a cycle at child start.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/inspect/test_inspect_importer.py tests/unit/inspect/test_task_replay.py tests/unit/inspect/test_task_replay_assembly.py -q`
Expected: all pass. The two PR 2 suites prove the `license` default and the anchor line changed
nothing for the image side.

- [ ] **Step 6: Commit**

```bash
git add src/screamingface_engine_inspect/prepare.py src/screamingface_engine_inspect/importer.py tests/unit/inspect/test_inspect_importer.py
git commit -m "feat(screamingface-engine): render a Task-replay declaration with its Case Sources"
```

### Task 7: CLI wiring and the license gate

**Files:**
- Modify: `src/screamingface_engine_inspect/importer.py` (`main` :1480–1562; `_hub_dataset_info` :936)
- Test: `tests/unit/inspect/test_inspect_importer.py` (append only)
- Test: `tests/unit/inspect/test_inspect_imported_benchmarks.py` (append only)

**Interfaces:**
- Produces: `_license_from_case_sources(sources: Sequence[CaseSource], *, dataset_info: Callable[[str, str | None], Any]) -> str`:
  when exactly one source is `hugging-face`, the card's license lowercased (or `LICENSE_TODO`
  when the card has none); otherwise `LICENSE_TODO`. The repo id is the location up to the
  first `/` after the owner (`bigbio/med_qa/main` → `bigbio/med_qa`); the revision is the pin's
  sha when the pin starts with `revision `.
- Produces: `main` takes a new keyword `import_by_task_replay: Callable[..., TaskReplayImport] = import_by_task_replay`
  for tests, next to `dataset_info=` and `count_rows=`.
- Produces: a `--task-replay` flag (D12) that skips the Hugging Face reader and imports by
  Task replay directly. Pinned by `test_the_task_replay_flag_skips_the_hugging_face_reader`
  (a task the reader would crash on still imports).
- License rule (D13): a card license outside `CLEARED_DATASET_LICENSES` comes back as
  `LICENSE_TODO`, and the card's own value travels to the TODO comment
  (`# TODO(review): the card says 'unknown', not a cleared license; the owner decides.`), so
  R7's gate still refuses it. `_license_from_case_sources` returns a small
  `CardLicense(value: str, card_says: str | None)`. Pinned by
  `test_an_uncleared_card_license_is_written_as_todo`.
- Produces: in `test_inspect_imported_benchmarks.py`, `test_task_replay_declarations_carry_an_owner_license_decision`.

- [ ] **Step 1: Write the failing tests** (append to `test_inspect_importer.py`)

```python
# ── OME-1273: the CLI takes the Task-replay path on a route (spec R1, R7) ───────


def test_main_imports_by_task_replay_when_the_reader_routes(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]
    seen: list[tuple[str, dict[str, Any] | None]] = []

    def fake_import(task_ref: str, task_args: Mapping[str, Any] | None, **_: Any) -> TaskReplayImport:
        seen.append((task_ref, dict(task_args) if task_args else None))
        return _task_replay_import()

    code: int = main(
        [f"{_FAKE_MODULE}:sums", "--key", "agieval_lsat_ar", "--task-arg", "cot=False",
         "--engine-src", str(engine_src_copy)],
        import_by_task_replay=fake_import,
    )

    assert code == 0
    assert seen == [(f"{_FAKE_MODULE}:sums", {"cot": False})]
    assert '"agieval_lsat_ar": TaskReplayCasesSpec(' in (engine_src_copy / "prepare.py").read_text()
    assert "importing by Task replay" in capsys.readouterr().err


def test_main_reports_a_task_replay_refusal_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _install_fake_eval(monkeypatch, sums=_free_text_task)
    del module.hf_dataset  # type: ignore[attr-defined]

    def refusing_import(task_ref: str, task_args: Mapping[str, Any] | None, **_: Any) -> TaskReplayImport:
        raise ImporterError(f"{task_ref}: two Task replays produced different Cases")

    code: int = main(
        [f"{_FAKE_MODULE}:sums", "--key", "x", "--engine-src", str(engine_src_copy)],
        import_by_task_replay=refusing_import,
    )

    assert code == 1
    assert "different Cases" in capsys.readouterr().err
    assert (engine_src_copy / "prepare.py").read_text() == (_SRC_DIR / "prepare.py").read_text()


def test_license_comes_from_the_card_when_the_one_source_is_hugging_face() -> None:
    def card(dataset: str, revision: str | None) -> Any:
        assert (dataset, revision) == ("bigbio/med_qa", "d" * 40)
        return types.SimpleNamespace(card_data={"license": "Apache-2.0"})

    license: str = _license_from_case_sources(
        [CaseSource("hugging-face", "bigbio/med_qa", "revision " + "d" * 40)], dataset_info=card
    )

    assert license == "apache-2.0"


def test_license_is_todo_for_a_url_source_or_several_sources() -> None:
    def never(dataset: str, revision: str | None) -> Any:
        raise AssertionError("no card to read")

    assert _license_from_case_sources([CaseSource("url", "https://x", "unpinned")], dataset_info=never) == "TODO"
    two = [CaseSource("hugging-face", "a/b", "unpinned"), CaseSource("hugging-face", "c/d", "unpinned")]
    assert _license_from_case_sources(two, dataset_info=never) == "TODO"
```

And append to `test_inspect_imported_benchmarks.py`:

```python
# ── OME-1273: Task-replay declarations (spec R7) ────────────────────────────────

from screamingface_engine_inspect.prepare import LICENSE_TODO, TASK_REPLAY_CASES  # noqa: E402


def test_task_replay_declarations_carry_an_owner_license_decision() -> None:
    """Spec R7: a license left as TODO means the owner never decided; the diff is unfinished.
    Sits next to test_benchmark_row_prose_is_filled_not_todo, which guards the catalogue prose."""

    undecided: list[str] = [key for key, spec in TASK_REPLAY_CASES.items() if spec.license == LICENSE_TODO]

    assert undecided == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_inspect_importer.py -q -k "task_replay_when or task_replay_refusal or license"`
Expected: FAIL with `TypeError: main() got an unexpected keyword argument 'import_by_task_replay'` and `ImportError` for `_license_from_case_sources`.
The imported-benchmarks test passes already (the registry is empty); it earns its keep in PR 4.

- [ ] **Step 3: Wire `main`**

Add the helper next to `_hub_dataset_info`:

```python
def _license_from_case_sources(
    sources: Sequence[CaseSource], *, dataset_info: Callable[[str, str | None], Any]
) -> str:
    """The license the importer can read: the card of the one Hugging Face Case Source, or TODO.

    WHY one source only: with several, no single card speaks for the Cases (spec R7).
    """

    hugging_face: list[CaseSource] = [source for source in sources if source.kind == HUGGING_FACE]
    if len(hugging_face) != 1:
        return LICENSE_TODO
    owner, _, rest = hugging_face[0].location.partition("/")
    repo_id: str = f"{owner}/{rest.partition('/')[0]}"
    pin: str = hugging_face[0].pin
    revision: str | None = pin.removeprefix("revision ") if pin.startswith("revision ") else None
    card: Any = getattr(dataset_info(repo_id, revision), "card_data", None) or {}
    license: Any = card.get("license") if isinstance(card, Mapping) else getattr(card, "license", None)
    return str(license).lower() if license else LICENSE_TODO
```

Imports this task adds to `importer.py`: `from collections.abc import Sequence`,
`from screamingface_engine_inspect.case_sources import HUGGING_FACE, CaseSource`, and
`LICENSE_TODO` in the existing `from screamingface_engine_inspect.prepare import (…)` block.
The test file needs `import types` and `from collections.abc import Mapping` if absent.

In `main`'s signature add `import_by_task_replay: Callable[..., TaskReplayImport] | None = None`
and resolve it lazily (`from screamingface_engine_inspect.import_replay import import_by_task_replay as default_import`)
to keep the child's import order one-directional. Then restructure the body's `try`:

```python
    try:
        try:
            facts: InspectTaskFacts = read_inspect_task(args.task_ref, _parse_task_args(args.task_arg))
        except TaskReplayRoute as route:
            # Spec R1: the Hugging Face reader could not see the fetch; Task replay can.
            print(f"NOTE: {route} — importing by Task replay", file=sys.stderr)
            imported: TaskReplayImport = (import_by_task_replay or default_import)(
                args.task_ref, _parse_task_args(args.task_arg)
            )
            license: str = _license_from_case_sources(imported.case_sources, dataset_info=dataset_info or _hub_dataset_info)
            write_task_replay_rows(args.key, imported, engine_src=args.engine_src, license=license)
            print(
                f"Task-replay rows for {args.key!r} written into {args.engine_src} — "
                f"{imported.declaration.case_count} Cases, Case Digest "
                f"{imported.declaration.case_digest[:12]}…; review the Case Sources and decide "
                "the license before merge.",
                file=sys.stderr,
            )
            return 0
        ...  # the existing Hugging Face body, unchanged
    except ImporterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
```

`_parse_task_args` runs `ast.literal_eval` on each value, so `--task-arg cot=False` arrives as
`{"cot": False}`, and `--task-arg 'languages=["en"]'` as a list.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/inspect -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/importer.py tests/unit/inspect/test_inspect_importer.py tests/unit/inspect/test_inspect_imported_benchmarks.py
git commit -m "feat(screamingface-engine): import by Task replay from the CLI and gate the license"
```

### Task 8: Spec amendments, ledger, gates, PR

**Files:**
- Modify: `docs/spec/2026-09-30-OME-1273-task-replay-import.md`
- Modify: `docs/work/2026-10-01-ome-1273-task-replay-import-side.md`
- Modify: `docs/tasks/2026-09-23-OME-1273-task-replay-import.md` (progress note only; the ticket stays open)

- [ ] **Step 0: Add `Task replay` to the glossary.** `CONTEXT.md` defines Case Source, Case
  Digest and Imported Benchmark but not the mechanism this stack is named after. Insert after
  **Case Digest**:

  ```markdown
  **Task replay**:
  Calling an eval's own task function in a child process with empty caches, so it fetches its
  Cases the way inspect would. It never calls inspect's `eval()`: no solver, scorer, model or
  Judge runs. The importer uses it when it cannot read the Case Sources off the task file, and
  Case Preparation uses it again at every image build, checking the Case Digest.
  _Avoid_: Running the eval, replaying the evaluation, replay alone
  ```

- [ ] **Step 1: Amend the spec** (each edit names its recon evidence in a one-line parenthesis):
  - Line 28: replace "an upstream bug at 0.20.0 gets in the way (bbh)" with "the importer's own
    stand-in Sample crashed the eval (bbh, personality, sciknoweval)".
  - R3's table: add the row `datasets.DownloadManager.download | loader-script builders fetching extra URLs (piqa)`.
  - R8: mark "Dropped (2026-10-01): bbeh's scorer is in its task file; livebench re-exports its
    scorer into its task file and leaves the 14 (see R13)". Keep the text for history.
  - R13's table: bbeh → "own scorer in its task file"; livebench → moved to a new line under the
    table: "livebench: out; needs its git dependency in the image and downloads nltk data inside
    its scorer (R17)"; sad → "lenient multiple choice; `seed` task arg pins its choice order";
    worldsense and chembench → "`shuffle=False` task arg"; cyberseceval_4 → "mitre_frr,
    malware_analysis, threat_intelligence only (the rest need a Judge or semgrep)".
  - R14: replace with "R14. Upstream notes. The four 'upstream bug' refusals were ours
    (three from the stand-in Sample) or a missing optional dependency (novelty_bench's torch).
    Two optional hygiene notes live in PR 5b's ledger; the owner decides whether to post them.
    bbh, personality_TRAIT and sciknoweval are re-checked under Task replay after PR 3."
  - Delivery: renumber to 1 spec · 2 image side (#1150) · 3 import side · 4 agieval, medqa, mgsm_en ·
    5a six plain packages · 5b five packages with extra wiring, plus the upstream notes.
- [ ] **Step 2: Ledger outcome**: files, commits, gate results, deviations (D1–D10 by number),
  status `done`; owner-verify note: "run the importer for agieval_lsat_ar locally before PR 4".
- [ ] **Step 3: Gates**: from the repo root, `uv run .claude/scripts/run_gates.py screamingface-engine`.
  Read the exit code, then commit.
- [ ] **Step 4: Commit and push**

```bash
git add docs/spec/2026-09-30-OME-1273-task-replay-import.md docs/work/2026-10-01-ome-1273-task-replay-import-side.md docs/tasks/2026-09-23-OME-1273-task-replay-import.md
git commit -m "docs(screamingface-engine): amend the Task-replay spec from the import-side recon"
git push upstream OME-1273-task-replay-import
```

- [ ] **Step 5: Open the draft PR** titled `feat(screamingface-engine): import Benchmarks by Task replay`,
  `Refs: OME-1273`, body per the PR ladder (TLDR → Before/After → Architecture with Data Flow,
  Trust boundaries and Failure modes → Known limitations → Review order beside the Architecture
  map). Attach the PR URL to OME-1273 (`save_issue` with `links`). Then run `sf-code-review` on
  the branch and fold confirmed findings before marking ready.

**PR 3 Known limitations to declare:** the recorder sees six primitives, nothing else (an eval
on plain `requests` is refused by name); the license is read from one Hugging Face card only;
run 2 doubles import time (a package's Cases download in minutes); `file()` reads outside the
cache and outside the package record as unpinned files; the recorder's "one fetch, one Case
Source" depth counter is shared across threads, so an eval that runs two top-level fetches
at once on two threads records only the first (a per-thread counter would instead record
every file `snapshot_download`'s worker threads fetch). R4 still refuses an eval whose only
fetch goes unseen.

---

## PR 4 — agieval, medqa, mgsm_en (branch `OME-1273-first-task-replay-benchmarks`)

Ten Benchmarks: eight agieval tasks, medqa, mgsm_en. Each follows the recipe below; Task 4.1
is written out in full for `agieval_lsat_ar` and the others repeat it with the table's values.
Expect ~45 lines of generated declaration and row plus ~70 lines of grading test per Benchmark,
so this PR lands near 1,100 lines of mostly generated code and tests; the owner accepted that
shape for PR 5 of the spec (ten Benchmarks of one family). If review wants it smaller, split
agieval off as PR 4a.

### Task 4.0: Ledger, then the catalogue contract learns the second registry

**Files:**
- Create: `docs/work/2026-10-02-ome-1273-first-task-replay-benchmarks.md`
- Modify: `tests/unit/inspect/test_inspect_imported_benchmarks.py` (**earlier tests edited:
  ask the owner for `--skip-append-only` on this commit, by name**)

Three existing tests assume every key in `BENCHMARKS` is in `BENCHMARK_CASES`:
- `test_catalogue_holds_every_imported_benchmark` (:76): change its equality to
  `set(BENCHMARK_CASES) | set(TASK_REPLAY_CASES)`.
- `_NEW_KEYS` and `_EXPECTED_FAMILIES` (:36): add the ten keys with family `"task-replay"`
  (or the family the file uses for MCQ/free-text; read the dict's values first).
- `test_cases_row_pins_benchmark_identity`, `test_cases_row_references_resolve_inside_the_pinned_eval`
  and `test_benchmark_row_prose_is_filled_not_todo` index `BENCHMARK_CASES[key]` and assert a
  `huggingface.co` dataset URL: parametrize them over `sorted(BENCHMARK_CASES)` instead of
  `_NEW_KEYS`, and append Task-replay twins that read `TASK_REPLAY_CASES[key]`, assert the
  digest is 64 lowercase hex, the `task` resolves (`_resolve`), and the prose is filled.

- [ ] Write the ledger; make the edits; run `uv run pytest tests/unit/inspect/test_inspect_imported_benchmarks.py -q`
  (fails until Task 4.1 adds a key; that is the RED); commit with the owner's skip:
  `git commit -m "test(screamingface-engine): the catalogue contract covers Task-replay declarations"`.

### Task 4.1: Import `agieval_lsat_ar` (the worked example)

**Files:**
- Modify (generated): `src/screamingface_engine_inspect/prepare.py`, `src/screamingface_engine_inspect/benchmarks.py`
- Test: `tests/unit/inspect/test_inspect_agieval_benchmarks.py` (new; one file for all eight)

- [ ] **Step 1: Run the importer** (the only step that touches the network; it runs on your machine, not in CI):

```bash
cd apps/screamingface-engine
uv run python -m screamingface_engine_inspect.importer \
  inspect_evals.agieval.agieval:agie_lsat_ar --key agieval_lsat_ar
```

Expected on stderr: `NOTE: inspect_evals.agieval.agieval has no hf_dataset binding — … — importing by Task replay`,
then `Task-replay rows for 'agieval_lsat_ar' written … 230 Cases, Case Digest …`. The Case count
is what the task yields at 0.20.0; record the real number. Open `prepare.py`: the entry's
comment lists one Case Source, `url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d9…7552/data/v1_1/lsat-ar.jsonl · pin commit 84ab72d9…`.

- [ ] **Step 2: Resolve the TODOs in the generated row** (`benchmarks.py`): title `AGIEval LSAT-AR`,
  description from the AGIEval paper's task description (analytical reasoning, N multiple-choice
  Cases, "graded by inspect's own choice scorer against the answer key, so no judge tokens are
  spent"), focus `Law-school analytical reasoning (multiple choice)`, difficulty per OME-1257's
  ladder (`hard`), and `license=` in `prepare.py`: **the owner decides** (the AGIEval repo
  carries an MIT license on its code; the owner's call is recorded in the row's `# License:`
  comment as `MIT (owner decision 2026-10-02: upstream repo license, no dataset card)`).

- [ ] **Step 3: Write the grading test** (wrapped in `no_network`; copy the shape of
  `test_inspect_gsm8k_benchmark.py`, but prepare two hand-written Cases with `_write_cases`):

```python
# tests/unit/inspect/test_inspect_agieval_benchmarks.py
# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The agieval Benchmarks: declared by Task replay, graded by inspect's choice scorer with no
network (spec R13, R17).

INVARIANT: grading reads only the prepared Cases in the image; nothing is downloaded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.envelopes import CHECK_SCHEMA  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
)

AGIEVAL_KEYS: tuple[str, ...] = (
    "agieval_lsat_ar",
    # the other seven join as their imports land
)

#: Two hand-written Cases in the shape the import child renders for an MCQ task. Case ids are
#: 1..N (the writer numbers them); the upstream `agieval_<hex>` Sample ids never reach a Case.
_PREPARED: list[PreparedCase] = [
    {
        "case": {"id": 1, "case_id": "1", "input": "Which seat is free?\n\nA) 1\nB) 2"},
        "grading_material": {"target": "B", "choices": ["1", "2"]},
    },
    {
        "case": {"id": 2, "case_id": "2", "input": "Who sits last?\n\nA) Ann\nB) Bo"},
        "grading_material": {"target": "A", "choices": ["Ann", "Bo"]},
    },
]


@pytest.mark.parametrize("key", AGIEVAL_KEYS)
def test_declaration_is_sealed_and_names_its_task(key: str) -> None:
    spec = TASK_REPLAY_CASES[key]

    assert spec.task.startswith("inspect_evals.agieval.agieval:agie_")
    assert len(spec.case_digest) == 64 and spec.case_digest == spec.case_digest.lower()
    assert spec.case_count > 0
    assert spec.license != "TODO"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", AGIEVAL_KEYS)
async def test_a_correct_letter_grades_correct_with_no_network(
    key: str, tmp_path: Path, no_network: None
) -> None:
    """Spec R17: the whole check runs with outbound network blocked."""

    benchmark = imported_benchmark(key)
    _write_cases(_PREPARED, tmp_path / benchmark.benchmark.id)
    node = _node(tmp_path)  # copy _node and _call from test_inspect_gsm8k_benchmark.py

    reply = json.loads(
        await _call(node, benchmark.check_route, encode_candidate_invocation("ANSWER: B", "stop", None), "1")
    )

    assert reply["schema"] == CHECK_SCHEMA
    assert reply["status"] == "completed"
    # then drive the case_evaluation route as the gsm8k test does and assert score 1.0 for B
    # and 0.0 for A on Case 1
```

Finish the test by copying `_node`, `_call` and the case-evaluation assertions from
`test_inspect_gsm8k_benchmark.py` (lines 81–260) and asserting a correct letter scores 1.0
and a wrong one 0.0.

- [ ] **Step 4: Run** `uv run pytest tests/unit/inspect -q` (all green, including the Task 4.0 contract tests).
- [ ] **Step 5: Commit** `feat(screamingface-engine): import agieval_lsat_ar by Task replay`.

### Task 4.2: The other nine, by the same recipe

Repeat Task 4.1 per row. Each row is one commit. Keys, task refs, args and traps:

| Benchmark key | Task reference | `--task-arg` | Scorer | Trap |
| -- | -- | -- | -- | -- |
| `agieval_lsat_lr` | `inspect_evals.agieval.agieval:agie_lsat_lr` | none | choice | — |
| `agieval_lsat_rc` | `…:agie_lsat_rc` | none | choice | long passages: check the rendered input keeps the passage |
| `agieval_sat_math` | `…:agie_sat_math` | none | choice | multiple-choice maths; not Judge-graded (only `agie_math` is) |
| `agieval_sat_en` | `…:agie_sat_en` | none | choice | — |
| `agieval_sat_en_without_passage` | `…:agie_sat_en_without_passage` | none | choice | — |
| `agieval_aqua_rat` | `…:agie_aqua_rat` | none | choice | — |
| `agieval_logiqa_en` | `…:agie_logiqa_en` | none | choice | — |
| `medqa` | `inspect_evals.medqa.medqa:medqa` | none | choice | Case Source is `hugging-face bigbio/med_qa · revision ddef95d2…`; the card says `UNKNOWN`, not a cleared license, so it comes out `license="TODO"` with the card's value in the comment (D13): **the owner decides** and replaces it |
| `mgsm_en` | `inspect_evals.mgsm.mgsm:mgsm` | `'languages=["en"]'` | `match(numeric=True)` | Case Source `url …/mgsm_en.tsv · pin sha256 …`; free-text, so the row gets `with_check_surface=True`; grading test asserts `42` matches and `41` does not |

The eight agieval rows share `test_inspect_agieval_benchmarks.py` (extend `AGIEVAL_KEYS`);
medqa and mgsm_en get `test_inspect_medqa_benchmark.py` and `test_inspect_mgsm_benchmark.py`.
`agie_math` is **not** imported: its scorer calls a model (spec R13).

### Task 4.3: Ledger outcome, gates, PR

As PR 3's Task 8: ledger outcome with the ten real Case counts and digests' first 12 hex, gates,
draft PR `feat(screamingface-engine): import agieval, medqa and mgsm by Task replay`,
`Refs: OME-1273`, Review order starting at `prepare.py`'s ten declarations (read each Case
Source line against the eval's loader), then the license decisions, then the grading tests.
Owner steps before merge: the ten license decisions in the diff. After merge: the owner
updates OME-1412's unblock table (ten rows move to "imported").

---

## PR 5a — the six plain packages (branch `OME-1273-task-replay-benchmarks-a`)

Same recipe. ~13 Benchmarks:

| Benchmark key | Task reference | `--task-arg` | Scorer | Trap |
| -- | -- | -- | -- | -- |
| `bbq` | `inspect_evals.bbq.bbq:bbq` | none (all 11 subsets; `shuffle=False` is the default) | choice | Case Source `hugging-face heegyu/bbq · revision 5d6faae5…`; license from the builder script `CC-BY-4.0` (the card may differ: owner checks) |
| `piqa` | `inspect_evals.piqa.piqa:piqa` | none | choice | three Case Sources: the Hugging Face repository at its revision plus two **unpinned** URLs from the builder (D7); the comment says the Case Digest is the only pin |
| `cybermetric_80` `_500` `_2000` `_10000` | `inspect_evals.cybermetric.cybermetric:cybermetric_<n>` | none | choice | Case Source `url …CyberMetric/205262cd…/<name>-v1.json · pin sha256 …`; has a `system_message`: check the declaration carries it |
| `worldsense` | `inspect_evals.worldsense.worldsense:worldsense` | `shuffle=False` (D6) | `pattern_with_metadata` (task file) | needs the `worldsense` extra's pandas (installed); scorer is custom: the grading test asserts the pattern on a hand Case |
| `sad_facts_llms` `sad_facts_human_defaults` `sad_influence` `sad_stages_full` `sad_stages_oversight` | `inspect_evals.sad.sad:sad_<name>` | `seed=42` (D6: fixes the choice order, which changes the answer letters) | `lenient_mcq_choice` (`sad/scorer.py`, re-exported) | Case Source `url api.github.com/…structs.zip?ref=dfc5c983… · pin sha256 …`; the stages tasks also randomise the prompt per Sample from `seed`, so the digest check proves the seed took |
| `sevenllm_mcq_zh` `sevenllm_mcq_en` | `inspect_evals.sevenllm.sevenllm:sevenllm_mcq_<lang>` | none | choice | Case Source `url huggingface.co/datasets/…/raw/1de23ce5…/test.jsonl · pin commit 1de23ce5…`; the QA tasks stay out (torch model at grade time) |

## PR 5b — the packages with extra wiring (branch `OME-1273-task-replay-benchmarks-b`)

| Benchmark key | Task reference | `--task-arg` | Scorer | Trap |
| -- | -- | -- | -- | -- |
| `bbeh` `bbeh_mini` | `inspect_evals.bbeh.bbeh:bbeh`, `:bbeh_mini` | none (`bbeh_mini` seeds its shuffle with 42 by default) | `bbeh_scorer` (task file) | Case Source `hugging-face BBEH/bbeh · revision 08e07a80…`; `bbeh` with no `benchmark_task` loads every subtask: check the count and consider one Benchmark per subtask later |
| `cyberseceval_4_mitre_frr` | `inspect_evals.cyberseceval_4.mitre_frr.task:cyse4_mitre_frr` | none | regex refusal (`scorers.py`, re-exported) | Case Source `url …PurpleLlama/fe05293b…/… · pin sha256 …` |
| `cyberseceval_4_malware_analysis` | `…malware_analysis:cyse4_malware_analysis` | none | `choice_with_jaccard` | the CrowdStrike archive zip with sha256 |
| `cyberseceval_4_threat_intelligence` | `…threat_intelligence:cyse4_threat_intelligence` | `modality="text"` | `choice_with_jaccard` | fetches report PDFs with sha256 at Case Preparation; grading reads none |
| `pre_flight` | `inspect_evals.pre_flight.pre_flight:pre_flight` | none | choice | default `FieldSpec`, so ids come from the Hugging Face columns: check they are unique (R4 refuses duplicates) |
| `chembench` | `inspect_evals.chembench.chembench:chembench` | `shuffle=False` (D6) | `chembench_scorer` (task file; `pattern` or `pattern_mae`) | nine Case Sources, one per subset, all `revision a8f7e226…`; `pattern_mae` needs a numeric target: grading test covers both branches |

PR 5b's ledger also carries the **upstream notes** (D9): bbh's `create_stable_id` ids silently
overwritten by `auto_id=True` (`bbh/bbh.py:333–374` vs `:121`), and novelty_bench importing
torch while the Task is built (`novelty_bench/novelty_bench.py:88`) rather than in its scorer.
The owner decides whether to post either.

## Not imported in this stack, with the named reason

| Package | Reason (one line, from the recon) |
| -- | -- |
| livebench | D5: git dependency not in the image; nltk download inside the scorer (R17) |
| sevenllm QA tasks | SentenceTransformer model download at scorer build (R17) |
| cyberseceval_4 mitre, multiturn_phishing, multilingual_prompt_injection | need Judge or victim models (Judge tickets) |
| cyberseceval_4 instruct, autocomplete | run `semgrep` as a subprocess at grade time |
| agieval `agie_math` | its scorer calls a model |
| bbh, personality_TRAIT, sciknoweval | not upstream bugs (D9): re-check under Task replay after PR 3; personality and sciknoweval may be Judge-graded |
| novelty_bench | torch at task build; `isolated: true` upstream |

## Owner actions, in order

1. Flip any of D1–D10 before PR 3 starts (reply to this plan).
2. PR 3: review; grant `--skip-append-only` for PR 4's Task 4.0 commit when asked.
3. PR 4: ten license decisions in the diff; run the three importer commands locally if you
   prefer the fetches on your machine (they are not paid; they download datasets).
4. PR 5a and 5b: thirteen plus seven license decisions; decide on the two upstream notes.
5. After each merge: update OME-1412's unblock table, and set OME-1273 Done after PR 5b with
   the close template.
