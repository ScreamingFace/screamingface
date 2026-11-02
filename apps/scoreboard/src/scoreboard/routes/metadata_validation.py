"""Keep every metadata rejection serializable without echoing untrusted input."""

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
                    if tuple(error["loc"][:2]) == ("body", "metadata"):
                        # WHY: type/size errors can also contain deep trees or NaN.
                        # Preserve diagnostics and unrelated field inputs, not metadata.
                        error.pop("input", None)
                raise

        return bounded_errors
