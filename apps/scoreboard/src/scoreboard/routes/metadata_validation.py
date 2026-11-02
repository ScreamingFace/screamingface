"""Keep metadata rejection bounded even when the rejected input is deeply nested."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute


class MetadataValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def bounded_errors(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                for error in exc.errors():
                    if error["type"] in {"metadata_too_deep", "metadata_non_finite"}:
                        # WHY: deep trees and non-finite numbers cannot be safely echoed
                        # as JSON. Preserve location/type/context and all other errors.
                        error.pop("input", None)
                raise

        return bounded_errors
