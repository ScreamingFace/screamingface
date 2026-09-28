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
        inspect_evals.arc.arc:arc_easy --key arc_easy

(gsm8k, the original example, now refuses: its hf_dataset call passes
``data_dir``, which the bake does not reproduce — its merged row was
hand-verified before the refusal existed.)

STORY: onboarding is AI-first — an agent runs the command, writes the catalogue
prose, and resolves every TODO(review); the human's whole job is verifying the
resulting diff. Nobody transcribes values or writes wiring code.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _datetime
import inspect as _inspect
import json
import re
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
    #: The eval's system instruction when it lives in a module-level constant —
    #: captured as a fact the row POINTS at; the bake delivers it as leading
    #: input text (a benchmark cannot address a candidate's system role — the
    #: contracteval named-deviation pattern, owner-approved on OME-1253). An
    #: inline-literal system message still earns the review flag instead.
    system_message: str | None = None
    #: The eval shuffles its exam order (hf_dataset shuffle=True). Without a seed
    #: the upstream order is random per run, so an import must pin one order —
    #: the upstream seed when the eval has one, else a --shuffle-seed policy seed.
    upstream_shuffle: bool = False
    upstream_shuffle_seed: int | None = None
    #: The eval shuffles each case's CHOICE order (hf_dataset shuffle_choices).
    #: Same conservation story as the row shuffle, one level down: unseeded
    #: (True) is random per run, so the import must pin one choice order —
    #: the upstream seed when shuffle_choices is an int, else a
    #: --choice-shuffle-seed policy seed (OME-1264).
    upstream_shuffle_choices: bool = False
    upstream_choice_shuffle_seed: int | None = None
    #: hf_dataset's data_files selection, forwarded to datasets.load_dataset —
    #: conserved as a literal dict[str, str] (infinite_bench's
    #: {"passkey": "passkey.jsonl"}); any other shape refuses (OME-1264 ext 2).
    data_files: dict[str, str] | None = None
    #: hf_dataset's Features schema as a dotted POINTER at the eval's own
    #: module constant (infinite_bench's constants:ft) — the row points, never
    #: copies; resolved and type-checked at bake time (OME-1264 ext 2).
    features: str | None = None


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
    # WHY bind against the REAL signature: 17 of 80 inspect_evals call sites pass
    # path (some also split) positionally — a kwargs-only recorder would drop them.
    signature: _inspect.Signature = _binding_signature(module.hf_dataset)

    def recorder(*args: Any, **kwargs: Any) -> Any:
        stub = MemoryDataset([Sample(input="stub", target="A", choices=["a", "b"])])
        recorded.append((_bound_call_arguments(signature, args, kwargs), stub))
        return stub

    original: Any = module.hf_dataset
    module.hf_dataset = recorder  # type: ignore[attr-defined]
    try:
        task: Any = task_fn(**dict(task_args or {}))
    finally:
        module.hf_dataset = original  # type: ignore[attr-defined]

    kwargs: dict[str, Any] = _exam_dataset_kwargs(task, recorded, task_ref)
    _refuse_irreproducible_dataset_kwargs(kwargs, task_ref)
    sample_fields: Any = _module_level_row_rule(kwargs.get("sample_fields"), task_ref)
    scorer_ref, scorer_kwargs, scorer_name = _scorer_reference(task, module)
    template_ref, choice_template_ref, system_message_ref, custom_solvers, uses_multiple_choice = (
        _solver_facts(task, module, task_ref)
    )
    return TaskFacts(
        task_ref=task_ref,
        dataset=str(kwargs["path"]),
        config=str(kwargs.get("name") or ""),
        split=str(kwargs.get("split", "")),
        pinned_revision=kwargs.get("revision"),
        record_to_sample=f"{sample_fields.__module__}:{sample_fields.__name__}",
        prompt_template=template_ref,
        # Two witnesses, either proves the MCQ shape: the multiple_choice solver
        # in the chain, OR the choice scorer (mmlu hides multiple_choice inside
        # its own @solver wrapper, so only the scorer testifies there; choice()
        # only grades states WITH choices, so its name proves the shape).
        mcq=uses_multiple_choice or scorer_name == "choice",
        scorer=scorer_ref,
        scorer_kwargs=scorer_kwargs,
        custom_solvers=custom_solvers,
        choice_template=choice_template_ref,
        system_message=system_message_ref,
        upstream_shuffle=bool(kwargs.get("shuffle")),
        upstream_shuffle_seed=kwargs.get("seed") if kwargs.get("shuffle") else None,
        upstream_shuffle_choices=_shuffles_choices(kwargs.get("shuffle_choices")),
        upstream_choice_shuffle_seed=_choice_shuffle_seed_fact(kwargs.get("shuffle_choices")),
        data_files=_conserved_data_files(kwargs.get("data_files"), task_ref),
        features=_features_reference(module, kwargs.get("features"), task_ref),
    )


