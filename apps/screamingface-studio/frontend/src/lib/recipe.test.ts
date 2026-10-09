import linked from "./engine/__fixtures__/linked.json";
import type { ModelParam, SavedModel } from "./ensemble-store";
import {
  createNode,
  convertKind,
  describeRecipe,
  describeRecipeKind,
  fusionFromSlots,
  memberSolos,
  rootSynthesizerSolo,
  type FusionNode,
  type PipelineNode,
  type RecipeNode,
  type SoloNode,
  collectSolos,
  createFusion,
  fusionOf,
  parseRecipe,
  recipeToUrl4,
  resolveModels,
} from "./recipe";

function model(id: string): SavedModel {
  const providerId = id.split("/")[0];
  return { id, name: id, providerId, providerName: providerId };
}

let nextId = 0;

function solo(id: string | null, prompt = "", params: ModelParam[] = []): SoloNode {
  return {
    kind: "solo",
    id: `n${++nextId}`,
    model: id ? model(id) : null,
    prompt,
    params,
  };
}

function fusion(members: RecipeNode[], synthesizer: RecipeNode): FusionNode {
  return { kind: "fusion", id: `n${++nextId}`, members, synthesizer };
}

function pipeline(stages: RecipeNode[]): PipelineNode {
  return { kind: "pipeline", id: `n${++nextId}`, stages };
}

const ANSWER = "Answer the request.";
const SYNTHESIZE = "Combine the member answers.";
const T07_SEED3: ModelParam[] = [
  { key: "temperature", value: "0.7" },
  { key: "seed", value: "3" },
];

// The Studio recipes that mirror scripts/gen-link-fixtures.py's SDK recipes.
const SDK_EQUIVALENTS: Record<keyof typeof linked, () => RecipeNode> = {
  fusion: () =>
    fusion(
      [solo("anthropic/claude-opus-4-5", ANSWER), solo("openai/gpt-4o", ANSWER)],
      solo("openai/gpt-4o", SYNTHESIZE),
    ),
  fusion_params: () =>
    fusion(
      [
        solo("openai/gpt-4o", ANSWER, T07_SEED3),
        solo("anthropic/claude-opus-4-5", "Say it's a \\ test."),
      ],
      solo("openai/gpt-4o", SYNTHESIZE, [{ key: "temperature", value: "0.2" }]),
    ),
  pipeline: () =>
    pipeline([
      solo("openai/gpt-4o", ANSWER),
      solo("anthropic/claude-opus-4-5", "Check the answer."),
    ]),
  solo_params: () => solo("openai/gpt-4o", ANSWER, T07_SEED3),
};

describe("recipeToUrl4", () => {
  it.each(Object.keys(SDK_EQUIVALENTS) as (keyof typeof linked)[])(
    "renders the SDK's compiled candidate text (%s)",
    (name) => {
      expect(recipeToUrl4(SDK_EQUIVALENTS[name]())).toBe(linked[name].candidate);
    },
  );

  it("puts params in url4's query form, with the context after q=", () => {
    expect(recipeToUrl4(solo("openai/gpt-4o", "Hi.", T07_SEED3))).toBe(
      "(model_1:0.0:/openai/gpt-4o?temperature=0.7&seed=3&q=($input)!'Hi.')!'$model_1'",
    );
  });

  it("leaves a call without params unchanged", () => {
    expect(recipeToUrl4(solo("openai/gpt-4o"))).toBe(
      "(model_1:0.0:/openai/gpt-4o($input)!'Answer.')!'$model_1'",
    );
  });

  it("skips params without a key or a value", () => {
    const params = [
      { key: "", value: "1" },
      { key: "seed", value: "" },
    ];
    expect(recipeToUrl4(solo("openai/gpt-4o", "", params))).toBe(
      "(model_1:0.0:/openai/gpt-4o($input)!'Answer.')!'$model_1'",
    );
  });
});

function roundTrip(root: RecipeNode) {
  const url4 = recipeToUrl4(root);
  const parsed = parseRecipe(url4);
  if (!parsed.ok) throw new Error(`rejected: ${parsed.error}`);
  return { url4, parsed: parsed.root, again: recipeToUrl4(parsed.root) };
}

