from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_attribute_docstrings=True)

    input_tokens: int = Field(
        default=0,
        validation_alias="gen_ai.usage.input_tokens",
        serialization_alias="gen_ai.usage.input_tokens",
    )
    output_tokens: int = Field(
        default=0,
        validation_alias="gen_ai.usage.output_tokens",
        serialization_alias="gen_ai.usage.output_tokens",
    )
    cache_read_tokens: int = Field(
        default=0,
        validation_alias="gen_ai.usage.cache_read_tokens",
        serialization_alias="gen_ai.usage.cache_read_tokens",
    )
    cache_creation_tokens: int = Field(
        default=0,
        validation_alias="gen_ai.usage.cache_creation_tokens",
        serialization_alias="gen_ai.usage.cache_creation_tokens",
    )
    reasoning_tokens: int = Field(
        default=0,
        validation_alias="gen_ai.usage.reasoning_tokens",
        serialization_alias="gen_ai.usage.reasoning_tokens",
    )


class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    input_usd: Decimal = Decimal("0")
    output_usd: Decimal = Decimal("0")
    cache_read_usd: Decimal = Decimal("0")
    cache_creation_usd: Decimal = Decimal("0")
    reasoning_usd: Decimal = Decimal("0")
    total_usd: Decimal
    """The authoritative cost of this scope.

    The per-type fields above are an OPTIONAL partial breakdown: a producer fills in the classes it
    has evidence for and leaves the rest at zero. Only this field is guaranteed to be populated.
    """

    @model_validator(mode="after")
    def _total_covers_components(self) -> "CostBreakdown":
        # WHY bounded-by rather than equal-to (OME-849): a provider may author one amount with no
        # per-class split — OpenRouter reports exactly that — and demanding equality forces the
        # producer to invent a breakdown it does not have, which is a false claim in a structured
        # field. So an INCOMPLETE breakdown is legal.
        # INVARIANT: components may be incomplete, never larger than the whole. A breakdown claiming
        # more than the total is incoherent whichever number you trust, so that half of the old
        # equality rule survives.
        # AIDEV-NOTE: the consumer already behaves this way — screamingface's engine contract warns
        # on a total that disagrees with its components and then uses total_usd. Do not restore
        # equality here without changing that consumer too.
        components = (
            self.input_usd
            + self.output_usd
            + self.cache_read_usd
            + self.cache_creation_usd
            + self.reasoning_usd
        )
        if components > self.total_usd:
            raise ValueError(f"Σ components {components} > total_usd {self.total_usd}")
        return self


class ErrorCauseInfo(BaseModel):
    """The handler's own failure behind an ``intent_error`` (Spec C §13.6)."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    code: str
    permanent: bool = False


class ErrorInfo(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    code: str
    message: str
    permanent: bool = False
    cause: ErrorCauseInfo | None = None
    """Present only when ``code`` is ``intent_error`` and its handler named its own code."""
