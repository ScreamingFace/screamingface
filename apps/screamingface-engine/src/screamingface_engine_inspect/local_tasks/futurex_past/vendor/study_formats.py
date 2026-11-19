"""The study's prompt rendering and answer reading, copied from the contributor's package.

Source: ``crowd-wisdom-package/1_forecasting_prompts/bench_formats.py`` (the study "behavior-aware
LLM crowds for future prediction"), whole file sha256
746eb79ec82aebb68697258f7c71fb7d671eeb1c85abd14fc5b6ba70cca19b47. Its author contributes it to
this repository under the repository's Apache-2.0 licence.

Everything below this docstring is that file byte for byte, after its own module docstring.
``tests/unit/inspect/test_local_task_futurex_past_study.py`` pins it; do not edit.
"""
import ast
import re

# ---------------------------------------------------------------- FutureX-Past

# The exact marker that opens FutureX's answer-format block. CoT is inserted before this, never inside.
FX_FORMAT_MARKER = "IMPORTANT: Your final answer MUST end with this exact format:"

FX_COT = ("Before answering, reason through this step by step: what is known, what the plausible "
          "outcomes are, and which is most likely. Show that reasoning, then give your final answer.\n\n")


def futurex_render(row, arm="original"):
    """`original` = the benchmark's own prompt, byte-for-byte. `cot` = the same with reasoning inserted."""
    p = row["prompt"]
    if arm == "original":
        return p
    if arm != "cot":
        raise ValueError(f"unknown arm {arm!r}")
    if FX_FORMAT_MARKER not in p:
        raise ValueError(f"FutureX prompt lacks its own format marker — the source changed; refusing to "
                         f"guess where reasoning belongs. id={row.get('id')!r}")
    head, sep, tail = p.partition(FX_FORMAT_MARKER)
    return head + FX_COT + sep + tail


# ONE canonical definition, imported by completeness_review rather than re-written there.
# THE DEFECT THIS FIXES (observed live in the FutureX gate stage, 2026-08-08): this pattern used
# `[^{}]*`, which CANNOT match a nested brace, while completeness_review's copy already handled one
# level. So `\\boxed{\\text{央视新闻, 新华社, 占豪}}` was an ANSWER to the verdict layer and NOTHING to
# the parser: two records came back COMPLETE with n_boxes=0, and the post-run invariant check
# halted the run. Codex flagged the nesting risk at the verification gate and the fix was applied to
# only one of the two readers; the divergence itself was the bug. Free-text levels 3-4 are where it
# bites -- the earlier 2-item smoke had only option letters and could not have shown it.
_BOXED = re.compile(r"\\boxed\s*\{((?:[^{}]|\{[^{}]*\})*)\}")


def futurex_parse(text):
    """Return {answer, raw_box, n_boxes, compliant}. The LAST \\boxed{} wins — the prompt says the answer
    must END with it, and a reasoning arm may legitimately show a worked box earlier."""
    boxes = _BOXED.findall(text or "")
    if not boxes:
        return {"answer": None, "raw_box": None, "n_boxes": 0, "compliant": False}
    raw = boxes[-1].strip()
    return {"answer": [x.strip() for x in raw.split(",") if x.strip()],
            "raw_box": raw, "n_boxes": len(boxes), "compliant": True}


def futurex_gold(row):
    """ground_truth is a STRING holding a list. Parsed, never eval'd loosely; carried for LATER scoring."""
    g = row["ground_truth"]
    if isinstance(g, (list, tuple)):
        return list(g)
    try:
        v = ast.literal_eval(g)
        return list(v) if isinstance(v, (list, tuple)) else [v]
    except Exception:
        return [str(g)]


# ---------------------------------------------------------------- BTF-3

BTF_COT = ("Before giving your answer, reason through the question step by step: the base rate, the "
           "status quo, and what would have to change.\n\n")

# BTF's own prompt already ends by demanding a probability on the last line; that tail is the parse target.
BTF_TAIL = "The last thing you write is your final answer as a probability between 0 and 1."


# THE TIGHTENED ANSWER CHANNEL (owner 2026-08-08: "adapt the updated format instruction on the test").
# Authored by Codex (job task-msl2wybv-nwe353) as candidate C, then validated locally: it moved
# llama-3.1-8b-instruct from 0/6 to 6/6, qwen2.5-7b from 4/6 to 6/6 and llama-3.2-3b from 2/6 to 6/6
# -- 6/18 to 18/18 with no model regressing.
#
# It REPLACES ONLY THE ANSWER LINE. The (a)-(e) reasoning block above it is byte-identical to the
# native arm, so this varies the answer CHANNEL and nothing else. That is the control that keeps a
# format change from silently becoming a reasoning change.
BTF_TIGHT = ("End your response with exactly one line in this format: "
             "`Final answer: <number between 0 and 1>`. Do not write anything after that line.")


