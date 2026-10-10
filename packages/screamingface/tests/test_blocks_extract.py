"""sf.Extract: how a member's answer is read (OME-1289 gap, block-api, GP-E2)."""

from __future__ import annotations

import pytest

import screamingface as sf
from screamingface.blocks import Extract

_RULES = (
    "boxed, last_number, field, regex, last_line, whole, json, benchmark, "
    "inspect_number, inspect_aime"
)
_NORMALIZERS = "numeric, text, set, inspect_numeric, identity"


def test_extract_validates_rule_normalizer_and_args() -> None:
    with pytest.raises(ValueError, match=_RULES):
        sf.Extract("nope")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sf.Extract(3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=_NORMALIZERS):
        sf.Extract("last_number", normalize="nope")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="does not take 'foo'"):
        sf.Extract("last_number", foo=1)
    with pytest.raises(ValueError, match="needs 'path'"):
        sf.Extract("field")
    with pytest.raises(ValueError, match="field"):
        sf.Extract("field", path="a..b")
    for not_text in (True, None, 3):
        with pytest.raises(TypeError, match="path must be text"):
            sf.Extract("field", path=not_text)
    with pytest.raises(ValueError, match="does not take 'path'"):
        sf.Extract("regex", pattern="a", path="x")
    with pytest.raises(ValueError, match="needs 'pattern'"):
        sf.Extract("regex")
    with pytest.raises(TypeError, match="JSON scalar"):
        sf.Extract("regex", pattern="a", group=[1])


def test_extract_benchmark_takes_no_normalizer() -> None:
    assert sf.Extract("benchmark").normalize is None
    with pytest.raises(ValueError, match="takes the benchmark's own normalizer"):
        sf.Extract("benchmark", normalize="text")


def test_extract_value_equality_hash_and_python_round_trip() -> None:
    blocks = [
        sf.Extract("last_number"),
        sf.Extract("last_number", normalize="numeric"),
        sf.Extract("field", normalize="text", path="a.b[0]"),
        sf.Extract("regex", normalize="text", pattern=r"Final: (\w+)", group=1),
        sf.Extract("regex", pattern="x", ignore_case=True, occurrence="first"),
        sf.Extract("benchmark"),
    ]
    for block in blocks:
        copy = eval(block._python(), {"sf": sf})  # noqa: S307
        assert copy == block
        assert hash(copy) == hash(block)
        assert len({block, copy}) == 1
    assert sf.Extract("last_number") != sf.Extract("last_number", normalize="numeric")
    assert sf.Extract("regex", pattern="(a)", group=1) != sf.Extract(
        "regex", pattern="(a)", group=0
    )
    assert (
        repr(blocks[3]) == "Extract('regex', normalize='text', group=1, pattern='Final: (\\\\w+)')"
    )
    assert blocks[0]._python() == "sf.Extract('last_number')"


def test_extract_args_are_frozen() -> None:
    block = sf.Extract("field", path="a")

    with pytest.raises(TypeError):
        block.args["path"] = "b"  # type: ignore[index]
    with pytest.raises(AttributeError):
        block.rule = "boxed"  # type: ignore[misc]


def test_extract_steps_map_rules_to_engine_operators() -> None:
    with pytest.raises(ValueError, match="extract='benchmark' needs a benchmark"):
        Extract("benchmark")._steps()


def test_extract_regex_ignore_case_false_is_the_default() -> None:
    plain = sf.Extract("regex", pattern="a")
    explicit = sf.Extract("regex", pattern="a", ignore_case=False)

    assert explicit == plain
    assert hash(explicit) == hash(plain)
    assert "ignore_case" not in explicit.args
    assert sf.Extract("regex", pattern="a", ignore_case=True) != plain
    with pytest.raises(TypeError, match="ignore_case must be a bool"):
        sf.Extract("regex", pattern="a", ignore_case=0)
