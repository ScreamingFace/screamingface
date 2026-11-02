"""Keep request errors encodable despite invalid Unicode or non-finite numbers."""

import json
from math import isfinite

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.responses import Response


def _contains_non_finite(value: object) -> bool:
    # WHY: validation inputs can be malformed nested shapes; inspect them without
    # recursion and without changing any otherwise valid error input.
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not isfinite(item):
            return True
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return False


async def safe_request_validation_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    # WHY: JSON has no representation for NaN/Infinity. Omit the unsafe input,
    # preserving the rejection's location/type/context and all other inputs.
    for error in exc.errors():
        if _contains_non_finite(error.get("input")):
            error.pop("input", None)
    # INVARIANT: ordinary 422 responses keep FastAPI's exact shape and UTF-8 encoding.
    try:
        return await request_validation_exception_handler(request, exc)
    except UnicodeEncodeError:
        # WHY: Pydantic echoes input and locations, including malformed shapes that never
        # reach field validators. JSON escapes preserve that detail without another 500.
        content = json.dumps(
            {"detail": jsonable_encoder(exc.errors())},
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        return Response(content=content, status_code=422, media_type="application/json")
