# VENDORED COPY -- sources (PyPI releases, the versions in apps/screamingface-engine/uv.lock):
#   inspect-ai 0.3.263:   inspect_ai/scorer/_common.py, inspect_ai/_util/text.py,
#                         inspect_ai/scorer/_unicode.py
#   inspect-evals 0.20.0: inspect_evals/utils/aime_common.py
# Local changes: this banner, the module docstring, the pin constants and VENDORED_NAMES below,
# and the selection (only the names in VENDORED_NAMES). Every copied definition is byte-identical;
# tests/unit/inspect/test_combine_inspect_vendor_drift.py enforces it. Do not edit.
#
# MIT License
#
# Copyright (c) 2024 UK AI Security Institute
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Inspect's numeric answer rule, copied so a combine plugin can use it (OME-1289, E4a, RX/GP).

FEATURE: ``inspect_number@1``, ``inspect_aime@1`` and ``inspect_numeric@1`` read and compare a
number exactly as inspect-ai ``match(numeric=True)`` and inspect-evals ``aime_scorer`` do.
WHY a copy: a combine plugin imports neither ``inspect_ai`` (a heavy optional extra) nor any module
on the plugin deny list (``random``, ``logging``, ...), which the upstream modules pull in.
INVARIANT: every definition below is byte-identical to the one in the pinned release. The drift
test compares the source of each name in ``VENDORED_NAMES`` with the installed package, and it
fails when the pinned versions change. To upgrade, copy the new definitions and move the pins.
AIDEV-NOTE: the upstream ``_unicode.py`` keeps module-level sets and dicts (for example
``_CH_DEC_WORDS``). They are never mutated here and never imported by an operator module, so the
"no module-level mutable state" check does not scan this file.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Optional, Tuple, cast

INSPECT_AI_VERSION = "0.3.263"
INSPECT_EVALS_VERSION = "0.20.0"
PINNED_PYTHON = (3, 13)  # the engine image (Dockerfile:54)
UNIDATA_VERSION = "15.1.0"  # unicodedata on PINNED_PYTHON
VENDORED_NAMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "inspect_ai.scorer._unicode",
        (
            "unicode_number_to_float",
            "_SUPERSCRIPT_DIGITS",
            "_SUPERSCRIPT_SIGNS",
            "_SUPERSCRIPT_TRANS",
            "_split_superscript_exponent",
            "_fraction_char_value",
            "_parse_number_with_optional_vulgar_fraction",
            "_parse_core_number_no_leading_signs",
            "_consume_leading_signs",
            "_try_single_char_numeric",
            "_MINUS_CHARS",
            "_PLUS_CHARS",
            "_DECIMAL_SEP_EXTRAS",
            "_GROUP_SEPARATORS",
            "_CH_DIGITS",
            "_CH_ALT_TENS",
            "_CH_SMALL_UNITS",
            "_CH_LARGE_UNITS",
            "_CH_NEG",
            "_CH_POS",
            "_CH_DEC_WORDS",
            "_looks_like_chinese_numeral",
            "_parse_generic_unicode_digits",
            "_char_to_ascii_digit",
            "_parse_chinese_number",
            "_parse_chinese_integer_with_units",
        ),
    ),
    ("inspect_ai._util.text", ("strip_numeric_punctuation",)),
    (
        "inspect_ai.scorer._common",
        (
            "_NUMERIC_PUNCTUATION_TRIM",
            "_clean_numeric_word",
            "_parse_number",
            "_is_number",
            "first_number_normalized",
            "normalize_number",
        ),
    ),
    (
        "inspect_evals.utils.aime_common",
        ("remove_boxed_from_ans", "_DELIMITER_ONLY_RE", "_find_last_substantive_line"),
    ),
)


# ---- inspect_ai/scorer/_unicode.py ----------------------------------------------------------

