"""The serve defaults have one source (audit HY-8).

``ServeConfig``'s field defaults are the defaults. ``resolve()`` falls back to them,
and the ``url4 serve --help`` text prints them. Every flag the CLI forwards is a
``ServeConfig`` field. A default changed in one place and not another fails here.
"""

from __future__ import annotations

import argparse
import dataclasses

import pytest

import url4.cli.app as cli
from url4.cli._config import SERVE_DEFAULTS, ServeConfig, resolve


def test_resolve_with_nothing_set_is_the_field_defaults() -> None:
    assert resolve({}, {}, None) == ServeConfig() == SERVE_DEFAULTS


def test_every_forwarded_flag_is_a_serve_config_field() -> None:
    fields = {field.name for field in dataclasses.fields(ServeConfig)}
    assert set(cli._SERVE_FIELDS) <= fields


def test_every_forwarded_flag_has_a_serve_option() -> None:
    sub = next(
        action
        for action in cli._build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    dests = {action.dest for action in sub.choices["serve"]._actions}
    assert set(cli._SERVE_FIELDS) <= dests


def test_help_prints_the_field_defaults(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["serve", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    for value in (
        SERVE_DEFAULTS.host,
        SERVE_DEFAULTS.port,
        SERVE_DEFAULTS.eval_path,
        SERVE_DEFAULTS.concurrency,
        SERVE_DEFAULTS.max_inflight,
        f"{SERVE_DEFAULTS.timeout:g}",
    ):
        assert f"(default {value})" in text
