import linked from "./engine/__fixtures__/linked.json";
import { quoteText } from "./engine/url4";
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
  RecipeError,
  recipeIssues,
  recipeName,
  renderRecipe,
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
// The same prompt texts as scripts/gen-link-fixtures.py.
const MEMBER_TEXT = "Answer in $USD.\nShow the total on its own line.";
const SYNTHESIS_TEXT = "Use $input and $$ literally;\nit's a \\ path.";
const SOLO_TEXT = "Line one\nLine two with $input, '$model_1', $$5 and C:\\dir\\.";
const T07_SEED3: ModelParam[] = [
  { key: "temperature", value: "0.7" },
  { key: "seed", value: "3" },
];

const GPT = "openai/gpt-4o";
const CLAUDE = "anthropic/claude-opus-4-5";
const LLAMA = "ollama/llama3";
const QWEN = "ollama/qwen";

// A user-given name, as the builder's rename sets it.
function named<T extends RecipeNode>(node: T, name: string): T {
  return { ...node, name };
}

// The Studio recipes that mirror scripts/gen-link-fixtures.py's SDK recipes, key for key.
const SDK_EQUIVALENTS: Record<keyof typeof linked, () => RecipeNode> = {
  solo: () => solo(GPT),
  solo_params: () => solo(GPT, ANSWER, T07_SEED3),
  params_text: () =>
    solo(GPT, ANSWER, [
      { key: "stop", value: "END:of/answer-1.0_x" },
      { key: "reasoning_effort", value: "high" },
      { key: "logprobs", value: "true" },
    ]),
  solo_prompt_encoded: () => solo(GPT, SOLO_TEXT),
  solo_named: () => named(solo(GPT, ANSWER), "drafter"),
  fusion_defaults: () => fusion([solo(CLAUDE), solo(GPT)], solo(GPT)),
  fusion: () => fusion([solo(CLAUDE, ANSWER), solo(GPT, ANSWER)], solo(GPT, SYNTHESIZE)),
  fusion_params: () =>
    fusion(
      [solo(GPT, ANSWER, T07_SEED3), solo(CLAUDE, "Say it's a \\ test.")],
      solo(GPT, SYNTHESIZE, [{ key: "temperature", value: "0.2" }]),
    ),
  prompts_encoded: () =>
    fusion([solo(GPT, MEMBER_TEXT), solo(CLAUDE, ANSWER)], solo(GPT, SYNTHESIS_TEXT)),
  fusion_named: () =>
    named(
      fusion([named(solo(CLAUDE), "careful"), solo(GPT)], named(solo(GPT), "judge")),
      "panel",
    ),
  fusion_single_member: () => fusion([solo(LLAMA)], solo(QWEN)),
  fusion_member_fusion: () =>
    fusion([fusion([solo(GPT), solo(LLAMA)], solo(QWEN)), solo(QWEN)], solo(GPT)),
  fusion_of_two_fusions: () =>
    fusion(
      [
        fusion([solo(GPT), solo(LLAMA)], solo(QWEN, "", T07_SEED3)),
        fusion([solo(CLAUDE), solo(QWEN)], solo(GPT, MEMBER_TEXT)),
      ],
      solo(CLAUDE),
    ),
  fusion_fusion_synthesizer: () =>
    fusion([solo(GPT), solo(LLAMA)], fusion([solo(QWEN), solo(GPT)], solo(LLAMA))),
  fusion_pipeline_synthesizer: () =>
    fusion([solo(GPT), solo(LLAMA)], pipeline([solo(QWEN), solo(GPT, "Check.")])),
  pipeline: () => pipeline([solo(GPT, ANSWER), solo(CLAUDE, "Check the answer.")]),
  pipeline_defaults: () => pipeline([solo(GPT), solo(CLAUDE)]),
  pipeline_single_stage: () => pipeline([solo(GPT)]),
  pipeline_named: () => named(pipeline([solo(GPT), solo(CLAUDE)]), "draft-review"),
  pipeline_nested_unnamed: () => pipeline([pipeline([solo(GPT), solo(LLAMA)]), solo(QWEN)]),
  pipeline_nested_named: () =>
    pipeline([named(pipeline([solo(GPT), solo(LLAMA)]), "draft"), solo(QWEN)]),
  pipeline_into_fusion: () =>
    pipeline([
      solo(GPT, ANSWER),
      fusion([solo(CLAUDE, ANSWER), solo(LLAMA, ANSWER)], solo(GPT, SYNTHESIZE)),
    ]),
  fusion_into_pipeline: () =>
    pipeline([fusion([solo(GPT), solo(LLAMA, "", T07_SEED3)], solo(QWEN)), solo(GPT, SOLO_TEXT)]),
  pipeline_of_two_fusions: () =>
    pipeline([
      fusion([solo(GPT), solo(LLAMA)], solo(QWEN)),
      fusion([solo(CLAUDE), solo(QWEN)], solo(GPT)),
    ]),
  fusion_member_pipeline: () =>
    fusion([pipeline([solo(GPT), solo(LLAMA)]), solo(QWEN)], solo(GPT)),
};

