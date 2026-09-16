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
    Stage 3 — emit (the stack's NEXT PR): render the row fragments and insert
              them at the three files' anchor comments, in place.

STORY: onboarding is AI-first — an agent runs the command, writes the catalogue
prose, and resolves every TODO(review); the human's whole job is verifying the
resulting diff. Nobody transcribes values or writes wiring code.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any

#: Solvers whose render the bake reproduces outright (prepare.py's templated/MCQ/raw
#: prompt paths). Anything else — including prompt settings the bake would silently
#: drop, like system instructions or a custom choice template — earns a review flag
#: in the facts rather than a guess (review finding on PR 965).
_FULLY_BAKED_SOLVERS: frozenset[str] = frozenset({"prompt_template", "generate", "multiple_choice"})


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


@dataclass(frozen=True)
class Observations:
    """What the importer OBSERVED at import time — the lockfile's captured rows."""

    revision: str
    case_count: int
    license: str | None


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
    sample_fields: Any = kwargs.get("sample_fields")
    if not callable(sample_fields):
        raise ImporterError(
            f"{task_ref}: sample_fields is not a function — the importer only handles "
            "record_to_sample-style conversions"
        )
    scorer_ref, scorer_kwargs, scorer_name = _scorer_reference(task, module)
    template_ref, custom_solvers = _solver_facts(task, module, task_ref)
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
    )


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


def _solver_facts(task: Any, module: Any, task_ref: str) -> tuple[str | None, tuple[str, ...]]:
    """The template reference (when a prompt_template solver carries one) + unknowns."""

    from inspect_ai._util.registry import registry_info, registry_params

    solvers: list[Any] = task.solver if isinstance(task.solver, list) else [task.solver]
    template_ref: str | None = None
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
            # WHY: the bake renders MCQ with inspect's default SINGLE_ANSWER
            # template; a custom template here would silently change the exam.
            custom.append(f"{registry_name} (custom choice template is not baked)")
        elif name not in _FULLY_BAKED_SOLVERS:
            custom.append(registry_name)
    return template_ref, tuple(custom)


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