def btf_render(base_prompt, arm="original"):
    """original = the paper's prompt byte-for-byte. tight = the same with ONLY the answer line
    replaced. cot = the same with a reasoning instruction inserted before the answer line."""
    if arm == "original":
        return base_prompt
    if arm not in ("cot", "tight"):
        raise ValueError(f"unknown arm {arm!r}")
    if BTF_TAIL not in base_prompt:
        raise ValueError("BTF prompt lacks its answer tail — the source changed; refusing to guess")
    if arm == "tight":
        out = base_prompt.replace(BTF_TAIL, BTF_TIGHT)
        if BTF_TAIL in out:
            raise ValueError("the native answer line survived the swap -- both instructions present")
        return out
    return base_prompt.replace(BTF_TAIL, BTF_COT + BTF_TAIL)


_ASTERISK = re.compile(r"\*\s*(0?\.\d+|0|1(?:\.0+)?)\s*\*")
_NUM = re.compile(r"(?<![\d.])(0?\.\d+|0|1(?:\.0+)?)(?![\d.])")


def btf_parse(text):
    """Returns {prob, compliant, source}.

    THE CONTRACT IS BTF-3'S OWN CLOSING LINE, read off the prompt we actually send:
        "The last thing you write is your final answer as a probability between 0 and 1."
    So compliance means the reply ENDS with a probability in [0,1]. Nothing about asterisks.

    TWO WRONG VERSIONS PRECEDED THIS, both caught before BTF-3 was ever run:
      1. compliant = the LAST number in [0,1] found ANYWHERE. That scored explicit refusals as
         forecasts -- "a 0.7 chance of Y. I cannot give a final figure." came back compliant/0.7 --
         so compliance would read near-100% regardless of behaviour and NO_ANSWER would vanish.
      2. compliant = the ASTERISK form *0.35*. That contract belongs to FORECASTBENCH, not BTF-3
         (forecast_prompts.py: "FB keeps its asterisk contract and BTF keeps its closing
         final-answer line"). Requiring it would have driven BTF compliance to ~0 -- the same
         mistake in the opposite direction. Found only by reading the rendered prompt's tail.

    A number found earlier in the reply is still EXTRACTED, because it is a real answer worth
    keeping for the later accuracy pass. It is simply not compliance: the two are kept apart.
    """
    t = (text or "").rstrip()
    if not t:
        return {"prob": None, "compliant": False, "source": None}
    # "The LAST THING you write" -- so the test is that nothing follows the number, not that the
    # closing line is bare. "my estimate is *0.35*" ends with the probability and complies;
    # "My answer is 0.8. But note this is uncertain." does not, because prose follows it.
    tail = t.splitlines()[-1].strip()
    m = re.search(r"(?<![\d.])(0?\.\d+|0|1(?:\.0+)?)[*_`\s]*[.]?$", tail)
    if m:
        return {"prob": float(m.group(1)), "compliant": True, "source": "final_line"}
    n = [float(x) for x in _NUM.findall(t)]
    n = [x for x in n if 0.0 <= x <= 1.0]
    if n:
        return {"prob": n[-1], "compliant": False, "source": "number_not_final"}
    return {"prob": None, "compliant": False, "source": None}


# ---------------------------------------------------------------- answer INTERPRETABILITY
# Owner ruling 2026-08-08: "make sure in the smoke tests, the answer's evaluation is part of the
# validation requirements. if the result is not interpretable, that is a bad result."
#
# FORMAT COMPLIANCE AND INTERPRETABILITY ARE DIFFERENT QUESTIONS, and this project had only been
# asking the first. `\boxed{maybe}` satisfies the format and answers nothing. `\boxed{Z}` on a
# four-option question names an option that does not exist. Both would have counted as compliant.
#
# The expected answer TYPE is derived from the item's OWN prompt -- never assumed from the level --
# because the prompt is what the model was actually told to produce.

_OPTION_LINE = re.compile(r"^\s*([A-Z])[.)]\s+\S", re.M)
_BINARY_DEMAND = re.compile(r"\\boxed\{\s*Yes\s*\}\s*or\s*\\boxed\{\s*No\s*\}", re.I)

