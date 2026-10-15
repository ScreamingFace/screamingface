# PRD: Display format of the Combine views (component)

**Source:** ans:Q3 · **Priority:** P0
**Lifecycle:** planned (new private module)
**Owner:** unassigned
Paths: [erd §6](../erd.md) · used by: [case-pane](case-pane.md), [run-summary](run-summary.md)

## 1. Summary and user story

As a researcher who reads the Combine views, I want each number short, the exact stored value on
hover, and a reason for each missing value, so that I can scan the table and still check the exact
data.

## 2. Background and constraints

- Owner answer: "Short + exact on hover (Recommended)": 4 significant digits; the exact stored
  value in a title tooltip; a missing value is an em dash with its reason. [stated ans:Q3]
- House conventions: the score shows `:g` (6 significant digits) [existing S/_ui/report_view.py:1167-1175];
  a missing figure is `—` with a `title` [existing S/_ui/report_view.py:370-375,597-606]; all data
  text goes through `html.escape` [existing S/_ui/report_view.py:9]; attribute values are in single
  quotes [existing S/_ui/report_view.py:604].
- Some existing tests assert that a token is NOT in the report HTML (for example
  `"abstained" not in report_html(without)`, `ST/test_case_abstained.py:158`). The new style rules
  are in every report, so they must not hold such a token. [existing]

### 2.1 Current behavior

There is no Combine view. The values exist in `CombineEvidence` and the trace.
[existing S/combine_evidence.py:48-106,259-389]

**Delta.** A new private module `S/_ui/combine_view.py` holds the format helpers and the style
rules. [proposed] P5–P9, P17

```python
"""The Combine views of the report (E4b part 4): the Case pane section and the run summary.

INVARIANT: every text from data goes through html.escape; a float shows 4 significant digits and
its exact stored value as the title (ans:Q3); a missing value is an em dash with its reason.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screamingface.combine_evidence import CombineAnswerRow

_DASH = "—"
_TEXT_CELL = 80  # characters of a member value shown in one cell (P7)

COMBINE_CSS = "\n".join(
    (
        ".sf-cmb{margin-top:6px;overflow-x:auto}",
        ".sf-cmb__t{width:100%;border-collapse:collapse;margin-top:6px;font-size:12px;"
        "font-variant-numeric:tabular-nums}",
        '.sf-cmb__t th{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;'
        "font-weight:600;text-align:left;color:var(--sf-ink-2);padding:4px 8px;"
        "border-bottom:1px solid var(--sf-line-2)}",
        ".sf-cmb__t td{padding:4px 8px;border-bottom:1px solid var(--sf-line);"
        "color:var(--sf-ink);overflow-wrap:anywhere}",
        ".sf-cmb__out td{color:var(--sf-ink-3)}",
        ".sf-cmb__na,.sf-cmb__nn{color:var(--sf-ink-3)}",
        ".sf-cmb__na,.sf-cmb__n{cursor:help}",
        ".sf-cmb__h{font-size:13px;font-weight:600;margin-top:10px}",
        ".sf-cmb__nn{font-size:11px}",
    )
)


def number_html(value: float | None, reason: str) -> str:
    """A float at 4 significant digits, the exact stored value as its title; None: a dash."""
    if value is None:
        return dash_html(reason)
    return (
        f"<span class='sf-cmb__n' title='{escape(repr(value))}'>"
        f"{escape(format(value, '.4g'))}</span>"
    )


def dash_html(reason: str) -> str:
    """The missing-value mark: an em dash whose title is the reason (ans:Q3)."""
    return f"<span class='sf-cmb__na' title='{escape(reason)}'>{_DASH}</span>"


def text_html(value: str | None, reason: str) -> str:
    """A member value: escaped, at most 80 characters then an ellipsis; None: a dash."""
    if value is None:
        return dash_html(reason)
    shown = value if len(value) <= _TEXT_CELL else value[:_TEXT_CELL] + "…"
    return escape(shown)


def missing_reason(row: CombineAnswerRow, label: str) -> str:
    """Why a cell of this member row is empty (MR-1..MR-3, P6)."""
    if row.status == "fail":
        return f"member failed: {row.reason}"
    if row.status == "excluded":
        return f"left out by the rule: {row.reason}"
    return f"no {label} recorded"


__all__: list[str] = []
```

