# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Task replay: the eval's own task function runs in a child process and yields prepared
Cases (spec R2, R9, R10).

INVARIANT: the child always starts with empty caches and reports through a file, never
stdout, so what it returns is what a fresh fetch produces and nothing an eval prints can
corrupt it. INVARIANT: Cases whose count or Case Digest differ from the pinned values are
never written; the Benchmark goes SKIPPED with the reason instead.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.deployment import UNCONFIRMED_CASES_KEY  # noqa: E402
from screamingface_engine_inspect.case_set import case_set_digest  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV,
    SKIPPED_MARKER,
    PrepareError,
    TaskReplayCasesSpec,
    case_digest,
)
from screamingface_engine_inspect.task_replay import (  # noqa: E402
    TaskReplayError,
    prepare_replayed_cases,
    replay_environment,
    replayed_cases,
)

#: A stand-in eval: its task functions build Samples the way an inspect_evals loader would.
FAKE_EVAL: str = textwrap.dedent(
    """
    import time
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample

    @task
    def arithmetic(extra: bool = False) -> Task:
        print("downloading from https://example.invalid/cases.jsonl")  # Review Focus 1
        samples = [Sample(input="What is 6 times 7?", target="42"),
                   Sample(input="What is 2 plus 2?", target="4")]
        if extra:
            samples.append(Sample(input="What is 1 plus 1?", target="2"))
        return Task(dataset=MemoryDataset(samples))

    @task
    def broken() -> Task:
        raise RuntimeError("upstream URL returned 404")

    @task
    def cache_probe() -> Task:
        # Report, as Case inputs, where each library would cache a fetch in this process.
        import datasets.config
        import huggingface_hub.constants
        from inspect_ai._util.appdirs import inspect_cache_dir
        from inspect_evals.constants import INSPECT_EVALS_CACHE_PATH
        paths = {
            "datasets": datasets.config.HF_DATASETS_CACHE,
            "hub": huggingface_hub.constants.HF_HUB_CACHE,
            "modules": datasets.config.HF_MODULES_CACHE,
            "inspect_evals": INSPECT_EVALS_CACHE_PATH,
            "inspect_ai": inspect_cache_dir("hf_datasets"),
        }
        return Task(dataset=MemoryDataset(
            [Sample(id=name, input=f"{name}={path}", target="x") for name, path in paths.items()]
        ))

    @task
    def stalled() -> Task:
        time.sleep(30)
        return Task(dataset=MemoryDataset([]))
    """
)

_UNPINNED: str = "0" * 64


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the child process can import it."""

    (tmp_path / "fake_replay_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_replay_eval"


def _pinned(fake_eval: str) -> TaskReplayCasesSpec:
    """A declaration whose count and digest are what the stand-in task really produces."""

    probe: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic", case_count=2, case_digest=_UNPINNED
    )
    return TaskReplayCasesSpec(
        task=probe.task, case_count=2, case_digest=case_digest(replayed_cases(probe))
    )


# ── the replay itself (Task 2) ───────────────────────────────────────────────


def test_replay_returns_the_cases_the_task_builds(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:arithmetic", case_count=2, case_digest=_UNPINNED)

    prepared = replayed_cases(spec)

    assert [item["case"]["input"] for item in prepared] == [
        "What is 6 times 7?",
        "What is 2 plus 2?",
    ]
    assert [item["grading_material"] for item in prepared] == [{"target": "42"}, {"target": "4"}]


def test_replay_passes_task_args_and_is_deterministic(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic",
        task_args={"extra": True},
        case_count=3,
        case_digest=_UNPINNED,
    )

    first = replayed_cases(spec)

    assert len(first) == 3
    assert case_digest(first) == case_digest(replayed_cases(spec))


def test_a_task_that_raises_is_a_named_replay_failure(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest=_UNPINNED)

    with pytest.raises(TaskReplayError, match="upstream URL returned 404"):
        replayed_cases(spec)


def test_a_stalled_fetch_ends_after_the_timeout(fake_eval: str) -> None:
    """Review Focus 2: a hung download must never hang the image build."""

    spec = TaskReplayCasesSpec(task=f"{fake_eval}:stalled", case_count=0, case_digest=_UNPINNED)

    with pytest.raises(TaskReplayError, match="timed out"):
        replayed_cases(spec, timeout=2)


def test_the_child_always_gets_its_own_empty_caches(tmp_path: Path) -> None:
    """Review Focus 4: a builder's stale cache must not hide a dead URL."""

    base = {
        "INSPECT_EVALS_CACHE_DIR": "/home/dev/.cache/inspect_evals",
        "HF_TOKEN": "hf_x",
        "PATH": "/bin",
    }

    env = replay_environment(tmp_path, base)

    assert env["INSPECT_EVALS_CACHE_DIR"] == str(tmp_path / "inspect_evals")
    assert env["HF_DATASETS_CACHE"] == str(tmp_path / "hf_datasets")
    assert env["HF_HUB_CACHE"] == str(tmp_path / "hf_hub")
    # WHY HF_TOKEN survives: gated datasets still need it; only caches are replaced.
    assert env["HF_TOKEN"] == "hf_x"
    assert env["PATH"] == "/bin"


