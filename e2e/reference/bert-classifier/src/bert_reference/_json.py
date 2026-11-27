import json
from typing import Never, cast


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _no_constant(_: str) -> Never:
    raise ValueError("invalid JSON number")


def decode_object(raw: bytes | bytearray) -> dict[str, object]:
    value: object = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_no_constant
    )
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return cast(dict[str, object], value)
