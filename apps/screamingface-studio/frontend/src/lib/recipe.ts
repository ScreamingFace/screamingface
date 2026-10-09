// Recipe-native model for the Studio builder.
//
// Mirrors ScreamingFace's real artifacts (packages/screamingface):
//   - Solo:     one Model (a "unit") — model route + optional prompt + params
//   - Fusion:   parallel `members` + a REQUIRED `synthesizer` (itself a Recipe)
//   - Pipeline: serial `stages` (only the last stage is graded)
// These nest arbitrarily. There is no "reduce" primitive — reduction IS the synthesizer.
//
// `recipeToUrl4` renders the recipe as url4 in the same `(sources)!intent` shape the SDK's
// `compile_candidate` produces (checked against SDK-generated goldens in `recipe.test.ts`), and
// `parseRecipe` reads exactly that text back, so a copied recipe imports as the same recipe.

import type { ModelParam, SavedModel, SavedSlot } from "./ensemble-store";
import { quoteText } from "./engine/url4";
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

// What `recipeToUrl4` writes for a solo with no model chosen yet, and for a solo with no
// prompt. `parseRecipe` reads both back as "unset".
const UNSET_MODEL = "‹model›";
const DEFAULT_PROMPT = {
  answer: "Answer.",
  synthesis: "Synthesize the member answers into one final answer.",
} as const;

// Prompt text as url4 Text, exactly as the SDK's `_url4_text`
// (`packages/screamingface/src/screamingface/_evaluation/candidate.py:436-447`): CR LF and CR
// become LF, LF becomes U+2028 (url4 Text is one line), a tab becomes a space, and `$` is
// doubled so `$input` / `$USD` stay literal text — the Engine collapses `$$` back to `$` when it
// substitutes (`url4/dag/semantics/ensemble.py` `_ENV_VAR_RE`). The SDK refuses any other control
// character; a builder preview cannot refuse, so Studio drops them. `quoteText` then escapes `\`
// and `'` (url4's `_quote`).
function encodePrompt(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")
    .replace(/\n/g, "\u2028")
    .replace(/\t/g, " ")
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .replace(/\$/g, "$$$$");
}

// The inverse, as the SDK reads a Candidate back (`screamingface/url4.py:446-447`
// `_python_text`): U+2028 is a newline again and `$$` is `$`.
function decodePrompt(text: string): string {
  return text.replace(/\u2028/g, "\n").replace(/\$\$/g, "$");
}

