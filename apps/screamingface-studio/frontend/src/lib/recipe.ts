// Recipe-native model for the Studio builder.
//
// Mirrors ScreamingFace's real artifacts (packages/screamingface):
//   - Solo:     one Model (a "unit") — model route + optional prompt + params
//   - Fusion:   parallel `members` + a REQUIRED `synthesizer` (itself a Recipe)
//   - Pipeline: serial `stages` (only the last stage is graded)
// These nest arbitrarily. There is no "reduce" primitive — reduction IS the synthesizer.
//
// `recipeToUrl4` renders a structurally-faithful url4 PREVIEW as the user builds. It is not
// the engine's byte-canonical string (that comes from the engine at run time); it captures
// the topology in url4's `(sources)!intent` shape, modelled on the compiled Fusion example
// in the walkthrough notebook.

import type { ModelParam, SavedModel, SavedSlot } from "./ensemble-store";
import { createUuid } from "./uuid";

export type RecipeKind = "solo" | "fusion" | "pipeline";

export type SoloNode = {
  kind: "solo";
  id: string;
  name?: string;
  model: SavedModel | null;
  prompt: string;
  params: ModelParam[];
};

export type FusionNode = {
  kind: "fusion";
  id: string;
  name?: string;
  members: RecipeNode[];
  synthesizer: RecipeNode;
};

export type PipelineNode = {
  kind: "pipeline";
  id: string;
  name?: string;
  stages: RecipeNode[];
};

export type RecipeNode = SoloNode | FusionNode | PipelineNode;

// ── Factories ────────────────────────────────────────────────────────────────

export function createSolo(model: SavedModel | null = null): SoloNode {
  return { kind: "solo", id: createUuid(), model, prompt: "", params: [] };
}

export function createFusion(): FusionNode {
  return {
    kind: "fusion",
    id: createUuid(),
    members: [createSolo(), createSolo()],
    synthesizer: createSolo(),
  };
}

export function createPipeline(): PipelineNode {
  return {
    kind: "pipeline",
    id: createUuid(),
    stages: [createSolo(), createSolo()],
  };
}

export function createNode(kind: RecipeKind): RecipeNode {
  if (kind === "fusion") return createFusion();
  if (kind === "pipeline") return createPipeline();
  return createSolo();
}

// The nodes a conversion should try to carry forward: a solo with a model carries itself
// (as a singleton, under a fresh id so it doesn't collide with the new root), a fusion
// carries its members, a pipeline carries its stages.
function carriableChildren(node: RecipeNode): RecipeNode[] {
  if (node.kind === "solo") return node.model ? [{ ...node, id: createUuid() }] : [];
  if (node.kind === "fusion") return node.members;
  return node.stages;
}

// Switch a node's kind in place (keeps its id so it stays put in its parent). Existing
// configuration is preserved wherever the target kind can represent it: a solo's model
// carries into the first member/stage; a fusion's members or a pipeline's stages carry
// straight across when converting between the two; a fusion's synthesizer is kept when the
// node stays a fusion. Only genuinely unrepresentable state (e.g. collapsing several
// members into a single solo) is dropped, and even then the first child's config is kept
// when it fits.
export function convertKind(node: RecipeNode, kind: RecipeKind): RecipeNode {
  if (node.kind === kind) return node;
  const carried = carriableChildren(node);
  if (kind === "solo") {
    const first = carried[0];
    if (first?.kind === "solo" && first.model) {
      return { ...first, id: node.id, name: node.name };
    }
    return { ...createSolo(), id: node.id, name: node.name };
  }
  if (kind === "fusion") {
    const base = createFusion();
    return {
      ...base,
      id: node.id,
      name: node.name,
      members: carried.length ? carried : base.members,
      synthesizer: node.kind === "fusion" ? node.synthesizer : base.synthesizer,
    };
  }
  const base = createPipeline();
  return {
    ...base,
    id: node.id,
    name: node.name,
    stages: carried.length ? carried : base.stages,
  };
}

// Human-readable summary of a recipe's top-level shape, for list/card views. Replaces the
// old "voting strategy" label — the recipe-native model has no such concept, so that field
// no longer reflects what was actually built.
export function describeRecipeKind(root: RecipeNode): string {
  if (root.kind === "solo") return "Solo";
  if (root.kind === "fusion") {
    const count = root.members.length;
    return `Fusion · ${count} member${count === 1 ? "" : "s"}`;
  }
  const count = root.stages.length;
  return `Pipeline · ${count} stage${count === 1 ? "" : "s"}`;
}

// ── Traversal ────────────────────────────────────────────────────────────────

