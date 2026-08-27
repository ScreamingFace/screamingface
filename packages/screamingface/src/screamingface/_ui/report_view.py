"""Notebook rendering for a completed Report (what `report = sf.evaluate()` displays)."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING, Any

from screamingface._ui.style import FUSION_GRADIENT_Y, STYLE

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.report import CandidateResult, MemberResult, Report

# Long free text (a case prompt, a model answer, a judge's reasoning) is shown behind a
# disclosure and clipped: a Report can carry many thousands of words per case, and the
# panel has to stay a summary rather than dumping a transcript into the notebook.
_TEXT_CLIP = 10_000

_STYLE = (
    STYLE
    + f"""<style>
.sf-report{{padding:4px 14px 14px}}
.sf-report__head-row{{display:flex;align-items:flex-start;gap:12px}}
/* the export sits with the identity, not the figures — it exports the whole Report */
.sf-report__dl{{margin-left:auto;flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;
  font:600 12px/1 "IBM Plex Mono",ui-monospace,monospace;text-decoration:none!important;
  color:var(--sf-ink-2)!important;border:1px solid var(--sf-line-2);padding:7px 12px;
  border-radius:0;white-space:nowrap}}
.sf-report__dl:hover{{color:var(--sf-ink)!important;border-color:var(--sf-ink-2);
  background:var(--sf-surface)}}
.sf-report__title{{font-size:28px;font-weight:700;line-height:1.15;letter-spacing:-.01em}}
.sf-report__sub{{font-size:14px;color:var(--sf-ink-2);margin-top:4px}}
/* the receipt strip: outcome tick · what ran · when · the totals, right-aligned */
.sf-report__strip{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  border:1px solid var(--sf-line-2);padding:12px 14px;margin-top:14px}}
.sf-report__tick{{flex:0 0 auto;width:18px;height:18px;display:flex;align-items:center;
  justify-content:center;font-size:12px;font-weight:700;color:var(--sf-success);
  border:1px solid var(--sf-success);background:var(--sf-success-bg)}}
.sf-report__tick--bad{{color:var(--sf-blind);border-color:var(--sf-blind);
  background:var(--sf-blind-bg)}}
.sf-report__strip-id{{font-size:14px;font-weight:600}}
.sf-report__strip-when,.sf-report__receipt{{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:13px;color:var(--sf-ink-3)}}
.sf-report__receipt{{margin-left:auto}}
/* result card: neutral hairline surface — the gradient lives on the SCORE cell alone */
.sf-report__card{{border:1px solid var(--sf-line-2);padding:12px;margin-top:14px;
  display:flex;flex-direction:column;gap:12px}}
.sf-report__card-h{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.sf-report__name{{font-size:14px;font-weight:600}}
.sf-report__ctx{{font-size:13px;color:var(--sf-ink-3)}}
/* hairline separators come from the 1px grid gap over a line-coloured ground */
.sf-report__grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(124px,1fr));
  gap:1px;background:var(--sf-line);border:1px solid var(--sf-line)}}
.sf-report__cell{{background:var(--sf-bg);padding:8px 12px;min-width:0}}
.sf-report__k{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-ink-2)}}
/* figures stay on ONE line — a wrapped number reads as two numbers */
.sf-report__v{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:18px;
  margin-top:4px;font-variant-numeric:tabular-nums;color:var(--sf-ink);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
/* the score cell carries the win: the fusion ramp as its left edge. margin -1px so the
   band overlays the grid border and BECOMES the edge, exactly as the system renders it */
.sf-report__cell--score{{position:relative;padding-left:15px;margin-left:-1px}}
.sf-report__cell--score::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
  background:{FUSION_GRADIENT_Y}}}
.sf-report__v--score{{color:var(--sf-accent)}}
.sf-report__det{{margin-top:14px;border:1px solid var(--sf-line)}}
.sf-report__det>summary{{cursor:pointer;padding:9px 12px;font-size:13px;
  background:var(--sf-surface);color:var(--sf-ink-2);list-style:none}}
.sf-report__det>summary::-webkit-details-marker{{display:none}}
.sf-report__det>summary::before{{content:"\u25b8 ";color:var(--sf-ink-3)}}
.sf-report__det[open]>summary::before{{content:"\u25be "}}
.sf-report__case{{padding:12px;border-top:1px solid var(--sf-line)}}
.sf-report__case-h{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.sf-report__case-id{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-ink-3)}}
.sf-check{{display:flex;align-items:flex-start;gap:10px;padding:8px 0;
  border-top:1px solid var(--sf-line)}}
.sf-check__label{{flex:1 1 auto;font-size:13px;min-width:0}}
.sf-check__why{{color:var(--sf-ink-3);font-size:12px;margin-top:3px}}
.sf-badge{{flex:0 0 auto;display:inline-flex;align-items:center;gap:5px;
  font:600 11px/1 "IBM Plex Mono",ui-monospace,monospace;text-transform:uppercase;
  letter-spacing:.06em;padding:4px 8px;border:1px solid var(--sf-line-2);white-space:nowrap}}
