"""Keep request validation errors encodable even when the rejected input is not UTF-8."""

import json

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.responses import Response


async def safe_request_validation_handler(
    request: Request, exc: RequestValidationError
) -> Response:
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