// url4's query form for a call with params: `?k=v&…&q=` and then the call's `(<context>)`
// (`url4/core/render.py` `_render_target_expr`). Without params a call is `/path(<context>)`.
function paramQuery(params: ModelParam[]): string {
  const kv = params
    .filter((param) => param.key && param.value !== "")
    .map((param) => `${param.key}=${param.value}`);
  return kv.length ? `?${kv.join("&")}&q=` : "";
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
      const path = `/${node.model ? node.model.name : UNSET_MODEL}`;
      // A blank prompt means the default (the SDK refuses a blank one outright).
      const prompt = node.prompt.trim() ? node.prompt : DEFAULT_PROMPT[role];
      const intent = quoteText(encodePrompt(prompt));
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

// ── url4 import ───────────────────────────────────────────────────────────────

export type ParsedRecipe = { ok: true; root: RecipeNode } | { ok: false; error: string };

type SourceContext = { kind: "ref"; ref: string } | { kind: "fusion"; members: string[] };

type ParsedSource = {
  name: string;
  modelId: string | null;
  params: ModelParam[];
  intent: string;
  context: SourceContext;
};

class RecipeSyntaxError extends Error {}

const NOT_A_RECIPE =
  "This isn't a recipe Studio can import. Paste the url4 that Share url4 copied.";

function fail(): never {
  throw new RecipeSyntaxError(NOT_A_RECIPE);
}

// A cursor over one recipe string. It reads only the shapes `recipeToUrl4` writes.
class Scanner {
  pos = 0;

  constructor(readonly text: string) {}

  expect(literal: string) {
    if (!this.text.startsWith(literal, this.pos)) fail();
    this.pos += literal.length;
  }

  match(pattern: RegExp): RegExpExecArray {
    const sticky = new RegExp(pattern.source, "y");
    sticky.lastIndex = this.pos;
    const found = sticky.exec(this.text);
    if (!found) fail();
    this.pos = sticky.lastIndex;
    return found;
  }

  // A url4 Text literal: `'…'` with only `\\` and `\'` escaped (url4's `_quote`).
  quoted(): string {
    this.expect("'");
    let out = "";
    while (this.pos < this.text.length) {
      const char = this.text[this.pos++];
      if (char === "'") return out;
      if (char === "\\") {
        const next = this.text[this.pos++];
        if (next !== "\\" && next !== "'") fail();
        out += next;
      } else {
        out += char;
      }
    }
    return fail();
  }

  // The body of a balanced `( … )`, skipping quoted text.
  parenthesized(): string {
    this.expect("(");
    const start = this.pos;
    let depth = 1;
    while (this.pos < this.text.length) {
      const char = this.text[this.pos];
      if (char === "'") {
        this.quoted();
        continue;
      }
      this.pos += 1;
      if (char === "(" || char === "{") depth += 1;
      if (char === ")" || char === "}") depth -= 1;
      if (depth === 0) return this.text.slice(start, this.pos - 1);
    }
    return fail();
  }
}

const FUSION_CONTEXT = /^\{input: '\$input', outputs: \{(.*)\}\}$/;
const FUSION_OUTPUT = /^member_(\d+): '\$([a-z]+_\d+)'$/;

function sourceContext(text: string): SourceContext {
  const ref = /^\$(input|[a-z]+_\d+)$/.exec(text);
  if (ref) return { kind: "ref", ref: ref[1] };
  const fusion = FUSION_CONTEXT.exec(text);
  if (!fusion) fail();
  const members = fusion[1].split(", ").map((output, index) => {
    const member = FUSION_OUTPUT.exec(output);
    if (!member || Number(member[1]) !== index + 1) fail();
    return member[2];
  });
  return { kind: "fusion", members };
}

function sourceParams(query: string | undefined): ModelParam[] {
  if (query === undefined) return [];
  return query
    .split("&")
    .slice(0, -1)
    .map((pair) => {
      const separator = pair.indexOf("=");
      if (separator <= 0) fail();
      return { key: pair.slice(0, separator), value: pair.slice(separator + 1) };
    });
}

function readSource(scanner: Scanner): ParsedSource {
  const [, name, route, query] = scanner.match(
    /([a-z]+_\d+):0\.0:\/([^?(]+)(?:\?((?:[^&()]*&)+)q=)?/,
  );
  const context = sourceContext(scanner.parenthesized());
  scanner.expect("!");
  const intent = scanner.quoted();
  return {
    name,
    modelId: route === UNSET_MODEL ? null : route,
    params: sourceParams(query),
    intent,
    context,
  };
}

function readSources(text: string): { sources: ParsedSource[]; root: string } {
  const scanner = new Scanner(text);
  const sources: ParsedSource[] = [];
  scanner.expect("(");
  for (;;) {
    sources.push(readSource(scanner));
    if (scanner.text.startsWith(")", scanner.pos)) break;
    scanner.expect(", ");
  }
  scanner.expect(")!");
  const root = /^\$([a-z]+_\d+)$/.exec(scanner.quoted());
  if (!root || scanner.pos !== text.length) fail();
  return { sources, root: root[1] };
}

function modelFromRoute(route: string): SavedModel {
  const providerId = route.split("/")[0];
  return { id: route, name: route, providerId, providerName: providerId };
}

// Rebuild the recipe tree from `recipeToUrl4`'s flat source list. A source's context says what
// produced its input: `$input` starts a chain, `$<ref>` continues a pipeline, and a fusion
// context starts a fusion's synthesizer (a `synthesis_N` solo, or a pipeline of `model_N`s).
function buildTree(sources: ParsedSource[], rootRef: string): RecipeNode {
  const byName = new Map(sources.map((source) => [source.name, source]));
  if (byName.size !== sources.length) fail();
  const used = new Set<string>();

  function take(ref: string): ParsedSource {
    const source = byName.get(ref);
    if (!source || used.has(ref)) fail();
    used.add(ref);
    return source;
  }

  function toSolo(source: ParsedSource): SoloNode {
    const role = source.name.startsWith("synthesis_") ? "synthesis" : "answer";
    return {
      kind: "solo",
      id: createUuid(),
      model: source.modelId ? modelFromRoute(source.modelId) : null,
      prompt: source.intent === DEFAULT_PROMPT[role] ? "" : decodePrompt(source.intent),
      params: source.params,
    };
  }

  function chainOf(nodes: RecipeNode[]): RecipeNode {
    return nodes.length === 1
      ? nodes[0]
      : { kind: "pipeline", id: createUuid(), stages: nodes };
  }

  function build(ref: string): RecipeNode {
    const chain = [take(ref)];
    let head = chain[0].context;
    while (head.kind === "ref" && head.ref !== "input") {
      chain.unshift(take(head.ref));
      head = chain[0].context;
    }
    if (head.kind === "ref") return chainOf(chain.map(toSolo));
    const members = head.members.map(build);
    if (!chain[0].name.startsWith("synthesis_")) {
      return {
        kind: "fusion",
        id: createUuid(),
        members,
        synthesizer: chainOf(chain.map(toSolo)),
      };
    }
    const fusion: FusionNode = {
      kind: "fusion",
      id: createUuid(),
      members,
      synthesizer: toSolo(chain[0]),
    };
    return chainOf([fusion, ...chain.slice(1).map(toSolo)]);
  }

  const root = build(rootRef);
  if (used.size !== sources.length) fail();
  return root;
}

// Read back exactly what `recipeToUrl4` writes (spec D8). Anything else — the old
// `url4://name?models=` form, a truncated copy, hand-edited text — is rejected whole, never
// half-parsed: the rebuilt recipe must render back to the very same text.
export function parseRecipe(url4: string): ParsedRecipe {
  const text = url4.trim();
  try {
    const { sources, root: rootRef } = readSources(text);
    const root = buildTree(sources, rootRef);
    if (recipeToUrl4(root) !== text) fail();
    return { ok: true, root };
  } catch (error) {
    if (error instanceof RecipeSyntaxError) return { ok: false, error: error.message };
    throw error;
  }
}

// A fusion of the given models with the synthesizer left for the user to choose: what the
// Models page's "Compose" and the leaderboard's "Remix" hand to the builder.
export function fusionOf(models: SavedModel[]): FusionNode {
  return {
    kind: "fusion",
    id: createUuid(),
    members: models.map((model) => createSolo(model)),
    synthesizer: createSolo(),
  };
}

// Swap each parsed model for the catalog's own entry (which carries the provider's display
// name). A model the catalog lacks is left unset and named in `unknown`, once.
export function resolveModels(
  root: RecipeNode,
  catalog: SavedModel[],
): { root: RecipeNode; unknown: string[] } {
  const unknown = new Set<string>();

  function resolve(node: RecipeNode): RecipeNode {
    if (node.kind === "solo") {
      if (!node.model) return node;
      const known = catalog.find((model) => model.id === node.model?.id) ?? null;
      if (!known) unknown.add(node.model.id);
      return { ...node, model: known };
    }
    if (node.kind === "fusion") {
      return {
        ...node,
        members: node.members.map(resolve),
        synthesizer: resolve(node.synthesizer),
      };
    }
    return { ...node, stages: node.stages.map(resolve) };
  }

  const resolved = resolve(root);
  return { root: resolved, unknown: [...unknown] };
}
