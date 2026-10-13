"""Code-pointer call types (url4 2.0, contracts C2): input lookup, params, handler call."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, MutableMapping
from typing import cast

import pytest

from url4.core.code import CodeCall, CodeHandler, CodeInput, call_handler


def _inputs() -> tuple[CodeInput, ...]:
    return (
        CodeInput(position=1, name="member_1", value="alpha", weight=None),
        CodeInput(position=2, name="member_2", value="beta", weight=0.0),
        CodeInput(position=3, name=None, value=3, weight={"a": 0.5}),
    )


def _call(
    params: Mapping[str, str] | None = None,
    inputs: tuple[CodeInput, ...] | None = None,
) -> CodeCall:
    return CodeCall(
        pointer="/ensemble/combine/v1",
        params={"reducer": "vote"} if params is None else params,
        inputs=_inputs() if inputs is None else inputs,
    )


# --- CodeCall.input by position -------------------------------------------------


def test_input_by_int_position() -> None:
    assert _call().input(2).value == "beta"


def test_input_by_dollar_position_string() -> None:
    assert _call().input("$2").value == "beta"


def test_input_by_bare_digit_string() -> None:
    assert _call().input("3").value == 3


def test_input_absent_position_is_key_error() -> None:
    with pytest.raises(KeyError):
        _call().input(9)


# --- CodeCall.input by name -----------------------------------------------------


def test_input_by_name() -> None:
    assert _call().input("member_1").value == "alpha"


def test_input_by_dollar_name_string() -> None:
    assert _call().input("$member_1").value == "alpha"


def test_input_absent_name_is_key_error() -> None:
    with pytest.raises(KeyError):
        _call().input("nobody")


def test_ambiguous_name_is_value_error_but_position_still_works() -> None:
    call = _call(
        inputs=(
            CodeInput(position=1, name="src[0]", value="a", weight=None),
            CodeInput(position=2, name="src[0]", value="b", weight=None),
        )
    )
    with pytest.raises(ValueError, match="ambiguous"):
        call.input("src[0]")
    assert call.input(1).value == "a"
    assert call.input(2).value == "b"


# --- bool refusal ---------------------------------------------------------------


def test_bool_ref_is_type_error() -> None:
    with pytest.raises(TypeError):
        _call().input(True)


# --- params are read-only -------------------------------------------------------


def test_params_equal_the_given_dict() -> None:
    assert dict(_call().params) == {"reducer": "vote"}
    assert _call().params == {"reducer": "vote"}


def test_params_cannot_be_assigned_through() -> None:
    mutable = cast(MutableMapping[str, str], _call().params)
    with pytest.raises(TypeError):
        mutable["reducer"] = "other"


def test_params_are_a_copy_of_the_given_dict() -> None:
    source = {"reducer": "vote"}
    call = _call(params=source)
    source["reducer"] = "changed"
    assert call.params["reducer"] == "vote"


# --- frozen dataclasses ---------------------------------------------------------


def test_code_input_is_frozen() -> None:
    item = _inputs()[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(item, "value", "changed")


def test_code_call_is_frozen() -> None:
    call = _call()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(call, "pointer", "/other")


# --- call_handler ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_handler_runs_a_sync_handler() -> None:
    def handler(call: CodeCall) -> str:
        return f"sync:{call.input(1).value}"

    assert await call_handler(handler, _call()) == "sync:alpha"


@pytest.mark.asyncio
async def test_call_handler_awaits_an_async_handler() -> None:
    async def handler(call: CodeCall) -> str:
        return f"async:{call.input(2).value}"

    assert await call_handler(handler, _call()) == "async:beta"


@pytest.mark.asyncio
async def test_call_handler_returns_a_non_str_result_unchecked() -> None:
    def handler(call: CodeCall) -> object:
        return 42

    assert await call_handler(cast(CodeHandler, handler), _call()) == 42