.sf-badge .sq{{width:6px;height:6px;background:var(--sf-ink-3)}}
.sf-badge--ok{{color:var(--sf-success);border-color:var(--sf-success);
  background:var(--sf-success-bg)}}
.sf-badge--ok .sq{{background:var(--sf-success-solid)}}
.sf-badge--bad{{color:var(--sf-blind);border-color:var(--sf-blind);
  background:var(--sf-blind-bg)}}
.sf-badge--bad .sq{{background:var(--sf-blind)}}
/* infra failure is a WARNING state, not a wrong answer — never the incorrect red */
.sf-badge--warn{{color:var(--sf-warning);border-color:var(--sf-warning-solid);
  background:var(--sf-warning-bg)}}
.sf-badge--warn .sq{{background:var(--sf-warning-solid)}}
.sf-report__pre{{margin:8px 0 0;padding:8px;background:var(--sf-surface);
  border:1px solid var(--sf-line);font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:12px;color:var(--sf-ink-2);white-space:pre-wrap;overflow-wrap:anywhere;
  max-height:280px;overflow:auto}}
.sf-report__fail{{margin-top:14px;padding:8px 10px;border-left:2px solid var(--sf-blind);
  background:var(--sf-blind-bg);color:var(--sf-blind);
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;white-space:pre-wrap}}
/* ---- master / detail over cases (pure CSS selection) ---- */
.sf-master{{display:grid;grid-template-columns:minmax(180px,260px) minmax(0,1fr);
  align-items:start}}
.sf-case-radio{{position:absolute;opacity:0;pointer-events:none;width:0;height:0}}
.sf-rail{{border-right:1px solid var(--sf-line);min-width:0}}
.sf-rail__item{{display:flex;align-items:center;gap:8px;padding:9px 12px;cursor:pointer;
  border-bottom:1px solid var(--sf-line);border-left:3px solid transparent;min-width:0}}
.sf-rail__item:hover{{background:var(--sf-surface)}}
.sf-rail__id{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;
  color:var(--sf-ink);white-space:nowrap}}
.sf-rail__who{{font-size:11px;color:var(--sf-ink-3);white-space:nowrap}}
.sf-rail__q{{font-size:12px;color:var(--sf-ink-2);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;min-width:0}}
/* the ✓/✗ marker: a drawn square, never a bare coloured dot */
.sf-mark{{flex:0 0 auto;width:16px;height:16px;display:flex;align-items:center;
  justify-content:center;font-size:11px;font-weight:700;color:var(--sf-success);
  border:1px solid var(--sf-success);background:var(--sf-success-bg)}}
.sf-mark--bad{{color:var(--sf-blind);border-color:var(--sf-blind);
  background:var(--sf-blind-bg)}}
.sf-mark--warn{{color:var(--sf-warning);border-color:var(--sf-warning-solid);
  background:var(--sf-warning-bg)}}
.sf-pane{{display:none;padding:12px 14px;min-width:0}}
.sf-pane__h{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}}
/* the task can run thousands of characters (GDPval work requests) — scroll like the
   answer pane instead of growing unbounded */
.sf-pane__q{{font-size:15px;line-height:1.45;color:var(--sf-ink);white-space:pre-wrap;
  max-height:280px;overflow:auto}}
.sf-detail__k{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-ink-3);margin-top:14px}}
.sf-check__who{{display:block;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11px;color:var(--sf-ink-3);margin-top:2px}}
.sf-report__run{{margin-left:auto;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11px;color:var(--sf-ink-3)}}
.sf-chips{{display:flex;flex-wrap:wrap;gap:6px}}
.sf-chip{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  color:var(--sf-ink-2);border:1px solid var(--sf-line-2);padding:2px 7px}}
.sf-axes{{display:flex;flex-direction:column;margin-top:6px;border:1px solid var(--sf-line)}}
.sf-axis{{display:grid;grid-template-columns:minmax(0,1fr) 76px 96px;gap:10px;
  padding:6px 10px;border-bottom:1px solid var(--sf-line);align-items:center}}
