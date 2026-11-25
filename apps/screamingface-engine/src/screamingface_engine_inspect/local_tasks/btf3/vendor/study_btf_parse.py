# ruff: noqa
# fmt: off
"""The crowd-wisdom study's BTF-3 reply reader, ``btf_parse``, copied verbatim.

Source: the contributor's study package, ``1_forecasting_prompts/bench_formats.py`` lines
121-158 (file sha256 746eb79ec82aebb68697258f7c71fb7d671eeb1c85abd14fc5b6ba70cca19b47), the
reader every BTF-3 reply in the study went through (``run_openrouter.py:885``). The study package
carries no licence; its author, the contributor, contributes this excerpt under this
repository's Apache-2.0 licence.

INVARIANT: everything below the ``# --- verbatim below ---`` line is the source's lines 121-158
byte for byte; ``tests/unit/inspect/test_local_task_btf3.py`` pins its sha256.
"""
import re

# --- verbatim below ---
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