def _conserved_data_files(raw: Any, task_ref: str) -> dict[str, str] | None:
    """data_files in a shape the bake reproduces verbatim, or a named refusal.

    Only the shape seen upstream is conserved: a dict of str split names to str
    file names (infinite_bench's {"passkey": "passkey.jsonl"}). Everything else
    — a bare str, lists, nested mappings, Path objects — refuses by name rather
    than guessing how it round-trips through a generated literal (YAGNI: extend
    when an eval actually ships another shape).
    """

    if raw is None:
        return None
    if isinstance(raw, dict) and all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
    ):
        return dict(raw)
    raise ImporterError(
        f"{task_ref}: hf_dataset data_files has a shape the importer does not conserve "
        f"({type(raw).__name__}) — only a dict of str to str is reproduced by the bake; "
        "extend the importer for this family"
    )


def _features_reference(module: Any, features: Any, task_ref: str) -> str | None:
    """The Features schema as a dotted pointer at the eval's own constant.

    WHY a pointer and not a serialized schema: the row must POINT at the eval's
    code (the record_to_sample/system_message convention) so the diff reviewer
    can anchor it and a dependency bump moves it with the eval. A features
    value with no module attribute (an inline Features(...)) refuses — a
    dropped schema would load different data with every guard green.
    """

    if features is None:
        return None
    try:
        return _template_attribute(module, features, task_ref)
    except ImporterError as exc:
        raise ImporterError(
            f"{task_ref}: hf_dataset features does not resolve to one module attribute "
            "the row could point at — extend the importer or add the row by hand"
        ) from exc


def _shuffles_choices(raw: Any) -> bool:
    """Whether hf_dataset's ``shuffle_choices`` value shuffles at all (False/None: no)."""

    return raw is not None and raw is not False


def _choice_shuffle_seed_fact(raw: Any) -> int | None:
    """The upstream choice-shuffle seed, when ``shuffle_choices`` carries one.

    WHY the bool guard: inspect reads ``shuffle_choices: bool | int | None`` and
    checks bool BEFORE int because ``True`` IS an int — reading it as seed 1
    would pin an order upstream never meant. Same precedence here.
    """

    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _binding_signature(binding: Any) -> _inspect.Signature:
    """The signature the recorded call arguments bind against.

    WHY the substitution: inspect_evals ≥0.20 routes hf_dataset through a fully
    variadic retry shim (``def hf_dataset(*args, **kwargs)`` in
    utils/huggingface.py). Binding against the shim buries every real kwarg in
    the VAR_KEYWORD bucket, and the conserved-kwargs guard then refuses the
    whole family as "kwarg(s) kwargs" (OME-1238). That ONE shim — checked by
    identity, never by shape — borrows the real hf_dataset's parameter names,
    because it is verified pass-through (it only injects ``retry=False``). Any
    other fully variadic wrapper is refused: a wrapper that renamed or mutated
    kwargs before forwarding would make the conserved-kwargs guard reason about
    arguments the real load never sees (review finding on PR 1009).
    """

    signature: _inspect.Signature = _inspect.signature(binding)
    if not all(
        parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        for parameter in signature.parameters.values()
    ):
        return signature
    from inspect_evals.utils.huggingface import hf_dataset as vendored_shim

    if binding is vendored_shim:
        from inspect_ai.dataset import hf_dataset as real_hf_dataset

        return _inspect.signature(real_hf_dataset)
    raise ImporterError(
        "hf_dataset is a fully variadic wrapper the importer does not recognize — only "
        "inspect_evals.utils.huggingface's shim is verified pass-through; extend the "
        "importer for this wrapper"
    )


