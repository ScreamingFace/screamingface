"""The combine operator registry (FW-1, FW-6 at registry level; OME-1289 E4a, unit 1)."""

from __future__ import annotations

import pytest

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import (
    OperatorDescriptor,
    OperatorUnknown,
    SpecInvalid,
    Stage,
    StageResult,
    accepted,
)
from screamingface_engine.combine.registry import OperatorRegistry


def _extract(text: str, args: object, /) -> StageResult:
    return accepted(text)


def _descriptor(name: str, version: int = 1, stage: Stage = "extract") -> OperatorDescriptor:
    return OperatorDescriptor(name, version, stage, f"{name} summary", _extract)  # type: ignore[arg-type]


def test_registry_rejects_a_duplicate_operator_id() -> None:
    first = _descriptor("dup")
    with pytest.raises(ValueError, match=r"dup@1"):
        OperatorRegistry((first, first))


def test_registry_resolves_exact_id_at_its_stage() -> None:
    wanted = _descriptor("last_word")
    registry = OperatorRegistry((wanted, _descriptor("lower", stage="normalize")))
    assert registry.resolve("last_word@1", "extract") is wanted
    with pytest.raises(SpecInvalid, match=r"last_word@1.*extract.*not normalize"):
        registry.resolve("last_word@1", "normalize")
    assert len(registry) == 2
    assert "lower@1" in registry
    assert "lower@2" not in registry


def test_registry_raises_operator_unknown_for_an_unregistered_id() -> None:
    registry = OperatorRegistry((_descriptor("last_word"),))
    with pytest.raises(OperatorUnknown, match=r"last_word@9"):
        registry.resolve("last_word@9", "extract")


def test_describe_is_sorted_by_id_with_exactly_the_catalog_keys() -> None:
    registry = OperatorRegistry(
        (_descriptor("zeta"), _descriptor("alpha"), _descriptor("alpha", 2))
    )
    entries = registry.describe()
    assert [entry["id"] for entry in entries] == ["alpha@1", "alpha@2", "zeta@1"]
    for entry in entries:
        assert set(entry) == {"id", "name", "version", "stage", "args_schema", "summary"}
    assert [descriptor.id for descriptor in registry] == ["alpha@1", "alpha@2", "zeta@1"]


def test_builtin_operators_is_built_at_import() -> None:
    assert isinstance(BUILTIN_OPERATORS, OperatorRegistry)