# ── Case Preparation with the Case Digest check (Task 3) ─────────────────────


def test_matching_digest_writes_the_cases(fake_eval: str, tmp_path: Path) -> None:
    spec = _pinned(fake_eval)
    out = tmp_path / "out"

    summary = prepare_replayed_cases(spec, out)

    assert summary["cases"] == 2
    assert summary["case_digest"] == spec.case_digest
    assert (out / "cases.json").is_file()
    assert not (out / SKIPPED_MARKER).exists()


def test_a_changed_digest_serves_nothing_and_names_the_reason(
    fake_eval: str, tmp_path: Path
) -> None:
    """Spec R10: different Cases are never served; the marker says why."""

    pinned = _pinned(fake_eval)
    spec = TaskReplayCasesSpec(task=pinned.task, case_count=2, case_digest="f" * 64)
    out = tmp_path / "out"

    summary = prepare_replayed_cases(spec, out)

    reason = (out / SKIPPED_MARKER).read_text(encoding="utf-8")
    assert not (out / "cases.json").exists()
    assert "f" * 64 in reason
    assert pinned.case_digest in reason
    assert summary["cases"] == 0
    assert summary[UNCONFIRMED_CASES_KEY] == reason.strip()


def test_a_changed_case_count_serves_nothing(fake_eval: str, tmp_path: Path) -> None:
    pinned = _pinned(fake_eval)
    spec = TaskReplayCasesSpec(
        task=pinned.task,
        task_args={"extra": True},
        case_count=2,
        case_digest=pinned.case_digest,
    )

    summary = prepare_replayed_cases(spec, tmp_path / "out")

    assert "3 Cases, pinned case count is 2" in summary[UNCONFIRMED_CASES_KEY]
    assert not (tmp_path / "out" / "cases.json").exists()


def test_a_failed_fetch_serves_nothing(fake_eval: str, tmp_path: Path) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest=_UNPINNED)

    summary = prepare_replayed_cases(spec, tmp_path / "out")

    assert "upstream URL returned 404" in summary[UNCONFIRMED_CASES_KEY]
    assert not (tmp_path / "out" / "cases.json").exists()


# ── review follow-ups: real-child caches, one-line reasons, disk matches the seal ─