def _bound_call_arguments(
    signature: _inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """One recorded hf_dataset call as ``{parameter name: value}``, with any
    VAR_KEYWORD bucket flattened so extra kwargs keep their own names.

    WHY: the conserved-kwargs guard judges kwargs BY NAME — a bucket entry like
    ``kwargs={'limit': 500}`` would be judged as one opaque kwarg called
    'kwargs' instead of the ``limit`` that actually changes the exam.
    """

    try:
        arguments: dict[str, Any] = dict(signature.bind_partial(*args, **kwargs).arguments)
    except TypeError as exc:
        # WHY: bind_partial raises a bare TypeError on a call the signature cannot
        # hold (e.g. a doubled argument); the importer's contract is that every
        # refusal is an ImporterError naming the fact that stopped it.
        raise ImporterError(
            f"the eval's hf_dataset call does not bind against the hf_dataset "
            f"signature ({exc}) — the importer cannot read this call's arguments"
        ) from exc
    for name, parameter in signature.parameters.items():
        if parameter.kind is parameter.VAR_KEYWORD and name in arguments:
            arguments.update(arguments.pop(name))
    return arguments


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
    if len(recorded) == 1 and _dataset_holds_the_stub(task.dataset):
        # WHY the fallback: some evals wrap the loaded dataset (shuffle/slice), so
        # identity breaks — but the wrapped dataset still CONTAINS the stub sample.
        # A single HF call whose stub never reached the Task (a json exam with HF
        # fewshots) must refuse: that call is not the exam (review round 2026-09-17).
        return recorded[0][0]
    raise ImporterError(
        f"{task_ref}: {len(recorded)} hf_dataset call(s) and none is the Task's dataset — "
        "cannot tell the exam load apart; pass task args that disable the extras"
    )


def _dataset_holds_the_stub(dataset: Any) -> bool:
    """True when the Task's dataset still yields the recorder's stub sample."""

    try:
        return any(getattr(sample, "input", None) == "stub" for sample in dataset)
    except Exception:  # noqa: BLE001 — WHY broad: an exotic dataset wrapper failing
        # to iterate must mean "cannot confirm", never crash the importer.
        return False


#: hf_dataset parameters the bake either reproduces (path/name/split/revision/
#: sample_fields; shuffle and shuffle_choices via a pinned seed each) or that
#: cannot change the exam's content (auto_id renumbers ids the bake reassigns
#: anyway; trust/cached/retry only affect how loading happens).
_REPRODUCED_DATASET_KWARGS: frozenset[str] = frozenset(
    {
        "path",
        "name",
        "split",
        "revision",
        "sample_fields",
        "shuffle",
        "seed",
        "shuffle_choices",
        "data_files",
        "features",
    }
)
_BENIGN_DATASET_KWARGS: frozenset[str] = frozenset({"auto_id", "trust", "cached", "retry"})


def _refuse_irreproducible_dataset_kwargs(kwargs: dict[str, Any], task_ref: str) -> None:
    """Every hf_dataset kwarg is conserved: reproduced, benign, or a refusal.

    WHY: dropped kwargs are exam identity vanishing silently — an eval with
    ``limit=500`` imported as the full split publishes a different exam with
    every guard green (review blocker, 2026-09-17).
    """

    dropped: list[str] = sorted(
        name
        for name, value in kwargs.items()
        if name not in _REPRODUCED_DATASET_KWARGS
        and name not in _BENIGN_DATASET_KWARGS
        and value not in (None, False, {})
    )
    if dropped:
        raise ImporterError(
            f"{task_ref}: hf_dataset kwarg(s) {', '.join(dropped)} are not reproduced "
            "by the bake — importing would silently change the exam; add the row by "
            "hand or extend the importer for this family"
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
) -> tuple[str | None, str | None, str | None, tuple[str, ...], bool]:
    """The template references (prompt_template / custom multiple_choice / module-level
    system message) + unknowns + whether the chain declares an MCQ exam."""

    from inspect_ai._util.registry import registry_info, registry_params

    # WHY setup first (OME-1272): inspect always runs Task(setup=...) before the
    # solver chain, so anything there reaches the candidate too — a walk of
    # task.solver alone let a setup system message vanish with no flag.
    solvers: list[Any] = [*_solver_list(task.setup), *_solver_list(task.solver)]
    choice_template_ref: str | None = None
    template_solvers: list[Any] = []
    system_solvers: list[Any] = []
    custom: list[str] = []
    uses_multiple_choice: bool = False
    for solver in solvers:
        registry_name: str = registry_info(solver).name
        name: str = registry_name.rpartition("/")[2]
        if name == "chain" and hasattr(solver, "__iter__"):
            # Task wraps a solver LIST into one chain; the facts live on its links.
            solvers.extend(solver)
            continue
        # Prompt templates and system messages are collected, not bound here:
        # whether the row can point at one depends on how many the whole walk
        # finds (_prompt_template_fact / _system_message_fact).
        if name == "prompt_template":
            template_solvers.append(solver)
        elif name == "system_message":
            system_solvers.append(solver)
        elif name == "multiple_choice":
            # WHY the flag: MCQ-ness is the exam's SHAPE (options + letter answer),
            # and this solver is one of its two witnesses (the other is the choice
            # scorer — see the mcq fact). The solver witness covers an eval grading
            # MCQ with its own scorer (lab_bench's precision_choice), which must
            # still be refused the check surface (OME-796); the scorer witness
            # covers an eval hiding multiple_choice inside a custom @solver
            # wrapper (mmlu's mmlu_multiple_choice), invisible to this walk.
            uses_multiple_choice = True
            if registry_params(solver).get("template") is not None:
                # A custom choice template the bake CAN reproduce — when it resolves
                # to one module attribute the row points at (the family renderer,
                # OME-1116 milestone C); an unresolvable one still earns the flag.
                choice_template_ref = _resolved_or_flagged(
                    module,
                    solver,
                    task_ref,
                    custom,
                    f"{registry_name} (custom choice template is not baked)",
                )
        elif name not in _FULLY_BAKED_SOLVERS:
            custom.append(registry_name)
    template_ref: str | None = _prompt_template_fact(module, template_solvers, task_ref)
    system_message_ref: str | None = _system_message_fact(module, system_solvers, task_ref, custom)
    return (
        template_ref,
        choice_template_ref,
        system_message_ref,
        tuple(custom),
        uses_multiple_choice,
    )


def _solver_list(solvers: Any) -> list[Any]:
    """A Task's solver slot as a fresh list: None, one solver, or a list of them."""

    if solvers is None:
        return []
    return list(solvers) if isinstance(solvers, list) else [solvers]


def _reads_a_file(template: Any) -> bool:
    """True when inspect would swap this template for a file's contents.

    inspect's prompt_template() and system_message() both pass their template
    through resource(): a path to an existing file (or a URL) becomes that
    file's text. Calling it again is safe — the eval's own solver already did,
    on the same value, while the task was being built.
    """

    from inspect_ai.util import resource

    return isinstance(template, str) and resource(template) != template


def _refuse_file_template(template: Any, task_ref: str) -> None:
    """A prompt_template read from a file refuses by name (OME-1272).

    WHY refuse, not flag: the bake formats the constant's own text, and a path
    has no {prompt} slot — every case would become the path string. That
    matches how an unresolvable prompt template already refuses.
    """

    if _reads_a_file(template):
        raise ImporterError(
            f"{task_ref}: prompt_template reads its template from a file ({template}) — "
            "the bake formats the constant's own text, so every case would become the "
            "path; add the row by hand or extend the importer for this family"
        )


def _prompt_template_fact(module: Any, solvers: list[Any], task_ref: str) -> str | None:
    """Point the row at THE prompt template constant, or refuse by name.

    inspect applies every prompt_template in turn, each wrapping the previous
    one's output ("Think carefully.\\n\\n{prompt}" around "Solve: {prompt}"); the
    row points at one template and the bake applies only it. So two or more
    refuse (OME-1272), as does a file-path template or one with no single module
    attribute to point at — the bake cannot reproduce any of them.
    """

    from inspect_ai._util.registry import registry_params

    if len(solvers) > 1:
        raise ImporterError(
            f"{task_ref}: the task applies {len(solvers)} prompt templates — inspect wraps "
            "each around the previous one's output, the bake applies only one; add the "
            "row by hand or extend the importer for this family"
        )
    if not solvers:
        return None
    template: Any = registry_params(solvers[0]).get("template")
    _refuse_file_template(template, task_ref)
    return _template_attribute(module, template, task_ref)


def _system_message_fact(
    module: Any, solvers: list[Any], task_ref: str, custom: list[str]
) -> str | None:
    """Point the row at THE system-message constant, or record why it cannot.

    A module-level system instruction the bake CAN deliver — as leading input
    text (a benchmark cannot address a candidate's system role; contracteval
    named-deviation pattern, owner-approved on OME-1253). The row holds ONE
    pointer, so a chain sending two or more system messages flags (inspect
    sends them all; OME-1272). An inline literal has no module attribute for
    the row to POINT at, and the importer never copies exam text, so it stays
    flagged too.
    """

    from inspect_ai._util.registry import registry_info

    if not solvers:
        return None
    registry_name: str = registry_info(solvers[0]).name
    rewrite: str | None = (
        f"the task sends {len(solvers)} system messages; the bake delivers only one"
        if len(solvers) > 1
        else _system_message_rewrite(solvers[0])
    )
    if rewrite is not None:
        # WHY no fact at all (OME-1272): the bake delivers ONE constant's text
        # verbatim, so any other text inspect sends would bake a different exam
        # with every guard green.
        custom.append(f"{registry_name} ({rewrite})")
        return None
    return _resolved_or_flagged(
        module,
        solvers[0],
        task_ref,
        custom,
        f"{registry_name} (system instructions are not baked)",
    )


def _system_message_rewrite(solver: Any) -> str | None:
    """Why the text inspect SENDS would differ from the template constant, or None.

    Think of the constant as a letter the bake photocopies. inspect does not post
    the letter as written: ``system_message(template, **params)`` (1) READS it
    through ``resource()`` — a path or URL becomes that file's contents — then
    (2) runs ``str.format`` over it with the params plus the sample's metadata and
    store. So the photocopy matches only when neither step changes anything:

    - params ``persona="tutor"`` → the text inspect sends has them filled in.
    - a path ``"prompts/system.txt"`` → inspect sends the file, not the path.
    - any brace, e.g. ``"Answer as {persona}."`` or ``"Reply in {{json}}."`` —
      a field can be filled per case from metadata, and an escaped ``{{``
      becomes ``{``; with no brace at all str.format is the identity.

    Returns a short reason for the review flag, or None when the constant's text
    IS what inspect sends (hellaswag's plain SYSTEM_MESSAGE).
    """

    from inspect_ai._util.registry import registry_params

    params: dict[str, Any] = dict(registry_params(solver))
    template: Any = params.pop("template", None)
    reason: str | None = None
    if params:
        reason = f"fills params {', '.join(sorted(params))} into the template at run time"
    elif not isinstance(template, str):
        # Not text at all: _template_attribute still points at it, and the bake
        # refuses a non-text resolution by name (prepare._resolved_system_text).
        reason = None
    elif _reads_a_file(template):
        reason = "template is read from a file"
    elif "{" in template or "}" in template:
        reason = "str.format rewrites the template's braces at run time"
    return reason


def _resolved_or_flagged(
    module: Any, solver: Any, task_ref: str, custom: list[str], flag: str
) -> str | None:
    """Resolve the solver's template to one module attribute, or record the review flag."""

    from inspect_ai._util.registry import registry_params

    try:
        return _template_attribute(module, registry_params(solver).get("template"), task_ref)
    except ImporterError:
        custom.append(flag)
        return None


def _template_attribute(module: Any, template: Any, task_ref: str) -> str:
    """Find the module attribute holding the template — the row must POINT, not copy.

    The task module wins; when it has no match the template may live in a shared
    helper elsewhere in the eval DISTRIBUTION (AIME's inspect_evals.utils.aime_common
    — OME-1238), so the search widens to the loaded modules under the task module's
    top-level package — still requiring exactly one match, because two candidate
    references cannot both be THE row's pointer.
    """

    matches: list[str] = [
        name
        for name, value in vars(module).items()
        if value is template and not name.startswith("_")
    ]
    if len(matches) == 1:
        return f"{module.__name__}:{matches[0]}"
    found: list[str] = [f"{module.__name__}:{name}" for name in matches]
    if not matches:
        package_prefix: str = f"{module.__name__.partition('.')[0]}."
        found = sorted(
            f"{sibling_name}:{attribute}"
            for sibling_name, sibling in sys.modules.items()
            if sibling is not None
            and sibling is not module
            and sibling_name.startswith(package_prefix)
            for attribute, value in vars(sibling).items()
            if value is template and not attribute.startswith("_")
        )
        if len(found) == 1:
            return found[0]
    raise ImporterError(
        f"{task_ref}: cannot resolve the prompt template to exactly one module "
        f"attribute (found {found!r}) — add the prompt_template reference by hand"
    )


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
    key: str,
    facts: TaskFacts,
    observations: Observations,
    shuffle_seed: int | None = None,
    choice_shuffle_seed: int | None = None,
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
    selection_pins, selection_imports, selection_snapshot_lines = _dataset_selection_fragments(
        prefix, facts
    )
    pin_lines.extend(selection_pins)
    import_names.extend(selection_imports)
    seed_pins, seed_imports, seed_snapshot_lines = _seed_fragments(
        prefix, shuffle_seed, choice_shuffle_seed
    )
    pin_lines.extend(seed_pins)
    import_names.extend(seed_imports)

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
    snapshot_lines.extend(selection_snapshot_lines)
    if facts.prompt_template is not None:
        snapshot_lines.append(f'        prompt_template="{facts.prompt_template}",')
    if facts.choice_template is not None:
        snapshot_lines.append(f'        choice_template="{facts.choice_template}",')
    if facts.system_message is not None:
        snapshot_lines.append(
            "        # Named deviation: the eval sends this as a SYSTEM message; the"
        )
        snapshot_lines.append(
            "        # bake delivers it as leading input text (a benchmark cannot"
        )
        snapshot_lines.append("        # address a candidate's system role).")
        snapshot_lines.append(f'        system_message="{facts.system_message}",')
    snapshot_lines.extend(seed_snapshot_lines)
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


def _dataset_selection_fragments(
    prefix: str, facts: TaskFacts
) -> tuple[list[str], list[str], list[str]]:
    """Fragment lines for the two conditional dataset-selection facts.

    Returns (pin lines, import names, SnapshotSpec kwarg lines). ``data_files``
    becomes a pin constant (a literal, like the dataset pins — json.dumps keeps
    double quotes for the format gate); ``features`` stays an inline dotted
    pointer (like ``record_to_sample``), so there is no pin for it.
    """

    pin_lines: list[str] = []
    import_names: list[str] = []
    snapshot_lines: list[str] = []
    if facts.data_files is not None:
        constant: str = f"{prefix}_DATA_FILES"
        pin_lines.append(f"{constant} = {json.dumps(facts.data_files, sort_keys=True)}")
        import_names.append(constant)
        snapshot_lines.append(f"        data_files={constant},")
    if facts.features is not None:
        snapshot_lines.append(f'        features="{facts.features}",')
    return pin_lines, import_names, snapshot_lines


def _seed_fragments(
    prefix: str, shuffle_seed: int | None, choice_shuffle_seed: int | None
) -> tuple[list[str], list[str], list[str]]:
    """The two conditional exam-identity seeds' fragment lines, in one place.

    Returns (pin lines, import names, SnapshotSpec kwarg lines) — each seed
    contributes to all three lists or to none, so the pin-name contract
    (imported ⇔ referenced) cannot drift per seed.
    """

    pin_lines: list[str] = []
    import_names: list[str] = []
    snapshot_lines: list[str] = []
    for constant_stem, seed in (
        ("SHUFFLE_SEED", shuffle_seed),
        ("CHOICE_SHUFFLE_SEED", choice_shuffle_seed),
    ):
        if seed is not None:
            constant: str = f"{prefix}_{constant_stem}"
            pin_lines.append(f"{constant} = {seed}")
            import_names.append(constant)
            snapshot_lines.append(f"        {constant_stem.lower()}={constant},")
    return pin_lines, import_names, snapshot_lines


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
        "        # TODO(review): assign the catalogue's easy→hard tier (OME-1257) —",
        '        # "easy" | "medium" | "hard". The literal TODO is',
        "        # refused by name at registration, so an unassigned tier cannot ship.",
        '        difficulty="TODO",  # type: ignore[arg-type]',
        # WHY two lines: a long task_ref must never push a generated line past
        # the 100-column lint gate.
        "        # Provenance: this scorer is declared by the Task of",
        f"        #   {facts.task_ref}.",
        f"        # License: {license_note}.",
        f'        scorer="{facts.scorer}",',
    ]
    if facts.scorer_kwargs:
        # WHY json.dumps for str values AND names: repr's single quotes fail the
        # emitted file's ruff-format gate; json escaping is as injection-safe as
        # repr's. Names are registry_params keys — identifiers in practice, but
        # a **kwargs-taking scorer could carry arbitrary upstream strings.
        rendered_kwargs: str = ", ".join(
            f"{json.dumps(name)}: {_scorer_kwarg_literal(value)}"
            for name, value in sorted(facts.scorer_kwargs.items())
        )
        board_lines.append(f"        scorer_kwargs={{{rendered_kwargs}}},")
    judged: bool = _is_judged(facts)
    if judged:
        # OME-1240: a judged row must never land silently — the TODO model is
        # refused at assembly by name, so an unreviewed judge cannot ship.
        board_lines.append(
            "        # TODO(review): this scorer grades with an LLM judge. Pin the judge"
        )
        board_lines.append("        # through our gateway: replace the judge-model kwarg with")
        board_lines.append(
            '        # "screamingface/<gateway-model-id>" and declare the SAME id (plus'
        )
        board_lines.append("        # pinned params) here — both join the board's exam identity.")
        board_lines.append("        # If the scorer dispatches on sample metadata, also set")
        board_lines.append("        # keep_sample_metadata=True on the SnapshotSpec row.")
        board_lines.append('        judge=JudgeSpec(model="TODO"),')
    if not facts.mcq and not judged:
        board_lines.append(
            "        # Free-form answers make mid-run feedback legitimate (spec §4);"
        )
        board_lines.append("        # MCQ boards must NOT set this (OME-796).")
        board_lines.append("        with_check_surface=True,")
    board_lines.append("    ),")
    return board_lines