describe("recipeToUrl4", () => {
  it.each(Object.keys(SDK_EQUIVALENTS) as (keyof typeof linked)[])(
    "renders the SDK's compiled candidate text (%s)",
    (name) => {
      expect(recipeToUrl4(SDK_EQUIVALENTS[name]())).toBe(linked[name].candidate);
    },
  );

  it.each(Object.keys(SDK_EQUIVALENTS) as (keyof typeof linked)[])(
    "imports the SDK's candidate text back to the same text (%s)",
    (name) => {
      const parsed = parseRecipe(linked[name].candidate);
      if (!parsed.ok) throw new Error(`rejected: ${parsed.error}`);
      expect(recipeToUrl4(parsed.root)).toBe(linked[name].candidate);
    },
  );

  it("puts params in url4's query form, with the context after q=", () => {
    expect(recipeToUrl4(solo("openai/gpt-4o", "Hi.", T07_SEED3))).toContain(
      "(model_1:0.0:/openai/gpt-4o?temperature=0.7&seed=3&q=($input)!'Hi.', _sf_recipe:0.0:",
    );
  });

  it("leaves a call without params unchanged", () => {
    expect(recipeToUrl4(solo("openai/gpt-4o"))).toBe(linked.solo.candidate);
  });

  it("skips params without a key or a value", () => {
    const params = [
      { key: "", value: "1" },
      { key: "seed", value: "" },
    ];
    expect(recipeToUrl4(solo("openai/gpt-4o", "", params))).toBe(linked.solo.candidate);
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
    [
      "a pipeline into a fusion",
      () =>
        pipeline([
          solo("openai/gpt-4o", "Draft."),
          fusion([solo("ollama/llama3"), solo("ollama/qwen", "", T07_SEED3)], solo("openai/gpt-4o")),
          solo("ollama/qwen", "Polish."),
        ]),
    ],
    [
      "a pipeline into a fusion with a pipeline synthesizer",
      () =>
        pipeline([
          solo("openai/gpt-4o"),
          fusion(
            [solo("ollama/llama3"), pipeline([solo("ollama/qwen"), solo("openai/gpt-4o")])],
            pipeline([solo("ollama/qwen", "Merge."), solo("openai/gpt-4o", "Check.")]),
          ),
        ]),
    ],
    [
      "a fusion whose synthesizer is a fusion",
      () =>
        fusion(
          [solo("openai/gpt-4o"), solo("ollama/llama3")],
          fusion([solo("ollama/qwen"), solo("openai/gpt-4o")], solo("ollama/llama3")),
        ),
    ],
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

  it.each([
    ["newlines", "First line.\nSecond line.\n\nAfter a blank line."],
    ["a dollar amount", "Answer in $USD."],
    ["text that looks like a reference", "use $input, then $model_1 and $synthesis_1"],
    ["a doubled dollar", "Costs $$5"],
    ["quotes and backslashes", "it's a \\ path, \\' and '\\"],
    ["all of them", SOLO_TEXT],
    ["runs of spaces", "  spaced   out  "],
  ])("decodes a prompt with %s back to the original text", (_name, prompt) => {
    for (const root of [
      solo("openai/gpt-4o", prompt),
      fusion([solo("openai/gpt-4o", prompt)], solo("ollama/llama3", prompt)),
    ]) {
      const { url4, parsed, again } = roundTrip(root);
      expect(again).toBe(url4);
      expect(collectSolos(parsed).map((node) => node.prompt)).toEqual(
        collectSolos(root).map(() => prompt),
      );
    }
  });

  it("never leaves a prompt's $ where url4 would read it as a reference", () => {
    const url4 = recipeToUrl4(solo("openai/gpt-4o", "use $input and $model_1"));
    expect(url4).toContain("'use $$input and $$model_1'");
  });

  it("encodes newlines as U+2028 and tabs as spaces, as the SDK does", () => {
    expect(recipeToUrl4(solo("a/b", "one\r\ntwo\rthree\tfour"))).toContain(
      "(model_1:0.0:/a/b($input)!'one\u2028two\u2028three four', _sf_recipe:0.0:",
    );
  });

  it("reports control characters the SDK refuses", () => {
    const root = solo("a/b", "be\u0000ep\u007f");
    expect(recipeIssues(root)).toEqual([expect.objectContaining({ nodeId: root.id, key: "prompt" })]);
    expect(() => recipeToUrl4(root)).toThrow(RecipeError);
  });

  it("uses the default prompt for a blank one", () => {
    expect(recipeToUrl4(solo("openai/gpt-4o", "  \n "))).toBe(linked.solo.candidate);
  });

  it("rejects a prompt with a single $, which would be a reference", () => {
    const golden = linked.solo_prompt_encoded.candidate;
    expect(golden).toContain("$$input");
    expect(parseRecipe(golden.replace("$$input", "$input")).ok).toBe(false);
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

describe("parameter validation", () => {
  it.each([
    ["an ampersand", "a&b"],
    ["a comma", "a,b"],
    ["parentheses", "f(x)"],
    ["a semicolon", "a;b"],
    ["a quote", "it's"],
    ["a space", "two words"],
    ["a backslash escape", "\\n\\n"],
    ["a newline", "a\nb"],
    ["a control character", "a\u0007"],
    ["an equals sign", "a=b"],
  ])("reports a value with %s instead of emitting it", (_name, value) => {
    const root = fusion([solo("openai/gpt-4o", "", [{ key: "stop", value }])], solo("ollama/llama3"));
    const issues = recipeIssues(root);

    expect(issues).toEqual([
      { nodeId: (root.members[0] as SoloNode).id, key: "stop", message: expect.stringContaining("stop") },
    ]);
    expect(() => recipeToUrl4(root)).toThrow(RecipeError);
    expect(renderRecipe(root)).toEqual({ ok: false, issues });
  });

  it.each([
    ["a name with a space", "top p"],
    ["a name with a dash", "top-p"],
    ["a reserved name", "q"],
    ["another reserved name", "model"],
  ])("reports %s", (_name, key) => {
    expect(recipeIssues(solo("a/b", "", [{ key, value: "1" }]))).toEqual([
      expect.objectContaining({ key, message: expect.any(String) }),
    ]);
  });

  it("accepts every value url4 carries unquoted, and skips unfinished rows", () => {
    const root = solo("a/b", "", [
      { key: "stop", value: "END:of/answer-1.0_x" },
      { key: "temperature", value: "-0.5" },
      { key: "", value: "x" },
      { key: "seed", value: "" },
    ]);
    expect(recipeIssues(root)).toEqual([]);
    expect(renderRecipe(root)).toEqual({ ok: true, url4: recipeToUrl4(root) });
  });

  it("refuses to import a parameter value url4 cannot carry", () => {
    const parsed = parseRecipe("(model_1:0.0:/a/b?stop=a,b&q=($input)!'Answer.')!'$model_1'");
    expect(parsed.ok).toBe(false);
  });
});

describe("recipe metadata", () => {
  const golden = linked.fusion_named.candidate;
  const calls = golden.slice(0, golden.indexOf(", _sf_recipe:"));
  const metadata = golden.slice(golden.indexOf("_sf_recipe:0.0:'") + 16, golden.lastIndexOf("')!'"));
  const withMetadata = (json: string) =>
    `${calls}, _sf_recipe:0.0:${quoteText(json)})!'$synthesis_1'`;

  it("recovers the recipe's names from the SDK metadata", () => {
    const parsed = parseRecipe(golden);
    if (!parsed.ok) throw new Error(parsed.error);
    const root = parsed.root as FusionNode;
    expect(root.name).toBe("panel");
    expect(root.members[0].name).toBe("careful");
    expect(root.members[1].name).toBeUndefined();
    expect(root.synthesizer.name).toBe("judge");
  });

  it.each([
    ["missing", `${calls})!'$synthesis_1'`, "missing"],
    ["not JSON", withMetadata("{not json"), "malformed"],
    ["another schema", withMetadata(metadata.replace("recipe.v1", "recipe.v2")), "malformed"],
    ["an extra key", withMetadata(metadata.replace('"named":true', '"named":true,"x":1')), "malformed"],
    [
      "a binding no call has",
      withMetadata(metadata.replace('"binding":"model_1"', '"binding":"model_9"')),
      "match",
    ],
    [
      "a different structure",
      withMetadata(metadata.replace('"kind":"fusion"', '"kind":"pipeline"')),
      "malformed",
    ],
    [
      "a role that disagrees with the call",
      withMetadata(metadata.replace('"role":"synthesis"', '"role":"model"')),
      "match",
    ],
  ])("rejects metadata that is %s", (_name, url4, word) => {
    const parsed = parseRecipe(url4);
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.error).toContain(word);
  });
});

describe("recipe issues the SDK would refuse", () => {
  it("reports a model id url4 cannot address", () => {
    const root = solo("ollama/llama3:8b");
    expect(recipeIssues(root)).toEqual([
      expect.objectContaining({ nodeId: root.id, key: "model" }),
    ]);
  });

  it("reports a name with a control character", () => {
    const root = named(solo(GPT), "bad\u0007name");
    expect(recipeIssues(root)).toEqual([expect.objectContaining({ nodeId: root.id, key: "name" })]);
  });

  it("reports a fusion with no members and a pipeline with no stages", () => {
    const empty = fusion([], solo(GPT));
    const none = pipeline([]);
    expect(recipeIssues(empty)).toEqual([expect.objectContaining({ nodeId: empty.id, key: "members" })]);
    expect(recipeIssues(none)).toEqual([expect.objectContaining({ nodeId: none.id, key: "stages" })]);
  });

  it("takes a blank name as no name", () => {
    expect(recipeToUrl4(named(solo(GPT), "   "))).toBe(linked.solo.candidate);
  });
});

describe("duplicate parameters", () => {
  it("reports a parameter set twice on one model instead of emitting both", () => {
    const root = solo(GPT, "", [
      { key: "seed", value: "1" },
      { key: "seed", value: "2" },
    ]);
    expect(recipeIssues(root)).toEqual([
      { nodeId: root.id, key: "seed", message: expect.stringContaining("seed") },
    ]);
    expect(() => recipeToUrl4(root)).toThrow(RecipeError);
  });

  it("allows the same parameter on different models", () => {
    const root = fusion([solo(GPT, "", T07_SEED3), solo(LLAMA, "", T07_SEED3)], solo(QWEN));
    expect(recipeIssues(root)).toEqual([]);
  });
});

describe("recipeName", () => {
  it("is the SDK's name: given, or inferred from the members", () => {
    expect(recipeName(SDK_EQUIVALENTS.fusion_named())).toBe("panel");
    expect(recipeName(SDK_EQUIVALENTS.fusion_defaults())).toBe("claude-opus-4-5+gpt-4o");
    expect(recipeName(SDK_EQUIVALENTS.pipeline_nested_named())).toBe("draft->qwen");
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

  it("refuses an empty pipeline, which the SDK cannot compile", () => {
    expect(() => recipeToUrl4(pipeline([]))).toThrow(RecipeError);
  });
});
