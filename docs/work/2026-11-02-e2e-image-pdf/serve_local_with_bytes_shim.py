"""TEST SHIM ONLY (OME-1551 e2e): start `screamingface-engine serve --local` with one patch.

Finding F2: local mode wraps every run's io in `FairShareIOLayer`, which forwards fetch_ex,
fetch_holdings, processor_routes and default_route but NOT `fetch_bytes`, so url4 refuses every
https attachment source with `unsupported_mode`. This shim forwards `fetch_bytes` through the
same gate, exactly as the class forwards `fetch_ex`, so the rest of the path can be exercised.
It is not a fix and lives only in this evidence directory.
"""

import json
import os
import sys
import time

from screamingface_engine.runner import fair_share

_original_init = fair_share.FairShareIOLayer.__init__


def _init(self, inner, gate, run):  # type: ignore[no-untyped-def]
    _original_init(self, inner, gate, run)
    inner_fetch_bytes = getattr(inner, "fetch_bytes", None)
    if inner_fetch_bytes is not None:

        async def fetch_bytes(request):  # type: ignore[no-untyped-def]
            # Evidence: one line per outbound attachment fetch (the fixture-hit count).
            log = os.environ.get("E2E_FETCH_LOG")
            if log:
                with open(log, "a") as f:
                    f.write(
                        json.dumps(
                            {
                                "t": time.time(),
                                "run": run,
                                "url": request.target,
                                "accept": request.accept,
                            }
                        )
                        + "\n"
                    )
            await gate.acquire(run)
            try:
                return await inner_fetch_bytes(request)
            finally:
                gate.release(run)

        self.fetch_bytes = fetch_bytes


fair_share.FairShareIOLayer.__init__ = _init

from screamingface_engine.cli import main  # noqa: E402

main(sys.argv[1:] or ["serve", "--local"])
