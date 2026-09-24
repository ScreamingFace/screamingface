"""Shared producer vocabulary; independent of logging policy and plugin implementation."""

from enum import StrEnum


class ActivityKind(StrEnum):
    """Four benchmark stages plus model-call detail within an operation."""

    CASE_LOADING = "case_loading"
    ANSWERING = "answering"
    GRADING = "grading"
    AGGREGATION = "aggregation"
    MODEL_CALL = "model_call"
