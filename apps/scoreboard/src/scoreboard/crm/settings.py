"""Settings of the HubSpot sync job, separate from the web app's `Settings`.

FEATURE: OME-1504. WHY a separate class: the HubSpot token must exist only in the sync job's pod.
Keeping it out of `scoreboard.config.Settings` means the web server that serves public traffic
never holds it, not even as an unused field.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .decisions import Stages

DEFAULT_PUBLIC_BASE_URL = "https://leaderboard.screamingface.ai"


def _comma_list(value: object) -> object:
    if not isinstance(value, str):
        return value
    return tuple(part.strip() for part in value.split(",") if part.strip())


class HubSpotSyncSettings(BaseSettings):
    # INVARIANT: `hide_input_in_errors` — a validation error otherwise echoes every input value,
    # the token included, into the CronJob's crash log.
    model_config = SettingsConfigDict(
        env_prefix="SCOREBOARD_HUBSPOT_", extra="ignore", hide_input_in_errors=True
    )

    # INVARIANT: unset means nothing is sent; dev and staging run this way.
    token: SecretStr | None = None
    pipeline_id: str | None = None
    # The private app's id, as HubSpot's property history names this sync's own writes. Unset
    # means every filled card field counts as someone else's and is never overwritten.
    app_id: str | None = None
    # Comma-separated HubSpot stage ids, in pipeline order (NoDecode: a list, not JSON).
    early_stage_ids: Annotated[tuple[str, ...], NoDecode] = Field(default=())
    submission_stage_ids: Annotated[tuple[str, ...], NoDecode] = Field(default=())
    dropped_out_stage_id: str | None = None
    # Internal people on other domains; `@openmined.org` is always internal.
    internal_emails: Annotated[frozenset[str], NoDecode] = Field(default=frozenset())
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL

    @field_validator("early_stage_ids", "submission_stage_ids", mode="before")
    @classmethod
    def _parse_stage_ids(cls, value: object) -> object:
        return _comma_list(value)

    @field_validator("internal_emails", mode="before")
    @classmethod
    def _parse_internal_emails(cls, value: object) -> object:
        parsed = _comma_list(value)
        if isinstance(parsed, tuple):
            return frozenset(email.lower() for email in parsed)
        return parsed

    @model_validator(mode="after")
    def _complete_when_sending(self) -> HubSpotSyncSettings:
        # INVARIANT: with a token, every id the job writes by is set; a half-configured job would
        # otherwise create cards in no pipeline or skip the Dropped out rule.
        if self.token is None:
            return self
        missing = [
            name
            for name, value in (
                ("SCOREBOARD_HUBSPOT_PIPELINE_ID", self.pipeline_id),
                ("SCOREBOARD_HUBSPOT_DROPPED_OUT_STAGE_ID", self.dropped_out_stage_id),
            )
            if not value
        ]
        if len(self.submission_stage_ids) != 3:  # noqa: PLR2004 - Submission 1, 2 and 3
            missing.append("SCOREBOARD_HUBSPOT_SUBMISSION_STAGE_IDS (exactly 3)")
        if missing:
            msg = "HubSpot sync has a token but is missing: " + ", ".join(missing)
            raise ValueError(msg)
        return self

    def stages(self) -> Stages:
        first, second, third = self.submission_stage_ids
        return Stages(
            early=self.early_stage_ids,
            submissions=(first, second, third),
            dropped_out=self.dropped_out_stage_id or "",
        )
