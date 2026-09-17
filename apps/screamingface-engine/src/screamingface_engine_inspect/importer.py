# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The pin generator — turn one inspect eval into this plugin's three row diffs.

Think of it as a customs officer for imported exams: the eval declares what it is
(the importer READS the task — never re-types it), the officer stamps what it
observed (revision sha, row count, license — facts no eval file carries), and the
paperwork lands as an in-place edit to pins.py / prepare.py / boards.py so that
``git diff`` IS the review artifact. Import time is the ONLY trust window (see
pins.py's lockfile docstring), so a human reviews that diff before anything merges.

Stages, in execution order (``main``):

    Stage 1 — introspect: import the eval's task module, replace its ``hf_dataset``
              binding with a recorder that returns a stub dataset, call the task
              function, and read the recorded kwargs (dataset path/config/split,
              ``record_to_sample``, an upstream revision pin if the eval has one)
              plus the Task's solver/scorer registry metadata. No network.
    Stage 2 — capture: the observations the eval cannot provide — resolve the HF
              revision sha (upstream pin wins when present), count the rows at that
              sha, read the dataset license. Network, build-side only.
    Stage 3 — emit: render the three row fragments and insert each at its file's
              anchor comment. An unlisted license WARNS but still emits (owner
              decision 2026-09-16): the human review of the diff is the gate.

Run from ``apps/screamingface-engine``::

    uv run python -m screamingface_engine_inspect.importer \
        inspect_evals.gsm8k.gsm8k:gsm8k --key gsm8k --task-arg fewshot=0

STORY: onboarding is AI-first — an agent runs the command, writes the catalogue
prose, and resolves every TODO(review); the human's whole job is verifying the
resulting diff. Nobody transcribes values or writes wiring code.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _datetime
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

#: Dataset licenses cleared for the public catalogue. An unlisted license still
#: emits rows, with a WARNING — the generated pins comment carries the license so
#: the diff reviewer sees it.
CLEARED_DATASET_LICENSES: frozenset[str] = frozenset(
    {"mit", "apache-2.0", "cc0-1.0", "cc-by-4.0", "cc-by-sa-4.0", "odc-by"}
)

#: Solvers whose render the bake reproduces outright (prepare.py's templated/MCQ/raw
#: prompt paths). Anything else — including prompt settings the bake would silently
#: drop, like system instructions or a custom choice template — earns a review flag
#: in the facts rather than a guess (review finding on PR 965).
_FULLY_BAKED_SOLVERS: frozenset[str] = frozenset({"prompt_template", "generate", "multiple_choice"})

# The insertion contract: each generated fragment lands immediately ABOVE its
# file's anchor comment. The anchors live in the three files themselves.
_PINS_ANCHOR = "# --- importer: generated pin rows land above this line ---"
_SNAPSHOTS_ANCHOR = "# --- importer: generated SnapshotSpec rows land above this line ---"
_BOARDS_ANCHOR = "# --- importer: generated BoardSpec rows land above this line ---"

_PINS_IMPORT_HEADER = "from screamingface_engine_inspect.pins import ("


class ImporterError(Exception):
    """The importer refuses to emit. Always says which fact stopped it."""


@dataclass(frozen=True)
class TaskFacts:
    """What the eval's own task DECLARES — read by introspection, never re-typed."""

    task_ref: str
    dataset: str
    config: str
    split: str
    pinned_revision: str | None
    record_to_sample: str
    prompt_template: str | None
    mcq: bool
    scorer: str
    scorer_kwargs: Mapping[str, Any]
    custom_solvers: tuple[str, ...]
    #: The eval's own multiple_choice template when it overrides the default AND
    #: resolves to one module attribute — captured as a fact instead of flagged
    #: (the family renderer, OME-1116 milestone C).
    choice_template: str | None = None


@dataclass(frozen=True)
class Observations:
    """What the importer OBSERVED at import time — the lockfile's captured rows."""

    revision: str
    case_count: int
    license: str | None


@dataclass(frozen=True)
class Fragments:
    """The three rendered row fragments plus the pin names prepare.py must import."""

    pins: str
    snapshot: str
    board: str
    import_names: tuple[str, ...]


# ---------------------------------------------------------------------------
# Stage 1 — introspect
# ---------------------------------------------------------------------------


def introspect_task(task_ref: str, task_args: Mapping[str, Any] | None = None) -> TaskFacts:
    """Read one eval task's declarations by running it against a recording stub.

    ``task_ref`` is a dotted ``"module:attr"`` reference to the task function
    (e.g. ``"inspect_evals.gsm8k.gsm8k:gsm8k"``); ``task_args`` are forwarded to
    it (e.g. ``fewshot=0``). The module's ``hf_dataset`` binding is replaced for
    the duration of the call, so nothing is downloaded.
    """

    from inspect_ai.dataset import MemoryDataset, Sample

    module_name, _, attribute = task_ref.partition(":")
    if not module_name or not attribute:
        raise ImporterError(f"task reference must be 'module:attr', got {task_ref!r}")
    module = import_module(module_name)
    task_fn: Any = getattr(module, attribute)
    if not hasattr(module, "hf_dataset"):
        raise ImporterError(
            f"{module_name} has no hf_dataset binding — the importer only reads evals "
            "that load their exam from the HuggingFace Hub"
        )

    recorded: list[tuple[dict[str, Any], Any]] = []

    def recorder(*args: Any, **kwargs: Any) -> Any:
        stub = MemoryDataset([Sample(input="stub", target="A", choices=["a", "b"])])
        recorded.append((dict(kwargs), stub))
        return stub

    original: Any = module.hf_dataset
    module.hf_dataset = recorder  # type: ignore[attr-defined]
    try:
        task: Any = task_fn(**dict(task_args or {}))
    finally:
        module.hf_dataset = original  # type: ignore[attr-defined]

    kwargs: dict[str, Any] = _exam_dataset_kwargs(task, recorded, task_ref)
    sample_fields: Any = _module_level_row_rule(kwargs.get("sample_fields"), task_ref)
    scorer_ref, scorer_kwargs, scorer_name = _scorer_reference(task, module)
    template_ref, choice_template_ref, custom_solvers = _solver_facts(task, module, task_ref)
    return TaskFacts(
        task_ref=task_ref,
        dataset=str(kwargs["path"]),
        config=str(kwargs.get("name") or kwargs.get("data_dir") or ""),
        split=str(kwargs.get("split", "")),
        pinned_revision=kwargs.get("revision"),
        record_to_sample=f"{sample_fields.__module__}:{sample_fields.__name__}",
        prompt_template=template_ref,
        mcq=scorer_name == "choice",
        scorer=scorer_ref,
        scorer_kwargs=scorer_kwargs,
        custom_solvers=custom_solvers,
        choice_template=choice_template_ref,
    )


def _module_level_row_rule(sample_fields: Any, task_ref: str) -> Any:
    """Refuse a row rule the emitted dotted reference could never resolve."""

    if not callable(sample_fields):
        raise ImporterError(
            f"{task_ref}: sample_fields is not a function — the importer only handles "
            "record_to_sample-style conversions"
        )
    resolved: Any = getattr(import_module(sample_fields.__module__), sample_fields.__name__, None)
    if resolved is not sample_fields:
        # WHY: some evals (truthfulqa) define record_to_sample INSIDE the task
        # function; the row's dotted reference could never resolve it, so the
        # dangling row would fail at image build instead of at import review.
        raise ImporterError(
            f"{task_ref}: record_to_sample is a task-local function — the row can only "
            "POINT at a module-level attribute; import this eval by hand or upstream a fix"
        )
    return sample_fields


def _exam_dataset_kwargs(
    task: Any, recorded: list[tuple[dict[str, Any], Any]], task_ref: str
) -> dict[str, Any]:
    """The hf_dataset call whose result the Task holds — fewshot loads are not the exam."""

    if not recorded:
        raise ImporterError(f"{task_ref}: the task never called hf_dataset")
    for kwargs, stub in recorded:
        if task.dataset is stub:
            return kwargs
    if len(recorded) == 1:
        # WHY the fallback: some evals wrap the loaded dataset (shuffle/slice), so
        # identity breaks — with a single load there is nothing else it could be.
        return recorded[0][0]
    raise ImporterError(
        f"{task_ref}: {len(recorded)} hf_dataset calls and none is the Task's dataset — "
        "cannot tell the exam load apart; pass task args that disable the extras"
    )


def _scorer_reference(task: Any, module: Any) -> tuple[str, dict[str, Any], str]:
    """The eval's scorer as a dotted constructor reference plus its creation kwargs."""

    from inspect_ai._util.registry import registry_info, registry_params

    scorers: list[Any] = task.scorer if isinstance(task.scorer, list) else [task.scorer]
    if len(scorers) != 1:
        raise ImporterError(f"expected exactly one scorer, the task declares {len(scorers)}")
    registry_name: str = registry_info(scorers[0]).name
    package, _, name = registry_name.rpartition("/")
    params: dict[str, Any] = {
        key: value for key, value in registry_params(scorers[0]).items() if _is_literal(value)
    }
    if package == "inspect_ai":
        import inspect_ai.scorer as scorer_module

        if not hasattr(scorer_module, name):
            raise ImporterError(f"scorer {registry_name!r} is not exported by inspect_ai.scorer")
        return f"inspect_ai.scorer:{name}", params, name
    if hasattr(module, name):
        return f"{module.__name__}:{name}", params, name
    raise ImporterError(
        f"cannot resolve scorer {registry_name!r} to an importable constructor — "
        "add the row by hand with the eval's own scorer reference"
    )


def _solver_facts(
    task: Any, module: Any, task_ref: str
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """The template references (prompt_template / custom multiple_choice) + unknowns."""

    from inspect_ai._util.registry import registry_info, registry_params

    solvers: list[Any] = task.solver if isinstance(task.solver, list) else [task.solver]
    template_ref: str | None = None
    choice_template_ref: str | None = None
    custom: list[str] = []
    for solver in solvers:
        registry_name: str = registry_info(solver).name
        name: str = registry_name.rpartition("/")[2]
        if name == "chain" and hasattr(solver, "__iter__"):
            # Task wraps a solver LIST into one chain; the facts live on its links.
            solvers.extend(solver)
            continue
        if name == "prompt_template":
            template_value: Any = registry_params(solver).get("template")
            template_ref = _template_attribute(module, template_value, task_ref)
        elif name == "system_message":
            # WHY always flagged: the bake has no system-message channel, so the
            # instruction would silently vanish from the imported exam.
            custom.append(f"{registry_name} (system instructions are not baked)")
        elif name == "multiple_choice" and registry_params(solver).get("template") is not None:
            # A custom choice template the bake CAN reproduce — when it resolves to
            # one module attribute the row points at (the family renderer, OME-1116
            # milestone C); an unresolvable one still earns the review flag.
            try:
                choice_template_ref = _template_attribute(
                    module, registry_params(solver).get("template"), task_ref
                )
            except ImporterError:
                custom.append(f"{registry_name} (custom choice template is not baked)")
        elif name not in _FULLY_BAKED_SOLVERS:
            custom.append(registry_name)
    return template_ref, choice_template_ref, tuple(custom)


def _template_attribute(module: Any, template: Any, task_ref: str) -> str:
    """Find the module attribute holding the template — the row must POINT, not copy."""

    matches: list[str] = [
        name
        for name, value in vars(module).items()
        if value is template and not name.startswith("_")
    ]
    if len(matches) != 1:
        raise ImporterError(
            f"{task_ref}: cannot resolve the prompt template to exactly one module "
            f"attribute (found {matches!r}) — add the prompt_template reference by hand"
        )
    return f"{module.__name__}:{matches[0]}"


def _is_literal(value: Any) -> bool:
    """True when the value survives a repr round-trip — safe to write into a row."""

    try:
        return ast.literal_eval(repr(value)) == value
    except (ValueError, SyntaxError):
        return False


# ---------------------------------------------------------------------------
# Stage 2 — capture
# ---------------------------------------------------------------------------


def capture_observations(
    facts: TaskFacts,
    *,
    dataset_info: Callable[[str, str | None], Any] | None = None,
    count_rows: Callable[[TaskFacts, str], int] | None = None,
) -> Observations:
    """Record the import-time observations: revision sha, row count, license.

    An upstream revision pin (from the eval's own hf_dataset call) wins — but it
    is RESOLVED through the Hub to the commit sha it names, so a mutable ref like
    a branch or tag can never land in pins.py (review finding on PR 965); the
    license is read at that same revision. Without a pin, HEAD resolves the same
    way, lockfile-style. Both loaders default to the real network calls and are
    injectable for tests.
    """

    info_of: Callable[[str, str | None], Any] = dataset_info or _hub_dataset_info
    counter: Callable[[TaskFacts, str], int] = count_rows or _hub_count_rows
    info: Any = info_of(facts.dataset, facts.pinned_revision)
    revision: str = str(info.sha)
    card: Any = getattr(info, "card_data", None) or {}
    license_value: Any = card.get("license") if hasattr(card, "get") else None
    if isinstance(license_value, list):
        license_value = ", ".join(str(item) for item in license_value)
    return Observations(
        revision=revision,
        case_count=int(counter(facts, revision)),
        license=None if license_value is None else str(license_value),
    )


def _hub_dataset_info(dataset: str, revision: str | None) -> Any:
    """The Hub's view of the dataset at ``revision`` (HEAD when None) — its
    resolved commit sha plus the card (license)."""

    from huggingface_hub import HfApi

    return HfApi().dataset_info(dataset, revision=revision)


def _hub_count_rows(facts: TaskFacts, revision: str) -> int:
    """Row count at the pinned revision — the bake's drift guard, observed once."""

    import datasets

    loaded: Any = datasets.load_dataset(
        facts.dataset, facts.config or None, split=facts.split, revision=revision
    )
    return int(loaded.num_rows)


# ---------------------------------------------------------------------------
# Stage 3 — emit
# ---------------------------------------------------------------------------


def _pin_prefix(key: str) -> str:
    """The board key's constant stem (``foo-bar`` → ``FOO_BAR``) — refused unless it
    is a valid Python identifier, so the generated pins always load."""

    prefix: str = "".join(ch if ch.isalnum() else "_" for ch in key).upper()
    if not prefix.isidentifier():
        raise ImporterError(
            f"board key {key!r} derives the constant stem {prefix!r}, which is not a "
            "valid Python identifier — start the key with a letter (e.g. "
            f"'wiki_{key}' instead of a leading digit)"
        )
    return prefix


def render_fragments(
    key: str, facts: TaskFacts, observations: Observations, shuffle_seed: int | None = None
) -> Fragments:
    """Render the three row fragments in the target files' own style."""

    prefix: str = _pin_prefix(key)
    today: str = _datetime.date.today().isoformat()
    license_note: str = observations.license or "UNKNOWN"

    pin_lines: list[str] = [
        # WHY two lines: a long task_ref must never push a generated line past
        # the 100-column lint gate.
        f"# {key} — generated by the importer on {today} from",
        f"#   {facts.task_ref};",
        f"# license: {license_note}. Review before merge — import time is the trust window.",
        f"# https://huggingface.co/datasets/{facts.dataset}/tree/{observations.revision}",
        f'{prefix}_DATASET = "{facts.dataset}"',
        f'{prefix}_CONFIG = "{facts.config}"',
        f'{prefix}_SPLIT = "{facts.split}"',
        f'{prefix}_DATASET_REVISION = "{observations.revision}"',
        f"{prefix}_CASE_COUNT = {observations.case_count}",
    ]
    import_names: list[str] = [
        f"{prefix}_CASE_COUNT",
        f"{prefix}_CONFIG",
        f"{prefix}_DATASET",
        f"{prefix}_DATASET_REVISION",
        f"{prefix}_SPLIT",
    ]
    if shuffle_seed is not None:
        pin_lines.append(f"{prefix}_SHUFFLE_SEED = {shuffle_seed}")
        import_names.append(f"{prefix}_SHUFFLE_SEED")

    snapshot_lines: list[str] = [
        f'    "{key}": SnapshotSpec(',
        f"        dataset={prefix}_DATASET,",
        f"        config={prefix}_CONFIG,",
        f"        split={prefix}_SPLIT,",
        f"        dataset_revision={prefix}_DATASET_REVISION,",
        f"        case_count={prefix}_CASE_COUNT,",
        "        # Generated from",
        f"        #   {facts.task_ref};\n        # verify against the eval's task.",
        f'        record_to_sample="{facts.record_to_sample}",',
    ]
    if facts.prompt_template is not None:
        snapshot_lines.append(f'        prompt_template="{facts.prompt_template}",')
    if facts.choice_template is not None:
        snapshot_lines.append(f'        choice_template="{facts.choice_template}",')
    if shuffle_seed is not None:
        snapshot_lines.append(f"        shuffle_seed={prefix}_SHUFFLE_SEED,")
    for solver_name in facts.custom_solvers:
        snapshot_lines.append(
            f"        # TODO(review): solver {solver_name} is not reproduced by "
            "the bake — verify the baked prompt matches the eval's render."
        )
    snapshot_lines.append("    ),")

    return Fragments(
        pins="\n".join(pin_lines) + "\n",
        snapshot="\n".join(snapshot_lines) + "\n",
        board="\n".join(_board_lines(key, facts, license_note)) + "\n",
        import_names=tuple(import_names),
    )


def _board_lines(key: str, facts: TaskFacts, license_note: str) -> list[str]:
    """The BoardSpec fragment — prose as TODOs, provenance as wrapped comments."""

    board_lines: list[str] = [
        "    BoardSpec(",
        f'        key="{key}",',
        "        # TODO(review): title/description/focus are catalogue prose — the",
        "        # importing agent writes them from the eval's own docs; the human",
        "        # reviewer verifies them against the dataset.",
        '        title="TODO",',
        '        description="TODO",',
        '        focus="TODO",',
        f'        dataset_url="https://huggingface.co/datasets/{facts.dataset}",',
        # WHY two lines: a long task_ref must never push a generated line past
        # the 100-column lint gate.
        "        # Provenance: this scorer is declared by the Task of",
        f"        #   {facts.task_ref}.",
        f"        # License: {license_note}.",
        f'        scorer="{facts.scorer}",',
    ]
    if facts.scorer_kwargs:
        rendered_kwargs: str = ", ".join(
            f'"{name}": {value!r}' for name, value in sorted(facts.scorer_kwargs.items())
        )
        board_lines.append(f"        scorer_kwargs={{{rendered_kwargs}}},")
    if not facts.mcq:
        board_lines.append(
            "        # Free-form answers make mid-run feedback legitimate (spec §4);"
        )
        board_lines.append("        # MCQ boards must NOT set this (OME-796).")
        board_lines.append("        with_check_surface=True,")
    board_lines.append("    ),")
    return board_lines


def generate_rows(
    key: str,
    facts: TaskFacts,
    observations: Observations,
    *,
    engine_src: Path,
    shuffle_seed: int | None = None,
) -> Fragments:
    """Insert one board's generated rows into the three files, in place.

    Refuses an already-imported key; warns (but emits) on an uncleared license.
    ``engine_src`` is the directory holding pins.py / prepare.py / boards.py.
    """

    pins_path: Path = engine_src / "pins.py"
    prepare_path: Path = engine_src / "prepare.py"
    boards_path: Path = engine_src / "boards.py"
    texts: dict[Path, str] = {
        path: path.read_text() for path in (pins_path, prepare_path, boards_path)
    }
    _refuse_existing_rows(key, _pin_prefix(key), texts)
    license_name: str = (observations.license or "UNKNOWN").lower()
    if license_name not in CLEARED_DATASET_LICENSES:
        print(
            f"WARNING: dataset license {observations.license or 'UNKNOWN'!s} is not on the "
            f"cleared list ({', '.join(sorted(CLEARED_DATASET_LICENSES))}) — emitting anyway; "
            "the diff review is the gate.",
            file=sys.stderr,
        )
    fragments: Fragments = render_fragments(key, facts, observations, shuffle_seed)
    # WHY compute-then-write: every insertion point is validated while building the
    # new texts, so a broken anchor refuses the WHOLE import — never a half-imported
    # tree that a retry then rejects as "already exists" (review finding on PR 966).
    new_texts: dict[Path, str] = {
        pins_path: _with_fragment(texts[pins_path], _PINS_ANCHOR, fragments.pins + "\n", "pins.py"),
        prepare_path: _with_fragment(
            _with_import_names(texts[prepare_path], fragments.import_names),
            _SNAPSHOTS_ANCHOR,
            fragments.snapshot,
            "prepare.py",
        ),
        boards_path: _with_fragment(
            texts[boards_path], _BOARDS_ANCHOR, fragments.board, "boards.py"
        ),
    }
    for path, text in new_texts.items():
        path.write_text(text)
    return fragments


def _refuse_existing_rows(key: str, prefix: str, texts: Mapping[Path, str]) -> None:
    """Never double a board — by key, OR by the constant stem two keys can share.

    WHY the prefix check: ``foo-bar`` and ``foo_bar`` are different keys but derive
    the same ``FOO_BAR_*`` constants; the second import would silently shadow the
    first board's dataset/revision/count (review finding on PR 966).
    """

    needles: tuple[str, ...] = (f'"{key}": SnapshotSpec(', f'key="{key}"')
    for path, text in texts.items():
        if any(needle in text for needle in needles):
            raise ImporterError(f"board key {key!r} already exists in {path.name}")
        if path.name == "pins.py" and f"{prefix}_DATASET" in text:
            raise ImporterError(
                f"pin constants {prefix}_* already exist in pins.py — another board key "
                f"derives the same constant stem as {key!r}; pick a distinct key"
            )


def _with_fragment(text: str, anchor: str, fragment: str, filename: str) -> str:
    """The whole insertion contract: the fragment lands immediately above the anchor.

    Pure text→text so callers can validate EVERY insertion before writing ANY file.
    """

    lines: list[str] = text.splitlines(keepends=True)
    positions: list[int] = [i for i, line in enumerate(lines) if line.strip() == anchor.strip()]
    if len(positions) != 1:
        raise ImporterError(
            f"{filename}: expected exactly one anchor line {anchor!r}, found {len(positions)} — "
            "the insertion contract is broken; restore the anchor comment"
        )
    lines.insert(positions[0], fragment)
    return "".join(lines)


def _with_import_names(text: str, names: tuple[str, ...]) -> str:
    """Add the new pin constants to prepare.py's pins import block, keeping it sorted."""

    lines: list[str] = text.splitlines(keepends=True)
    try:
        start: int = next(i for i, line in enumerate(lines) if line.strip() == _PINS_IMPORT_HEADER)
        end: int = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == ")")
    except StopIteration as exc:
        raise ImporterError(
            "prepare.py: cannot find the pins import block — the insertion contract is broken"
        ) from exc
    existing: list[str] = [lines[i].strip().rstrip(",") for i in range(start + 1, end)]
    merged: list[str] = sorted(set(existing) | set(names))
    block: list[str] = [f"    {name},\n" for name in merged]
    lines[start + 1 : end] = block
    return "".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    dataset_info: Callable[[str, str | None], Any] | None = None,
    count_rows: Callable[[TaskFacts, str], int] | None = None,
) -> int:
    """Stage 1 → 2 → 3, then tell the dev to review the diff."""

    parser = argparse.ArgumentParser(
        prog="python -m screamingface_engine_inspect.importer",
        description="Generate one imported board's row diffs from an inspect task.",
    )
    parser.add_argument("task_ref", help="dotted task reference, e.g. inspect_evals.mod.mod:task")
    parser.add_argument("--key", required=True, help="the board key (catalogue id suffix)")
    parser.add_argument(
        "--task-arg",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="argument forwarded to the task function (repeatable), e.g. fewshot=0",
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        default=None,
        help="seeded shuffle for grouped splits (the seed becomes exam identity)",
    )
    parser.add_argument(
        "--engine-src",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="directory holding pins.py/prepare.py/boards.py (default: this package)",
    )
    args = parser.parse_args(argv)

    try:
        facts: TaskFacts = introspect_task(args.task_ref, _parse_task_args(args.task_arg))
        observations: Observations = capture_observations(
            facts, dataset_info=dataset_info, count_rows=count_rows
        )
        generate_rows(
            args.key,
            facts,
            observations,
            engine_src=args.engine_src,
            shuffle_seed=args.shuffle_seed,
        )
    except ImporterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"Rows for {args.key!r} written into {args.engine_src} "
        f"(revision {observations.revision}, {observations.case_count} cases, "
        f"license {observations.license or 'UNKNOWN'}).\n"
        "Onboarding is AI-first: agent, now fill the TODO catalogue prose and resolve "
        "every TODO(review), then run the gates — a human must review the diff before merge."
    )
    return 0


def _parse_task_args(pairs: list[str]) -> dict[str, Any]:
    """``NAME=VALUE`` flags → task kwargs; values parse as literals, else stay strings."""

    parsed: dict[str, Any] = {}
    for pair in pairs:
        name, separator, raw = pair.partition("=")
        if not separator:
            raise ImporterError(f"--task-arg must be NAME=VALUE, got {pair!r}")
        try:
            parsed[name] = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            parsed[name] = raw
    return parsed


if __name__ == "__main__":  # pragma: no cover — the module IS the command
    sys.exit(main())