def test_the_real_child_caches_nothing_where_the_builder_caches(
    fake_eval: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 4, probed in a real child: a builder's configured caches are never read.

    WHY a probe and not an env assertion: a cache the redirect forgot is invisible to a test
    that only checks the variables it sets.
    """

    builder: Path = tmp_path / "builder-cache"
    for variable in ("XDG_CACHE_HOME", "HF_DATASETS_CACHE", "HF_HUB_CACHE", "HF_MODULES_CACHE"):
        monkeypatch.setenv(variable, str(builder / variable.lower()))
    monkeypatch.setenv("INSPECT_EVALS_CACHE_DIR", str(builder / "inspect_evals"))
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:cache_probe", case_count=5, case_digest=_UNPINNED)

    reported: dict[str, str] = dict(
        item["case"]["input"].split("=", 1) for item in replayed_cases(spec)
    )

    checked: set[str] = {"datasets", "hub", "modules", "inspect_evals"}
    if sys.platform == "linux":
        # AIDEV-NOTE: platformdirs honours XDG_CACHE_HOME on Linux only (image builds).
        checked.add("inspect_ai")
    for library in checked:
        assert str(builder) not in reported[library], library
        assert "task-replay-" in reported[library], library


def test_a_skipped_reason_is_one_line_naming_the_cause(fake_eval: str, tmp_path: Path) -> None:
    """The reason reaches callers at run time: it names the error, never builder paths."""

    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest=_UNPINNED)

    summary = prepare_replayed_cases(spec, tmp_path / "out")

    reason: str = summary[UNCONFIRMED_CASES_KEY]
    assert reason.endswith("RuntimeError: upstream URL returned 404")
    assert "\n" not in reason
    assert "Traceback" not in reason
    assert 'File "' not in reason


def test_the_files_written_are_the_cases_the_digest_checked(fake_eval: str, tmp_path: Path) -> None:
    """Spec R5: what lands on disk re-seals to the pinned Case Digest, order included."""

    spec = _pinned(fake_eval)
    out = tmp_path / "out"

    prepare_replayed_cases(spec, out)

    cases: list[dict[str, object]] = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    on_disk = [
        {
            "case": case,
            "grading_material": json.loads(
                (out / "targets" / f"{case['id']}.json").read_text(encoding="utf-8")
            ),
        }
        for case in cases
    ]
    assert case_digest(on_disk) == spec.case_digest


# ── review follow-ups: odd bytes and broken files never crash the image build ─

#: Stand-in tasks with an odd edge: healthy Cases, but noisy bytes or a broken result file.
ODD_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from fake_replay_eval import arithmetic

    @task
    def latin1_noise() -> Task:
        # A healthy loader that logs one Latin-1 byte, which is not valid UTF-8.
        import sys
        sys.stderr.buffer.write(b"caf\\xe9 loaded\\n")
        sys.stderr.buffer.flush()
        return arithmetic()

    @task
    def truncated_result() -> Task:
        # Exits 0 but leaves a cut-off result file, as a killed write would.
        import atexit
        import sys
        result_path = sys.argv[2]
        atexit.register(lambda: open(result_path, "w").write('[{"case":'))
        return arithmetic()
    """
)


@pytest.fixture
def odd_eval(fake_eval: str, tmp_path: Path) -> str:
    """Write the odd stand-in tasks beside the stand-in eval (same import path)."""

    (tmp_path / "fake_odd_eval.py").write_text(ODD_EVAL, encoding="utf-8")
    return "fake_odd_eval"


def test_a_non_utf8_byte_on_stderr_still_prepares_the_cases(
    fake_eval: str, odd_eval: str, tmp_path: Path
) -> None:
    """Spec R10: a loader that logs one Latin-1 byte must not crash the image build.

    WHY: the child's output is only read for the log and the one-line reason, so a byte that
    is not UTF-8 is replaced; decoding strictly raised UnicodeDecodeError, which no caller
    catches, and every other Benchmark in the image was lost with it.
    """

    pinned = _pinned(fake_eval)
    spec = TaskReplayCasesSpec(
        task=f"{odd_eval}:latin1_noise", case_count=2, case_digest=pinned.case_digest
    )

    summary = prepare_replayed_cases(spec, tmp_path / "out")

    assert summary["cases"] == 2
    assert (tmp_path / "out" / "cases.json").is_file()


def test_a_truncated_result_file_is_a_named_skip_not_a_crash(odd_eval: str, tmp_path: Path) -> None:
    """Spec R10: a child that exits 0 with a cut-off result.json skips only its Benchmark."""

    spec = TaskReplayCasesSpec(
        task=f"{odd_eval}:truncated_result", case_count=2, case_digest=_UNPINNED
    )

    summary = prepare_replayed_cases(spec, tmp_path / "out")

    assert "unreadable result" in summary[UNCONFIRMED_CASES_KEY]
    assert (tmp_path / "out" / SKIPPED_MARKER).is_file()
    assert not (tmp_path / "out" / "cases.json").exists()


def test_a_skipped_reason_names_the_benchmark_first(fake_eval: str, tmp_path: Path) -> None:
    """Spec R10: the reason a board visitor sees starts with the Benchmark's key, not the
    inspect task path."""

    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest=_UNPINNED)

    summary = prepare_replayed_cases(spec, tmp_path / "out", benchmark_key="arithmetic_demo")

    assert summary[UNCONFIRMED_CASES_KEY].startswith("arithmetic_demo: ")


