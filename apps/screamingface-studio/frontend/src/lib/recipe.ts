// Recipe-native model for the Studio builder.
//
// Mirrors ScreamingFace's real artifacts (packages/screamingface):
//   - Solo:     one Model (a "unit") — model route + optional prompt + params
//   - Fusion:   parallel `members` + a REQUIRED `synthesizer` (itself a Recipe)
//   - Pipeline: serial `stages` (only the last stage is graded)
// These nest arbitrarily. There is no "reduce" primitive — reduction IS the synthesizer.
//
// `recipeToUrl4` compiles the recipe to the very text the SDK's `compile_candidate` produces for
// the same Recipe, `_sf_recipe` metadata included (spec D4; checked against SDK-generated goldens
// in `recipe.test.ts`), and `parseRecipe` reads that text back, so a copied recipe imports as the
// same recipe.

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

// ── url4 compilation ──────────────────────────────────────────────────────────

// A solo with no model chosen yet. The SDK has no such thing (it cannot compile a Model without
// a route), so this placeholder is the one place Studio's text cannot match the SDK's: a recipe
// containing it can be previewed and shared, never run.
const UNSET_MODEL = "‹model›";
// The SDK's default prompts (`packages/screamingface/src/screamingface/_evaluation/policy.py:7-15`),
// used when a solo has no prompt of its own. `parseRecipe` reads them back as "no prompt".
const DEFAULT_PROMPT = {
  model:
    "Answer the request accurately and completely. " +
    "Follow every instruction and formatting constraint in the request.",
  synthesis:
    "Produce the final answer to the original request. " +
    "Synthesize the strongest supported answer from the panel responses, and follow every " +
    "instruction and formatting constraint in the original request.",
} as const;

type Role = keyof typeof DEFAULT_PROMPT;

// Prompt text as url4 Text, exactly as the SDK's `_url4_text`
// (`packages/screamingface/src/screamingface/_evaluation/candidate.py:436-447`): CR LF and CR
// become LF, LF becomes U+2028 (url4 Text is one line), a tab becomes a space, and `$` is
// doubled so `$input` / `$USD` stay literal text — the Engine collapses `$$` back to `$` when it
// substitutes (`url4/dag/semantics/ensemble.py` `_ENV_VAR_RE`). Any other control character is
// refused (`recipeIssues`), as the SDK refuses it. `quoteText` then escapes `\` and `'`.
function encodePrompt(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")
    .replace(/\n/g, "\u2028")
    .replace(/\t/g, " ")
    .replace(/\$/g, "$$$$");
}

// The inverse, as the SDK reads a Candidate back (`screamingface/url4.py:446-447`
// `_python_text`): U+2028 is a newline again and `$$` is `$`.
function decodePrompt(text: string): string {
  return text.replace(/\u2028/g, "\n").replace(/\$\$/g, "$");
}

// ── Issues the SDK would refuse ───────────────────────────────────────────────

// Parameter names the SDK keeps for the Benchmark and Engine
// (`packages/screamingface/src/screamingface/_candidate_policy.py:12-28`).
const RESERVED_PARAMS = new Set([
  "input",
  "messages",
  "model",
  "plugins",
  "provider",
  "q",
  "stream",
  "tool_choice",
  "tools",
  "web_search",
  "web_search_exclude",
  "web_search_excluded_domains",
  "web_search_policy",
]);
// url4 `param-key` (`packages/url4/src/url4/core/_annotations.py:63`), as the SDK checks it
// (`_candidate_policy.py:54-65`).
const PARAM_KEY = /^[A-Za-z0-9._]+$/;
// url4 `param-value` (`_annotations.py:64-67`: ALPHA / DIGIT / . - _ , : /) without the `,` that
// the renderer refuses in a query value (`url4/core/render.py:504-511`) and the SDK refuses too
// (`_candidate_policy.py:73-76`). Anything else cannot be carried unquoted, and the SDK never
// quotes a parameter, so the SDK would refuse to compile it.
const PARAM_VALUE = /^[A-Za-z0-9._\-:/]+$/;
// The model routes the SDK can address (`_evaluation/candidate.py` `_MODEL_ROUTE_RE`).
const MODEL_ROUTE = /^[A-Za-z0-9\-_.~]+(?:\/[A-Za-z0-9\-_.~]+)*$/;
// Control characters the SDK refuses in a prompt after mapping tab, CR and LF
// (`candidate.py:439-446`).
const PROMPT_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
// A name with any Unicode "other" character (category C*) is refused (`recipe.py:35-39` `_name`).
const NAME_CONTROL = /\p{C}/u;

