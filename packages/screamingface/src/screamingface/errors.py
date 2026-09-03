"""Small public exception hierarchy at the SF Client/Engine boundary."""

from __future__ import annotations

from urllib.parse import urlsplit


class ScreamingFaceError(Exception):
    """Base class for expected failures at the public Client interface."""

    _default_code: str = "screamingface_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        permanent: bool | None = None,
        details: object = None,
        hint: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.message: str = message
        self.code: str = code or self._default_code
        self.status: int | None = status
        self.permanent: bool | None = permanent
        self.details: object = details
        self.hint: str | None = hint if hint is not None else _default_hint(self.code)
        # WHY on the BASE class and not on ExecutionError alone (OME-967): the failures this
        # id exists to make joinable are the ones BEFORE the first frame — capability mint,
        # run start, WS handshake — and those raise EngineUnavailableError and
        # AuthenticationError, never ExecutionError. Narrowing the field to ExecutionError
        # would leave exactly the class the ticket was filed for without an id.
        self.trace_id: str | None = trace_id
        super().__init__(message)

    @property
    def user_message(self) -> str:
        """Concise safe text for notebooks, CLIs, and other presentation adapters."""

        if self.hint is None:
            return self.message
        return f"{self.message}\n\nHint: {self.hint}"

    @property
    def retryable(self) -> bool | None:
        """Whether retrying may succeed without changing the request."""

        return None if self.permanent is None else not self.permanent

    def _render_traceback_(self) -> list[str]:
        """Render expected failures concisely in IPython without a global exception hook."""

        rendered = [f"{type(self).__name__}: {self.message}"]
        if self.hint is not None:
            rendered.append(f"Hint: {self.hint}")
        rendered.append(f"Code: {self.code}")
        # WHY rendered and not merely retained (OME-967): the Client already receives a
        # traceparent on every event and has zero read sites for it. An id the user cannot
        # read is an id they cannot quote in a report, which is the whole point of holding it.
        if self.trace_id is not None:
            rendered.append(f"Trace: {self.trace_id}")
        return ["\n".join(rendered)]


class _DiagnosticError(ScreamingFaceError):
    """Internal grouping for the stable diagnostic fields on handled errors."""


class AuthenticationError(_DiagnosticError):
    """The configured SF Engine rejected caller authentication."""

    _default_code: str = "authentication_failed"


class PlanningError(_DiagnosticError):
    """An Evaluation could not be resolved or validated safely."""

    _default_code: str = "planning_failed"


class ExecutionError(_DiagnosticError):
    """A Run ended without a valid Report."""

    _default_code: str = "execution_failed"


class ProviderConnectionError(_DiagnosticError):
    """A provider connection could not be read or updated safely."""

    _default_code: str = "provider_connection_failed"

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        code: str | None = None,
        status: int | None = None,
        permanent: bool | None = None,
        details: object = None,
        hint: str | None = None,
    ) -> None:
        self.provider: str | None = provider
        super().__init__(
            message,
            code=code,
            status=status,
            permanent=permanent,
            details=details,
            hint=hint,
        )


class LeaderboardError(_DiagnosticError):
    """A public Scoreboard operation could not be completed safely."""

    _default_code: str = "leaderboard_failed"

    def __init__(
        self,
        message: str,
        *,
        scoreboard_url: str | None = None,
        code: str | None = None,
        status: int | None = None,
        permanent: bool | None = None,
        details: object = None,
        hint: str | None = None,
    ) -> None:
        self.scoreboard_url: str | None = scoreboard_url
        if hint is None and code == "scoreboard_unreachable":
            hint = _scoreboard_hint(scoreboard_url)
        super().__init__(
            message,
            code=code,
            status=status,
            permanent=permanent,
            details=details,
            hint=hint,
        )


class EngineUnavailableError(_DiagnosticError):
    """The configured SF Engine could not be reached."""

    def __init__(self, message: str, *, engine_url: str, trace_id: str | None = None) -> None:
        self.engine_url: str = engine_url
        # WHY this subclass forwards the id and its two siblings do not (OME-967): this is
        # the error of the pre-first-frame failures — capability mint, run start, WS
        # handshake. `ProviderConnectionError` and `LeaderboardError` are raised on paths
        # that originate no client trace today; they gain the parameter when they do.
        super().__init__(
            message,
            code="engine_unreachable",
            permanent=False,
            hint=_engine_hint(engine_url),
            trace_id=trace_id,
        )


def _default_hint(code: str | None) -> str | None:
    if code == "engine_unreachable":
        return "Check that the configured SF Engine is running and reachable."
    if code == "authentication_required":
        return "Call `client.login()` and retry the operation."
    return None


def _engine_hint(engine_url: str) -> str:
    hostname = urlsplit(engine_url).hostname
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return (
            "Start the local Engine with `uv run url4-cloud serve --local`, "
            "or configure a different `engine_url`."
        )
    return (
        "Check that the configured SF Engine is running and reachable, "
        "or configure a different `engine_url`."
    )


def _scoreboard_hint(scoreboard_url: str | None) -> str:
    hostname = urlsplit(scoreboard_url).hostname if scoreboard_url is not None else None
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return (
            "Start the local stack with `screamingface up`, or configure a different "
            "`scoreboard_url`."
        )
    return (
        "Check that the configured Scoreboard is reachable, "
        "or configure a different `scoreboard_url`."
    )


__all__ = [
    "AuthenticationError",
    "EngineUnavailableError",
    "ExecutionError",
    "LeaderboardError",
    "PlanningError",
    "ProviderConnectionError",
    "ScreamingFaceError",
]
