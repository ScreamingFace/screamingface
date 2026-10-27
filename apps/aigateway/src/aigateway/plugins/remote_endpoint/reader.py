"""Read the remote-endpoint config from a private TOML file, bounded before parsing.

# INVARIANT: this is the only file access the feature has; definitions and instances never read
# files, so another source (a database, a publisher) can feed `parse_remote_endpoint_config` later.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .definitions import (
    RemoteEndpointConfig,
    RemoteEndpointConfigError,
    parse_remote_endpoint_config,
)

MAX_CONFIG_BYTES = 1024 * 1024


def read_remote_endpoint_config(path: Path) -> RemoteEndpointConfig:
    """Parse and validate the whole file; any problem refuses it with a sanitized reason."""
    try:
        with path.open("rb") as handle:
            # WHY one byte over: it tells "exactly the limit" from "larger" without reading more.
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except OSError:
        raise RemoteEndpointConfigError("remote endpoint config is unreadable") from None
    if len(raw) > MAX_CONFIG_BYTES:
        raise RemoteEndpointConfigError("remote endpoint config exceeds 1 MiB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RemoteEndpointConfigError("remote endpoint config is not UTF-8") from None
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        # WHY only line and column: the decoder's message may quote part of the document. Python
        # 3.14 adds them as attributes; earlier runtimes report no location.
        line, column = getattr(exc, "lineno", None), getattr(exc, "colno", None)
        where = f" at line {line}, column {column}" if line is not None else ""
        raise RemoteEndpointConfigError(
            f"remote endpoint config is not valid TOML{where}"
        ) from None
    return parse_remote_endpoint_config(document)