describe("parseRecipe", () => {
  const shapes: [string, () => RecipeNode][] = [
    ["solo", () => solo("openai/gpt-4o")],
    ["solo with params and a prompt", () => solo("openai/gpt-4o", "Be brief.", T07_SEED3)],
    [
      "fusion",
      () => fusion([solo("openai/gpt-4o"), solo("ollama/llama3")], solo("openai/gpt-4o")),
    ],
    [
      "fusion with params and prompts",
      () =>
        fusion(
          [
            solo("openai/gpt-4o", "Say it's a \\ test.", T07_SEED3),
            solo("ollama/llama3", "Answer {in} (briefly), please!"),
          ],
          solo("openai/gpt-4o", SYNTHESIZE, [{ key: "temperature", value: "0.2" }]),
        ),
    ],
    ["pipeline", () => pipeline([solo("openai/gpt-4o"), solo("ollama/llama3")])],
    [
      "pipeline with params and prompts",
      () =>
        pipeline([
          solo("openai/gpt-4o", "Draft it.", T07_SEED3),
          solo("ollama/llama3", "Check 'the' draft.", [{ key: "seed", value: "1" }]),
          solo("openai/gpt-4o", "Polish."),
        ]),
    ],
    [
      "a fusion whose members are pipelines",
      () =>
        fusion(
          [pipeline([solo("openai/gpt-4o"), solo("ollama/llama3")]), solo("ollama/qwen")],
          solo("openai/gpt-4o"),
        ),
    ],
    [
      "a fusion of fusions",
      () =>
        fusion(
          [
            fusion([solo("openai/gpt-4o"), solo("ollama/llama3")], solo("ollama/qwen")),
            solo("ollama/qwen"),
          ],
          solo("openai/gpt-4o"),
        ),
    ],
    [
      "a fusion with a pipeline synthesizer",
      () =>
        fusion(
          [solo("openai/gpt-4o"), solo("ollama/llama3")],
          pipeline([solo("ollama/qwen", "Merge."), solo("openai/gpt-4o", "Check.")]),
        ),
    ],
    [
      "a pipeline that starts with a fusion",
      () =>
        pipeline([
          fusion([solo("openai/gpt-4o"), solo("ollama/llama3")], solo("ollama/qwen")),
          solo("openai/gpt-4o", "Polish."),
        ]),
    ],
    ["a fusion with unset models", () => createFusion()],
  ];

  it.each(shapes)("round-trips %s", (_name, build) => {
    const { url4, again } = roundTrip(build());
    expect(again).toBe(url4);
  });

  it("rebuilds the recipe's structure, models, prompts and params", () => {
    const { parsed } = roundTrip(
      fusion(
        [solo("openai/gpt-4o", "Say it's a \\ test.", T07_SEED3), solo("ollama/llama3")],
        solo(null),
      ),
    );

    expect(parsed.kind).toBe("fusion");
    const { members, synthesizer } = parsed as FusionNode;
    expect(members).toHaveLength(2);
    expect(members[0]).toMatchObject({
      kind: "solo",
      model: model("openai/gpt-4o"),
      prompt: "Say it's a \\ test.",
      params: T07_SEED3,
    });
    // A default prompt comes back as "no prompt", so the builder keeps showing the default.
    expect(members[1]).toMatchObject({ kind: "solo", model: model("ollama/llama3"), prompt: "" });
    expect(synthesizer).toMatchObject({ kind: "solo", model: null, prompt: "" });
  });

  it("gives every node a fresh id", () => {
    const { parsed } = roundTrip(
      fusion([solo("openai/gpt-4o"), solo("ollama/llama3")], solo("openai/gpt-4o")),
    );
    const ids = [parsed.id, ...collectSolos(parsed).map((node) => node.id)];
    expect(new Set(ids).size).toBe(ids.length);
  });

  it.each([
    ["the old url4:// form", "url4://shared?models=ollama/llama3+ollama/qwen"],
    ["an empty string", ""],
    ["a truncated recipe", recipeToUrl4(solo("openai/gpt-4o")).slice(0, -5)],
    [
      "a recipe cut inside a prompt",
      "(model_1:0.0:/openai/gpt-4o($input)!'Answer.)!'$model_1'",
    ],
    ["trailing text", `${recipeToUrl4(solo("openai/gpt-4o"))} extra`],
    ["a root that names no source", "(model_1:0.0:/openai/gpt-4o($input)!'Answer.')!'$model_2'"],
    [
      "a source nothing uses",
      "(model_1:0.0:/a/b($input)!'Answer.', model_2:0.0:/a/c($input)!'Answer.')!'$model_1'",
    ],
    [
      "non-canonical numbering",
      "(model_7:0.0:/openai/gpt-4o($input)!'Answer.')!'$model_7'",
    ],
    ["an unknown escape", "(model_1:0.0:/a/b($input)!'An\\swer.')!'$model_1'"],
    ["a param without a value", "(model_1:0.0:/a/b?seed&q=($input)!'Answer.')!'$model_1'"],
    ["an unknown context", "(model_1:0.0:/a/b($other)!'Answer.')!'$model_1'"],
    ["a reference loop", "(model_1:0.0:/a/b($model_1)!'Answer.')!'$model_1'"],
    ["a source without its weight", "(model_1:/a/b($input)!'Answer.')!'$model_1'"],
    ["an unclosed context", "(model_1:0.0:/a/b($input"],
    ["a repeated source name", "(model_1:0.0:/a/b($input)!'Answer.', model_1:0.0:/a/b($input)!'Answer.')!'$model_1'"],
    [
      "fusion members out of order",
      "(model_1:0.0:/a/b($input)!'Answer.', synthesis_1:0.0:/a/b({input: '$input', outputs: {member_2: '$model_1'}})!'S.')!'$synthesis_1'",
    ],
    [
      "a malformed fusion context",
      "(model_1:0.0:/a/b($input)!'Answer.', synthesis_1:0.0:/a/b({outputs: {member_1: '$model_1'}})!'S.')!'$synthesis_1'",
    ],
  ])("rejects %s with a message", (_name, url4) => {
    const parsed = parseRecipe(url4);
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.error).toMatch(/\S/);
  });
});