export type RecipeIssue = { nodeId: string; key: string; message: string };

// A recipe the SDK would refuse to compile. `issues` says why, for the UI to show.
export class RecipeError extends Error {
  readonly issues: RecipeIssue[];

  constructor(issues: RecipeIssue[]) {
    super(issues.map((issue) => issue.message).join(" "));
    this.name = "RecipeError";
    this.issues = issues;
  }
}

// A row with no name or no value is still being typed, and is left out, not reported.
function filledParams(params: ModelParam[]): ModelParam[] {
  return params.filter((param) => param.key && param.value !== "");
}

function paramIssue(param: ModelParam): string | null {
  if (!PARAM_KEY.test(param.key)) {
    return `"${param.key}" isn't a valid parameter name: use letters, digits, "." and "_".`;
  }
  if (RESERVED_PARAMS.has(param.key)) {
    return `"${param.key}" is set by the Engine and can't be a model parameter.`;
  }
  if (!PARAM_VALUE.test(param.value)) {
    return `The value of "${param.key}" can only use letters, digits and . - _ : /`;
  }
  return null;
}

// A user-given name, trimmed as the SDK trims it; blank means "no name".
function givenName(node: RecipeNode): string | null {
  const name = node.name?.trim();
  return name ? name : null;
}

// Everything in the recipe the SDK would refuse to compile, so the builder can show it instead
// of sharing or running text the SDK could never have produced.
export function recipeIssues(root: RecipeNode): RecipeIssue[] {
  const issues: RecipeIssue[] = [];
  const add = (node: RecipeNode, key: string, message: string) =>
    issues.push({ nodeId: node.id, key, message });

  function visit(node: RecipeNode) {
    const name = givenName(node);
    if (name && NAME_CONTROL.test(name)) {
      add(node, "name", `The name "${name}" contains a control character.`);
    }
    if (node.kind === "solo") {
      if (node.model && !MODEL_ROUTE.test(node.model.name)) {
        add(node, "model", `The Engine can't address the model id "${node.model.name}" in url4.`);
      }
      if (PROMPT_CONTROL.test(node.prompt)) {
        add(node, "prompt", "A prompt can't contain control characters.");
      }
      for (const param of filledParams(node.params)) {
        const message = paramIssue(param);
        if (message) add(node, param.key, message);
      }
    } else if (node.kind === "fusion") {
      if (node.members.length === 0) add(node, "members", "A fusion needs at least one member.");
      node.members.forEach(visit);
      visit(node.synthesizer);
    } else {
      if (node.stages.length === 0) add(node, "stages", "A pipeline needs at least one stage.");
      node.stages.forEach(visit);
    }
  }

  visit(root);
  return issues;
}

// url4's query form for a call with params: `?k=v&…&q=` and then the call's `(<context>)`
// (`url4/core/render.py` `_render_target_expr`). Without params a call is `/path(<context>)`.
function paramQuery(params: ModelParam[]): string {
  const kv = filledParams(params).map((param) => `${param.key}=${param.value}`);
  return kv.length ? `?${kv.join("&")}&q=` : "";
}

// ── SDK naming and topology ───────────────────────────────────────────────────

