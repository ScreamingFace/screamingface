from __future__ import annotations

import logging

import uvicorn

from .config import Settings

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str) -> None:
    """Give the `scoreboard` loggers a level and a stderr handler.

    INVARIANT (MRA-1): the admin audit line (C10) is an INFO record on `scoreboard.routes.admin`.
    `uvicorn.run(log_level=...)` configures only the `uvicorn*` loggers, so without this the root
    logger stays at WARNING with no handler and every audit line is dropped in production.
    AIDEV-NOTE: idempotent. A second call sets the level again and adds no second handler.
    """
    logger = logging.getLogger("scoreboard")
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "scoreboard.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