# ── OME-1460: gated datasets on Task replay (spec R8, F7) ─────────────────────────────────


def _gated(fake_eval: str) -> TaskReplayCasesSpec:
    """A declaration of a gated Benchmark; the stand-in task itself fetches nothing gated."""

    return TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic",
        case_count=2,
        case_digest=_UNPINNED,
        # A stand-in commit: the gate check runs before any fetch, so no Hub is asked.
        source_pins={"walledai/XSTest": "1" * 40},
        needs_hf_token=True,
    )


def test_a_gated_declaration_with_no_token_is_refused_by_name(
    fake_eval: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A main or release image can never ship missing a gated Benchmark: no token, no flag
    → the build stops, naming the dataset."""

    monkeypatch.setattr("screamingface_engine_inspect.prepare._available_hf_token", lambda: None)
    monkeypatch.delenv(SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV, raising=False)

    with pytest.raises(PrepareError, match="walledai/XSTest.*gated"):
        prepare_replayed_cases(_gated(fake_eval), tmp_path / "out")


def test_a_gated_declaration_skips_under_the_flag_without_unconfirmed_cases(
    fake_eval: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F7: a PR build gets no secret; the skip is loud in the log but carries no
    unconfirmed_cases key, so the strict PR image job stays green."""

    monkeypatch.setattr("screamingface_engine_inspect.prepare._available_hf_token", lambda: None)
    monkeypatch.setenv(SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV, "1")
    out: Path = tmp_path / "out"

    summary: dict[str, object] = prepare_replayed_cases(_gated(fake_eval), out)

    assert summary["cases"] == 0
    assert "gated dataset walledai/XSTest" in str(summary["skipped"])
    assert UNCONFIRMED_CASES_KEY not in summary
    assert (out / SKIPPED_MARKER).read_text(encoding="utf-8").startswith("gated dataset")
    assert not (out / "cases.json").exists()


def test_a_gated_declaration_with_a_token_replays(
    fake_eval: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "screamingface_engine_inspect.prepare._available_hf_token", lambda: "hf_stand_in"
    )
    pinned: TaskReplayCasesSpec = _pinned(fake_eval)
    gated: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=pinned.task, case_count=2, case_digest=pinned.case_digest, needs_hf_token=True
    )

    summary: dict[str, object] = prepare_replayed_cases(gated, tmp_path / "out")

    assert summary["cases"] == 2


# ── OME-1460: the image-side child enforces the declaration's fetch pins (spec R4, F1, F6) ──

#: Two commits of the stand-in Hub repo. HEAD is `_HEAD_SHA`; `_OLD_SHA` holds other rows,
#: so a Case's text says which commit was read.
_HEAD_SHA: str = "a" * 40
_OLD_SHA: str = "b" * 40

#: A stand-in eval whose dataset comes from a fake Hub: at import it replaces
#: datasets.load_dataset (the recorder installs later and wraps the fake, as it would wrap
#: the real one). It proves which commit and which shuffle seed the child's fetch used; it
#: does not prove the real Hub serves a given commit.
FAKE_HUB_EVAL: str = textwrap.dedent(
    f"""
    import datasets
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, hf_dataset
    from inspect_ai.scorer import match

    HEAD = "{_HEAD_SHA}"
    OLD = "{_OLD_SHA}"
    FIELDS = FieldSpec(input="q", target="a", id="id")

    def fake_load_dataset(path, name=None, data_dir=None, split=None, revision=None, **kwargs):
        commit = HEAD if revision in (None, "main") else revision
        if commit not in (HEAD, OLD):
            raise FileNotFoundError(f"no commit {{revision}} in {{path}}")
        label = "head" if commit == HEAD else "old"
        return datasets.Dataset.from_list(
            [{{"id": str(i), "q": f"{{label}} question {{i}}", "a": str(i)}} for i in range(1, 5)]
        )

    datasets.load_dataset = fake_load_dataset

    @task
    def unpinned_fetch() -> Task:
        # fetches with no revision: HEAD's rows, unless the enforcer pins another commit
        return Task(dataset=hf_dataset("stand-in/hub", split="test", sample_fields=FIELDS),
                    scorer=match())

    @task
    def unseeded_shuffle() -> Task:
        return Task(dataset=hf_dataset("stand-in/hub", split="test", sample_fields=FIELDS,
                                       revision=HEAD, shuffle=True),
                    scorer=match())
    """
)