// The SDK's flattening of an unnamed nested Pipeline into its parent (`pipeline.py` `_stages`).
function flatStages(node: PipelineNode): RecipeNode[] {
  return node.stages.flatMap((stage) =>
    stage.kind === "pipeline" && !givenName(stage) ? flatStages(stage) : [stage],
  );
}

// The SDK's Recipe name: the given name, or the inferred one — a Model's last route segment
// (`model.py`), members joined by `+` (`fusion.py`), stages joined by `->` (`pipeline.py`).
function sdkName(node: RecipeNode): string {
  const name = givenName(node);
  if (name) return name;
  if (node.kind === "solo") return (node.model?.name ?? UNSET_MODEL).split("/").at(-1) as string;
  if (node.kind === "fusion") return node.members.map(sdkName).join("+");
  return flatStages(node).map(sdkName).join("->");
}

// `_RecipeTopology` as `topology.py` `_encode_*` writes it, keys already in sorted order so
// `JSON.stringify` matches `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
type Topology =
  | { binding: string; kind: "model"; name: string; named: boolean; role: Role }
  | { binding: string; kind: "pipeline"; name: string; named: boolean; stages: Topology[] }
  | {
      binding: string;
      kind: "fusion";
      members: Topology[];
      name: string;
      synthesizer: Topology;
    };

const TOPOLOGY_SCHEMA = "screamingface.recipe.v1";
const TOPOLOGY_SOURCE = "_sf_recipe";

// Compile a recipe to Candidate url4 exactly as the SDK's `compile_candidate` does
// (`_evaluation/candidate.py` `_CandidateCompiler`): one `model_N` source per Model in
// compile order, a `synthesis_N` source for a fusion's Model synthesizer (the number is spent
// when the fusion is compiled, even when its synthesizer is a whole Recipe), the same
// contexts, and the `_sf_recipe` topology source last.
function compile(root: RecipeNode): string {
  const sources: string[] = [];
  let models = 0;
  let syntheses = 0;

  function call(binding: string, node: SoloNode, context: string, role: Role): Topology {
    const route = node.model ? node.model.name : UNSET_MODEL;
    const prompt = node.prompt.trim() ? node.prompt : DEFAULT_PROMPT[role];
    sources.push(
      `${binding}:0.0:/${route}${paramQuery(node.params)}(${context})!${quoteText(encodePrompt(prompt))}`,
    );
    return { binding, kind: "model", name: sdkName(node), named: Boolean(givenName(node)), role };
  }

  // `_recipe`: a Model compiles as `model_N`, in the synthesis role when it is (or starts) a
  // fusion's synthesizer Recipe.
  function recipe(node: RecipeNode, context: string, synthesis: boolean): Topology {
    if (node.kind === "solo") {
      return call(`model_${++models}`, node, context, synthesis ? "synthesis" : "model");
    }
    if (node.kind === "fusion") {
      const members = node.members.map((member) => recipe(member, context, false));
      // `_fusion_context`: the fusion's input as url4 text, beside each member's answer.
      const outputs = members.map((member, i) => `member_${i + 1}: '$${member.binding}'`);
      const fusionContext = `{input: ${quoteText(context)}, outputs: {${outputs.join(", ")}}}`;
      const binding = `synthesis_${++syntheses}`;
      const synthesizer =
        node.synthesizer.kind === "solo"
          ? call(binding, node.synthesizer, fusionContext, "synthesis")
          : recipe(node.synthesizer, fusionContext, true);
      return {
        binding: synthesizer.binding,
        kind: "fusion",
        members,
        name: sdkName(node),
        synthesizer,
      };
    }
    let stageContext = context;
    const stages = flatStages(node).map((stage, index) => {
      const compiled = recipe(stage, stageContext, synthesis && index === 0);
      stageContext = `$${compiled.binding}`;
      return compiled;
    });
    return {
      binding: stages.at(-1)?.binding ?? "",
      kind: "pipeline",
      name: sdkName(node),
      named: Boolean(givenName(node)),
      stages,
    };
  }

  const topology = recipe(root, "$input", false);
  const metadata = JSON.stringify({ recipe: topology, schema: TOPOLOGY_SCHEMA });
  sources.push(`${TOPOLOGY_SOURCE}:0.0:${quoteText(metadata)}`);
  return `(${sources.join(", ")})!'$${topology.binding}'`;
}