#: Kwarg names evals use to take their judge model — mirrored by the assembly
#: guard's _JUDGE_MODEL_KWARGS in boards.py; the two lists move together.
_JUDGE_MODEL_KWARG_NAMES = frozenset({"model", "grader_model", "judge_model", "scorer_model"})


def _is_judged(facts: TaskFacts) -> bool:
    """A row is judged when its scorer takes a judge — by builtin NAME or by KWARG.

    WHY the kwarg check: a custom eval-module scorer (frontierscience) carries its
    judge under `model` while matching no `model_graded_*` name; a name-only check
    emitted it as a silently-unjudged row (review finding, 2026-09-24). No check
    surface is emitted for a judged row: assembly refuses the pair until the
    check-cost knob (OME-1116), so the generated row stays green-by-construction.
    """

    if facts.scorer.rpartition(":")[2].startswith("model_graded_"):
        return True
    return any(name in _JUDGE_MODEL_KWARG_NAMES for name in facts.scorer_kwargs)


def _scorer_kwarg_literal(value: Any) -> str:
    """One scorer kwarg value as source text the emitted file's gates accept."""

    return json.dumps(value) if isinstance(value, str) else repr(value)


def generate_rows(
    key: str,
    facts: TaskFacts,
    observations: Observations,
    *,
    engine_src: Path,
    shuffle_seed: int | None = None,
    choice_shuffle_seed: int | None = None,
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
    _refuse_injectable_text(facts, observations)
    license_name: str = (observations.license or "UNKNOWN").lower()
    if license_name not in CLEARED_DATASET_LICENSES:
        print(
            f"WARNING: dataset license {observations.license or 'UNKNOWN'!s} is not on the "
            f"cleared list ({', '.join(sorted(CLEARED_DATASET_LICENSES))}) — emitting anyway; "
            "the diff review is the gate.",
            file=sys.stderr,
        )
    fragments: Fragments = render_fragments(
        key, facts, observations, shuffle_seed, choice_shuffle_seed
    )
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
        _write_verified_python(path, text)
    return fragments


#: Character sets for text that gets interpolated into GENERATED PYTHON. The Hub
#: controls dataset names and card licenses, so templating them into code is an
#: injection sink (Lane 4): a hostile card could land an executable line in
#: pins.py. Everything outside these charsets is refused, and the composed files
#: are additionally ast.parse-verified before writing.
_REFERENCE_CHARSET = re.compile(r"^[A-Za-z0-9._:/\- ]*\Z")
_LICENSE_CHARSET = re.compile(r"^[A-Za-z0-9.,+\- ]*\Z")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}\Z")


