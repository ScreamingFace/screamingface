"""Allow-listed projections from local runtime state into diagnostic facts."""

from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from types import TracebackType
from urllib.parse import urlsplit

from websockets.exceptions import ConnectionClosed

from screamingface._environment import running_in_notebook
from screamingface.errors import ScreamingFaceError

_DEPENDENCIES = ("httpx", "websockets", "pydantic", "ipywidgets")
_SAFE_DETAIL_KEYS = frozenset(
    {
        "applicable_auth_modes",
        "case_id",
        "error_kind",
        "model",
        "parameter",
        "provider",
        "reason",
        "row_index",
        "stage",
    }
)
_MAX_CHAIN = 8
_MAX_FRAMES = 32
_SAFE_REASON_CODES = frozenset({"unsupported_model_parameter"})


def _client_document() -> dict[str, object]:
    dependencies = {
        package: selected
        for package in _DEPENDENCIES
        if (selected := _package_version(package)) is not None
    }
    return {
        "name": "screamingface-python",
        "version": _package_version("screamingface") or "unknown",
        "host": "notebook" if running_in_notebook() else "cli",
        "platform": sys.platform,
        "architecture": platform.machine() or "unknown",
        "runtime": {
            "name": sys.implementation.name,
            "version": platform.python_version(),
        },
        "dependencies": dependencies,
    }


def _engine_document(engine_url: str) -> dict[str, str]:
    selected = urlsplit(engine_url)
    host = selected.hostname
    if host is None:
        raise ValueError("Engine URL must contain a host")
    mode = "local" if host in {"localhost", "127.0.0.1", "::1"} else "hosted"
    return {"host": host, "mode": mode}


def _error_document(error: BaseException) -> dict[str, object]:
    document: dict[str, object] = {"type": type(error).__name__}
    if isinstance(error, ScreamingFaceError):
        document.update(
            {
                "code": error.code,
                "message": error.message,
                "status": error.status,
                "permanent": error.permanent,
                "retryable": error.retryable,
                "hint": error.hint,
            }
        )
        if details := _safe_details(error.details, code=error.code):
            document["details"] = details
    document["chain"] = _exception_chain(error)
    return {key: value for key, value in document.items() if value is not None}


def _exception_chain(error: BaseException) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and len(values) < _MAX_CHAIN and id(current) not in seen:
        seen.add(id(current))
        item: dict[str, object] = {"type": type(current).__name__}
        if isinstance(current, ScreamingFaceError):
            item["message"] = current.message
            item["code"] = current.code
        if websocket_close := _websocket_close(current):
            item["websocket_close"] = websocket_close
        if frames := _frames(current.__traceback__):
            item["frames"] = frames
        values.append(item)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return values


def _websocket_close(error: BaseException) -> dict[str, object]:
    if not isinstance(error, ConnectionClosed):
        return {}
    selected: dict[str, object] = {}
    for name, close in (("received", error.rcvd), ("sent", error.sent)):
        if close is None:
            continue
        value: dict[str, object] = {"code": close.code}
        if reason := _safe_wire_text(close.reason):
            value["reason"] = reason
        selected[name] = value
    return selected


def _safe_wire_text(value: str) -> str:
    return "".join(character for character in value if character.isprintable())[:256].strip()


def _frames(traceback: TracebackType | None) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    current = traceback
    while current is not None and len(values) < _MAX_FRAMES:
        module = current.tb_frame.f_globals.get("__name__")
        selected_module = module if isinstance(module, str) and module else "unknown"
        values.append(
            {
                "package": selected_module.partition(".")[0],
                "module": selected_module,
                "function": current.tb_frame.f_code.co_name,
                "line": current.tb_lineno,
            }
        )
        current = current.tb_next
    return values


def _safe_details(value: object, *, code: str) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    selected: dict[str, object] = {}
    for key in sorted(_SAFE_DETAIL_KEYS & value.keys()):
        if key == "reason" and code not in _SAFE_REASON_CODES:
            continue
        item = value[key]
        if isinstance(item, (str, int, bool)) or item is None:
            selected[key] = item
        elif isinstance(item, (list, tuple)) and all(isinstance(member, str) for member in item):
            selected[key] = list(item)
    return selected


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


__all__ = ["_client_document", "_engine_document", "_error_document"]
