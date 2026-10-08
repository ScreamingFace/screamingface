"""The accumulator base both MuSiQue scorers extend, copied from the paper's repo.

Source, pinned to the commit we copied (CC BY 4.0, licence text beside this file):
https://github.com/StonyBrookNLP/musique/blob/922ac98f19a201998dbdae6d7f2887a5258dbdeb/metrics/metric.py

Everything below this docstring is that file byte for byte.
``tests/unit/inspect/test_local_task_musique_vendor.py`` pins it; do not edit.
"""
from typing import Any, Dict


class Metric:
    """
    An abstract class representing a metric which can be accumulated.
    """

    def __call__(self, predictions: Any, gold_labels: Any):
        raise NotImplementedError

    def get_metric(self, reset: bool) -> Dict[str, Any]:
        """
        Compute and return the metric. Optionally also call `self.reset`.
        """
        raise NotImplementedError

    def reset(self) -> None:
        """
        Reset any accumulators or internal state.
        """
        raise NotImplementedError