`S/_ui/report_view.py`: import `COMBINE_CSS` and put `{COMBINE_CSS}` into the `_STYLE` f-string on
its own line, directly before the line that starts `@media(max-width:680px)`
[existing S/_ui/report_view.py:203]. Do not add a `<style>` tag.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DF-1** Given these floats, then `number_html(v, "x")` shows the text and the title in the table.
  Hand-computed with Python `format(v, ".4g")` and `repr(v)`:

  | v | text | title |
  |---|---|---|
  | `0.123456` | `0.1235` | `0.123456` |
  | `90.0` | `90` | `90.0` |
  | `2 / 3` | `0.6667` | `0.6666666666666666` |
  | `12345.678` | `1.235e+04` | `12345.678` |
  | `-1.5` | `-1.5` | `-1.5` |
  | `0.0` | `0` | `0.0` |

  The exact HTML for the first row is
  `<span class='sf-cmb__n' title='0.123456'>0.1235</span>`. [stated ans:Q3]
- **DF-2** Given `None`, then `number_html(None, "member failed: empty")` is exactly
  `<span class='sf-cmb__na' title='member failed: empty'>—</span>` (U+2014), and
  `text_html(None, "member failed: empty")` is the same. [stated ans:Q3]
- **DF-3** Given a text of 80 characters, then `text_html` returns it unchanged; given 81
  characters (`"x" * 81`), then it returns `"x" * 80 + "…"` (U+2026). [proposed] P7

### 3.2 Error paths

- **DF-E1** Given a reason `a<b'c&`, then the title is `a&lt;b&#x27;c&amp;`. [proposed] P8
- **DF-E2** Given the value `<img src=x onerror=evil()>`, then `text_html` returns
  `&lt;img src=x onerror=evil()&gt;`, and the result has no `<img`. [proposed] P8

### 3.3 Derived scenarios (risk-ordered)

- **DF-D1** (M×H) [proposed] `missing_reason` follows the status (P6). With the SDK fixture
  `vote_one_failed`: member_2 (`fail`, `empty`) and label `value` → `member failed: empty`;
  member_1 (`answered`) and label `weight` → `no weight recorded`. With the `rank_cut_not_met` wire
  ([case-pane](case-pane.md) §7): member_2 (`excluded`, `no_signal`) and label `score` →
  `left out by the rule: no_signal`.
- **DF-D2** (M×M) [existing] The score formatter keeps 6 significant digits:
  `_score_text(0.123456789) == "0.123457"`. The new format does not replace it.
- **DF-D3** (M×M) [proposed] P9 Every rule of `COMBINE_CSS` has selectors that start with
  `.sf-cmb`; it has no `#`, no `<`, and none of the tokens `abstained`, `excluded`, `incorrect`,
  `graded`, `reasoning`, `cost`, `scores`, ` — `, ` · `. `COMBINE_CSS` is in `_STYLE` once, inside
  the last `<style>…</style>` block, and the number of `<style` in `_STYLE` does not change.
- **DF-D4** (M×L) [stated ans:Q1] The module adds no public name: `combine_view.__all__ == []`.

## 4. Non-functional requirements

- Pure functions, no I/O. [proposed]
- Theme: colors come only from the `--sf-*` variables, so light and dark themes work.
  [existing S/_ui/style.py]

## 5. Out of scope

- A locale-aware number format. [proposed]
- A new score format: `_score_text` stays the one score formatter. [existing S/_ui/report_view.py:1167-1175]

## 6. Open questions

None.

## 7. TDD plan

Test file: `ST/test_combine_display_format.py` (new). RED commit: `combine_view.py` with the four
functions raising `NotImplementedError` and `COMBINE_CSS = ""`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `score_text_keeps_six_significant_digits` | unit | DF-D2 | M×M | passes today and after |
| 2 | CHAR `cost_cell_dash_has_a_title` | unit | [existing S/_ui/report_view.py:370-375] | M×L | `_cell("cost", "—", title="cost not reported by this run")` holds `title='cost not reported by this run'` and `—` |
| 3 | `number_shows_four_significant_digits_and_the_exact_title` | unit | DF-1 | M×H | `format(v, ".4g")`, `repr(v)`; parametrize the DF-1 table |
| 4 | `missing_number_is_an_em_dash_with_its_reason` | unit | DF-2 | M×H | `dash_html` |
| 5 | `reason_in_the_title_is_escaped` | unit | DF-E1 | H×M | `escape` (quote=True) |
| 6 | `text_cell_clips_at_80_characters` | unit | DF-3 | L×M | `_TEXT_CELL` |
| 7 | `text_cell_escapes_markup` | unit | DF-E2 | H×M | `escape` |
| 8 | `missing_text_is_an_em_dash_with_its_reason` | unit | DF-2 | M×M | `text_html(None, …)` |
| 9 | `missing_reason_follows_the_status` | unit | DF-D1 | M×H | MR-1..MR-3 |
| 10 | `combine_css_is_scoped_themed_and_has_no_banned_token` | unit | DF-D3 | M×M | the rule list above, `{COMBINE_CSS}` in `_STYLE` |
| 11 | `combine_view_adds_no_public_name` | unit | DF-D4 | M×L | `__all__ = []`; `ST/test_public_surface.py` stays green |