describe("fusionOf", () => {
  it("makes a fusion of the models, with the synthesizer left to choose", () => {
    const root = fusionOf([model("ollama/llama3"), model("ollama/qwen")]);
    expect(root.members.map((member) => (member as SoloNode).model?.id)).toEqual([
      "ollama/llama3",
      "ollama/qwen",
    ]);
    expect(root.synthesizer).toMatchObject({ kind: "solo", model: null });
    expect(parseRecipe(recipeToUrl4(root)).ok).toBe(true);
  });
});

describe("resolveModels", () => {
  it("swaps in the catalog's models and leaves out the ones it lacks", () => {
    const catalogModel = { ...model("ollama/llama3"), providerName: "Ollama" };
    const { root, unknown } = resolveModels(
      pipeline([solo("ollama/llama3"), fusion([solo("gone/old")], solo(null))]),
      [catalogModel],
    );

    expect(unknown).toEqual(["gone/old"]);
    const solos = collectSolos(root);
    expect(solos.map((node) => node.model)).toEqual([catalogModel, null, null]);
  });

  it("names each missing model once", () => {
    const { unknown } = resolveModels(
      fusion([solo("gone/old"), solo("gone/old")], solo("gone/old")),
      [],
    );
    expect(unknown).toEqual(["gone/old"]);
  });
});

