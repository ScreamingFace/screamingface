"""The node's code table (url4 2.0, contracts C2): mounts that code-pointer intents run.

STORY: as a node author I mount a handler at a code path, and a code-pointer intent
runs it in-process. The path stays out of the endpoint table and out of HTTP reach,
so a code handler never becomes a processor candidate.

The mixin is mixed into :class:`~url4.peer.server.Url4Node`, which owns the routing
checks (``_check_routable``, ``_is_eval_path``) and the ``_code`` table it sets up.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from url4.core.code import CodeCall, CodeHandler, invoke_mounted
from url4.core.errors import ParseError
from url4.core.intent import parse_code_pointer


class CodeMounts:
    """The node's code table (url4 2.0, contracts C2).

    A separate registry from endpoints and data routes.
    """

    _code: dict[str, CodeHandler]

    if TYPE_CHECKING:  # WHY: provided by Url4Node; declared here only for the type checker.

        def _check_routable(self, path: str) -> None: ...

        def _is_eval_path(self, path: str) -> bool: ...

    def code(self, path: str) -> Callable[[CodeHandler], CodeHandler]:
        """Mount a code handler at ``path`` (decorator); a code-pointer intent runs it.

        A path under the eval path, or one that is not a plain code path (``?``, ``$``,
        an invalid segment), raises ``ValueError`` at registration.
        """
        self._check_routable(path)
        if self._is_eval_path(path.partition("?")[0]):
            raise ValueError(f"code mount {path!r} is under the eval path")
        if "?" in path or "$" in path:
            raise ValueError(f"code mount {path!r} must be a plain path (no '?' or '$')")
        try:
            parse_code_pointer(path)
        except ParseError as error:
            raise ValueError(f"invalid code path {path!r}: {error}") from error

        def register(handler: CodeHandler) -> CodeHandler:
            self._code[path] = handler
            return handler

        return register

    def has_code(self, pointer: str) -> bool:
        """Whether a code handler is mounted at ``pointer`` (exact path)."""
        return pointer in self._code

    async def invoke_code(self, call: CodeCall) -> object:
        """Run the handler mounted at ``call.pointer``; its raw result."""
        return await invoke_mounted(self._code, call)