def unicode_number_to_float(s: str) -> float:
    """
    Convert a Unicode number string to a Python float.

    Supports:
      • Unicode vulgar fractions embedded in the base:  '2½', '−½', '十二⅓'
      • Superscript exponents:                          '3²', '1.5⁻³', '⅔³'
    while preserving:
      • Chinese numerals (十/百/千/万/億/兆, 零/〇/○, 两/兩, financial forms; 點/点 decimals)
      • Digits from many scripts, Unicode signs, mixed separators
      • Single-char numerics (Ⅻ, ½, ⅔, etc.)
      • ASCII scientific notation 'e'/'E' in the base

    Precedence:
      - Leading sign binds to the base, then superscript exponent is applied:
        '-2²' → (-2)**2 == 4.0;  '-½²' → (-0.5)**2 == 0.25.

    Raises ValueError if the input cannot be interpreted as a number.
    """
    if not isinstance(s, str):
        raise TypeError("Input must be a str")

    text = s.strip()
    if not text:
        raise ValueError("Empty string")

    # 1) Consume leading signs (ASCII/Unicode/Chinese). Keep sign with the base.
    text, base_is_negative = _consume_leading_signs(text)

    # 2) If what's left is a single numeric symbol (e.g., ½, Ⅻ), handle fast-path.
    single = _try_single_char_numeric(text)
    if single is not None:
        base_value = float(single)
        if base_is_negative:
            base_value = -base_value
        return base_value

    # 3) Split off a trailing superscript exponent, if present (e.g., '³', '⁻²').
    base_text, exp = _split_superscript_exponent(text)

    # 4) Parse base (no leading sign here), with optional embedded vulgar fraction.
    parsed_base_value = _parse_number_with_optional_vulgar_fraction(base_text)
    if parsed_base_value is None:
        raise ValueError(f"Could not parse number from {s!r}")
    base_value = parsed_base_value

    if base_is_negative:
        base_value = -base_value

    # 5) Apply superscript exponent if any.
    if exp is not None:
        try:
            result = base_value**exp
        except Exception as exc:
            raise ValueError(f"Invalid exponent operation for {s!r}: {exc}") from exc
        return float(result)

    return float(base_value)


# ---- Superscript exponent handling -----------------------------------------

