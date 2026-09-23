"""Runner-local failures translated by the URL4 connector boundary."""

from __future__ import annotations

from screamingface_engine.model_outcomes import ModelOutcome


class RunnerRequestError(ValueError):
    """A model-request failure with stable wire semantics but no URL4 dependency."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        permanent: bool,
        outcome: ModelOutcome | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.permanent = permanent
        self.outcome = outcome
