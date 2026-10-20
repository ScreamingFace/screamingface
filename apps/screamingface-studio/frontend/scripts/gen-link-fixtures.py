"""Generate Studio's golden Candidate and link fixtures from the ScreamingFace SDK itself.

Studio compiles a recipe to Candidate url4 on its own and must match the SDK's
`compile_candidate` byte for byte, `_sf_recipe` topology metadata included (spec D4, owner
decision 2026-10-20); it then links the Candidate into a Benchmark as `link_candidate` does.
These fixtures are the SDK's output, never hand-written, so a drift on either side fails
`src/lib/recipe.test.ts` and `src/lib/engine/url4.test.ts`.

Regenerate (from the monorepo root), then commit the JSON:

    cd packages/screamingface
    uv run --frozen python \
      ../../apps/screamingface-studio/frontend/scripts/gen-link-fixtures.py \
      > ../../apps/screamingface-studio/frontend/src/lib/engine/__fixtures__/linked.json

`--frozen` keeps `uv.lock` untouched; revert it if a run changes it anyway.

Each case records the SDK's compiled Candidate, the canonical Benchmark text, and the SDK's
`link_candidate` of the two. `recipe.test.ts` builds the same recipe in Studio's shape under the
same key.
"""

from __future__ import annotations

import json
import sys

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.linking import link_candidate
from url4 import build, render

# A canonical Benchmark that invokes the whole Candidate once, as the Engine's do.
BENCHMARK = "(case:0.0:/sf/case-1($candidate)!'grade')!'$case'"

ANSWER = "Answer the request."
SYNTHESIZE = "Combine the member answers."
MEMBER_TEXT = "Answer in $USD.\nShow the total on its own line."
SYNTHESIS_TEXT = "Use $input and $$ literally;\nit's a \\ path."
SOLO_TEXT = "Line one\nLine two with $input, '$model_1', $$5 and C:\\dir\\."

GPT = "openai/gpt-4o"
CLAUDE = "anthropic/claude-opus-4-5"
LLAMA = "ollama/llama3"
QWEN = "ollama/qwen"
T07_SEED3 = {"temperature": 0.7, "seed": 3}

M = sf.Model