@pytest.fixture
def fake_hub_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the fake-Hub stand-in eval where the child process can import it."""

    (tmp_path / "fake_hub_eval.py").write_text(FAKE_HUB_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_hub_eval"


def _inputs(prepared: list[dict[str, dict[str, object]]]) -> list[str]:
    """The Case inputs, in served order."""

    return [str(case["case"]["input"]) for case in prepared]


def test_the_image_side_child_fetches_at_the_pinned_commit(fake_hub_eval: str) -> None:
    """F3: the eval names no revision, yet every build reads the declared commit, not HEAD."""

    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_hub_eval}:unpinned_fetch",
        case_count=4,
        case_digest=_UNPINNED,
        source_pins={"stand-in/hub": _OLD_SHA},
    )

    inputs: list[str] = _inputs(replayed_cases(spec))

    assert inputs and all(text.startswith("old question") for text in inputs)


def test_a_hub_fetch_with_no_pin_is_skipped_at_build_with_the_f1_reason(
    fake_hub_eval: str, tmp_path: Path
) -> None:
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_hub_eval}:unpinned_fetch", case_count=4, case_digest=_UNPINNED
    )

    summary: dict[str, object] = prepare_replayed_cases(spec, tmp_path / "out")

    assert summary["cases"] == 0
    assert "stand-in/hub" in str(summary[UNCONFIRMED_CASES_KEY])
    assert "pins no revision" in str(summary[UNCONFIRMED_CASES_KEY])


def test_the_image_side_child_forces_the_declared_shuffle_seed(fake_hub_eval: str) -> None:
    """R3: an unseeded upstream shuffle replays in one order at every build."""

    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_hub_eval}:unseeded_shuffle",
        case_count=4,
        case_digest=_UNPINNED,
        source_pins={"stand-in/hub": _HEAD_SHA},
        shuffle_seed=7,
    )

    first: list[dict[str, dict[str, object]]] = replayed_cases(spec)
    second: list[dict[str, dict[str, object]]] = replayed_cases(spec)

    assert case_digest(first) == case_digest(second)
    assert sorted(_inputs(first)) == [f"head question {index}" for index in range(1, 5)]


def test_an_unseeded_shuffle_with_no_declared_seed_is_skipped_at_build(
    fake_hub_eval: str, tmp_path: Path
) -> None:
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_hub_eval}:unseeded_shuffle",
        case_count=4,
        case_digest=_UNPINNED,
        source_pins={"stand-in/hub": _HEAD_SHA},
    )

    summary: dict[str, object] = prepare_replayed_cases(spec, tmp_path / "out")

    assert "shuffle_seed" in str(summary[UNCONFIRMED_CASES_KEY])


# ── OME-1460: a cached Hugging Face login reaches the replay child (spec R8) ──────────────


def test_the_child_keeps_the_builders_token_path_when_xdg_moves(tmp_path: Path) -> None:
    """huggingface_hub reads its login from HF_HOME/token, and HF_HOME defaults to
    XDG_CACHE_HOME/huggingface; the replay moves XDG_CACHE_HOME, so without this the child
    looks for the token in its own empty cache and a gated dataset fails to load."""

    env: dict[str, str] = replay_environment(
        tmp_path / "cache", {"XDG_CACHE_HOME": "/builder/cache", "HOME": "/home/builder"}
    )

    assert env["HF_TOKEN_PATH"] == "/builder/cache/huggingface/token"
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "cache" / "xdg")


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ({"HOME": "/home/builder"}, "/home/builder/.cache/huggingface/token"),
        ({"HF_HOME": "/hf", "XDG_CACHE_HOME": "/x"}, "/hf/token"),
        ({"HF_TOKEN_PATH": "/secrets/hf", "HF_HOME": "/hf"}, "/secrets/hf"),
    ],
    ids=["home default", "HF_HOME wins over XDG", "an explicit token path is kept"],
)
def test_the_token_path_follows_huggingface_hubs_own_rule(
    tmp_path: Path, base: dict[str, str], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY HOME: the home default expands "~", which reads HOME on every platform here.
    monkeypatch.setenv("HOME", base.get("HOME", "/home/builder"))

    assert replay_environment(tmp_path / "cache", base)["HF_TOKEN_PATH"] == expected


#: A stand-in eval reporting, as its one Case, the token the child would send to the Hub.
#: It proves the child can read a cached login; the token is a stand-in, never a real one.
FAKE_TOKEN_EVAL: str = textwrap.dedent(
    """
    from huggingface_hub import get_token
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample

    @task
    def token_probe() -> Task:
        return Task(dataset=MemoryDataset([Sample(input=f"token={get_token()}", target="x")]))
    """
)


def test_a_cached_login_reaches_the_replay_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dev who ran `hf auth login` (no HF_TOKEN exported) can replay a gated dataset."""

    (tmp_path / "fake_token_eval.py").write_text(FAKE_TOKEN_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    builder_cache: Path = tmp_path / "builder-cache"
    (builder_cache / "huggingface").mkdir(parents=True)
    (builder_cache / "huggingface" / "token").write_text("hf_stand_in_login", encoding="utf-8")
    monkeypatch.setenv("XDG_CACHE_HOME", str(builder_cache))
    for variable in ("HF_HOME", "HF_TOKEN", "HF_TOKEN_PATH", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task="fake_token_eval:token_probe", case_count=1, case_digest=_UNPINNED
    )

    prepared: list[dict[str, dict[str, object]]] = replayed_cases(spec)

    assert prepared[0]["case"]["input"] == "token=hf_stand_in_login"


# ── OME-1492: every prepared bundle says where its Cases came from ─────────────────────────

#: The provenance file Case Preparation writes beside cases.json.
_PROVENANCE: str = "provenance.json"


def _block(out: Path) -> dict[str, Any]:
    """The provenance block a prepared bundle carries on disk."""

    return json.loads((out / _PROVENANCE).read_text(encoding="utf-8"))


def test_a_prepared_bundle_records_where_its_cases_came_from(
    fake_eval: str, tmp_path: Path
) -> None:
    """The child's facts land in the bundle AND the summary line, so a cache hit (no summary
    printed) and a red build (no bundle served) can each still say where the Cases came from."""

    out: Path = tmp_path / "out"

    summary: dict[str, object] = prepare_replayed_cases(_pinned(fake_eval), out)

    block: dict[str, Any] = _block(out)
    assert block["samples"] == {"yielded": 2, "excluded": 0, "kept": 2}
    assert set(block["pins"]) == {"inspect-ai", "inspect-evals"}
    assert isinstance(block["seconds"], float) and block["seconds"] > 0
    assert block["seeds_applied"] == {}
    assert summary["provenance"] == block


def test_the_block_names_the_pinned_commit_and_the_forced_seed(
    fake_hub_eval: str, tmp_path: Path
) -> None:
    """The seed's VALUE travels, not only its name: two builds forced to different seeds
    must read differently in the log."""

    probe: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_hub_eval}:unseeded_shuffle",
        case_count=4,
        case_digest=_UNPINNED,
        source_pins={"stand-in/hub": _HEAD_SHA},
        shuffle_seed=7,
    )
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        **{**probe.__dict__, "case_digest": case_digest(replayed_cases(probe))}
    )
    out: Path = tmp_path / "out"

    prepare_replayed_cases(spec, out)

    block: dict[str, Any] = _block(out)
    assert block["seeds_applied"] == {"shuffle_seed": 7}
    sources: list[dict[str, str]] = block["sources"]
    assert any(_HEAD_SHA in source["pin"] for source in sources)
    assert all(source["location"].startswith("stand-in/hub") for source in sources)