export function collectSolos(node: RecipeNode): SoloNode[] {
  if (node.kind === "solo") return [node];
  if (node.kind === "fusion") {
    return [...node.members.flatMap(collectSolos), ...collectSolos(node.synthesizer)];
  }
  return node.stages.flatMap(collectSolos);
}

// Solos that "answer" — for a fusion, everything except its own synthesizer; for a pipeline,
// every stage except the last (which is the graded/final stage, not a parallel member).
// Used to feed the mock RunsPanel's member list without double-counting the grading step.
export function memberSolos(root: RecipeNode): SoloNode[] {
  if (root.kind === "fusion") return root.members.flatMap(collectSolos);
  if (root.kind === "pipeline") return root.stages.slice(0, -1).flatMap(collectSolos);
  return collectSolos(root);
}

// The node that grades/produces the final result — a fusion's synthesizer, or a pipeline's
// last stage — when it is a single Model. Surfaced as the run's synthesis/judge step. Nested
// / composite graders return null (the mock simply omits the step).
export function rootSynthesizerSolo(root: RecipeNode): SoloNode | null {
  if (root.kind === "fusion" && root.synthesizer.kind === "solo" && root.synthesizer.model) {
    return root.synthesizer;
  }
  if (root.kind === "pipeline") {
    const last = root.stages[root.stages.length - 1];
    if (last?.kind === "solo" && last.model) return last;
  }
  return null;
}

// ── Legacy migration (flat slots + optional judge → a Fusion) ─────────────────

export function fusionFromSlots(
  slots: SavedSlot[] | undefined,
  judge: SavedSlot | null,
): FusionNode {
  const members = (slots ?? []).map((slot) => ({
    ...createSolo(slot.model),
    prompt: slot.systemPrompt ?? "",
    params: slot.params ?? [],
  }));
  const synthesizer = judge
    ? { ...createSolo(judge.model), prompt: judge.systemPrompt ?? "" }
    : createSolo();
  return {
    kind: "fusion",
    id: createUuid(),
    members: members.length > 0 ? members : [createSolo()],
    synthesizer,
  };
}

// ── url4 preview ──────────────────────────────────────────────────────────────

function quoteIntent(text: string): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  return `'${oneLine.replace(/'/g, "\\'")}'`;
}

function paramQuery(params: ModelParam[]): string {
  const kv = params
    .filter((param) => param.key && param.value !== "")
    .map((param) => `${param.key}=${param.value}`);
  return kv.length ? `?${kv.join("&")}` : "";
}

export function recipeToUrl4(root: RecipeNode): string {
  const sources: string[] = [];
  const counters = { model: 0, synthesis: 0 };

  function emit(
    node: RecipeNode,
    context: string,
    role: "answer" | "synthesis",
  ): string {
    if (node.kind === "solo") {
      const prefix = role === "synthesis" ? "synthesis" : "model";
      const index = role === "synthesis" ? ++counters.synthesis : ++counters.model;
      const name = `${prefix}_${index}`;
      const path = node.model ? `/${node.model.name}` : "/‹model›";
      const intent = node.prompt
        ? quoteIntent(node.prompt)
        : role === "synthesis"
          ? "'Synthesize the member answers into one final answer.'"
          : "'Answer.'";
      sources.push(`${name}:0.0:${path}${paramQuery(node.params)}(${context})!${intent}`);
      return name;
    }
    if (node.kind === "fusion") {
      const memberRefs = node.members.map((member) => emit(member, "$input", "answer"));
      const outputs = memberRefs
        .map((ref, i) => `member_${i + 1}: '$${ref}'`)
        .join(", ");
      const synthContext = `{input: '$input', outputs: {${outputs}}}`;
      return emit(node.synthesizer, synthContext, "synthesis");
    }
    // pipeline — each stage consumes the previous stage's output
    let ctx = context;
    let last = "";
    for (const stage of node.stages) {
      last = emit(stage, ctx, "answer");
      ctx = `$${last}`;
    }
    return last || (context.startsWith("$") ? context.slice(1) : "input");
  }

  const rootRef = emit(root, "$input", "answer");
  return `(${sources.join(", ")})!'$${rootRef}'`;
}

// A short human-readable one-line shape, e.g. "Fusion(2 members → synthesizer)".
export function describeRecipe(node: RecipeNode): string {
  if (node.kind === "solo") {
    return node.model ? node.model.name : "unset model";
  }
  if (node.kind === "fusion") {
    return `Fusion(${node.members.length} member${
      node.members.length === 1 ? "" : "s"
    } → synthesizer)`;
  }
  return `Pipeline(${node.stages.length} stage${node.stages.length === 1 ? "" : "s"})`;
}