CASES: dict[str, sf.Model | sf.Fusion | sf.Pipeline] = {
    # ── solo ──
    "solo": M(GPT),
    "solo_params": M(GPT, prompt=ANSWER, params=T07_SEED3),
    # The widest text parameter value url4 carries unquoted: `param-value` (`url4/core/
    # _annotations.py` `_PARAM_VALUE_RE`) minus the `,` the renderer refuses in a query.
    "params_text": M(
        GPT,
        prompt=ANSWER,
        params={
            "stop": "END:of/answer-1.0_x",
            "reasoning_effort": "high",
            "logprobs": True,
        },
    ),
    # Prompt text the SDK transforms (`candidate.py` `_url4_text`): newlines become U+2028 and
    # `$` becomes `$$`, so `$USD` / `$input` stay literal text, never url4 references.
    "solo_prompt_encoded": M(GPT, prompt=SOLO_TEXT),
    "solo_named": M(GPT, name="drafter", prompt=ANSWER),
    # ── fusion ──
    "fusion_defaults": sf.Fusion(members=[M(CLAUDE), M(GPT)], synthesizer=M(GPT)),
    "fusion": sf.Fusion(
        members=[M(CLAUDE, prompt=ANSWER), M(GPT, prompt=ANSWER)],
        synthesizer=M(GPT, prompt=SYNTHESIZE),
    ),
    "fusion_params": sf.Fusion(
        members=[
            M(GPT, prompt=ANSWER, params=T07_SEED3),
            M(CLAUDE, prompt="Say it's a \\ test."),
        ],
        synthesizer=M(GPT, prompt=SYNTHESIZE, params={"temperature": 0.2}),
    ),
    "prompts_encoded": sf.Fusion(
        members=[M(GPT, prompt=MEMBER_TEXT), M(CLAUDE, prompt=ANSWER)],
        synthesizer=M(GPT, prompt=SYNTHESIS_TEXT),
    ),
    "fusion_named": sf.Fusion(
        members=[M(CLAUDE, name="careful"), M(GPT)],
        synthesizer=M(GPT, name="judge"),
        name="panel",
    ),
    "fusion_single_member": sf.Fusion(members=[M(LLAMA)], synthesizer=M(QWEN)),
    # A fusion inside a fusion member.
    "fusion_member_fusion": sf.Fusion(
        members=[sf.Fusion(members=[M(GPT), M(LLAMA)], synthesizer=M(QWEN)), M(QWEN)],
        synthesizer=M(GPT),
    ),
    # Two fusions as members: several synthesizers.
    "fusion_of_two_fusions": sf.Fusion(
        members=[
            sf.Fusion(
                members=[M(GPT), M(LLAMA)], synthesizer=M(QWEN, params=T07_SEED3)
            ),
            sf.Fusion(
                members=[M(CLAUDE), M(QWEN)], synthesizer=M(GPT, prompt=MEMBER_TEXT)
            ),
        ],
        synthesizer=M(CLAUDE),
    ),
    # A fusion whose synthesizer is a fusion: the outer synthesis number is spent first.
    "fusion_fusion_synthesizer": sf.Fusion(
        members=[M(GPT), M(LLAMA)],
        synthesizer=sf.Fusion(members=[M(QWEN), M(GPT)], synthesizer=M(LLAMA)),
    ),
    # A fusion whose synthesizer is a pipeline: its first stage takes the synthesis role.
    "fusion_pipeline_synthesizer": sf.Fusion(
        members=[M(GPT), M(LLAMA)],
        synthesizer=sf.Pipeline(stages=[M(QWEN), M(GPT, prompt="Check.")]),
    ),
    # ── pipeline ──
    "pipeline": sf.Pipeline(
        stages=[M(GPT, prompt=ANSWER), M(CLAUDE, prompt="Check the answer.")]
    ),
    "pipeline_defaults": sf.Pipeline(stages=[M(GPT), M(CLAUDE)]),
    "pipeline_single_stage": sf.Pipeline(stages=[M(GPT)]),
    "pipeline_named": sf.Pipeline(stages=[M(GPT), M(CLAUDE)], name="draft-review"),
    # An unnamed nested pipeline is flattened into its parent; a named one keeps its grouping.
    "pipeline_nested_unnamed": sf.Pipeline(
        stages=[sf.Pipeline(stages=[M(GPT), M(LLAMA)]), M(QWEN)]
    ),
    "pipeline_nested_named": sf.Pipeline(
        stages=[sf.Pipeline(stages=[M(GPT), M(LLAMA)], name="draft"), M(QWEN)]
    ),
    # A fusion at pipeline stage 2: its members and synthesizer read stage 1's output.
    "pipeline_into_fusion": sf.Pipeline(
        stages=[
            M(GPT, prompt=ANSWER),
            sf.Fusion(
                members=[M(CLAUDE, prompt=ANSWER), M(LLAMA, prompt=ANSWER)],
                synthesizer=M(GPT, prompt=SYNTHESIZE),
            ),
        ]
    ),
    "fusion_into_pipeline": sf.Pipeline(
        stages=[
            sf.Fusion(
                members=[M(GPT), M(LLAMA, params=T07_SEED3)], synthesizer=M(QWEN)
            ),
            M(GPT, prompt=SOLO_TEXT),
        ]
    ),
    "pipeline_of_two_fusions": sf.Pipeline(
        stages=[
            sf.Fusion(members=[M(GPT), M(LLAMA)], synthesizer=M(QWEN)),
            sf.Fusion(members=[M(CLAUDE), M(QWEN)], synthesizer=M(GPT)),
        ]
    ),
    "fusion_member_pipeline": sf.Fusion(
        members=[sf.Pipeline(stages=[M(GPT), M(LLAMA)]), M(QWEN)],
        synthesizer=M(GPT),
    ),
}


def main() -> None:
    if render(build(BENCHMARK)) != BENCHMARK:
        raise SystemExit("BENCHMARK is not canonical url4")
    fixtures = {}
    for name, recipe in CASES.items():
        candidate = compile_candidate(recipe).url4
        fixtures[name] = {
            "candidate": candidate,
            "benchmark": BENCHMARK,
            "linked": link_candidate(candidate, BENCHMARK).url4,
        }
    json.dump(fixtures, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