def _refuse_injectable_text(facts: TaskFacts, observations: Observations) -> None:
    """Refuse any Hub-controlled string that could escape the generated rows."""

    references: dict[str, str | None] = {
        "dataset": facts.dataset,
        "config": facts.config,
        "split": facts.split,
        "record_to_sample": facts.record_to_sample,
        "prompt_template": facts.prompt_template,
        "choice_template": facts.choice_template,
        "scorer": facts.scorer,
        "task_ref": facts.task_ref,
        "features": facts.features,
    }
    for name, value in references.items():
        if value is not None and not _REFERENCE_CHARSET.match(value):
            raise ImporterError(
                f"{name} {value!r} contains characters that cannot be written into "
                "generated code — refusing (injection guard)"
            )
    # data_files strings land in a generated dict literal — same sink, same guard.
    data_files_strings: list[str] = (
        [text for pair in facts.data_files.items() for text in pair]
        if isinstance(facts.data_files, dict)
        else []
    )
    for text in data_files_strings:
        if not _REFERENCE_CHARSET.match(text):
            raise ImporterError(
                f"data_files entry {text!r} contains characters that cannot be written "
                "into generated code — refusing (injection guard)"
            )
    if observations.license is not None and not _LICENSE_CHARSET.match(observations.license):
        raise ImporterError(
            f"dataset license {observations.license!r} contains characters that cannot "
            "be written into generated code — refusing (injection guard)"
        )
    if not _COMMIT_SHA.match(observations.revision):
        raise ImporterError(
            f"captured revision {observations.revision!r} is not a 40-hex commit sha — "
            "the Hub client returned a mutable ref or nothing; refusing at the tool"
        )


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
    merged: list[str] = sorted({name for name in (*existing, *names) if name})
    block: list[str] = [f"    {name},\n" for name in merged]
    lines[start + 1 : end] = block
    return "".join(lines)


