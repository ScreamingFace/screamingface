"""Generate Studio's golden url4 link fixtures from the ScreamingFace SDK itself.

Studio links a Candidate into a Benchmark on its own (spec D4) and must match the SDK byte for
byte. These fixtures are the SDK's output, never hand-written, so a drift in either side fails
`src/lib/engine/url4.test.ts` and `src/lib/recipe.test.ts`.

Regenerate (from the monorepo root), then commit the JSON:

    cd packages/screamingface
    uv run --frozen python \
      ../../apps/screamingface-studio/frontend/scripts/gen-link-fixtures.py \
      > ../../apps/screamingface-studio/frontend/src/lib/engine/__fixtures__/linked.json

`--frozen` keeps `uv.lock` untouched; revert it if a run changes it anyway.

Each case records the SDK's compiled Candidate with its `_sf_recipe` metadata source removed
(Studio does not send it; the Engine never reads it), the canonical Benchmark text, and the
SDK's `link_candidate` of the two. Prompts are explicit so Studio's recipe can carry the same
text; Studio's default prompts differ from the SDK's.
"""

from __future__ import annotations

import dataclasses
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


def _studio_candidate(recipe: sf.Model | sf.Fusion | sf.Pipeline) -> str:
    """The SDK's compiled Candidate text without the `_sf_recipe` metadata source."""

    expression = build(compile_candidate(recipe).url4)
    sources = tuple(
        source for source in expression.sources if source.name != "_sf_recipe"
    )
    return render(dataclasses.replace(expression, sources=sources))


CASES: dict[str, sf.Model | sf.Fusion | sf.Pipeline] = {
    "fusion": sf.Fusion(
        members=[
            sf.Model("anthropic/claude-opus-4-5", prompt=ANSWER),
            sf.Model("openai/gpt-4o", prompt=ANSWER),
        ],
        synthesizer=sf.Model("openai/gpt-4o", prompt=SYNTHESIZE),
    ),
    "fusion_params": sf.Fusion(
        members=[
            sf.Model(
                "openai/gpt-4o",
                prompt=ANSWER,
                params={"temperature": 0.7, "seed": 3},
            ),
            sf.Model("anthropic/claude-opus-4-5", prompt="Say it's a \\ test."),
        ],
        synthesizer=sf.Model(
            "openai/gpt-4o", prompt=SYNTHESIZE, params={"temperature": 0.2}
        ),
    ),
    "pipeline": sf.Pipeline(
        stages=[
            sf.Model("openai/gpt-4o", prompt=ANSWER),
            sf.Model("anthropic/claude-opus-4-5", prompt="Check the answer."),
        ]
    ),
    "solo_params": sf.Model(
        "openai/gpt-4o", prompt=ANSWER, params={"temperature": 0.7, "seed": 3}
    ),
}


def main() -> None:
    if render(build(BENCHMARK)) != BENCHMARK:
        raise SystemExit("BENCHMARK is not canonical url4")
    fixtures = {}
    for name, recipe in CASES.items():
        candidate = _studio_candidate(recipe)
        fixtures[name] = {
            "candidate": candidate,
            "benchmark": BENCHMARK,
            "linked": link_candidate(candidate, BENCHMARK).url4,
        }
    json.dump(fixtures, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