describe("recipe helpers", () => {
  it("creates each kind of node", () => {
    expect(createNode("solo")).toMatchObject({ kind: "solo", model: null });
    expect(createNode("fusion")).toMatchObject({ kind: "fusion" });
    expect((createNode("pipeline") as PipelineNode).stages).toHaveLength(2);
  });

  it("describes a recipe's shape", () => {
    const two = fusion([solo("a/b"), solo("a/c")], solo("a/d"));
    expect(describeRecipeKind(solo("a/b"))).toBe("Solo");
    expect(describeRecipeKind(two)).toBe("Fusion · 2 members");
    expect(describeRecipeKind(fusion([solo("a/b")], solo("a/d")))).toBe("Fusion · 1 member");
    expect(describeRecipeKind(pipeline([solo("a/b")]))).toBe("Pipeline · 1 stage");
    expect(describeRecipeKind(pipeline([solo("a/b"), solo("a/c")]))).toBe("Pipeline · 2 stages");
    expect(describeRecipe(solo("a/b"))).toBe("a/b");
    expect(describeRecipe(solo(null))).toBe("unset model");
    expect(describeRecipe(two)).toBe("Fusion(2 members → synthesizer)");
    expect(describeRecipe(fusion([solo("a/b")], solo("a/d")))).toBe(
      "Fusion(1 member → synthesizer)",
    );
    expect(describeRecipe(pipeline([solo("a/b")]))).toBe("Pipeline(1 stage)");
    expect(describeRecipe(pipeline([solo("a/b"), solo("a/c")]))).toBe("Pipeline(2 stages)");
  });

  it("finds the answering members and the final solo", () => {
    const synth = solo("a/d");
    const two = fusion([solo("a/b"), solo("a/c")], synth);
    expect(memberSolos(two).map((node) => node.model?.id)).toEqual(["a/b", "a/c"]);
    expect(rootSynthesizerSolo(two)).toBe(synth);

    const last = solo("a/c");
    const chain = pipeline([solo("a/b"), last]);
    expect(memberSolos(chain).map((node) => node.model?.id)).toEqual(["a/b"]);
    expect(rootSynthesizerSolo(chain)).toBe(last);

    const single = solo("a/b");
    expect(memberSolos(single)).toEqual([single]);
    expect(rootSynthesizerSolo(single)).toBeNull();
    expect(rootSynthesizerSolo(pipeline([solo(null)]))).toBeNull();
  });

  it("converts between kinds, keeping what the target can hold", () => {
    const one = solo("a/b");
    expect(convertKind(one, "solo")).toBe(one);
    expect(convertKind(one, "fusion")).toMatchObject({ kind: "fusion", id: one.id });
    expect((convertKind(one, "fusion") as FusionNode).members[0]).toMatchObject({
      model: model("a/b"),
    });
    expect((convertKind(solo(null), "pipeline") as PipelineNode).stages).toHaveLength(2);

    const two = fusion([solo("a/b"), solo("a/c")], solo("a/d"));
    const asPipeline = convertKind(two, "pipeline") as PipelineNode;
    expect(asPipeline.stages).toBe(two.members);
    const back = convertKind(asPipeline, "fusion") as FusionNode;
    expect(back.members).toBe(two.members);
    expect(back.synthesizer.kind).toBe("solo");
    expect(convertKind(two, "solo")).toMatchObject({ kind: "solo", id: two.id, model: model("a/b") });
    expect(convertKind(fusion([solo(null)], solo(null)), "solo")).toMatchObject({
      kind: "solo",
      model: null,
    });
  });

  it("migrates flat slots and a judge into a fusion", () => {
    const slot = {
      id: "s1",
      model: model("a/b"),
      systemPrompt: "Be brief.",
      weight: 0.5,
      params: T07_SEED3,
    };
    const migrated = fusionFromSlots([slot], { ...slot, model: model("a/d"), systemPrompt: "" });
    expect(migrated.members[0]).toMatchObject({ model: model("a/b"), prompt: "Be brief." });
    expect(migrated.synthesizer).toMatchObject({ model: model("a/d"), prompt: "" });

    const empty = fusionFromSlots(undefined, null);
    expect(empty.members).toHaveLength(1);
    expect(empty.synthesizer).toMatchObject({ model: null });
  });

  it("renders an empty pipeline as its input", () => {
    expect(recipeToUrl4(pipeline([]))).toBe("()!'$input'");
  });
});
