"""LiteLLM-compatible AI gateway for ScreamingFace."""

import os

# WHY: litellm decides which parameters each model accepts (``reasoning_effort`` among them)
# from its model map, which it loads once, at import (``litellm/__init__.py``:
# ``model_cost = get_model_cost_map(url=model_cost_map_url)``). That loader
# (``litellm/litellm_core_utils/get_model_cost_map.py``, litellm 1.102.1) first checks
#     if os.getenv("LITELLM_LOCAL_MODEL_COST_MAP", "").lower() == "true":
#         -> return the JSON copy shipped inside the litellm package
# and otherwise downloads the map from litellm's GitHub main branch, using the shipped copy
# only when the download fails. Left alone, then, the gateway's behaviour can change on a
# restart with no deploy and no lockfile change: on 2026-10-15 the downloaded map had lost
# all 269 OpenRouter entries, and every OpenRouter call that sent a reasoning setting failed
# inside litellm as a provider error. Forcing the map bundled with the pinned litellm version
# ties it to ``uv.lock``, so it changes only when a reviewed PR upgrades litellm.
# INVARIANT: set here, in the package's first module, before anything imports litellm; and set,
# not defaulted, so an inherited ``False`` cannot reopen the download.
# ``tests/unit/test_litellm_model_map_pinned.py`` pins it.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

__version__ = "1.0.0"