# Placeholders and hedges that are syntactically an answer but carry no prediction.
_NON_ANSWER = re.compile(
    r"^\s*(n/?a|tbd|unknown|unclear|none|null|nil|\?+|\.{2,}|-+|insert answer here|"
    r"cannot\s+(be\s+)?determine\w*|no\s+answer|not\s+enough\s+(information|data)|"
    r"i\s+(don'?t|do\s+not)\s+know|undetermined|indeterminate|maybe|possibly|uncertain)"
    r"\s*[.!]?\s*$", re.I)


def expected_answer_type(item_prompt):
    """binary | multiple_choice | free_text -- read off the item's own prompt."""
    if _BINARY_DEMAND.search(item_prompt):
        return "binary"
    if len(set(_OPTION_LINE.findall(item_prompt))) >= 2:
        return "multiple_choice"
    return "free_text"


def options_offered(item_prompt):
    return sorted(set(_OPTION_LINE.findall(item_prompt)))


def interpret_btf_answer(parsed, item_prompt=None):
    """BTF-3's answer is a PROBABILITY, not a boxed option (Codex C2).

    A12 was written against FutureX's `raw_box` and would have been meaningless on BTF -- every BTF
    record would have looked uninterpretable because it has no box. The BTF question is different
    and simpler: is the number a usable probability?
    """
    p = (parsed or {}).get("prob")
    if p is None:
        return {"interpretable": False, "kind": "probability", "value": None,
                "why": "no probability was extracted"}
    if not isinstance(p, (int, float)):
        return {"interpretable": False, "kind": "probability", "value": p,
                "why": f"not a number: {p!r}"}
    if not 0.0 <= float(p) <= 1.0:
        return {"interpretable": False, "kind": "probability", "value": p,
                "why": f"outside [0,1]: {p} -- a probability that cannot be scored"}
    return {"interpretable": True, "kind": "probability", "value": float(p), "why": None}


def interpret_answer(box, item_prompt):
    """Is what the model put in the box a USABLE answer to THIS question?

    Returns {interpretable, kind, value, why}. `why` is filled only when it is not.
    """
    kind = expected_answer_type(item_prompt)
    raw = (box or "").strip()
    if not raw:
        return {"interpretable": False, "kind": kind, "value": None,
                "why": "the box is empty"}
    if _NON_ANSWER.match(raw):
        return {"interpretable": False, "kind": kind, "value": raw,
                "why": f"a placeholder or hedge, not a prediction: {raw!r}"}

    if kind == "binary":
        v = raw.rstrip(".").strip().lower()
        if v in ("yes", "no"):
            return {"interpretable": True, "kind": kind, "value": v.capitalize(), "why": None}
        return {"interpretable": False, "kind": kind, "value": raw,
                "why": f"the prompt demanded Yes or No; the box holds {raw!r}"}

    if kind == "multiple_choice":
        offered = options_offered(item_prompt)
        picked = [t.strip().rstrip(".").upper() for t in re.split(r"[,;/]| and ", raw) if t.strip()]
        if not picked:
            return {"interpretable": False, "kind": kind, "value": raw, "why": "no option named"}
        bad = [p for p in picked if p not in offered]
        if bad:
            return {"interpretable": False, "kind": kind, "value": raw,
                    "why": f"named option(s) {bad} that this question does not offer "
                           f"(offered: {offered})"}
        # selecting EVERY option is not a discriminating answer to a scored multiple-choice item
        if len(set(picked)) == len(offered) and len(offered) > 1:
            return {"interpretable": False, "kind": kind, "value": raw,
                    "why": f"selected ALL {len(offered)} options, which states no prediction"}
        return {"interpretable": True, "kind": kind, "value": sorted(set(picked)), "why": None}

    # free_text (FutureX levels 3-4): a substantive answer, not a shrug.
    # Strip a presentational LaTeX \\text{} wrapper -- models wrap free-text answers in it and the
    # content is what the later accuracy pass needs. Compliance is unaffected either way.
    mt = re.match(r"^\\text\s*\{(.*)\}$", raw, re.S)
    if mt:
        raw = mt.group(1).strip()
    if len(raw) < 2:
        return {"interpretable": False, "kind": kind, "value": raw,
                "why": f"too short to be an answer: {raw!r}"}
    return {"interpretable": True, "kind": kind, "value": raw, "why": None}