def _write_verified_python(path: Path, text: str) -> None:
    """The last injection backstop: never write a file that does not parse."""

    try:
        ast.parse(text, filename=path.name)
    except SyntaxError as exc:
        raise ImporterError(
            f"{path.name}: the composed file does not parse ({exc.msg}, line {exc.lineno}) — "
            "refusing to write; the generated fragment is malformed"
        ) from exc
    path.write_text(text)


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
        "--choice-shuffle-seed",
        type=int,
        default=None,
        help="pin one per-case choice order for an eval whose shuffle_choices is "
        "unseeded (the seed becomes exam identity)",
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
        # WHY: shuffle=True without a seed means the upstream order is random per
        # run — the import must pin ONE order. An explicit --shuffle-seed (policy)
        # wins; otherwise the eval's own seed is pinned AS EXAM IDENTITY.
        # AIDEV-NOTE: pinning upstream's seed does NOT reproduce upstream's row
        # order — the bake shuffles with random.Random, upstream with HF's
        # Dataset.shuffle (different algorithm, same seed). Harmless while rows
        # are the only shuffle (any pinned order is a valid exam); combined with
        # a choice shuffle it is refused below (review blocker on PR #1031).
        shuffle_seed: int | None = (
            args.shuffle_seed if args.shuffle_seed is not None else facts.upstream_shuffle_seed
        )
        if facts.upstream_shuffle and shuffle_seed is None:
            raise ImporterError(
                f"{args.task_ref}: the eval shuffles its exam order with no seed — "
                "pass --shuffle-seed to pin one order as exam identity"
            )
        # Same conservation one level down (choice order); the full refusal
        # matrix lives in the helper's docstring.
        choice_shuffle_seed: int | None = _resolved_choice_shuffle_seed(
            args.task_ref, facts, args.choice_shuffle_seed, shuffle_seed
        )
        observations: Observations = capture_observations(
            facts, dataset_info=dataset_info, count_rows=count_rows
        )
        generate_rows(
            args.key,
            facts,
            observations,
            engine_src=args.engine_src,
            shuffle_seed=shuffle_seed,
            choice_shuffle_seed=choice_shuffle_seed,
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


def _resolved_choice_shuffle_seed(
    task_ref: str, facts: TaskFacts, flag_seed: int | None, row_shuffle_seed: int | None
) -> int | None:
    """The one pinned choice-order seed this import bakes with, or None.

    The policy flag exists for exactly one situation: the eval shuffles choices
    UNSEEDED, so someone must pick the order. Everywhere else the flag would
    silently deviate from the exam upstream defines, so it refuses by name —
    over a seeded upstream (upstream already picked ONE order; review finding
    on PR #1031) and over an eval that does not shuffle choices at all. An
    unseeded shuffle with no flag refuses too: conserved, never dropped.

    One more cell refuses (review blocker on PR #1031): a choice shuffle
    COMBINED with a row shuffle when upstream seeded either one. The bake's row
    shuffle is Python's, upstream's is HF's ``Dataset.shuffle`` — same seed,
    different order — and the choice shuffle draws each case's permutation from
    one stream in row order, so the upstream-seeded exam cannot be reproduced.
    With both seeds OURS (lab_bench) there is no fixed upstream exam to miss,
    so the combination stays importable as pinned policy.
    """

    if facts.upstream_shuffle_choices:
        if flag_seed is not None and facts.upstream_choice_shuffle_seed is not None:
            raise ImporterError(
                f"{task_ref}: the eval pins its own choice-shuffle seed "
                f"({facts.upstream_choice_shuffle_seed}) — --choice-shuffle-seed would "
                "bake a different exam than upstream ever produces; drop the flag"
            )
        if flag_seed is None and facts.upstream_choice_shuffle_seed is None:
            raise ImporterError(
                f"{task_ref}: the eval shuffles each case's choice order with no seed — "
                "pass --choice-shuffle-seed to pin one choice order as exam identity"
            )
        if row_shuffle_seed is not None and (
            facts.upstream_shuffle_seed is not None
            or facts.upstream_choice_shuffle_seed is not None
        ):
            raise ImporterError(
                f"{task_ref}: upstream seeds its shuffle, and a row shuffle combined "
                "with a choice shuffle cannot reproduce that exam — the bake's row "
                "shuffle is not HF's algorithm, and each case's choice order depends "
                "on its row position; import this eval by hand or extend the bake to "
                "replay HF's row permutation"
            )
        return flag_seed if flag_seed is not None else facts.upstream_choice_shuffle_seed
    if flag_seed is not None:
        raise ImporterError(
            f"{task_ref}: --choice-shuffle-seed was passed but the eval does not "
            "shuffle choices — the policy seed would bake a different exam; drop the flag"
        )
    return None


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
