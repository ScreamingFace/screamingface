from __future__ import annotations

import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings()
    # `log_level` reaches the app's own logger through create_app's logs.configure(); this
    # argument governs uvicorn's loggers, which are a separate tree.
    uvicorn.run(
        "report_intake.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