def test_excluded_samples_are_counted(fake_hub_eval: str, tmp_path: Path) -> None:
    """A declaration that drops Samples (sad_stages_full 800 → 797) shows both counts, so
    an upstream row change reads as a count change, not only as a digest change."""

    probe: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_hub_eval}:unpinned_fetch",
        case_count=3,
        case_digest=_UNPINNED,
        source_pins={"stand-in/hub": _HEAD_SHA},
        excluded_sample_ids=("2",),
    )
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        **{**probe.__dict__, "case_digest": case_digest(replayed_cases(probe))}
    )
    out: Path = tmp_path / "out"

    prepare_replayed_cases(spec, out)

    assert _block(out)["samples"] == {"yielded": 4, "excluded": 1, "kept": 3}


def test_a_mismatch_skip_still_carries_the_block(fake_eval: str, tmp_path: Path) -> None:
    """A sealed mismatch is exactly when on-call needs the commit and the seed."""

    pinned: TaskReplayCasesSpec = _pinned(fake_eval)
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=pinned.task, case_count=2, case_digest="f" * 64
    )
    out: Path = tmp_path / "out"

    summary: dict[str, object] = prepare_replayed_cases(spec, out)

    assert summary[UNCONFIRMED_CASES_KEY]
    assert (out / SKIPPED_MARKER).is_file()
    assert not (out / "cases.json").exists()
    assert summary["provenance"] == _block(out)