export type RenderedRecipe = { ok: true; url4: string } | { ok: false; issues: RecipeIssue[] };

// The recipe's url4, or what keeps the SDK from compiling it.
export function renderRecipe(root: RecipeNode): RenderedRecipe {
  const issues = recipeIssues(root);
  return issues.length ? { ok: false, issues } : { ok: true, url4: compile(root) };
}

// The recipe's Candidate url4, byte-identical to the SDK's `compile_candidate` for the same
// Recipe. Throws a `RecipeError` for anything the SDK would refuse (see `recipeIssues`).
export function recipeToUrl4(root: RecipeNode): string {
  const rendered = renderRecipe(root);
  if (!rendered.ok) throw new RecipeError(rendered.issues);
  return rendered.url4;
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

type ParsedSource = {
  name: string;
  modelId: string | null;
  params: ModelParam[];
  intent: string;
};

class RecipeSyntaxError extends Error {}

const NOT_A_RECIPE =
  "This isn't a recipe Studio can import. Paste the url4 that Share url4 copied.";
const METADATA_MISSING = `${NOT_A_RECIPE} Its _sf_recipe metadata is missing.`;
const METADATA_MALFORMED = `${NOT_A_RECIPE} Its _sf_recipe metadata is malformed.`;
const METADATA_MISMATCH = `${NOT_A_RECIPE} Its _sf_recipe metadata doesn't match its model calls.`;

function fail(message = NOT_A_RECIPE): never {
  throw new RecipeSyntaxError(message);
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
  // The context is checked by rendering the rebuilt recipe again, not read here.
  scanner.parenthesized();
  scanner.expect("!");
  const intent = scanner.quoted();
  return {
    name,
    modelId: route === UNSET_MODEL ? null : route,
    params: sourceParams(query),
    intent,
  };
}

function readSources(text: string): { sources: ParsedSource[]; metadata: string; root: string } {
  const scanner = new Scanner(text);
  const sources: ParsedSource[] = [];
  let metadata: string | null = null;
  scanner.expect("(");
  for (;;) {
    if (metadata !== null) fail();
    if (text.startsWith(`${TOPOLOGY_SOURCE}:0.0:`, scanner.pos)) {
      scanner.expect(`${TOPOLOGY_SOURCE}:0.0:`);
      metadata = scanner.quoted();
    } else {
      sources.push(readSource(scanner));
    }
    if (scanner.text.startsWith(")", scanner.pos)) break;
    scanner.expect(", ");
  }
  scanner.expect(")!");
  const root = /^\$([a-z]+_\d+)$/.exec(scanner.quoted());
  if (!root || scanner.pos !== text.length) fail();
  if (metadata === null) fail(METADATA_MISSING);
  return { sources, metadata, root: root[1] };
}

function modelFromRoute(route: string): SavedModel {
  const providerId = route.split("/")[0];
  return { id: route, name: route, providerId, providerName: providerId };
}

function exactKeys(value: Record<string, unknown>, keys: string[]) {
  const actual = Object.keys(value).sort();
  if (actual.length !== keys.length || actual.some((key, i) => key !== keys[i])) {
    fail(METADATA_MALFORMED);
  }
}

function metadataObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(METADATA_MALFORMED);
  return value as Record<string, unknown>;
}

function metadataText(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) fail(METADATA_MALFORMED);
  return value;
}

