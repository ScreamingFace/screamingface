"""The study's FutureX and BTF-3 scores, copied from the contributor's crowd-wisdom package.

Source: ``crowd-wisdom-package/3_results_report/committee_kit/metrics.py`` (the scoring kit of the
study "behavior-aware LLM crowds for future prediction"), whole file sha256
2c94cb74d2d990ae168b599df1cc15d94e40107272c66485e455fb5510c150a0. Its author contributes it to
this repository under the repository's Apache-2.0 licence.

Everything below this docstring is that file byte for byte, after its own module docstring.
``tests/unit/inspect/test_local_task_futurex_past_study.py`` pins it; do not edit.
"""
import collections
import statistics


class _NoResponse:
    """Sentinel: nothing responded for this item, so it is UNSCOREABLE, not wrong.

    It lives here, in the lowest layer, so that every consumer of a decision can recognise it. The
    metrics below REFUSE to score it: FutureX excludes a missing prediction from the denominator
    (section 3.4.2), so a NO_RESPONSE reaching a metric means some caller forgot to filter, and
    scoring it as zero would quietly penalise an API failure as if it were a wrong answer.
    """

    def __repr__(self):
        return "NO_RESPONSE"


NO_RESPONSE = _NoResponse()


def _reject_sentinel(value, where):
    if value is NO_RESPONSE:
        raise TypeError(
            f"{where}: got NO_RESPONSE. Items where nothing responded must be filtered out before "
            "scoring, not scored as zero -- see rank.score_entry, which drops them from both sides "
            "of the fraction.")

# BTF-3 -----------------------------------------------------------------------------------------

THRESHOLD = 0.5          # the corpus convention: a probability of exactly 0.5 counts as Yes
ABSTAIN_BRIER = 0.25     # no forecast == a 0.5 forecast == (0.5 - y)^2 == 0.25 for either outcome


def brier(p, y):
    """Squared error of a probability against a 0/1 outcome. Lower is better; 0.25 is a coin."""
    return (p - y) ** 2


def is_correct(p, y, threshold=THRESHOLD):
    """Accuracy reading: which side of the threshold the forecast fell on."""
    return (p >= threshold) == bool(y)


# FutureX ---------------------------------------------------------------------------------------

FX_WEIGHTS = {1: 10, 2: 20, 3: 30, 4: 40}      # the benchmark's own difficulty weights


def f1(gold, got):
    """Set F1 — the level-2 rule. Order is ignored, count is not."""
    g, p = set(gold), set(got)
    if not g and not p:
        return 1.0
    if not g or not p:
        return 0.0
    tp = len(g & p)
    if not tp:
        return 0.0
    prec, rec = tp / len(p), tp / len(g)
    return 2 * prec * rec / (prec + rec)


def ordered_overlap(gold, got):
    """The level-3/4 rule: 1.0 for an exact ordered match, else 0.8 * overlap / len(gold).

    The 0.8 ceiling for an unordered hit is the benchmark's, not ours: getting the right names in
    the wrong order is worth less than getting the ranking right.
    """
    k = len(gold)
    if not k:
        return 0.0
    if list(gold) == list(got):
        return 1.0
    return 0.8 * len(set(gold) & set(got)) / k


def item_score(level, gold, got):
    """One FutureX item, 0.0-1.0. An abstention (got is None) scores 0 — it was asked and gave nothing."""
    _reject_sentinel(got, "item_score")
    if got is None:
        return 0.0
    if level == 1:
        return 1.0 if list(gold) == list(got) else 0.0
    if level == 2:
        return f1(gold, got)
    return ordered_overlap(gold, got)


def tier_weighted(scores_by_level):
    """Combine per-level means with the 10/20/30/40 weights.

    Levels absent from this slice are dropped from BOTH sides of the fraction, so a fold that
    happens to contain no level-4 item is not silently penalised for it.
    """
    present = {lvl: v for lvl, v in scores_by_level.items() if v}
    if not present:
        return None
    num = sum(FX_WEIGHTS[lvl] * statistics.fmean(v) for lvl, v in present.items())
    den = sum(FX_WEIGHTS[lvl] for lvl in present)
    return num / den


def futurex_score(gold, decisions, items):
    """Tier-weighted score over `items`. Every item counts: an abstention contributes 0, not a gap."""
    by_level = collections.defaultdict(list)
    for it in items:
        level, g = gold[it]
        by_level[level].append(item_score(level, g, decisions.get(it)))
    return tier_weighted(by_level)


def btf3_scores(gold, decisions, items):
    """(mean Brier, accuracy) over `items`, with abstentions costing 0.25 and a miss respectively."""
    briers, hits = [], 0
    for it in items:
        p = decisions.get(it)
        _reject_sentinel(p, f"btf3_scores[{it}]")
        if p is None:
            briers.append(ABSTAIN_BRIER)
        else:
            briers.append(brier(p, gold[it]))
            hits += 1 if is_correct(p, gold[it]) else 0
    if not items:
        return None, None
    return statistics.fmean(briers), hits / len(items)