def test_no_case_text_reaches_the_block_or_the_summary_line(fake_eval: str, tmp_path: Path) -> None:
    """INVARIANT: the Actions log is public and some datasets are gated or non-commercial, so
    the block carries commits, seeds, counts and versions, never a Case's input or target."""

    out: Path = tmp_path / "out"

    summary: dict[str, object] = prepare_replayed_cases(_pinned(fake_eval), out)

    printed: str = json.dumps(summary) + (out / _PROVENANCE).read_text(encoding="utf-8")
    for text in ("What is 6 times 7?", "What is 2 plus 2?", '"42"', '"4"'):
        assert text not in printed


# ── OME-1492 PR 2: a broken seal says whether only the order moved ────────────────────────


def test_a_reordered_replay_reads_as_order_only(fake_hub_eval: str, tmp_path: Path) -> None:
    """The seal holds seed 7's order; a build forced to seed 8 replays the same 4 Cases in
    another order, so on-call reads "order only" instead of an opaque digest pair."""

    sealed_spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_hub_eval}:unseeded_shuffle",
        case_count=4,
        case_digest=_UNPINNED,
        source_pins={"stand-in/hub": _HEAD_SHA},
        shuffle_seed=7,
    )
    sealed: list[dict[str, dict[str, object]]] = replayed_cases(sealed_spec)
    reshuffled: TaskReplayCasesSpec = TaskReplayCasesSpec(
        **{
            **sealed_spec.__dict__,
            "case_digest": case_digest(sealed),
            "case_set_digest": case_set_digest(sealed),
            "shuffle_seed": 8,
        }
    )

    summary: dict[str, object] = prepare_replayed_cases(reshuffled, tmp_path / "out")

    assert str(summary[UNCONFIRMED_CASES_KEY]).endswith("— same 4 Cases in another order")


def test_rewritten_text_reads_as_text_changed(fake_eval: str, tmp_path: Path) -> None:
    """A sealed case-set digest that no longer matches stands in for a template that rewrote
    a Case; it simulates the comparison, not a real template change."""

    pinned: TaskReplayCasesSpec = _pinned(fake_eval)
    resealed: TaskReplayCasesSpec = TaskReplayCasesSpec(
        **{**pinned.__dict__, "case_digest": "f" * 64, "case_set_digest": "e" * 64}
    )

    summary: dict[str, object] = prepare_replayed_cases(resealed, tmp_path / "out")

    reason: str = str(summary[UNCONFIRMED_CASES_KEY])
    assert reason.endswith("— same count, different Cases: text changed")
    for text in ("What is", "42"):
        assert text not in reason


def test_a_row_without_a_case_set_digest_keeps_todays_reason(
    fake_eval: str, tmp_path: Path
) -> None:
    pinned: TaskReplayCasesSpec = _pinned(fake_eval)
    resealed: TaskReplayCasesSpec = TaskReplayCasesSpec(
        **{**pinned.__dict__, "case_digest": "f" * 64}
    )

    summary: dict[str, object] = prepare_replayed_cases(resealed, tmp_path / "out")

    assert str(summary[UNCONFIRMED_CASES_KEY]).endswith(f"does not match the pinned {'f' * 64}")