// Rebuild the recipe from its `_sf_recipe` topology (checked as strictly as the SDK's
// `topology.py` `_decode_*`), filling each Model from the call its binding names. Names come back
// as given names where the SDK marks them `named` (Models, Pipelines) or where they differ from
// the inferred name (Fusions, which carry no `named` flag).
function buildTree(sources: ParsedSource[], metadata: string): RecipeNode {
  let payload: Record<string, unknown>;
  try {
    payload = metadataObject(JSON.parse(metadata));
  } catch {
    return fail(METADATA_MALFORMED);
  }
  exactKeys(payload, ["recipe", "schema"]);
  if (payload.schema !== TOPOLOGY_SCHEMA) fail(METADATA_MALFORMED);

  const byName = new Map(sources.map((source) => [source.name, source]));
  if (byName.size !== sources.length) fail();
  const used = new Set<string>();

  function node(value: unknown): RecipeNode {
    const topology = metadataObject(value);
    const name = metadataText(topology.name);
    metadataText(topology.binding);
    if (topology.kind === "model") {
      exactKeys(topology, ["binding", "kind", "name", "named", "role"]);
      if (typeof topology.named !== "boolean") fail(METADATA_MALFORMED);
      if (topology.role !== "model" && topology.role !== "synthesis") fail(METADATA_MALFORMED);
      const source = byName.get(topology.binding as string);
      if (!source || used.has(source.name)) fail(METADATA_MISMATCH);
      used.add(source.name);
      const role = topology.role as Role;
      return {
        kind: "solo",
        id: createUuid(),
        ...(topology.named ? { name } : {}),
        model: source.modelId ? modelFromRoute(source.modelId) : null,
        prompt: source.intent === encodePrompt(DEFAULT_PROMPT[role]) ? "" : decodePrompt(source.intent),
        params: source.params,
      };
    }
    if (topology.kind === "pipeline") {
      exactKeys(topology, ["binding", "kind", "name", "named", "stages"]);
      if (typeof topology.named !== "boolean" || !Array.isArray(topology.stages)) {
        fail(METADATA_MALFORMED);
      }
      if (topology.stages.length === 0) fail(METADATA_MALFORMED);
      return {
        kind: "pipeline",
        id: createUuid(),
        ...(topology.named ? { name } : {}),
        stages: topology.stages.map(node),
      };
    }
    if (topology.kind === "fusion") {
      exactKeys(topology, ["binding", "kind", "members", "name", "synthesizer"]);
      if (!Array.isArray(topology.members) || topology.members.length === 0) {
        fail(METADATA_MALFORMED);
      }
      const fusion: FusionNode = {
        kind: "fusion",
        id: createUuid(),
        members: topology.members.map(node),
        synthesizer: node(topology.synthesizer),
      };
      return name === sdkName(fusion) ? fusion : { ...fusion, name };
    }
    return fail(METADATA_MALFORMED);
  }

  const root = node(payload.recipe);
  if (used.size !== sources.length) fail(METADATA_MISMATCH);
  return root;
}

// Read back exactly what `recipeToUrl4` (and the SDK's `compile_candidate`) writes (spec D8).
// Anything else — the old `url4://name?models=` form, a truncated copy, metadata that does not
// describe the calls, hand-edited text — is rejected whole, never half-parsed: the rebuilt
// recipe must compile back to the very same text.
export function parseRecipe(url4: string): ParsedRecipe {
  const text = url4.trim();
  try {
    const { sources, metadata, root: rootRef } = readSources(text);
    const root = buildTree(sources, metadata);
    const rendered = renderRecipe(root);
    if (!rendered.ok) return { ok: false, error: `${NOT_A_RECIPE} ${new RecipeError(rendered.issues).message}` };
    if (rendered.url4 !== text) {
      fail(compile(root).endsWith(`)!'$${rootRef}'`) ? METADATA_MISMATCH : NOT_A_RECIPE);
    }
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
