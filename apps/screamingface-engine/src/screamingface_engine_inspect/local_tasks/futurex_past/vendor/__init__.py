"""COPIED code: the crowd-wisdom study's scoring kit. Do not edit below the header.

What this is
    ``study_metrics.py`` is ``committee_kit/metrics.py`` from the contributor's crowd-wisdom study
    package ("behavior-aware LLM crowds for future prediction"). Its upstream code, after the
    module docstring, has sha256
    b9a81867c34e6b76f581456809afc2b99024e18358e08a64bb18f23303676176
    (whole file 2c94cb74d2d990ae168b599df1cc15d94e40107272c66485e455fb5510c150a0). The study's
    package carries no licence of its own. Its author contributes this file to this repository
    under the repository's Apache-2.0 licence.

Why a copy
    ``futurex_past_study`` exists to reproduce the study's published FutureX-Past numbers (spec
    ``docs/spec/2026-11-16-futurex-past-local-task.md`` §10). The number means the study's number
    only while the code that computes it is the study's code, so the code is copied, not
    re-implemented.

The ONLY change we made
    The module docstring is ours: a header naming the source. The test
    ``tests/unit/inspect/test_local_task_futurex_past_study.py`` drops it and requires the upstream
    code sha256 above, so any other edit fails CI.
"""