.sf-axis:last-child{{border-bottom:0}}
.sf-axis__k{{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sf-axis__v,.sf-axis__r{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13px;
  font-variant-numeric:tabular-nums;text-align:right}}
.sf-axis__r{{color:var(--sf-ink-3)}}
/* grading trouble is a WARNING, not a failure: the run completed, the evidence thinned */
/* a WARNING role, never gold — gold in this system means the win, not 'be careful' */
.sf-report__warn{{padding:8px 10px;border-left:2px solid var(--sf-warning-solid);
  background:var(--sf-warning-bg);color:var(--sf-warning);font-size:12px}}
.sf-members{{display:flex;flex-direction:column;margin-top:6px;border:1px solid var(--sf-line)}}
.sf-member{{display:grid;grid-template-columns:minmax(0,1.1fr) 70px minmax(0,1.4fr) 76px 76px;
  gap:10px;padding:7px 10px;border-bottom:1px solid var(--sf-line);align-items:center;
  font-size:13px}}
.sf-member:last-child{{border-bottom:0}}
.sf-member__n{{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sf-member__k,.sf-member__m{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  color:var(--sf-ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sf-member__d,.sf-member__u{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;
  font-variant-numeric:tabular-nums;text-align:right;color:var(--sf-ink-2)}}
.sf-report__det--tight{{margin-top:0}}
.sf-steps{{display:flex;flex-wrap:wrap;gap:6px;padding:10px 12px 0}}
.sf-step{{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--sf-line-2);
  padding:2px 8px}}
.sf-step__k{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-ink-3)}}
.sf-step__l{{font-size:12px;color:var(--sf-ink-2)}}
@media(max-width:680px){{.sf-report__receipt{{margin-left:0;width:100%}}
  .sf-member{{grid-template-columns:1fr 70px}}
  .sf-member__m,.sf-member__d,.sf-member__u{{display:none}}
  .sf-master{{grid-template-columns:1fr}}
  .sf-rail{{border-right:0;border-bottom:1px solid var(--sf-line)}}}}
</style>"""
)


def report_html(report: Report) -> str:
    """Render a completed Report as one self-contained panel."""

    cards = "".join(_card_html(item, report) for item in report.candidates)
    return (
        f"{_STYLE}<div class='sf-ui sf-report' aria-label='ScreamingFace evaluation report'>"
        f"{_head_html(report)}"
        f"{_strip_html(report)}"
        f"{cards}"
        f"{_failures_html(report)}"
        f"{_cases_html(report)}</div>"
    )


def _head_html(report: Report) -> str:
    return (
        "<div class='sf-report__head-row'><div>"
        "<div class='sf-report__title'>Report</div>"
        f"<div class='sf-report__sub'>Benchmark · {escape(str(report.benchmark.id))}</div>"
        f"</div>{_download_html(report)}</div>"
    )


def _download_html(report: Report) -> str:
    """Export the portable artifact as a real file.

    A `data:` URI on a download anchor, because notebook HTML is routinely stripped of
    <script> — a JS-built Blob would render as a dead button. The whole Report is
    base64'd inline, so this grows the saved .ipynb by roughly 4/3 of the JSON size.
    """

    try:
        payload = report.to_json()
    except Exception:
        # Export is a convenience; a Report that cannot serialise must still render.
        return ""
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    stem = re.sub(r"[^a-z0-9]+", "-", str(report.benchmark.id).lower()).strip("-") or "report"
    size = _bytes(len(payload.encode("utf-8")))
    return (
        f"<a class='sf-report__dl' download='{escape(stem)}-report.json' "
        f"href='data:application/json;base64,{encoded}' "
        f"title='Download the full report.to_json() artifact'>"
        f"&darr; report.json <span style='opacity:.6'>{escape(size)}</span></a>"
    )


def _bytes(count: int) -> str:
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{count / 1024:.0f} KB"
    return f"{count / (1024 * 1024):.1f} MB"


def _strip_html(report: Report) -> str:
    """The receipt: did it run clean, what against, when, and what it cost in total."""

    ok = report.ok
    tick = "sf-report__tick" + ("" if ok else " sf-report__tick--bad")
    mark = "&check;" if ok else "&times;"
    usage = report.usage
    cases = f"{report.case_count} case" + ("" if report.case_count == 1 else "s")
    receipt = " · ".join(
        (
            "cost " + ("—" if usage.cost_usd is None else _money(usage.cost_usd)),
            f"{_tokens(usage)} tokens",
            cases,
            _duration(report.duration_ms),
        )
    )
    revision = getattr(report.benchmark, "revision", None)
    identity = str(report.benchmark.id) + (f" · rev {revision}" if revision else "")
    return (
        f"<div class='sf-report__strip'><span class='{tick}' aria-hidden='true'>{mark}</span>"
        f"<span class='sf-report__strip-id'>{escape(identity)}</span>"
        f"<span class='sf-report__strip-when'>{escape(_stamp(report.completed_at))}</span>"
        f"<span class='sf-report__receipt'>{escape(receipt)}</span></div>"
    )


def _card_html(candidate: CandidateResult, report: Report) -> str:
    """One candidate's result card: identity, the figures grid, then what it was made of."""

    metrics = candidate.metrics
    usage = candidate.usage
    if candidate.score is None:
        state = "incomplete"
    elif candidate.coverage < 1.0:
        state = "partial"
    elif candidate.failures:
        state = "complete with warnings"
    else:
        state = "complete"
    runs = _metric(metrics, "n_runs")
    # Repeat count belongs in the context line: a 7th figure would orphan a grid row.
    repeats = f" · {int(runs)} runs" if runs and runs > 1 else ""
    ctx = f"· {report.benchmark.id} · {state}{repeats}"
    # The fusion edge marks a rankable result. Any finite benchmark-native score —
    # including zero and negative (HealthBench worst-30 is all-negative) — is a real
    # outcome worth highlighting; only an unscored candidate stays neutral (OME-866:
    # a `> 0` gate here was a leftover 0..1 accuracy assumption).
    scored = candidate.score is not None
    cells = [
        _cell("score", _score_text(candidate.score), score=scored),
        _cell("pass rate", _percent(_metric(metrics, "pass_rate"))),
        _cell("coverage", _percent(candidate.coverage)),
        # WHY (OME-793): the two dash meanings differ — cost is "not reported by this
        # run" (a pipeline gap), while partial or unavailable scores get explicit context.
        _cell(
            "cost",
            "—" if usage.cost_usd is None else _money(usage.cost_usd),
            title="cost not reported by this run" if usage.cost_usd is None else "",
        ),
        _cell("tokens", _tokens_total(usage)),
        _cell("duration", _duration(candidate.duration_ms)),
    ]
    return (
        "<div class='sf-report__card'><div class='sf-report__card-h'>"
        f"<span class='sf-report__name'>{escape(candidate.name)}</span>"
        f"<span class='sf-report__ctx'>{escape(ctx)}</span>"
        f"<span class='sf-report__run'>{escape(_short(candidate.run_id))}</span></div>"
        f"{_models_html(candidate)}"
        f"<div class='sf-report__grid'>{''.join(cells)}</div>"
        f"{_coverage_notice_html(candidate)}"
        f"{_axes_html(metrics)}"
        f"{_grading_html(metrics)}"
        f"{_members_html(candidate)}"
        f"{_recipe_html(candidate)}</div>"
    )


def _coverage_notice_html(candidate: CandidateResult) -> str:
    """Explain Engine-owned partial coverage or an unavailable aggregate score."""

    if candidate.score is not None:
        if candidate.coverage < 1.0:
            heading = "partial evaluation"
            message = (
                "score covers "
                f"{escape(_percent(candidate.coverage))} of selected cases; ungraded cases "
                "were excluded by the Engine."
            )
        elif candidate.failures:
            heading = "completed with warnings"
            count = len(candidate.failures)
            label = "warning" if count == 1 else "warnings"
            message = (
                f"{count} {label}; the score covers all selected cases; inspect the retained "
                "Candidate failures for details."
            )
        else:
            return ""
    else:
        heading = "score unavailable"
        states = tuple(_case_state(case) for case in candidate.cases)
        incomplete = tuple(state for state in states if state in {"refused", "failed", "unscored"})
        message = ""
        if incomplete:
            total = len(candidate.cases)
            parts = tuple(
                f"{incomplete.count(state)} {state}"
                for state in ("refused", "failed", "unscored")
                if state in incomplete
            )
            message = (
                f"{len(incomplete)} of {total} cases not scored ({', '.join(parts)}); "
                "no aggregate score is available."
            )
            message += _candidate_failure_suffix(candidate)
        elif candidate.failures:
            count = len(candidate.failures)
            label = "failure" if count == 1 else "failures"
            message = (
                f"candidate execution reported {count} {label}; no aggregate score is available."
            )
    return f"<div class='sf-report__warn'>{heading} — {message}</div>" if message else ""


def _candidate_failure_suffix(candidate: CandidateResult) -> str:
    count = len(candidate.failures)
    if not count:
        return ""
    label = "failure" if count == 1 else "failures"
    return f" Candidate execution also reported {count} {label}."


def _models_html(candidate: CandidateResult) -> str:
    """Which models actually ran — the first thing you ask of any score."""

    if not candidate.models:
        return ""
    chips = "".join(f"<span class='sf-chip'>{escape(model)}</span>" for model in candidate.models)
    return f"<div class='sf-chips'>{chips}</div>"


def _axes_html(metrics: Any) -> str:
    """Per-axis scores say WHERE the score came from, not just how big it was."""

    axes = metrics.get("axis_scores") if metrics else None
    if not isinstance(axes, Mapping) or not axes:
        return ""
    rates = metrics.get("axis_pass_rates")
    rates = rates if isinstance(rates, Mapping) else {}
    rows = "".join(_axis_row(name, value, rates.get(name)) for name, value in axes.items())
    return f"<div class='sf-detail__k'>by axis</div><div class='sf-axes'>{rows}</div>"


def _axis_row(name: object, score: object, rate: object) -> str:
    """Pass rate is only shown when it says something the score does not.

    With one binary criterion on an axis the two are identical by construction; printing
    both would imply a second, independent measurement that does not exist.
    """

    score_value, rate_value = _number(score), _number(rate)
    extra = (
        f"{_percent(rate_value)} pass"
        if rate_value is not None and rate_value != score_value
        else ""
    )
    return (
        f"<div class='sf-axis'><span class='sf-axis__k'>{escape(str(name))}</span>"
        f"<span class='sf-axis__v'>{_percent(score_value)}</span>"
        f"<span class='sf-axis__r'>{extra}</span></div>"
    )


def _grading_html(metrics: Any) -> str:
    """Only shown when grading itself misfired — silence here means every verdict landed."""

    if not metrics:
        return ""
    trouble = {
        name: int(_metric(metrics, f"verdicts_{name}") or 0)
        for name in ("rejected", "invalid", "missing")
    }
    if not any(trouble.values()):
        return ""
    detail = " · ".join(f"{count} {name}" for name, count in trouble.items() if count)
    expected = int(_metric(metrics, "verdicts_expected") or 0)
    suffix = f" of {expected} verdicts" if expected else ""
    return (
        "<div class='sf-report__warn'>Grading did not fully land: "
        f"{escape(detail)}{escape(suffix)} — the score rests on fewer verdicts than planned."
        "</div>"
    )


def _members_html(candidate: CandidateResult) -> str:
    """A Fusion's direct members — the participants behind a fused answer."""

    if not candidate.members:
        return ""
    # WHY: display names are cosmetic and may collide (the same model reached via two
    # providers); identity is the operation_id, so a collision disambiguates here at
    # render — with the provider — instead of failing a run that was already paid for.
    names = [member.name for member in candidate.members]
    duplicated = {name for name in names if names.count(name) > 1}
    rows = "".join(
        "<div class='sf-member'>"
        f"<span class='sf-member__n'>{escape(_member_display_name(member, duplicated))}</span>"
        f"<span class='sf-member__k'>{escape(member.kind)}</span>"
        f"<span class='sf-member__m'>{escape(', '.join(member.models))}</span>"
        f"<span class='sf-member__d'>"
        f"{'—' if member.duration_ms is None else _duration(member.duration_ms)}</span>"
        f"<span class='sf-member__u'>"
        f"{'—' if member.usage is None else _tokens_total(member.usage)}</span></div>"
        for member in candidate.members
    )
    return f"<div class='sf-detail__k'>members</div><div class='sf-members'>{rows}</div>"


def _member_display_name(member: MemberResult, duplicated: set[str]) -> str:
    if member.name not in duplicated or not member.models:
        return member.name
    provider = member.models[0].split("/", 1)[0]
    return f"{member.name} ({provider})" if provider else member.name


def _recipe_html(candidate: CandidateResult) -> str:
    """The URL4 expression is the candidate's identity — kept folded, it is enormous.

    Shown as the expression, NOT as an absolute link. The Engine executes it as
    ``GET {engine}/?q=<expression>`` carrying a freshly minted ``URL4-Capability``
    header, with events arriving over a separate WebSocket attach — so a bare URL is
    not independently runnable, and a Report does not carry the Engine origin anyway.
    """

    steps = "".join(
        f"<div class='sf-step'><span class='sf-step__k'>{escape(op.kind)}</span>"
        f"<span class='sf-step__l'>{escape(op.label)}</span></div>"
        for op in candidate.operations
    )
    steps_html = f"<div class='sf-steps'>{steps}</div>" if steps else ""
    return (
        "<details class='sf-report__det sf-report__det--tight'><summary>URL4</summary>"
        f"{steps_html}<pre class='sf-report__pre'>{escape(_clip(candidate.url4, 1200))}</pre>"
        "</details>"
    )


def _cell(key: str, value: str, *, score: bool = False, title: str = "") -> str:
    """One figure. The score cell is the card's hero — it alone takes the fusion edge."""

    cell_class = "sf-report__cell" + (" sf-report__cell--score" if score else "")
    value_class = "sf-report__v" + (" sf-report__v--score" if score else "")
    title_attr = f" title='{escape(title)}'" if title else ""
    return (
        f"<div class='{cell_class}'{title_attr}><div class='sf-report__k'>{escape(key)}</div>"
        f"<div class='{value_class}'>{escape(value)}</div></div>"
    )


def _stamp(moment: Any) -> str:
    return moment.strftime("%-d %b, %H:%M")


def _failures_html(report: Report) -> str:
    """The failure banner names every failed case — a bare message forces raw-JSON triage.

    Identical failures (same stage · code · message) collapse into ONE line carrying every
    affected case id, so three dead cases read as one diagnosis, not three mysteries
    (OME-793: the worst30 fusion incident rendered 3 id-less duplicate lines).
    """

    failures = report.failures
    if not failures:
        return ""
    groups: dict[tuple[str, str, str], list[Any]] = {}
    for item in failures:
        key = (
            str(getattr(item, "stage", "?")),
            str(getattr(item, "code", "") or ""),
            str(getattr(item, "message", item)),
        )
        groups.setdefault(key, []).append(item)
    lines = "\n".join(_failure_line(key, items) for key, items in groups.items())
    count = f"{len(failures)} failure" + ("" if len(failures) == 1 else "s")
    details = json.dumps(
        [item.to_dict() for item in failures],
        ensure_ascii=False,
        indent=2,
    )
    return (
        f"<div class='sf-report__fail' role='alert'>{escape(count)}\n{escape(lines)}</div>"
        "<details><summary>failure details</summary>"
        f"<pre class='sf-report__pre'>{escape(details)}</pre></details>"
    )


def _failure_line(key: tuple[str, str, str], items: list[Any]) -> str:
    stage, code, message = key
    case_ids = [
        str(value)
        for value in (getattr(item, "case_id", None) for item in items)
        if value is not None
    ]
    # A failure with no code and no case identity keeps the plain `stage · message` shape.
    if not code and not case_ids:
        return f"{stage} · {message}"
    head = " · ".join(part for part in (stage, code) if part)
    cases = ""
    if case_ids:
        label = "case" if len(case_ids) == 1 else "cases"
        cases = f" · {label} {', '.join(case_ids)}"
    underlying = next(
        (found for found in (_first_collected_error(item) for item in items) if found), ""
    )
    return f"{head}{cases} — {message}{underlying}"


def _first_collected_error(failure: Any) -> str:
    """Pull `(Kind: message)` out of a failure's collected_errors metadata, if present."""

    metadata = getattr(failure, "metadata", None)
    collected = metadata.get("collected_errors") if isinstance(metadata, Mapping) else None
    first = collected[0] if isinstance(collected, list | tuple) and collected else None
    error = first.get("error") if isinstance(first, Mapping) else None
    kind = error.get("kind") if isinstance(error, Mapping) else None
    message = error.get("message") if isinstance(error, Mapping) else None
    if not kind and not message:
        return ""
    return f" ({kind}: {message})" if kind else f" ({message})"


def _cases_html(report: Report) -> str:
    """Master/detail over every case: a rail of outcomes beside the selected case.

    Selection is pure CSS (a radio group + `:checked ~` sibling rules). Notebook HTML is
    routinely sanitised of <script>, so a JS-driven widget would silently render dead.
    """

    entries = [(candidate, case) for candidate in report.candidates for case in candidate.cases]
    if not entries:
        return ""
    # Group name must be unique per rendered Report, or two reports in one notebook would
    # share a radio group and fight over the selection. Candidate run IDs are unique.
    group = f"sf-case-{_group_key(report)}"
    inputs, rail, panes = [], [], []
    for index, (candidate, case) in enumerate(entries):
        item = f"{group}-{index}"
        checked = " checked" if index == 0 else ""
        inputs.append(
            f"<input class='sf-case-radio' type='radio' name='{group}' id='{item}'{checked}>"
        )
        rail.append(_rail_item(item, candidate, case, len(report.candidates) > 1))
        panes.append(_pane_html(candidate, case))
    total = len(entries)
    label = f"{total} case result" + ("" if total == 1 else "s")
    return (
        f"<details class='sf-report__det' open><summary>{escape(label)}</summary>"
        f"{_selection_css(group, total)}"
        f"<div class='sf-master'>{''.join(inputs)}"
        f"<div class='sf-rail'>{''.join(rail)}</div>"
        f"<div class='sf-detail'>{''.join(panes)}</div></div></details>"
    )


def _selection_css(group: str, total: int) -> str:
    """Wire each radio to its pane and rail row.

    One rule pair per case, scoped to this Report's group id — `:checked ~` can only
    reach forward to siblings, which is why the inputs are emitted before both columns.
    """

    rules = []
    for index in range(total):
        item = f"{group}-{index}"
        nth = index + 1
        rules.append(
            f"#{item}:checked~.sf-detail>.sf-pane:nth-child({nth}){{display:block}}"
            f"#{item}:checked~.sf-rail>.sf-rail__item:nth-child({nth})"
            f"{{background:var(--sf-surface);border-left-color:var(--sf-accent)}}"
        )
    return f"<style>{''.join(rules)}</style>"


def _group_key(report: Report) -> str:
    names = "|".join(candidate.run_id for candidate in report.candidates)
    return f"{abs(hash(names)) % 10**8:08d}"


def _rail_item(item: str, candidate: CandidateResult, case: CaseResult, show_who: bool) -> str:
    state = _case_state(case)
    # WHY (OME-793): a failed case gets the warning mark, never the incorrect ✗ — the rail
    # must not present an infra failure as a graded wrong answer.
    mark = (
        "sf-mark"
        + {
            "passed": "",
            "incorrect": " sf-mark--bad",
            "refused": " sf-mark--warn",
            "failed": " sf-mark--warn",
            "unscored": " sf-mark--warn",
        }[state]
    )
    glyph = {
        "passed": "&check;",
        "incorrect": "&times;",
        "refused": "!",
        "failed": "!",
        "unscored": "?",
    }[state]
    who = f" <span class='sf-rail__who'>{escape(candidate.name)}</span>" if show_who else ""
    preview = _clip(case.prompt_preview, 90) if case.input is not None else "input unavailable"
    return (
        f"<label class='sf-rail__item' for='{item}'>"
        f"<span class='{mark}' aria-hidden='true'>{glyph}</span>"
        f"<span class='sf-rail__id'>case {escape(str(case.case_id))}</span>{who}"
        f"<span class='sf-rail__q'>{escape(preview)}</span></label>"
    )


def _pane_html(candidate: CandidateResult, case: CaseResult) -> str:
    state = _case_state(case)
    # WHY (OME-793): tri-state verdict — "failed" (warning) is neither correct nor
    # incorrect; the case was never graded, and the badge must say so.
    if state in {"refused", "failed", "unscored"}:
        verdict = _badge(state, good=False, warn=True)
    else:
        verdict = _badge("correct" if state == "passed" else "incorrect", good=state == "passed")
    grade = case.grade
    checks = "".join(_check_html(check) for check in (grade.checks if grade else ()))
    checks_head = (
        "<div class='sf-detail__k'>criteria · the judge's verdict and reasoning</div>"
        if checks
        else ""
    )
    answer = _clip(case.output)
    answer_html = (
        f"<div class='sf-detail__k'>answer</div><pre class='sf-report__pre'>{escape(answer)}</pre>"
        if answer
        else ""
    )
    refusal_html = (
        "<div class='sf-detail__k'>provider refusal</div>"
        f"<pre class='sf-report__pre'>{escape(case.refusal)}</pre>"
        if case.refusal is not None
        else ""
    )
    # A non-"stop" finish is a quality signal in its own right: a truncated answer can
    # fail criteria for reasons that have nothing to do with the model's knowledge.
    finish = case.finish_reason
    finish_html = _badge(f"finish · {finish}", good=False) if finish and finish != "stop" else ""
    rounds_html = ""
    if case.stop_reason is not None and case.rounds_executed is not None:
        noun = "round" if case.rounds_executed == 1 else "rounds"
        reason = "passed" if case.stop_reason == "passed" else "round limit"
        rounds_html = _badge(
            f"loop · {reason} · {case.rounds_executed} {noun}",
            good=case.stop_reason == "passed",
        )
    tags = "".join(
        f"<span class='sf-chip'>{escape(str(key))} · {escape(str(value))}</span>"
        for key, value in (case.metadata or {}).items()
    )
    tags_html = f"<div class='sf-chips' style='margin-top:8px'>{tags}</div>" if tags else ""
    if case.input is not None:
        # same clip budget as the answer — the pane scrolls, so no need to cut at a glance-size
        question = f"<div class='sf-pane__q'>{escape(_clip(case.display_input))}</div>"
    else:
        # INVARIANT (OME-793): absence is stated, never rendered as an empty body — a
        # failed case's input was not retained by the Engine (see OME-784 for fixing that).
        question = (
            "<div class='sf-pane__q'>input unavailable — "
            "the case failed before it was recorded</div>"
        )
    return (
        "<div class='sf-pane'><div class='sf-pane__h'>"
        f"<span class='sf-report__case-id'>case {escape(str(case.case_id))} · "
        f"{escape(candidate.name)}</span>{verdict}{finish_html}{rounds_html}</div>{tags_html}"
        f"{question}{answer_html}{refusal_html}{_case_failures_html(case)}"
        f"{checks_head}{checks}</div>"
    )


def _case_failures_html(case: CaseResult) -> str:
    """The failure chain IS the failed case's content — stage, code, message, evidence."""

    if not case.failures:
        return ""
    lines = "\n".join(
        f"{failure.stage} · {failure.code} — {failure.message}{_first_collected_error(failure)}"
        for failure in case.failures
    )
    details = json.dumps(
        [failure.to_dict() for failure in case.failures],
        ensure_ascii=False,
        indent=2,
    )
    return (
        "<div class='sf-detail__k'>failures</div>"
        f"<div class='sf-report__fail'>{escape(lines)}</div>"
        "<details><summary>failure details</summary>"
        f"<pre class='sf-report__pre'>{escape(details)}</pre></details>"
    )


def _case_passed(case: CaseResult) -> bool:
    """A case passes only when it was graded and every JUDGED check landed the desired way.

    WHY judged-only (OME-848): a check without an outcome was never decided — counting
    it as failed painted every DRACO case INCORRECT while its outcomes went unemitted.
    Absence must not masquerade as a verdict; with no judged checks at all, the score
    is the only signal, exactly like the no-checks fallback below.
    """

    grade = case.grade
    if grade is None:
        return False
    judged = [check for check in grade.checks if check.outcome is not None]
    if judged:
        return all(_check_good(check) for check in judged)
    return grade.score is not None and grade.score > 0


def _case_state(case: CaseResult) -> str:
    """Present the Engine outcome without re-deriving it from Benchmark semantics."""

    if case.status == "refused":
        return "refused"
    if case.status == "failed":
        return "unscored" if case.grade is not None else "failed"
    return "passed" if _case_passed(case) else "incorrect"


def _check_negative(check: Any) -> bool:
    """A negative criterion, in either Benchmark vocabulary (OME-900).

    DRACO names polarity outright (`criterion_type: negative`); HealthBench carries it
    as the sign of the rubric item's `points`. One rule reads both so no rubric
    benchmark's penalties can masquerade as positives.
    """

    metadata = check.metadata or {}
    if str(metadata.get("criterion_type", "")).lower() == "negative":
        return True
    points = metadata.get("points")
    return isinstance(points, int | float) and not isinstance(points, bool) and points < 0


def _check_good(check: Any) -> bool:
    """MET is only good news on a POSITIVE criterion; a negative criterion inverts it."""

    met = ("" if check.outcome is None else str(check.outcome)).upper() == "MET"
    return not met if _check_negative(check) else met


def _check_html(check: Any) -> str:
    """One criterion: its verdict, who judged it, and why — the participant-row analogue."""

    # An undecided check gets the neutral warn badge (OME-848): red would claim a miss
    # and green a pass — verdicts nobody rendered.
    if check.outcome is None:
        badge = _badge("unjudged", good=False, warn=True)
    else:
        # INVARIANT (OME-900): the chip TEXT is the score consequence (PASS helped,
        # FAIL hurt) so word and color always agree — the judge's polarity-blind
        # MET/UNMET stays in the tooltip, because that raw verdict is what archives
        # store and the paper's vocabulary; it is derived here, never rewritten.
        good = _check_good(check)
        gloss = ""
        if _check_negative(check):
            gloss = " (avoided)" if good else " (did the thing to avoid)"
        badge = _badge(
            "PASS" if good else "FAIL",
            good=good,
            title=f"judge: {check.outcome}{gloss}",
        )
    judge = next(
        (item.producer.id for item in check.evidence if getattr(item, "producer", None)),
        None,
    )
    why = next((item.explanation for item in check.evidence if item.explanation), None)
    judge_html = f"<span class='sf-check__who'>{escape(judge)}</span>" if judge else ""
    why_html = f"<div class='sf-check__why'>{escape(_clip(why, 400))}</div>" if why else ""
    return (
        f"<div class='sf-check'><span class='sf-check__label'>{escape(check.label)}"
        f"{judge_html}{why_html}</span>{badge}</div>"
    )


def _badge(text: str, *, good: bool, warn: bool = False, title: str | None = None) -> str:
    variant = "sf-badge--warn" if warn else ("sf-badge--ok" if good else "sf-badge--bad")
    tooltip = f" title='{escape(title)}'" if title else ""
    return f"<span class='sf-badge {variant}'{tooltip}><i class='sq'></i>{escape(text)}</span>"


def _metric(metrics: Any, name: str) -> float | None:
    if not metrics:
        return None
    value = metrics.get(name)
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _short(value: str, keep: int = 12) -> str:
    return value if len(value) <= keep else f"{value[:keep]}…"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _score_text(value: float | None) -> str:
    # INVARIANT (OME-866): CandidateResult.score is benchmark-native — render the
    # Engine-graded number as-is (DRACO 0.399, HealthBench -1.143), never ×100 or
    # percent. `:g` keeps up to 6 significant digits. This is the ONE score
    # formatter — the submit receipt (score_view) and board widget
    # (leaderboard_view) import it, and the portal mirrors the 6-digit rule
    # (formatScore in portal/main.js), so the same figure never renders two ways
    # between the notebook and the board.
    return "—" if value is None else f"{float(value):g}"


def _tokens_total(usage: Any) -> str:
    """One figure for the cell — the in/out split is carried by the receipt strip."""

    if usage.input_tokens is None and usage.output_tokens is None:
        return "—"
    return _compact((usage.input_tokens or 0) + (usage.output_tokens or 0))


def _tokens(usage: Any) -> str:
    if usage.input_tokens is None and usage.output_tokens is None:
        return "—"
    return f"{_compact(usage.input_tokens or 0)} / {_compact(usage.output_tokens or 0)}"


def _compact(value: int) -> str:
    if value < 1_000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1_000:.1f}k"
    return f"{value / 1_000_000:.1f}M"


def _money(value: Decimal) -> str:
    if value != 0 and abs(value) < Decimal("0.01"):
        return f"${value:.4f}"
    return f"${value:,.2f}"


def _duration(milliseconds: int) -> str:
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _clip(value: object, limit: int = _TEXT_CLIP) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… {len(text) - limit:,} more characters"


__all__: list[str] = []