_SUPERSCRIPT_DIGITS = set("⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUPERSCRIPT_SIGNS = {"⁻", "⁺"}
_SUPERSCRIPT_TRANS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


def _split_superscript_exponent(s: str) -> Tuple[str, Optional[int]]:
    """If s ends with superscript digits (optionally preceded by a superscript sign), return (base_without_exponent, exponent_int). Otherwise return (s, None).

    Whitespace at the end is ignored for detection. If removing the exponent
    would leave an empty base (e.g., '²'), we do NOT treat it as an exponent.
    """
    if not s:
        return s, None

    # Ignore trailing whitespace/group separators to find the superscript tail
    end = len(s) - 1
    while end >= 0 and (s[end].isspace() or s[end] in _GROUP_SEPARATORS):
        end -= 1
    if end < 0:
        return s.strip(), None

    j = end
    # Collect superscript digits from the end
    while j >= 0 and s[j] in _SUPERSCRIPT_DIGITS:
        j -= 1
    start = j + 1

    # No superscript digits -> no exponent
    if start > end:
        return s.strip(), None

    # Optionally include a single leading superscript sign
    if j >= 0 and s[j] in _SUPERSCRIPT_SIGNS:
        start = j

    base = s[:start].rstrip()
    exponent_text = s[start : end + 1]

    # If the base would be empty, don't treat it as an exponent (e.g., '²')
    if not base:
        return s.strip(), None

    exp_ascii = exponent_text.translate(_SUPERSCRIPT_TRANS)
    # Must contain digits (not just a '+'/'-')
    if exp_ascii in ("", "+", "-") or all(c in "+-" for c in exp_ascii):
        raise ValueError(f"Invalid exponent in {s!r}")

    try:
        exp_val = int(exp_ascii)
    except Exception:
        raise ValueError(f"Invalid exponent in {s!r}")
    return base, exp_val


# ---- Vulgar fraction handling (embedded in base) ----------------------------


def _fraction_char_value(ch: str) -> Optional[float]:
    """Return numeric value if ch is a 'vulgar fraction'-like character (0<val<1)."""
    try:
        val = unicodedata.numeric(ch)
    except Exception:
        return None
    return float(val) if 0.0 < val < 1.0 else None


def _parse_number_with_optional_vulgar_fraction(s: str) -> Optional[float]:
    """Parse a number possibly containing a single embedded vulgar fraction char.

    Examples: '2½', '１２½', '十二⅓', '½'  (signs already removed).
    """
    if not s:
        return None

    # Find any single 'fraction-like' char (0<unicodedata.numeric(ch)<1)
    frac_hits = [(i, _fraction_char_value(ch)) for i, ch in enumerate(s)]
    frac_hits = [(i, v) for i, v in frac_hits if v is not None]

    if not frac_hits:
        return _parse_core_number_no_leading_signs(s)

    if len(frac_hits) > 1:
        raise ValueError(f"Multiple fraction characters in {s!r}")

    idx, frac_val = frac_hits[0]
    head = s[:idx].strip()
    tail = s[idx + 1 :].strip()

    # The tail after a vulgar fraction must be empty or just separators/space
    if tail and any(not (c.isspace() or c in _GROUP_SEPARATORS) for c in tail):
        raise ValueError(f"Unexpected characters after fraction in {s!r}")

    # Parse the head (it might be empty, or Chinese, or any supported digits)
    if head:
        parsed_head_val = _parse_core_number_no_leading_signs(head)
        if parsed_head_val is None:
            raise ValueError(f"Invalid base part in {s!r}")
        head_val = parsed_head_val
    else:
        head_val = 0.0

    return head_val + cast(float, frac_val)


# ---- Core number parsing (no leading signs here) ----------------------------


def _parse_core_number_no_leading_signs(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None

    # Chinese numerals?
    if _looks_like_chinese_numeral(s):
        val = _parse_chinese_number(s)
        if val is not None:
            return float(val)

    # Generic Unicode digits with locale-like separators and ASCII e/E notation
    gen = _parse_generic_unicode_digits(s)
    if gen is not None:
        return float(gen)

    # Last-chance: a single numeric symbol (Ⅻ, Ⅴ, etc.)
    if len(s) == 1:
        return _try_single_char_numeric(s)

    return None


# ---- Shared helpers & original parsing utilities ----------------------------


def _consume_leading_signs(s: str) -> Tuple[str, bool]:
    """Remove leading plus/minus (ASCII/Unicode) and Chinese 正/负(負).

    Returns (remaining_text, is_negative).
    Multiple minus signs toggle: '−-+3' -> negative if odd number of minuses.
    """
    neg = False
    text = s.lstrip()
    while text:
        ch = text[0]
        if ch in _MINUS_CHARS or ch in _CH_NEG:
            neg = not neg
            text = text[1:].lstrip()
            continue
        if ch in _PLUS_CHARS or ch in _CH_POS:
            text = text[1:].lstrip()
            continue
        break
    return text, neg


def _try_single_char_numeric(s: str) -> Optional[float]:
    if len(s) == 1:
        try:
            return float(unicodedata.numeric(s))
        except Exception:
            return None
    return None


# Unicode signs and separators
_MINUS_CHARS = {"-", "−", "﹣", "－"}  # hyphen-minus, minus sign, small, fullwidth
_PLUS_CHARS = {"+", "＋", "﹢"}
_DECIMAL_SEP_EXTRAS = {"٫", "．"}  # Arabic decimal sep, fullwidth dot
_GROUP_SEPARATORS = {
    ",",
    "，",
    "﹐",
    "、",
    "٬",
    " ",
    "\u00a0",
    "\u202f",
    "\u2009",
    "\u2007",
    "\u2008",
    "'",
    "’",
    "ʼ",
    "＇",
}

# Chinese numerals and symbols
_CH_DIGITS = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "壹": 1,
    "贰": 2,
    "貳": 2,
    "叁": 3,
    "參": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "陸": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
    "两": 2,
    "兩": 2,
    "幺": 1,
}
_CH_ALT_TENS = {"廿": 20, "卅": 30, "卌": 40}
_CH_SMALL_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CH_LARGE_UNITS = {
    "万": 10_000,
    "萬": 10_000,
    "亿": 100_000_000,
    "億": 100_000_000,
    "兆": 1_000_000_000_000,
}
_CH_NEG = {"负", "負"}
_CH_POS = {"正"}
_CH_DEC_WORDS = {"点", "點"}


def _looks_like_chinese_numeral(s: str) -> bool:
    pool = (
        set(_CH_DIGITS)
        | set(_CH_SMALL_UNITS)
        | set(_CH_LARGE_UNITS)
        | _CH_DEC_WORDS
        | _CH_NEG
        | _CH_POS
        | set(_CH_ALT_TENS)
    )
    return any(ch in pool for ch in s)


def _parse_generic_unicode_digits(s: str) -> Optional[float]:
    """Parse numbers composed of digits across scripts, with locale-ish decimal/grouping and ASCII e/E.

    Leading signs should already be removed by the caller.
    """
    s = s.strip()
    if not s:
        return None

    dot_positions = [i for i, ch in enumerate(s) if ch == "."]
    comma_positions = [i for i, ch in enumerate(s) if ch == ","]

    # Choose decimal mark heuristic
    decimal_char: Optional[str] = None
    if dot_positions and comma_positions:
        decimal_char = "." if dot_positions[-1] > comma_positions[-1] else ","
    elif dot_positions:
        decimal_char = "."
    elif comma_positions:
        last = comma_positions[-1]
        tail_digits = sum(
            1 for ch in s[last + 1 :] if _char_to_ascii_digit(ch) is not None
        )
        if tail_digits in (1, 2, 3) and "." not in s:
            decimal_char = ","

    out: list[str] = []
    seen_decimal = False
    seen_exp = False

    i = 0
    while i < len(s):
        ch = s[i]

        # ASCII scientific notation exponent
        if ch in ("e", "E") and not seen_exp:
            if not out:
                return None
            out.append(ch)
            seen_exp = True
            i += 1
            if i < len(s) and (s[i] in _PLUS_CHARS or s[i] in _MINUS_CHARS):
                out.append("+" if s[i] in _PLUS_CHARS else "-")
                i += 1
            continue

        # treat only the chosen decimal as decimal
        if ch in _DECIMAL_SEP_EXTRAS or (decimal_char and ch == decimal_char):
            if seen_decimal:
                return None  # keep strict behavior on a 2nd decimal
            out.append(".")
            seen_decimal = True
            i += 1
            continue

        # treat the *other* punctuation as grouping
        if (
            ch in _GROUP_SEPARATORS
            or ch.isspace()
            or (decimal_char and ch in {",", "."} and ch != decimal_char)
        ):
            i += 1
            continue

        # Digits across scripts
        dig = _char_to_ascii_digit(ch)
        if dig is not None:
            out.append(dig)
            i += 1
            continue

        # Whitespace → skip
        if ch.isspace():
            i += 1
            continue

        # Chinese numerals encountered → let the Chinese parser handle at higher level
        if (
            ch in _CH_DEC_WORDS
            or ch in _CH_DIGITS
            or ch in _CH_SMALL_UNITS
            or ch in _CH_LARGE_UNITS
            or ch in _CH_ALT_TENS
        ):
            return None

        # Unknown symbol → fail
        return None

    if not out or all(c in {".", "e", "E", "+", "-"} for c in out):
        return None

    try:
        return float("".join(out))
    except Exception:
        return None


def _char_to_ascii_digit(ch: str) -> Optional[str]:
    if "0" <= ch <= "9":
        return ch
    try:
        return str(unicodedata.decimal(ch))
    except Exception:
        pass
    try:
        d = unicodedata.digit(ch)
        return str(d)
    except Exception:
        pass
    if ch in _CH_DIGITS:
        return str(_CH_DIGITS[ch])
    return None


def _parse_chinese_number(s: str) -> Optional[float]:
    """Parse a Chinese numeral string (no leading sign here).

    Supports 點/点 as decimal and large units up to 兆. Does not implement '三分之二'.
    """
    if not s:
        return None

    s = s.strip()

    # Split integer / fractional on Chinese or fullwidth/ASCII dot
    integer_part = s
    frac_part = ""
    for dec in list(_CH_DEC_WORDS) + ["．", "."]:
        if dec in s:
            integer_part, _, frac_part = s.partition(dec)
            break

    # Digits-only Chinese (e.g., 二〇二五)
    if not any(
        ch in _CH_SMALL_UNITS or ch in _CH_LARGE_UNITS or ch in _CH_ALT_TENS
        for ch in integer_part
    ):
        digits = []
        for ch in integer_part:
            if ch.isspace():
                continue
            d = _char_to_ascii_digit(ch)
            if d is None:
                return None
            digits.append(d)
        int_val = int("".join(digits)) if digits else 0
    else:
        parsed_int_val = _parse_chinese_integer_with_units(integer_part)
        if parsed_int_val is None:
            return None
        int_val = parsed_int_val

    frac_val = 0.0
    if frac_part:
        base = 0.1
        for ch in frac_part:
            if ch.isspace():
                continue
            d = _char_to_ascii_digit(ch)
            if d is None:
                return None
            frac_val += int(d) * base
            base /= 10.0

    return float(int_val) + frac_val


def _parse_chinese_integer_with_units(s: str) -> Optional[int]:
    total = 0
    section = 0
    number = 0

    def flush_section_with(large_unit: Optional[int] = None) -> None:
        nonlocal total, section, number
        section += number
        number = 0
        if large_unit is None:
            total += section
            section = 0
        else:
            total += section * large_unit
            section = 0

    i = 0
    while i < len(s):
        ch = s[i]
        i += 1

        if ch.isspace():
            continue

        if ch in _CH_ALT_TENS:
            section += _CH_ALT_TENS[ch]
            continue

        if ch in ("零", "〇", "○"):
            continue

        if ch in _CH_DIGITS:
            number = _CH_DIGITS[ch]
            continue

        d = _char_to_ascii_digit(ch)
        if d is not None:
            number = int(d)
            continue

        if ch in _CH_SMALL_UNITS:
            unit_val = _CH_SMALL_UNITS[ch]
            section += (number or 1) * unit_val
            number = 0
            continue

        if ch in _CH_LARGE_UNITS:
            large_val = _CH_LARGE_UNITS[ch]
            flush_section_with(large_val)
            continue

        return None

    flush_section_with(None)
    return total


# ---- inspect_ai/_util/text.py ---------------------------------------------------------------

def strip_numeric_punctuation(s: str) -> str:
    # un-escape LaTeX-escaped currency/formatting symbols (e.g. "\$20" -> "$20").
    # Models frequently escape these inside LaTeX math mode, since a bare "$"
    # would otherwise open/close a math expression. Without this, "\$20" is
    # left as "\20" below (the backslash isn't a stripped character), which
    # fails to parse as a number and is silently rejected as a non-numeric
    # token by callers such as match(numeric=True).
    s = re.sub(r"\\([$,£,€*_])", r"\1", s)

    # strip $, €, £, and ,
    # *,_ to string formatting characters sometimes added by LLMs
    stripped = re.sub(r"[$,£,€,*,_]", "", s)

    # strip . if it's followed by a space, the end of the string,
    # or a non-digit character
    stripped = re.sub(r"\.(?=\s|$|\D)", "", stripped)
    return stripped


# ---- inspect_ai/scorer/_common.py -----------------------------------------------------------

# Sentence/enclosing punctuation only. Operator characters (~ < > = etc.)
# are deliberately excluded: "<42", ">=42", "~42" express bounds or
# approximations, not the value itself, and trimming them would grade a
# hedge as the exact answer (false CORRECTs).
_NUMERIC_PUNCTUATION_TRIM = "!?:;()[]{}'\"`"


def _clean_numeric_word(s: str) -> str:
    return s.strip(_NUMERIC_PUNCTUATION_TRIM)


def _parse_number(s: str, *, trim_punctuation: bool = True) -> float | None:
    """Parse `s` as a finite number, or None.

    Recognises plain float syntax (signs, decimals, exponents) and the
    full set of inputs handled by ``unicode_number_to_float`` (unicode
    minus, vulgar fractions, superscripts, Chinese numerals, fullwidth
    digits, locale grouping). Rejects strings with trailing non-numeric
    content (so ``"5 some text"`` returns None). Sentence/enclosing
    punctuation attached to the number ("42!", "(42)") is trimmed unless
    ``trim_punctuation=False`` — the ``location="exact"`` path passes False
    so that exact stays actually exact. ``nan`` and ``inf`` also return None.
    """
    s_cleaned = _clean_numeric_word(s) if trim_punctuation else s
    for parse in (float, unicode_number_to_float):
        try:
            num = parse(s_cleaned)
        except ValueError:
            continue
        if math.isfinite(num):
            return num
    return None


def _is_number(s: str) -> bool:
    return _parse_number(s) is not None


def first_number_normalized(words: list[str]) -> str:
    number = next((word for word in words if _is_number(word)), None)
    return normalize_number(number) if number is not None else ""



def normalize_number(
    number: str, precision: int = 5, *, trim_punctuation: bool = True
) -> str:
    num = _parse_number(number, trim_punctuation=trim_punctuation)
    if num is None:
        return number
    return format(num, f".{precision}g")


# ---- inspect_evals/utils/aime_common.py -----------------------------------------------------

def remove_boxed_from_ans(answer: str) -> str:
    # Sometimes, LLMs respond by formatting their responses
    # with \boxed{...}, which inspect_ai.scorer.match
    # does not handle well, so we remove it here.
    return re.sub(r"\\boxed\{(.+)\}", r"\1", answer)


# A line counts as "delimiter-only" (skippable when hunting for the true
# last substantive line) if, once stripped, it consists solely of LaTeX
# display-math delimiters or markdown emphasis/heading punctuation - never
# actual answer content.
_DELIMITER_ONLY_RE = re.compile(r"^[\$\*\-#\s]*$")


def _find_last_substantive_line(raw: str) -> str:
    r"""Return the true final line of content, skipping trailing delimiter-only lines.

    Skips trailing lines that are purely delimiter noise (e.g. a lone "$$"
    closing a display-math block after the real answer).

    Reasoning models frequently close their answer like::

        $$
        \\boxed{70}
        $$

    where the literal last line is just "$$", not the boxed answer one
    line above it. Falls back to the literal last line if every line is
    delimiter-only (shouldn't happen for a real completion).
    """
    lines = raw.strip().splitlines()
    for line in reversed(lines):
        if line.strip() and not _DELIMITER_ONLY_RE.match(line):
            return line
    return lines[-1] if lines else ""
